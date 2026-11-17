# Demo

<!-- TODO: record with vhs or asciinema and drop the GIF here -->

![bodyguard demo](demo.gif)

Reproduce without a watch:

```bash
export BODYGUARD_FAKE='{"body_battery": 18, "sleep_score": 74, "stress_avg": 46, "hrv_status": "LOW"}'

uv run bodyguard status
uv run bodyguard statusline

echo '{"tool_name":"Bash","tool_input":{"command":"git push --force origin main"}}' \
  | uv run bodyguard hook pre-tool-use | jq
```

Expected hook output:

```json
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "ask",
    "permissionDecisionReason": "bodyguard [LOW]: `git push --force origin main` looks like a force push and your vitals are low (Body Battery 18 · sleep 74 · stress 46 · HRV LOW; Body Battery 18 < 25; HRV status LOW). Double-check before running it."
  }
}
```

Try `REST` (late night + stress):

```bash
export BODYGUARD_FAKE='{"body_battery": 8}'
echo '{"tool_name":"Write","tool_input":{"file_path":"main.py"}}' | uv run bodyguard hook pre-tool-use | jq
```
