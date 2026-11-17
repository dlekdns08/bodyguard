<h1 align="center">bodyguard</h1>

<p align="center"><strong>vibe coding, but it checks your actual vibes.</strong></p>

<p align="center">
A Claude Code plugin that reads your Garmin wearable (Body Battery, stress, sleep score, HRV status)
and dials the coding agent's autonomy up or down to match the state of the human in the loop.
</p>

<p align="center">
  <a href="#install">Install</a> ·
  <a href="#the-autonomy-policy">Policy</a> ·
  <a href="#configuration">Config</a> ·
  <a href="#privacy">Privacy</a> ·
  <a href="#faq">FAQ</a> ·
  <a href="docs/demo.md">Demo</a>
</p>

---

## What it does

1. Every 15 minutes (never more often) it pulls four numbers from Garmin Connect into a tiny local cache.
2. A pure policy function turns them into an autonomy level: `HIGH`, `NORMAL`, `LOW` or `REST`.
3. Claude Code hooks read that level on every tool call and act on it:
   - **`LOW`** – risky shell commands (`rm -rf`, `git push --force`, `terraform apply`, `sudo`, `curl | sh`, …) switch from "just run it" to "ask the human first", with the reason spelled out.
   - **`REST`** – *every* shell command and file write asks, and Claude is told to help you wrap up instead of starting something new.
   - **`HIGH` / `NORMAL`** – nothing changes. Your permission settings stay exactly as they were.
4. At session start Claude gets one line of context ("the user is running low; prefer smaller steps, confirm before irreversible actions"), so it adapts its *behaviour*, not only its permissions.
5. Reads are never blocked. Ever. At any level.
6. An optional status line shows your vitals next to the model name.

Here is what it looks like when Claude tries to force-push at 00:40 on a bad night:

```
⏺ Bash(git push --force origin main)
  ⎿  Permission required

  bodyguard [LOW]: `git push --force origin main` looks like a force push and your
  vitals are low (Body Battery 18 · sleep 74 · HRV LOW; Body Battery 18 < 25;
  HRV status LOW). Double-check before running it.

  Do you want to proceed?  ❯ Yes / No
```

And the status line underneath the prompt:

```
🔋 BB 18 · 😴 74 · 😤 46 · HRV LOW · autonomy: LOW
```

## Why

Agent autonomy is usually a static setting: `--dangerously-skip-permissions` on or off, an allowlist, a mode.
But the right amount of autonomy is not a property of the agent. It is a property of the **pair**: how good
the agent is *and* how able the human is to catch its mistakes right now. At 10:00 after eight hours of sleep
you will notice the wrong `--force`. At 01:30 with a Body Battery of 12 you will press Enter.
`bodyguard` makes the guard-rails tighten exactly when your own guard drops.

## Install

Three steps. You need Python 3.12+ and [`uv`](https://docs.astral.sh/uv/).

### 1. Create Garmin tokens (once)

`bodyguard` reuses the token format of the `garminconnect` library, so any tool that produces it works.
The simplest is the auth helper from [garmin_mcp](https://github.com/Taxuspt/garmin_mcp):

```bash
uvx --from git+https://github.com/Taxuspt/garmin_mcp garmin-mcp-auth
```

It asks for your Garmin Connect e-mail/password (and MFA code if enabled) and writes tokens to
`~/.garminconnect/`. Your password is never stored; only the tokens are. Set `GARMINTOKENS=/other/dir`
if you keep them elsewhere.

### 2. Install the plugin

From inside Claude Code (adds the marketplace and installs in one go):

```
/plugin install bodyguard --marketplace dlekdns08/bodyguard
```

Or from your shell:

```bash
claude plugin marketplace add dlekdns08/bodyguard
claude plugin install bodyguard@bodyguard-marketplace
```

Or for a single session, straight from a clone:

```bash
git clone https://github.com/dlekdns08/bodyguard
claude --plugin-dir ./bodyguard
```

The hooks are thin shell wrappers that call `uv run --project <plugin> bodyguard hook …`.
The first call creates the plugin's virtualenv (a few seconds); after that every hook is a cache read.

Check that it works:

```bash
cd bodyguard && uv run bodyguard status
```

```
bodyguard 0.1.0 — vibe coding, but it checks your actual vibes

  🔋 Body Battery   37
  😴 Sleep          score 74  (6.8h)
  😤 Stress         avg 46  max 93
  💓 HRV            LOW  (last night 31, weekly 38)

  🟠 autonomy: LOW
     • HRV status LOW

  source: garmin  ·  2s ago  ·  cache: ~/.cache/bodyguard/vitals.json
```

### 3. (Optional) status line

Add to `~/.claude/settings.json`, pointing at the plugin's `scripts/statusline.sh`
(for a marketplace install the plugin lives under `~/.claude/plugins/`; run `claude plugin list` to find the path):

```json
{
  "statusLine": {
    "type": "command",
    "command": "/path/to/bodyguard/scripts/statusline.sh",
    "refreshInterval": 300
  }
}
```

Output: `🔋 BB 37 · 😴 74 · 😤 46 · HRV LOW · autonomy: LOW`

## The autonomy policy

Evaluated top to bottom; the first matching row wins. Unknown values never trigger a row and never grant `HIGH`.

| Level | Triggers (defaults) | Effect on Claude Code |
|---|---|---|
| **REST** | Body Battery **< 10**, **or** local time in **00:30–05:00** *and* avg stress **≥ 50** | Every `Bash` / `Write` / `Edit` asks for confirmation. Context tells Claude to help you wrap up. |
| **LOW** | Body Battery **< 25**, **or** sleep score **< 50**, **or** HRV status **LOW**, **or** avg stress **≥ 75** | Risky `Bash` commands ask (reason cites your vitals). Claude is told to take smaller steps. |
| **HIGH** | Body Battery **≥ 70** *and* sleep score **≥ 70** *and* avg stress **≤ 40** *and* HRV `BALANCED` (or unknown) | No permission change. Claude is told it may take larger steps. |
| **NORMAL** | everything else, including "no data" | Nothing. |

Risky commands (`src/bodyguard/risky.py`): recursive `rm`, `git push --force`/`-f`, `git reset --hard`,
`git rebase`, `git checkout -- .`, `git clean -f`, `DROP TABLE|DATABASE`, `TRUNCATE`, `DELETE FROM`,
`kubectl apply|delete`, `terraform apply|destroy`, `helm install|upgrade`, `*/deploy.sh`, `npm|twine|cargo publish`,
`sudo`, `curl … | sh`, `mkfs`/`dd`, `chmod 777`, `kill -9`, package uninstalls. False positives are preferred
over false negatives: the worst case is one extra "are you sure?".

See the reasons for the current level any time:

```bash
uv run bodyguard policy --explain
```

## Configuration

`~/.config/bodyguard/config.toml` (or `$BODYGUARD_CONFIG`). Every key is optional.

```toml
[thresholds]
# LOW: any one of these
low_body_battery = 25
low_sleep_score  = 50
low_stress_avg   = 75
low_hrv_statuses = ["LOW"]            # add "UNBALANCED" if you want to be stricter

# REST
rest_body_battery = 10
rest_after  = "00:30"                 # local time
rest_until  = "05:00"
rest_stress_avg = 50

# HIGH: all of these
high_body_battery = 70
high_sleep_score  = 70
high_stress_avg   = 40
high_hrv_statuses = ["BALANCED"]

cache_ttl_seconds = 900               # how often Garmin is contacted
```

Environment variables:

| Variable | Purpose |
|---|---|
| `GARMINTOKENS` | token directory (default `~/.garminconnect`) |
| `BODYGUARD_FAKE` | JSON vitals, bypasses Garmin entirely (see FAQ) |
| `BODYGUARD_CACHE` | cache file (default `~/.cache/bodyguard/vitals.json`) |
| `BODYGUARD_CONFIG` | config file |
| `BODYGUARD_NO_BACKGROUND` | disable the detached background refresh |

## CLI

```
bodyguard status [--refresh]   one-screen summary
bodyguard statusline           one-liner for the status line
bodyguard refresh              fetch now, update cache
bodyguard policy [--explain]   current level (+ reasons and thresholds)
bodyguard hook <event>         pre-tool-use | session-start | user-prompt-submit (JSON on stdin)
```

## Privacy

- All data stays on your machine. The only thing written is `~/.cache/bodyguard/vitals.json`
  (eight numbers and a timestamp). No telemetry, no server, no account other than your own Garmin login.
- Garmin is contacted **read-only**, at most once per `cache_ttl_seconds`, and never on the hook hot path:
  a stale cache is served immediately and refreshed in a detached background process.
- The hook reason strings contain your current numbers ("Body Battery 18"). They are shown to you in the
  permission prompt and, for `SessionStart`/`UserPromptSubmit`, injected into Claude's context. If you do
  not want vitals in your transcript, that is the thing to patch (`hooks.py: format_vitals_short`).
- Test fixtures are synthetic. The repo contains no real health data.

## FAQ

**I don't have a Garmin.** Set `BODYGUARD_FAKE` and everything works without a watch:

```bash
BODYGUARD_FAKE='{"body_battery": 18, "sleep_score": 74, "hrv_status": "LOW"}' uv run bodyguard status
```

This is also how the tests and the demo run. Fields: `body_battery`, `stress_avg`, `stress_max`,
`sleep_score`, `sleep_hours`, `hrv_status`, `hrv_last_night`, `hrv_weekly_avg`. Missing fields are `null`.

**Oura / Whoop / Apple Watch / Fitbit?** PRs welcome. The adapter contract is one function that returns a
`Vitals` dataclass (`src/bodyguard/vitals.py: fetch_from_garmin`). Everything downstream (policy, hooks, CLI)
only sees `Vitals`, so a new source is a new `fetch_from_<vendor>` plus a switch on an env var.

**Will a broken watch / expired token break Claude Code?** No. The hook wrappers always exit 0 and print
nothing on any error, which Claude Code treats as "no opinion". You will just be back to the default
permission flow. `bodyguard status` shows the error.

**Does it ever `deny`?** No. It only ever turns an automatic `allow` into an `ask`. You remain in charge,
which is the whole point.

**Can it run without `uv`?** `pip install .` and put `bodyguard` on your `PATH`; the wrapper scripts
prefer a `bodyguard` binary when one exists.

**How much does it cost in context?** One short line at session start, and one more per prompt only while
you are `LOW`/`REST`. No skills or agents are registered.

## Development

```bash
uv sync
uv run pytest
claude plugin validate .
```

## License

MIT © 2026 dlekdns08
