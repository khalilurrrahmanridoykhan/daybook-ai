"""Generates the static bearer token voice clients send to /api/voice/ask
-- separate from the admin login, since a Siri Shortcut can't hold a
browser session cookie the way the web app does.

Usage:
    .venv/bin/python scripts/create_voice_api_key.py

Prints a generated key once, to stdout only. Put it in .env as
VOICE_API_KEY, and paste the exact same value into your Shortcut's
"Get Contents of URL" action as the Authorization header
(Bearer <key>).
"""

from __future__ import annotations

import secrets


def main() -> None:
    key = secrets.token_urlsafe(32)
    print("")
    print("──────────────────────────────────────────────")
    print(f"  VOICE_API_KEY={key}")
    print("")
    print("  Put this in .env, and use the exact same value as the")
    print("  Authorization header in your Shortcut:")
    print(f"    Bearer {key}")
    print("──────────────────────────────────────────────")
    print("This key is shown once and is not stored anywhere else. Copy it now.")


if __name__ == "__main__":
    main()
