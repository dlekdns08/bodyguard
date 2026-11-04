#!/usr/bin/env sh
# Status line wrapper. Point settings.json at this file:
#   "statusLine": { "type": "command", "command": "/path/to/bodyguard/scripts/statusline.sh" }
# Reads Claude Code's JSON on stdin (ignored) and prints one compact line.
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if command -v bodyguard >/dev/null 2>&1; then
  bodyguard statusline 2>/dev/null
elif command -v uv >/dev/null 2>&1; then
  uv run --quiet --project "$ROOT" bodyguard statusline 2>/dev/null
elif [ -x "$HOME/.local/bin/uv" ]; then
  "$HOME/.local/bin/uv" run --quiet --project "$ROOT" bodyguard statusline 2>/dev/null
fi
exit 0
