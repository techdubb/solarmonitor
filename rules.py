"""Pure detection logic: decide whether the array is DOWN and what to alert.

Everything here is deterministic and side-effect free so it can be unit tested
without touching the network. Times are naive datetimes in the *site's* local
timezone (that's what SolarEdge returns and what astral is configured with).
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from typing import Optional


@dataclass
class Config:
    low_power_watts: float
    stale_data_hours: float
    confirm_checks: int
    reminder_interval_hours: float
    api_failure_alert_after: int


@dataclass
class Reading:
    """A single observation. `ok` is False when the API call itself failed."""

    ok: bool
    power_watts: float = 0.0
    last_update_time: Optional[datetime] = None
    lifetime_energy_wh: float = 0.0
    error: str = ""


@dataclass
class State:
    status: str = "OK"  # "OK" | "DOWN"
    consecutive_down: int = 0
    consecutive_api_failures: int = 0
    api_alerted: bool = False
    down_since: Optional[str] = None      # ISO local time
    last_reminder: Optional[str] = None   # ISO local time

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "State":
        known = {f: data[f] for f in cls().to_dict() if f in data}
        return cls(**known)


@dataclass
class Event:
    kind: str      # "down" | "recovered" | "reminder" | "api_down" | "api_recovered"
    message: str


def _fmt_age(delta: timedelta) -> str:
    hours = delta.total_seconds() / 3600
    if hours < 1:
        return f"{int(delta.total_seconds() // 60)} min"
    return f"{hours:.1f} h"


def evaluate(
    prev: State,
    reading: Reading,
    is_daylight: bool,
    now: datetime,
    cfg: Config,
) -> tuple[State, list[Event]]:
    """Advance the state machine by one check. Returns (new_state, events)."""
    state = State.from_dict(prev.to_dict())  # copy
    events: list[Event] = []

    # --- API reachability is tracked independently of production status. ---
    if not reading.ok:
        state.consecutive_api_failures += 1
        if (
            state.consecutive_api_failures >= cfg.api_failure_alert_after
            and not state.api_alerted
        ):
            state.api_alerted = True
            events.append(Event(
                "api_down",
                f"⚠️ Can't reach the SolarEdge API for "
                f"{state.consecutive_api_failures} checks. "
                f"The monitor is blind (this may be an API issue, not your panels). "
                f"Last error: {reading.error}",
            ))
        return state, events  # can't judge production when we can't see it

    if state.consecutive_api_failures > 0:
        state.consecutive_api_failures = 0
        if state.api_alerted:
            state.api_alerted = False
            events.append(Event("api_recovered", "✅ SolarEdge API reachable again."))

    # --- Production is only meaningful while the sun is up. ---
    if not is_daylight:
        return state, events  # hold current status through the night

    age = now - reading.last_update_time if reading.last_update_time else timedelta(0)
    stale = age > timedelta(hours=cfg.stale_data_hours)
    low = reading.power_watts <= cfg.low_power_watts
    down_condition = stale or low

    if down_condition:
        state.consecutive_down += 1
        reason = (
            f"no data for {_fmt_age(age)}" if stale
            else f"output {reading.power_watts:.0f} W"
        )
        if state.status == "OK" and state.consecutive_down >= cfg.confirm_checks:
            state.status = "DOWN"
            state.down_since = now.isoformat(timespec="seconds")
            state.last_reminder = now.isoformat(timespec="seconds")
            events.append(Event(
                "down",
                f"🚨 Solar array appears DOWN.\n"
                f"Reason: {reason} during daylight, confirmed over "
                f"{state.consecutive_down} checks.\n"
                f"Last report: {reading.last_update_time:%Y-%m-%d %H:%M}.",
            ))
        elif state.status == "DOWN":
            last = (
                datetime.fromisoformat(state.last_reminder)
                if state.last_reminder else now
            )
            if now - last >= timedelta(hours=cfg.reminder_interval_hours):
                state.last_reminder = now.isoformat(timespec="seconds")
                down_since = (
                    datetime.fromisoformat(state.down_since)
                    if state.down_since else now
                )
                events.append(Event(
                    "reminder",
                    f"🚨 Solar array still DOWN — {_fmt_age(now - down_since)} so far. "
                    f"Current: {reason}.",
                ))
    else:
        state.consecutive_down = 0
        if state.status == "DOWN":
            state.status = "OK"
            down_since = (
                datetime.fromisoformat(state.down_since)
                if state.down_since else now
            )
            state.down_since = None
            state.last_reminder = None
            events.append(Event(
                "recovered",
                f"✅ Solar array recovered. Output back to "
                f"{reading.power_watts:.0f} W after {_fmt_age(now - down_since)} down.",
            ))

    return state, events
