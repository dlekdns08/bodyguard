"""Build Claude Code hook responses. Pure: no I/O, easy to test.

Output shapes follow the Claude Code hooks reference:

* PreToolUse -> ``hookSpecificOutput.permissionDecision`` in {allow, deny, ask}
* SessionStart / UserPromptSubmit -> ``hookSpecificOutput.additionalContext``

Returning ``None`` means "no opinion": the wrapper prints nothing and Claude
Code continues with its normal permission flow.
"""

from __future__ import annotations

from typing import Any

from .policy import Decision
from .risky import classify_command
from .vitals import Vitals

WRITE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}
SHELL_TOOLS = {"Bash"}


def format_vitals_short(v: Vitals | None) -> str:
    """``BB 37 · sleep 71 · stress 42 · HRV LOW`` (only the metrics we have)."""
    if v is None:
        return "no vitals"
    parts: list[str] = []
    if v.body_battery is not None:
        parts.append(f"Body Battery {v.body_battery}")
    if v.sleep_score is not None:
        parts.append(f"sleep {v.sleep_score}")
    if v.stress_avg is not None:
        parts.append(f"stress {v.stress_avg}")
    if v.hrv_status:
        parts.append(f"HRV {v.hrv_status}")
    return " · ".join(parts) if parts else "no vitals"


def _ask(reason: str) -> dict[str, Any]:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "ask",
            "permissionDecisionReason": reason,
        }
    }


def pre_tool_use(payload: dict[str, Any], decision: Decision) -> dict[str, Any] | None:
    """Decide whether a tool call should ask for confirmation."""
    tool = payload.get("tool_name") or ""
    tool_input = payload.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        tool_input = {}

    # Reads are never touched, whatever the level.
    if tool not in SHELL_TOOLS and tool not in WRITE_TOOLS:
        return None

    why = "; ".join(decision.reasons) or "vitals"
    vitals = format_vitals_short(decision.vitals)

    if decision.level == "REST":
        target = tool_input.get("file_path") or tool_input.get("command") or tool
        target = str(target).strip().splitlines()[0][:80] if target else tool
        return _ask(
            f"bodyguard [REST]: {why}. Your vitals ({vitals}) say it is time to stop. "
            f"Confirm {tool} on `{target}` or wrap up and rest."
        )

    if decision.level == "LOW" and tool in SHELL_TOOLS:
        command = tool_input.get("command") or ""
        label = classify_command(command)
        if label:
            first = command.strip().splitlines()[0][:80]
            return _ask(
                f"bodyguard [LOW]: `{first}` looks like a {label} and your "
                f"vitals are low ({vitals}; {why}). Double-check before running it."
            )
        return None

    return None  # HIGH / NORMAL, or LOW with a non-risky command: let Claude Code decide


def _context(event: str, decision: Decision) -> dict[str, Any]:
    vitals = format_vitals_short(decision.vitals)
    text = (
        f"[bodyguard] Autonomy level: {decision.level} ({vitals}). "
        f"{decision.instruction}"
    )
    return {"hookSpecificOutput": {"hookEventName": event, "additionalContext": text}}


def session_start(decision: Decision) -> dict[str, Any] | None:
    """Always inject the level at session start so Claude knows the baseline."""
    if decision.vitals is not None and decision.vitals.is_empty():
        return None  # nothing to say without data
    return _context("SessionStart", decision)


def user_prompt_submit(decision: Decision) -> dict[str, Any] | None:
    """Only speak up when it matters, to keep the context lean."""
    if decision.level in ("LOW", "REST"):
        return _context("UserPromptSubmit", decision)
    return None
