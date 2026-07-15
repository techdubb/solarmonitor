# solarmonitor

Watches your SolarEdge array and pings you on **Telegram** if output drops to
zero (or the system stops reporting) during daylight — so a dead inverter gets
caught in ~an hour instead of days.

Runs as a **GitHub Actions cron** every 15 minutes. No server to maintain, and
it's independent of your home's power/internet (which matters — if the monitor
lived on a Pi at home, a home outage would take the monitor down too).

## How it works

Each run calls the SolarEdge `/site/{id}/overview` endpoint once (96 calls/day,
well under the 300/day API limit), then a small state machine decides:

- **DOWN** if output is ≤ `low_power_watts` **or** the site hasn't reported for
  > `stale_data_hours`, *during daylight* (sun elevation via `astral`, so no
  nighttime false alarms), confirmed across `confirm_checks` consecutive checks
  (~45 min) to ignore passing clouds.
- Alerts **once** on OK→DOWN, once on recovery, plus one "still down" nudge per
  day. API-unreachable is tracked separately so a flaky API isn't mistaken for a
  dead inverter.

State lives in `state.json`, which the workflow commits back only when it
changes.

## Setup

### 1. Get your SolarEdge API key + Site ID
In the [SolarEdge monitoring portal](https://monitoring.solaredge.com):
**Admin → Site Access → API Access** → accept the terms → copy the **Site ID**
and generate/copy the **API key** (site-level is enough).

### 2. Create a Telegram bot + get your chat ID
1. In Telegram, message **@BotFather** → `/newbot` → copy the **bot token**.
2. Send any message to your new bot, then visit
   `https://api.telegram.org/bot<TOKEN>/getUpdates` in a browser and copy the
   `chat.id` value. (That's your `TELEGRAM_CHAT_ID`.)

### 3. Push this repo to GitHub
A **public** repo is recommended — Actions minutes are unlimited for public
repos, and there are no secrets in the code (all live in GitHub Secrets).

### 4. Add GitHub Secrets
Repo → **Settings → Secrets and variables → Actions → New repository secret**:

| Secret | Value |
|---|---|
| `SOLAREDGE_API_KEY` | from step 1 |
| `SOLAREDGE_SITE_ID` | from step 1 |
| `TELEGRAM_BOT_TOKEN` | from step 2 |
| `TELEGRAM_CHAT_ID` | from step 2 |

### 5. Fill in `config.yaml`
Set your `latitude`, `longitude`, and IANA `timezone`. Tune thresholds if you
like (defaults are sensible).

### 6. Turn it on
Push, then go to the **Actions** tab and run **Solar monitor** once via
*"Run workflow"* to confirm it's green. The cron then runs every 15 min.

> Tip: temporarily set `low_power_watts` very high (e.g. `99999`) and run the
> workflow manually to confirm you actually receive a Telegram alert, then set
> it back to `50`.

## Local development

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt pytest
python -m pytest            # run the detection-logic tests
```

To run a real check locally, export the four env vars from step 4 and run
`python monitor.py`.

## Files

| File | Purpose |
|---|---|
| `monitor.py` | entrypoint: fetch → evaluate → notify → save state |
| `solaredge.py` | SolarEdge API client (`/overview`) |
| `rules.py` | pure detection state machine (unit-tested) |
| `notify.py` | Telegram sender |
| `config.yaml` | location + detection thresholds |
| `state.json` | persisted status (committed back by the workflow) |
| `.github/workflows/monitor.yml` | the 15-minute cron |
