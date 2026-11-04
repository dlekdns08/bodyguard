"""Hook JSON output, driven end-to-end through the CLI with BODYGUARD_FAKE."""

import json
import subprocess
import sys
from datetime import datetime

import pytest

from bodyguard import hooks
from bodyguard.policy import Thresholds, evaluate
from bodyguard.vitals import Vitals
from conftest import fake

NOON = datetime(2026, 1, 1, 12, 0)
LATE = datetime(2026, 1, 1, 1, 0)


def decision(now=NOON, **vitals):
    return evaluate(Vitals(**vitals), Thresholds(), now=now)


# ---- unit level ------------------------------------------------------------


def test_low_asks_for_force_push():
    out = hooks.pre_tool_use(
        {"tool_name": "Bash", "tool_input": {"command": "git push --force origin main"}},
        decision(body_battery=18, sleep_score=70),
    )
    hso = out["hookSpecificOutput"]
    assert hso["hookEventName"] == "PreToolUse"
    assert hso["permissionDecision"] == "ask"
    assert "force push" in hso["permissionDecisionReason"]
    assert "Body Battery 18" in hso["permissionDecisionReason"]


def test_low_allows_safe_command():
    out = hooks.pre_tool_use(
        {"tool_name": "Bash", "tool_input": {"command": "git status"}},
        decision(body_battery=18),
    )
    assert out is None


def test_low_does_not_touch_edits():
    out = hooks.pre_tool_use(
        {"tool_name": "Edit", "tool_input": {"file_path": "a.py"}}, decision(body_battery=18)
    )
    assert out is None


def test_rest_asks_for_everything_writable():
    d = decision(now=LATE, stress_avg=70, body_battery=50)
    assert d.level == "REST"
    for tool, inp in [
        ("Bash", {"command": "ls"}),
        ("Write", {"file_path": "x.txt", "content": "hi"}),
        ("Edit", {"file_path": "x.txt"}),
    ]:
        out = hooks.pre_tool_use({"tool_name": tool, "tool_input": inp}, d)
        assert out["hookSpecificOutput"]["permissionDecision"] == "ask"
        assert "REST" in out["hookSpecificOutput"]["permissionDecisionReason"]


@pytest.mark.parametrize("tool", ["Read", "Glob", "Grep", "WebFetch", "Agent", "mcp__x__y"])
def test_reads_never_blocked_even_at_rest(tool):
    d = decision(body_battery=3)
    assert d.level == "REST"
    assert hooks.pre_tool_use({"tool_name": tool, "tool_input": {}}, d) is None


def test_high_and_normal_have_no_opinion():
    for d in (decision(body_battery=90, sleep_score=90, stress_avg=10), decision(body_battery=50)):
        assert d.level in ("HIGH", "NORMAL")
        out = hooks.pre_tool_use(
            {"tool_name": "Bash", "tool_input": {"command": "rm -rf build"}}, d
        )
        assert out is None


def test_session_start_context():
    out = hooks.session_start(decision(body_battery=18))
    hso = out["hookSpecificOutput"]
    assert hso["hookEventName"] == "SessionStart"
    assert "Autonomy level: LOW" in hso["additionalContext"]
    assert "smaller steps" in hso["additionalContext"]


def test_session_start_silent_without_data():
    assert hooks.session_start(decision()) is None


def test_user_prompt_submit_only_when_low_or_rest():
    assert hooks.user_prompt_submit(decision(body_battery=80, sleep_score=80)) is None
    out = hooks.user_prompt_submit(decision(body_battery=18))
    assert out["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"


# ---- CLI level (what Claude Code actually runs) ----------------------------


def run_hook(event, payload, env_extra, monkeypatch):
    for k, v in env_extra.items():
        monkeypatch.setenv(k, v)
    import os

    proc = subprocess.run(
        [sys.executable, "-m", "bodyguard.cli", "hook", event],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=os.environ.copy(),
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout


def test_cli_pre_tool_use_asks(isolated_env, monkeypatch):
    out = run_hook(
        "pre-tool-use",
        {"tool_name": "Bash", "tool_input": {"command": "git push --force"}},
        {"BODYGUARD_FAKE": fake(body_battery=18, sleep_score=71, hrv_status="LOW")},
        monkeypatch,
    )
    data = json.loads(out)
    assert data["hookSpecificOutput"]["permissionDecision"] == "ask"


def test_cli_prints_nothing_when_no_opinion(isolated_env, monkeypatch):
    out = run_hook(
        "pre-tool-use",
        {"tool_name": "Bash", "tool_input": {"command": "ls"}},
        {"BODYGUARD_FAKE": fake(body_battery=80, sleep_score=80)},
        monkeypatch,
    )
    assert out == ""


def test_cli_session_start(isolated_env, monkeypatch):
    out = run_hook("session-start", {"source": "startup"}, {"BODYGUARD_FAKE": fake(body_battery=18)}, monkeypatch)
    assert json.loads(out)["hookSpecificOutput"]["hookEventName"] == "SessionStart"


def test_cli_survives_garbage_stdin_and_bad_fake(isolated_env, monkeypatch):
    monkeypatch.setenv("BODYGUARD_FAKE", "{not json")
    import os

    proc = subprocess.run(
        [sys.executable, "-m", "bodyguard.cli", "hook", "pre-tool-use"],
        input="not json either",
        capture_output=True,
        text=True,
        env=os.environ.copy(),
    )
    assert proc.returncode == 0
    assert proc.stdout == ""
