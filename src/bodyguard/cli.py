"""``bodyguard`` command line interface."""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from typing import Any

from . import __version__, hooks
from .policy import evaluate, explain, load_thresholds
from .vitals import Vitals, cache_path, get_vitals, refresh

LEVEL_ICON = {"HIGH": "🟢", "NORMAL": "🔵", "LOW": "🟠", "REST": "🔴"}


def _fmt(value: Any, suffix: str = "") -> str:
    return "—" if value is None else f"{value}{suffix}"


def _age(v: Vitals) -> str:
    s = int(v.age_seconds())
    if s < 60:
        return f"{s}s ago"
    if s < 3600:
        return f"{s // 60}m ago"
    return f"{s // 3600}h{(s % 3600) // 60:02d}m ago"


# --------------------------------------------------------------------------- #
# Subcommands
# --------------------------------------------------------------------------- #


def cmd_status(args: argparse.Namespace) -> int:
    t = load_thresholds()
    v = get_vitals(t.cache_ttl_seconds, force=args.refresh, block=args.refresh)
    d = evaluate(v, t)
    icon = LEVEL_ICON[d.level]
    print(f"bodyguard {__version__} — vibe coding, but it checks your actual vibes")
    print()
    print(f"  🔋 Body Battery   {_fmt(v.body_battery)}")
    print(f"  😴 Sleep          score {_fmt(v.sleep_score)}  ({_fmt(v.sleep_hours, 'h')})")
    print(f"  😤 Stress         avg {_fmt(v.stress_avg)}  max {_fmt(v.stress_max)}")
    print(f"  💓 HRV            {_fmt(v.hrv_status)}  (last night {_fmt(v.hrv_last_night)}, weekly {_fmt(v.hrv_weekly_avg)})")
    print()
    print(f"  {icon} autonomy: {d.level}")
    for r in d.reasons:
        print(f"     • {r}")
    print()
    print(f"  source: {v.source}  ·  {_age(v)}  ·  cache: {cache_path()}")
    if v.error:
        print(f"  ⚠ {v.error}")
    return 0


def cmd_refresh(args: argparse.Namespace) -> int:
    v = refresh()
    if not args.quiet:
        if v.error:
            print(f"refresh failed: {v.error}", file=sys.stderr)
            return 1
        print(f"refreshed: {hooks.format_vitals_short(v)} -> {cache_path()}")
    return 0


def cmd_statusline(args: argparse.Namespace) -> int:
    # Claude Code pipes session JSON on stdin; we don't need it, but drain it.
    try:
        if not sys.stdin.isatty():
            sys.stdin.read()
    except OSError:
        pass
    t = load_thresholds()
    v = get_vitals(t.cache_ttl_seconds)
    d = evaluate(v, t)
    parts: list[str] = []
    if v.body_battery is not None:
        parts.append(f"🔋 BB {v.body_battery}")
    if v.sleep_score is not None:
        parts.append(f"😴 {v.sleep_score}")
    if v.stress_avg is not None:
        parts.append(f"😤 {v.stress_avg}")
    if v.hrv_status:
        parts.append(f"HRV {v.hrv_status}")
    if not parts:
        parts.append("⌚ no vitals")
    parts.append(f"autonomy: {d.level}")
    print(" · ".join(parts))
    return 0


def cmd_policy(args: argparse.Namespace) -> int:
    t = load_thresholds()
    v = get_vitals(t.cache_ttl_seconds)
    if args.explain:
        print(explain(v, t))
    else:
        print(evaluate(v, t).level)
    return 0


def _read_stdin_json() -> dict[str, Any]:
    try:
        raw = sys.stdin.read()
        data = json.loads(raw) if raw.strip() else {}
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def cmd_hook(args: argparse.Namespace) -> int:
    """Hooks must be silent on failure and always exit 0."""
    try:
        payload = _read_stdin_json()
        t = load_thresholds()
        v = get_vitals(t.cache_ttl_seconds)
        d = evaluate(v, t)
        if args.event == "pre-tool-use":
            out = hooks.pre_tool_use(payload, d)
        elif args.event == "session-start":
            out = hooks.session_start(d)
        elif args.event == "user-prompt-submit":
            out = hooks.user_prompt_submit(d)
        else:
            out = None
        if out is not None:
            sys.stdout.write(json.dumps(out))
            sys.stdout.write("\n")
            sys.stdout.flush()
    except Exception:  # noqa: BLE001 - a broken watch must never break Claude Code
        pass
    return 0


# --------------------------------------------------------------------------- #
# Parser
# --------------------------------------------------------------------------- #


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="bodyguard",
        description="Vitals-aware autonomy for Claude Code.",
    )
    p.add_argument("--version", action="version", version=f"bodyguard {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("status", help="one-screen summary of vitals and autonomy level")
    s.add_argument("--refresh", action="store_true", help="fetch from Garmin now, ignore cache")
    s.set_defaults(func=cmd_status)

    s = sub.add_parser("refresh", help="fetch from Garmin now and update the cache")
    s.add_argument("--quiet", action="store_true")
    s.set_defaults(func=cmd_refresh)

    s = sub.add_parser("statusline", help="compact one-liner for the Claude Code status line")
    s.set_defaults(func=cmd_statusline)

    s = sub.add_parser("policy", help="print the current autonomy level")
    s.add_argument("--explain", action="store_true", help="show reasons and thresholds")
    s.set_defaults(func=cmd_policy)

    s = sub.add_parser("hook", help="Claude Code hook entry points (JSON on stdin)")
    s.add_argument("event", choices=["pre-tool-use", "session-start", "user-prompt-submit"])
    s.set_defaults(func=cmd_hook)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # python -m bodyguard.cli
    sys.exit(main())
