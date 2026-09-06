"""One-time interactive authorization: connects this backend to a Google
Calendar and stores a refresh token locally. Run this once, on a machine
with a browser (your laptop -- not the headless VPS); it opens a Google
consent screen, then you copy the resulting token file to the VPS.

Google Cloud Console setup (also one-time, before running this):
  1. console.cloud.google.com -> create or select a project.
  2. APIs & Services -> Library -> enable "Google Calendar API".
  3. APIs & Services -> OAuth consent screen -> External -> add your own
     Google account under "Test users". Staying in "Testing" mode is
     fine and expected for a single personal account -- no Google review
     needed, and it never goes further than test users you name.
  4. APIs & Services -> Credentials -> Create Credentials -> OAuth client
     ID -> Application type: Desktop app.
  5. Put the Client ID and Client Secret it gives you into backend/.env:
       GOOGLE_CLIENT_ID=...
       GOOGLE_CLIENT_SECRET=...

Usage:
    .venv/bin/python scripts/setup_google_calendar.py

Opens your default browser for the Google consent screen. On success,
writes the token to GOOGLE_TOKEN_PATH (default: data/google_token.json)
-- copy that one file to the same path on the VPS and restart the
backend there. The client id/secret are not secret enough on their own
to matter much if seen, but the token file **is** a live credential:
never commit it (already covered by .gitignore).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, ".")
from app.config import settings  # noqa: E402
from app.services.google_calendar import SCOPES  # noqa: E402


def main() -> None:
    if not settings.google_client_id or not settings.google_client_secret:
        print(
            "Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in backend/.env first -- "
            "see this script's module docstring for how to create them.",
            file=sys.stderr,
        )
        sys.exit(1)

    # Imported here, not at module load, so importing google_calendar.py
    # elsewhere (tests included) never requires this OAuth-flow-only
    # dependency to be installed.
    from google_auth_oauthlib.flow import InstalledAppFlow

    client_config = {
        "installed": {
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }
    flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
    creds = flow.run_local_server(port=0)

    token_path = Path(settings.google_token_path)
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(creds.to_json())

    print("")
    print("──────────────────────────────────────────────")
    print(f"  Saved Google Calendar token to: {token_path.resolve()}")
    print("  Copy this file to the same path on the VPS, then restart the backend there.")
    print("──────────────────────────────────────────────")


if __name__ == "__main__":
    main()
