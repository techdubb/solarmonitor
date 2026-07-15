"""Unit tests for the detection state machine (no network)."""
from datetime import datetime, timedelta

import pytest

from rules import Config, Reading, State, evaluate

CFG = Config(
    low_power_watts=50,
    stale_data_hours=2,
    confirm_checks=3,
    reminder_interval_hours=24,
    api_failure_alert_after=4,
)
NOON = datetime(2026, 7, 14, 12, 0, 0)


def healthy_reading(now=NOON, watts=3000):
    return Reading(ok=True, power_watts=watts, last_update_time=now - timedelta(minutes=5))


def zero_reading(now=NOON):
    return Reading(ok=True, power_watts=0.0, last_update_time=now - timedelta(minutes=5))


def stale_reading(now=NOON):
    return Reading(ok=True, power_watts=1500, last_update_time=now - timedelta(hours=5))


# --- Happy path ---------------------------------------------------------------

def test_healthy_daylight_stays_ok_no_events():
    state, events = evaluate(State(), healthy_reading(), True, NOON, CFG)
    assert state.status == "OK"
    assert events == []


def test_night_holds_status_and_never_alerts_on_zero():
    # Zero production at night is normal: must not count toward DOWN.
    state, events = evaluate(State(), zero_reading(), False, NOON, CFG)
    assert state.status == "OK"
    assert state.consecutive_down == 0
    assert events == []


# --- Going down ---------------------------------------------------------------

def test_zero_output_requires_confirmation_before_alert():
    state = State()
    for i in range(CFG.confirm_checks - 1):
        state, events = evaluate(state, zero_reading(), True, NOON, CFG)
        assert state.status == "OK"
        assert events == []
    state, events = evaluate(state, zero_reading(), True, NOON, CFG)
    assert state.status == "DOWN"
    assert len(events) == 1 and events[0].kind == "down"


def test_stale_data_during_daylight_triggers_down():
    state = State()
    for _ in range(CFG.confirm_checks):
        state, events = evaluate(state, stale_reading(), True, NOON, CFG)
    assert state.status == "DOWN"
    assert events[0].kind == "down"


def test_cloud_blip_resets_streak_and_no_alert():
    state = State()
    state, _ = evaluate(state, zero_reading(), True, NOON, CFG)
    state, _ = evaluate(state, zero_reading(), True, NOON, CFG)
    assert state.consecutive_down == 2
    # Sun comes back before the third confirming check.
    state, events = evaluate(state, healthy_reading(), True, NOON, CFG)
    assert state.consecutive_down == 0
    assert state.status == "OK"
    assert events == []


# --- Recovery & reminders -----------------------------------------------------

def _drive_down(now=NOON):
    state = State()
    for _ in range(CFG.confirm_checks):
        state, _ = evaluate(state, zero_reading(now), True, now, CFG)
    assert state.status == "DOWN"
    return state


def test_recovery_emits_event_and_clears_down_since():
    state = _drive_down()
    state, events = evaluate(state, healthy_reading(), True, NOON, CFG)
    assert state.status == "OK"
    assert state.down_since is None
    assert len(events) == 1 and events[0].kind == "recovered"


def test_no_reminder_before_interval():
    state = _drive_down()
    later = NOON + timedelta(hours=1)
    state, events = evaluate(state, zero_reading(later), True, later, CFG)
    assert events == []  # still within reminder interval


def test_reminder_after_interval():
    state = _drive_down()
    later = NOON + timedelta(hours=25)
    state, events = evaluate(state, zero_reading(later), True, later, CFG)
    assert len(events) == 1 and events[0].kind == "reminder"


# --- API reachability ---------------------------------------------------------

def test_api_failure_alerts_only_after_threshold_and_not_marked_down():
    state = State()
    for _ in range(CFG.api_failure_alert_after - 1):
        state, events = evaluate(state, Reading(ok=False, error="boom"), True, NOON, CFG)
        assert events == []
    state, events = evaluate(state, Reading(ok=False, error="boom"), True, NOON, CFG)
    assert len(events) == 1 and events[0].kind == "api_down"
    assert state.status == "OK"  # blindness is not the same as DOWN


def test_api_recovery_after_outage():
    state = State()
    for _ in range(CFG.api_failure_alert_after):
        state, _ = evaluate(state, Reading(ok=False, error="boom"), True, NOON, CFG)
    state, events = evaluate(state, healthy_reading(), True, NOON, CFG)
    assert any(e.kind == "api_recovered" for e in events)
    assert state.consecutive_api_failures == 0


def test_state_roundtrips_through_dict():
    state = _drive_down()
    assert State.from_dict(state.to_dict()) == state
