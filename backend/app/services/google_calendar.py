"""Google Calendar client -- reminders and events, authorized via a
one-time local script (scripts/setup_google_calendar.py), not an in-app
login flow. The stored refresh token lives at settings.google_token_path
and is refreshed automatically here when it expires.

_get_service() is the seam, not an abstraction for its own sake: tests
monkeypatch it to return a fake object shaped like googleapiclient's
events() resource, so list_events()/create_event()/delete_event()'s
request-shaping and error-handling logic is fully exercised with no real
Google API call.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from app.config import settings

# Full read/write access to events -- reminders and events both need
# create/update/delete, not just read.
SCOPES = ["https://www.googleapis.com/auth/calendar"]


class GoogleCalendarError(RuntimeError):
    """Raised for anything Google-Calendar-related that isn't a normal
    response -- no token set up yet, or a Google API error. Callers
    surface this as a tool error, never a silently empty result."""


def _load_credentials() -> Credentials:
    if not os.path.exists(settings.google_token_path):
        raise GoogleCalendarError(
            f"No Google Calendar token found at {settings.google_token_path} -- "
            "run scripts/setup_google_calendar.py once (on a machine with a "
            "browser) to connect an account."
        )
    creds = Credentials.from_authorized_user_file(settings.google_token_path, SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(GoogleAuthRequest())
        Path(settings.google_token_path).write_text(creds.to_json())
    return creds


def _get_service():
    return build("calendar", "v3", credentials=_load_credentials(), cache_discovery=False)


def _summarize_event(event: dict[str, Any]) -> dict[str, Any]:
    start = event.get("start", {})
    end = event.get("end", {})
    return {
        "id": event.get("id"),
        "summary": event.get("summary"),
        # dateTime for a timed event, date for an all-day one -- surface
        # whichever Google actually gave us rather than assuming timed.
        "start": start.get("dateTime") or start.get("date"),
        "end": end.get("dateTime") or end.get("date"),
        "description": event.get("description"),
        "html_link": event.get("htmlLink"),
    }


def list_events(
    time_min: str | None = None,
    time_max: str | None = None,
    max_results: int = 10,
) -> list[dict[str, Any]]:
    # Live-caught bug: Google's API does NOT default timeMin to "now" when
    # omitted -- it returns events from the start of the calendar's entire
    # history instead (observed live: events from 2025 came back ahead of
    # 2026 ones). "list my events"/"what's upcoming" means from now on, so
    # default it here rather than let every caller get this wrong.
    if time_min is None:
        time_min = datetime.now(timezone.utc).isoformat()
    try:
        response = (
            _get_service()
            .events()
            .list(
                calendarId=settings.google_calendar_id,
                timeMin=time_min,
                timeMax=time_max,
                maxResults=max_results,
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )
    except HttpError as e:
        raise GoogleCalendarError(f"Could not list calendar events: {e}") from e
    return [_summarize_event(e) for e in response.get("items", [])]


def create_event(
    summary: str,
    start: str,
    end: str | None = None,
    description: str | None = None,
    reminder_minutes_before: int | None = None,
) -> dict[str, Any]:
    # No `end` given -> a zero-length event at `start`: the normal shape
    # for a plain point-in-time reminder, not an error.
    body: dict[str, Any] = {
        "summary": summary,
        "start": {"dateTime": start, "timeZone": settings.local_timezone},
        "end": {"dateTime": end or start, "timeZone": settings.local_timezone},
    }
    if description:
        body["description"] = description
    if reminder_minutes_before is not None:
        body["reminders"] = {
            "useDefault": False,
            "overrides": [{"method": "popup", "minutes": reminder_minutes_before}],
        }
    try:
        event = _get_service().events().insert(calendarId=settings.google_calendar_id, body=body).execute()
    except HttpError as e:
        raise GoogleCalendarError(f"Could not create calendar event: {e}") from e
    return _summarize_event(event)


def delete_event(event_id: str) -> dict[str, Any]:
    try:
        _get_service().events().delete(calendarId=settings.google_calendar_id, eventId=event_id).execute()
    except HttpError as e:
        raise GoogleCalendarError(f"Could not delete calendar event: {e}") from e
    return {"deleted": event_id}
