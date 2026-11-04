#!/usr/bin/env sh
# Thin wrapper used by hooks/hooks.json.
# Usage: hook.sh <session-start|user-prompt-submit|pre-tool-use>
#
# Design rule: this script must NEVER break Claude Code. Any failure
# (no uv, no tokens, Garmin down, bug) results in exit 0 with no output,
# which Claude Code treats as "no opinion".
ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
export BODYGUARD_HOOK=1

if command -v bodyguard >/dev/null 2>&1; then
  bodyguard hook "$1" 2>/dev/null
elif command -v uv >/dev/null 2>&1; then
  uv run --quiet --project "$ROOT" bodyguard hook "$1" 2>/dev/null
elif [ -x "$HOME/.local/bin/uv" ]; then
  "$HOME/.local/bin/uv" run --quiet --project "$ROOT" bodyguard hook "$1" 2>/dev/null
fi
exit 0
