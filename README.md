# yosuri-agent

Autonomous free AI agent running on GitHub Actions, built on the
[Rescenix Yosuri](https://github.com/Rescenix/Yosuri) CLI (`rescene`).

**No API key required.** The CLI ships with a built-in free model network — its
own help text says `免 key 模型开箱即用` ("key-free models work out of the box").
Verified working headlessly before this repo was created.

## What it does

Twice a day (and on demand) it runs a task through `rescene exec`, cleans the
terminal-UI output down to plain text, sends the result to Telegram, and commits
it to [`runs/`](runs/).

## Schedule

| Trigger | When |
|---|---|
| `schedule` | `0 6 * * *` (06:00 UTC daily) |
| `workflow_dispatch` | manual, with an optional custom task |

Change the cron in [`.github/workflows/agent.yml`](.github/workflows/agent.yml).

## Run it manually

```bash
gh workflow run "Yosuri Agent" --repo ildus650-pixel/yosuri-agent \
  -f task="Summarise the top 3 Hacker News stories today in 5 lines."
```

Leaving `task` empty runs the default daily technology briefing.

## Required secrets

| Secret | Purpose |
|---|---|
| `TELEGRAM_BOT_TOKEN` | bot that delivers the result |
| `TELEGRAM_CHAT_ID` | your personal chat id (not the bot's) |

Optional, to unlock extra free capacity on top of the built-in network:

| Secret | Provider |
|---|---|
| `SENSENOVA_API_KEY` | SenseTime free tier |
| `MODELSCOPE_API_KEY` | ModelScope free tier |

## How it is put together

| File | Role |
|---|---|
| `.github/workflows/agent.yml` | installs the CLI, runs the task, notifies, commits |
| `scripts/clean_output.py` | strips ANSI + TUI spinner/box chrome from CLI output |
| `scripts/notify.py` | chunks and posts the result to Telegram |

## Notes and limitations

- The CLI is a Go binary downloaded from `download.shanca.me`. If that host is
  unavailable the run fails at the install step — the URL and SHA are not pinned,
  so a `curl` failure is surfaced rather than silently ignored.
- TUI output is de-chromed rather than JSON-parsed; the CLI offers no
  machine-readable output mode for `exec`.
- The built-in free model network has no published rate limits. Failure modes are
  a non-zero exit or empty output; both are logged and still reported.
