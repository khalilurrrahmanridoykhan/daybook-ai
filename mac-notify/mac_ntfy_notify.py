#!/usr/bin/env python3
"""Background bridge: subscribes to an ntfy topic and shows each message
as a real macOS notification. No GUI, no Dock icon, no window -- meant to
run continuously via the LaunchAgent next to this file
(com.daybookai.notify.plist), not launched by hand.

Live-observed on macOS 26 (Tahoe): terminal-notifier -- the usual tool
for a *clickable* notification -- could not register for notification
permission at all ("Notifications are not allowed for this
application"), and never appeared in System Settings to be granted one
either. Plain osascript `display notification` worked immediately, under
the already-permitted "Script Editor" identity -- so this uses that,
trading away click-to-open (osascript's command has no such option) for
something that reliably shows up at all on this OS version.

Config comes from environment variables (set by the LaunchAgent's own
EnvironmentVariables block, not a .env file -- launchd doesn't read
those):
    NTFY_TOPIC      required
    NTFY_BASE_URL   optional, defaults to the public https://ntfy.sh
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request
from collections import deque

NTFY_BASE_URL = os.environ.get("NTFY_BASE_URL", "https://ntfy.sh")
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "")

# Live-observed bug this guards against: the ntfy connection dropped and
# reconnected roughly every 90 seconds, and each reconnect redelivered
# the same still-cached message -- the same notification kept coming
# back every ~2 minutes until manually dismissed. Tracking seen message
# ids makes a duplicate delivery a no-op regardless of why it happened,
# rather than chasing the exact reconnect cause.
_SEEN_IDS: deque[str] = deque(maxlen=500)
_SEEN_SET: set[str] = set()


def _already_shown(message_id: str) -> bool:
    if message_id in _SEEN_SET:
        return True
    if len(_SEEN_IDS) == _SEEN_IDS.maxlen:
        _SEEN_SET.discard(_SEEN_IDS[0])
    _SEEN_IDS.append(message_id)
    _SEEN_SET.add(message_id)
    return False


def show_notification(title: str, message: str) -> None:
    # AppleScript string literals need their own quotes/backslashes
    # escaped -- an unescaped message containing a straight quote would
    # otherwise break the whole osascript command instead of just failing
    # to show one notification.
    def escape(s: str) -> str:
        return s.replace("\\", "\\\\").replace('"', '\\"')

    script = f'display notification "{escape(message)}" with title "{escape(title)}"'
    subprocess.run(["/usr/bin/osascript", "-e", script], check=False)


def main() -> None:
    if not NTFY_TOPIC:
        print("NTFY_TOPIC is not set -- check the plist's EnvironmentVariables block", file=sys.stderr)
        sys.exit(1)

    url = f"{NTFY_BASE_URL}/{NTFY_TOPIC}/json"
    while True:
        try:
            with urllib.request.urlopen(url, timeout=90) as resp:
                for raw_line in resp:
                    line = raw_line.decode("utf-8").strip()
                    if not line:
                        continue
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if event.get("event") != "message":
                        continue  # "open"/"keepalive" events, not real notifications
                    if _already_shown(event.get("id", "")):
                        continue
                    show_notification(event.get("title") or "DayBook AI", event.get("message", ""))
        except Exception as e:  # noqa: BLE001 -- must never just die silently; always reconnect
            print(f"ntfy stream error, reconnecting in 10s: {e}", file=sys.stderr)
            time.sleep(10)


if __name__ == "__main__":
    main()
