"""Send alert messages to Telegram via the Bot API."""
from __future__ import annotations

import requests


def send_telegram(bot_token: str, chat_id: str, text: str, timeout: int = 30) -> None:
    """Post a message to a Telegram chat. Raises on failure."""
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    resp = requests.post(
        url,
        json={"chat_id": chat_id, "text": text, "disable_web_page_preview": True},
        timeout=timeout,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"Telegram send failed: HTTP {resp.status_code} {resp.text[:200]}")
