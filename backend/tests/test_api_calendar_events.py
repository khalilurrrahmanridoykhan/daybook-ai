"""API-level tests for the dashboard's Schedule tab routes -- the
underlying google_calendar.py logic is covered in
test_google_calendar.py; these check the request/response wiring, auth,
and error-status mapping.
"""

from fastapi.testclient import TestClient

from app.services.auth import hash_password
from app.services.google_calendar import GoogleCalendarError


def _authed_client(monkeypatch) -> TestClient:
    monkeypatch.setattr("app.api.auth.settings.admin_username", "admin")
    monkeypatch.setattr("app.api.auth.settings.admin_password_hash", hash_password("realpassword"))
    monkeypatch.setattr("app.services.auth.settings.session_secret", "test-secret")

    from app.main import app

    client = TestClient(app, base_url="https://testserver")
    resp = client.post("/api/auth/login", json={"username": "admin", "password": "realpassword"})
    assert resp.status_code == 200
    return client


def test_list_events_requires_auth():
    from app.main import app

    with TestClient(app) as client:
        resp = client.get("/api/calendar/events")
    assert resp.status_code == 401


def test_list_events_returns_data_layer_result(monkeypatch):
    import app.api.calendar_events as cal_api

    monkeypatch.setattr(cal_api.google_calendar, "list_events", lambda **kw: [{"id": "e1", "summary": "Dentist"}])
    client = _authed_client(monkeypatch)

    resp = client.get("/api/calendar/events")

    assert resp.status_code == 200
    assert resp.json() == [{"id": "e1", "summary": "Dentist"}]


def test_create_event_passes_body_through(monkeypatch):
    import app.api.calendar_events as cal_api

    captured = {}
    monkeypatch.setattr(cal_api.google_calendar, "create_event", lambda **kw: captured.update(kw) or {"id": "e2", **kw})
    client = _authed_client(monkeypatch)

    resp = client.post("/api/calendar/events", json={"summary": "Take medicine", "start": "2026-10-05T20:00:00+06:00"})

    assert resp.status_code == 200
    assert captured["summary"] == "Take medicine"


def test_update_event_returns_404_when_not_found(monkeypatch):
    import app.api.calendar_events as cal_api

    def boom(event_id, **kw):
        raise GoogleCalendarError(f"No event with id {event_id}")

    monkeypatch.setattr(cal_api.google_calendar, "update_event", boom)
    client = _authed_client(monkeypatch)

    resp = client.patch("/api/calendar/events/does-not-exist", json={"summary": "x"})

    assert resp.status_code == 404


def test_delete_event_succeeds(monkeypatch):
    import app.api.calendar_events as cal_api

    monkeypatch.setattr(cal_api.google_calendar, "delete_event", lambda event_id: {"deleted": event_id})
    client = _authed_client(monkeypatch)

    resp = client.delete("/api/calendar/events/e1")

    assert resp.status_code == 200
    assert resp.json() == {"deleted": "e1"}


def test_not_connected_yet_becomes_a_502(monkeypatch):
    import app.api.calendar_events as cal_api

    def boom(**kw):
        raise GoogleCalendarError("No Google Calendar token found -- run scripts/setup_google_calendar.py")

    monkeypatch.setattr(cal_api.google_calendar, "list_events", boom)
    client = _authed_client(monkeypatch)

    resp = client.get("/api/calendar/events")

    assert resp.status_code == 502
