"""Push notifications to Mac + iPhone via ntfy (https://ntfy.sh) -- a
plain HTTP POST to a topic URL, no account, no SDK, no push certificate
of our own to manage. The free public ntfy server is the default; a
self-hosted instance is a drop-in replacement via NTFY_BASE_URL.

_client() is the seam, not an abstraction for its own sake: tests
monkeypatch it to return an httpx.Client wired to a MockTransport, same
pattern as ollama_client.py.
"""

from __future__ import annotations

from typing import Any

import httpx

from app.config import settings


class NotifyError(RuntimeError):
    """Raised for anything ntfy-related that isn't a normal response --
    no topic configured, or a non-2xx from the ntfy server. Callers
    surface this as a tool error, never a silently swallowed failure."""


def _client() -> httpx.Client:
    return httpx.Client(base_url=settings.ntfy_base_url, timeout=15.0)


def send(
    message: str,
    title: str | None = None,
    priority: int | None = None,
    tags: list[str] | None = None,
) -> None:
    """priority: 1 (min) - 5 (max), ntfy's own default is 3 if omitted.
    tags: ntfy renders known emoji-shortcode tags as an icon, e.g.
    ["warning"], ["moneybag"], ["calendar"]."""
    if not settings.ntfy_topic:
        raise NotifyError(
            "No ntfy topic configured -- set NTFY_TOPIC in .env to a long, random topic name "
            "and subscribe to it in the ntfy app first."
        )
    headers: dict[str, str] = {}
    if title:
        headers["Title"] = title
    if priority is not None:
        headers["Priority"] = str(priority)
    if tags:
        headers["Tags"] = ",".join(tags)

    try:
        resp = _client().post(f"/{settings.ntfy_topic}", content=message.encode("utf-8"), headers=headers)
    except httpx.ConnectError as e:
        raise NotifyError(f"Could not reach ntfy at {settings.ntfy_base_url}: {e}") from e
    if resp.status_code >= 300:
        raise NotifyError(f"ntfy returned {resp.status_code}: {resp.text}")
