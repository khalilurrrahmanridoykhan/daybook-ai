"""Offline tests for the Google Calendar client. A fake service/events
resource stands in for googleapiclient's Resource objects -- no real
Google API call or OAuth token required, same "replace the seam, not the
logic" pattern as test_daybook_db.py and test_ollama_client.py.
"""

from datetime import datetime, timezone

import httplib2
import pytest
from googleapiclient.errors import HttpError

from app.services import google_calendar
from app.services.google_calendar import GoogleCalendarError


class _FakeExecutable:
    def __init__(self, result):
        self._result = result

    def execute(self):
        return self._result


class _FakeEventsResource:
    def __init__(self, list_result=None, insert_result=None):
        self._list_result = list_result
        self._insert_result = insert_result
        self.calls: dict[str, dict] = {}

    def list(self, **kwargs):
        self.calls["list"] = kwargs
        return _FakeExecutable(self._list_result)

    def insert(self, **kwargs):
        self.calls["insert"] = kwargs
        return _FakeExecutable(self._insert_result)

    def delete(self, **kwargs):
        self.calls["delete"] = kwargs
        return _FakeExecutable(None)


class _FakeService:
    def __init__(self, events_resource):
        self._events_resource = events_resource

    def events(self):
        return self._events_resource


def _patch_service(monkeypatch, events_resource):
    monkeypatch.setattr(google_calendar, "_get_service", lambda: _FakeService(events_resource))


def _http_error(status: int, message: str) -> HttpError:
    return HttpError(httplib2.Response({"status": status}), message.encode())


def test_list_events_summarizes_timed_and_all_day_events(monkeypatch):
    events = _FakeEventsResource(
        list_result={
            "items": [
                {
                    "id": "e1",
                    "summary": "Dentist",
                    "start": {"dateTime": "2026-10-05T09:00:00+06:00"},
                    "end": {"dateTime": "2026-10-05T09:30:00+06:00"},
                },
                {"id": "e2", "summary": "Public holiday", "start": {"date": "2026-10-06"}, "end": {"date": "2026-10-07"}},
            ]
        }
    )
    _patch_service(monkeypatch, events)

    result = google_calendar.list_events(time_min="2026-10-01T00:00:00+06:00")

    assert result == [
        {
            "id": "e1",
            "summary": "Dentist",
            "start": "2026-10-05T09:00:00+06:00",
            "end": "2026-10-05T09:30:00+06:00",
            "description": None,
            "html_link": None,
        },
        {
            "id": "e2",
            "summary": "Public holiday",
            "start": "2026-10-06",
            "end": "2026-10-07",
            "description": None,
            "html_link": None,
        },
    ]
    assert events.calls["list"]["timeMin"] == "2026-10-01T00:00:00+06:00"
    assert events.calls["list"]["singleEvents"] is True


def test_list_events_defaults_time_min_to_now_when_not_given(monkeypatch):
    """Live-caught bug: Google's API does not default timeMin to 'now'
    when omitted -- it returns events from the start of the calendar's
    entire history instead (observed live: 2025 events came back ahead of
    2026 ones on 2026-09-07). 'list my events' must mean upcoming, not
    ever-recorded."""
    events = _FakeEventsResource(list_result={"items": []})
    _patch_service(monkeypatch, events)

    before = datetime.now(timezone.utc)
    google_calendar.list_events()
    after = datetime.now(timezone.utc)

    time_min = events.calls["list"]["timeMin"]
    assert time_min is not None
    assert before <= datetime.fromisoformat(time_min) <= after


def test_list_events_leaves_an_explicit_time_min_untouched(monkeypatch):
    events = _FakeEventsResource(list_result={"items": []})
    _patch_service(monkeypatch, events)

    google_calendar.list_events(time_min="2026-10-01T00:00:00+06:00")

    assert events.calls["list"]["timeMin"] == "2026-10-01T00:00:00+06:00"


def test_list_events_raises_google_calendar_error_on_http_error(monkeypatch):
    events = _FakeEventsResource()
    events.list = lambda **kw: (_ for _ in ()).throw(_http_error(500, "backend error"))
    _patch_service(monkeypatch, events)

    with pytest.raises(GoogleCalendarError, match="Could not list"):
        google_calendar.list_events()


def test_create_event_defaults_end_to_start_for_a_point_in_time_reminder(monkeypatch):
    events = _FakeEventsResource(insert_result={"id": "e3", "summary": "Take medicine", "start": {"dateTime": "2026-10-05T20:00:00+06:00"}, "end": {"dateTime": "2026-10-05T20:00:00+06:00"}})
    _patch_service(monkeypatch, events)

    result = google_calendar.create_event(summary="Take medicine", start="2026-10-05T20:00:00+06:00")

    assert result["id"] == "e3"
    body = events.calls["insert"]["body"]
    assert body["start"]["dateTime"] == "2026-10-05T20:00:00+06:00"
    assert body["end"]["dateTime"] == "2026-10-05T20:00:00+06:00"  # defaulted, not left missing


def test_create_event_sets_reminder_override_when_given(monkeypatch):
    events = _FakeEventsResource(insert_result={"id": "e4", "summary": "Pay rent", "start": {"dateTime": "2026-10-01T09:00:00+06:00"}, "end": {"dateTime": "2026-10-01T09:00:00+06:00"}})
    _patch_service(monkeypatch, events)

    google_calendar.create_event(summary="Pay rent", start="2026-10-01T09:00:00+06:00", reminder_minutes_before=60)

    body = events.calls["insert"]["body"]
    assert body["reminders"] == {"useDefault": False, "overrides": [{"method": "popup", "minutes": 60}]}


def test_create_event_omits_reminders_key_when_not_given(monkeypatch):
    events = _FakeEventsResource(insert_result={"id": "e5", "summary": "x", "start": {"dateTime": "2026-10-01T09:00:00+06:00"}, "end": {"dateTime": "2026-10-01T09:00:00+06:00"}})
    _patch_service(monkeypatch, events)

    google_calendar.create_event(summary="x", start="2026-10-01T09:00:00+06:00")

    assert "reminders" not in events.calls["insert"]["body"]


def test_create_event_raises_google_calendar_error_on_http_error(monkeypatch):
    events = _FakeEventsResource()
    events.insert = lambda **kw: (_ for _ in ()).throw(_http_error(400, "bad request"))
    _patch_service(monkeypatch, events)

    with pytest.raises(GoogleCalendarError, match="Could not create"):
        google_calendar.create_event(summary="x", start="2026-10-01T09:00:00+06:00")


def test_delete_event_returns_deleted_id(monkeypatch):
    events = _FakeEventsResource()
    _patch_service(monkeypatch, events)

    result = google_calendar.delete_event("e1")

    assert result == {"deleted": "e1"}
    assert events.calls["delete"]["eventId"] == "e1"


def test_delete_event_raises_google_calendar_error_on_http_error(monkeypatch):
    events = _FakeEventsResource()
    events.delete = lambda **kw: (_ for _ in ()).throw(_http_error(404, "not found"))
    _patch_service(monkeypatch, events)

    with pytest.raises(GoogleCalendarError, match="Could not delete"):
        google_calendar.delete_event("does-not-exist")


def test_load_credentials_raises_clear_error_when_no_token_file(monkeypatch, tmp_path):
    """Live-relevant: before scripts/setup_google_calendar.py has ever been
    run, any calendar tool call must fail with a clear, actionable message
    -- not a raw FileNotFoundError from deep inside the Google client."""
    monkeypatch.setattr(google_calendar.settings, "google_token_path", str(tmp_path / "does_not_exist.json"))

    with pytest.raises(GoogleCalendarError, match="setup_google_calendar.py"):
        google_calendar._load_credentials()
