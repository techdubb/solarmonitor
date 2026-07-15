"""Entrypoint: fetch SolarEdge overview, evaluate rules, send Telegram alerts.

Run by the GitHub Actions cron every 15 minutes. Reads secrets from the
environment and non-secret settings from config.yaml. Persists state.json,
which the workflow commits back only when it changes.

Exit codes:
  0  ran cleanly (with or without alerts)
  1  configuration / secret error
  2  an alert needed sending but Telegram delivery failed (state NOT saved,
     so the next run retries the alert)
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml
from astral import Observer
from astral.sun import elevation

import solaredge
from notify import send_telegram
from rules import Config, Reading, State, evaluate

CONFIG_PATH = Path(__file__).parent / "config.yaml"
STATE_PATH = Path(__file__).parent / "state.json"


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        print(f"ERROR: missing required environment variable {name}", file=sys.stderr)
        sys.exit(1)
    return value


def load_state() -> State:
    if STATE_PATH.exists():
        return State.from_dict(json.loads(STATE_PATH.read_text()))
    return State()


def save_state(state: State) -> None:
    STATE_PATH.write_text(json.dumps(state.to_dict(), indent=2) + "\n")


def main() -> int:
    cfg_raw = yaml.safe_load(CONFIG_PATH.read_text())
    loc = cfg_raw["location"]
    det = cfg_raw["detection"]
    cfg = Config(
        low_power_watts=det["low_power_watts"],
        stale_data_hours=det["stale_data_hours"],
        confirm_checks=det["confirm_checks"],
        reminder_interval_hours=det["reminder_interval_hours"],
        api_failure_alert_after=det["api_failure_alert_after"],
    )

    api_key = _require_env("SOLAREDGE_API_KEY")
    site_id = _require_env("SOLAREDGE_SITE_ID")
    bot_token = _require_env("TELEGRAM_BOT_TOKEN")
    chat_id = _require_env("TELEGRAM_CHAT_ID")

    tz = ZoneInfo(loc["timezone"])
    now_aware = datetime.now(tz)
    now_local = now_aware.replace(tzinfo=None)

    observer = Observer(latitude=loc["latitude"], longitude=loc["longitude"])
    sun_elevation = elevation(observer, now_aware)
    is_daylight = sun_elevation >= det["min_sun_elevation_deg"]

    # --- Fetch (one API call). A failure becomes a not-ok Reading, not a crash. ---
    try:
        ov = solaredge.get_overview(site_id, api_key)
        reading = Reading(
            ok=True,
            power_watts=ov.power_watts,
            last_update_time=ov.last_update_time,
            lifetime_energy_wh=ov.lifetime_energy_wh,
        )
        obs = f"{ov.power_watts:.0f} W, last update {ov.last_update_time:%Y-%m-%d %H:%M}"
    except solaredge.SolarEdgeError as exc:
        reading = Reading(ok=False, error=str(exc))
        obs = f"API error: {exc}"

    prev = load_state()
    new_state, events = evaluate(prev, reading, is_daylight, now_local, cfg)

    print(
        f"[{now_local:%Y-%m-%d %H:%M}] sun={sun_elevation:.1f}° "
        f"daylight={is_daylight} status={new_state.status} "
        f"down_streak={new_state.consecutive_down} | {obs}"
    )

    # Deliver alerts before persisting: if delivery fails we skip the save so
    # the next run re-evaluates and retries rather than silently losing an alert.
    delivery_failed = False
    for ev in events:
        try:
            send_telegram(bot_token, chat_id, ev.message)
            print(f"  sent [{ev.kind}]")
        except Exception as exc:  # noqa: BLE001 - report and keep going
            delivery_failed = True
            print(f"  FAILED to send [{ev.kind}]: {exc}", file=sys.stderr)

    if delivery_failed:
        return 2

    save_state(new_state)
    return 0


if __name__ == "__main__":
    sys.exit(main())
