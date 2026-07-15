"""Minimal SolarEdge Monitoring API client.

Docs: https://monitoringapi.solaredge.com  (see se_monitoring_api.pdf)
Auth is a single API key passed as the `api_key` query parameter.
The whole account is limited to 300 requests/day per site, so we call
exactly one endpoint (/overview) per check.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import requests

BASE_URL = "https://monitoringapi.solaredge.com"
_TIME_FMT = "%Y-%m-%d %H:%M:%S"


@dataclass
class Overview:
    """Parsed result of the /site/{id}/overview endpoint."""

    power_watts: float
    # Naive datetime in the *site's* local timezone (SolarEdge returns no offset).
    last_update_time: datetime
    lifetime_energy_wh: float


class SolarEdgeError(Exception):
    """Raised when the API call fails or returns something unexpected."""


def get_overview(site_id: str, api_key: str, timeout: int = 30) -> Overview:
    """Fetch the site overview: current power + last update time.

    Raises SolarEdgeError on any network/HTTP/parse failure so the caller can
    treat "couldn't reach the API" distinctly from "site is producing zero".
    """
    url = f"{BASE_URL}/site/{site_id}/overview"
    try:
        resp = requests.get(url, params={"api_key": api_key}, timeout=timeout)
    except requests.RequestException as exc:
        raise SolarEdgeError(f"request failed: {exc}") from exc

    if resp.status_code == 429:
        raise SolarEdgeError("rate limited (429): exceeded 300 requests/day")
    if resp.status_code != 200:
        raise SolarEdgeError(f"HTTP {resp.status_code}: {resp.text[:200]}")

    try:
        overview = resp.json()["overview"]
        return Overview(
            power_watts=float(overview["currentPower"]["power"]),
            last_update_time=datetime.strptime(
                overview["lastUpdateTime"], _TIME_FMT
            ),
            lifetime_energy_wh=float(overview["lifeTimeData"]["energy"]),
        )
    except (KeyError, ValueError, TypeError) as exc:
        raise SolarEdgeError(f"unexpected response shape: {exc}") from exc
