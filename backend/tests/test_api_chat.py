"""Tests for the session-management chat routes (delete/rename) -- the
request/response layer on top of memory.py, exercised via FastAPI's
TestClient the same way test_auth.py does, including that both correctly
require an authenticated session like the rest of the chat router.
"""

from fastapi.testclient import TestClient

from app.services import memory
from app.services.auth import hash_password


def _authed_client(monkeypatch, tmp_path) -> TestClient:
    monkeypatch.setattr("app.api.auth.settings.admin_username", "admin")
    monkeypatch.setattr("app.api.auth.settings.admin_password_hash", hash_password("realpassword"))
    monkeypatch.setattr("app.services.auth.settings.session_secret", "test-secret")
    monkeypatch.setattr(memory.settings, "memory_db_path", str(tmp_path / "test.sqlite3"))

    from app.main import app

    # The login cookie is set with secure=True (correct in production,
    # behind real HTTPS) -- TestClient's default http://testserver origin
    # would otherwise make its cookie jar silently drop it before the next
    # request, so every "authenticated" call after login would 401 anyway.
    client = TestClient(app, base_url="https://testserver")
    resp = client.post("/api/auth/login", json={"username": "admin", "password": "realpassword"})
    assert resp.status_code == 200
    return client


def test_delete_session_removes_it_from_the_list(monkeypatch, tmp_path):
    client = _authed_client(monkeypatch, tmp_path)
    session_id = client.post("/api/chat/sessions").json()["session_id"]

    resp = client.delete(f"/api/chat/sessions/{session_id}")

    assert resp.status_code == 200
    ids = [s["id"] for s in client.get("/api/chat/sessions").json()]
    assert session_id not in ids


def test_delete_unknown_session_returns_404(monkeypatch, tmp_path):
    client = _authed_client(monkeypatch, tmp_path)
    resp = client.delete("/api/chat/sessions/does-not-exist")
    assert resp.status_code == 404


def test_delete_session_requires_auth():
    from app.main import app

    with TestClient(app) as client:
        resp = client.delete("/api/chat/sessions/some-id")
    assert resp.status_code == 401


def test_rename_session_updates_its_title(monkeypatch, tmp_path):
    client = _authed_client(monkeypatch, tmp_path)
    session_id = client.post("/api/chat/sessions").json()["session_id"]

    resp = client.patch(f"/api/chat/sessions/{session_id}", json={"title": "Budget planning"})

    assert resp.status_code == 200
    titles = {s["id"]: s["title"] for s in client.get("/api/chat/sessions").json()}
    assert titles[session_id] == "Budget planning"


def test_rename_session_rejects_a_blank_title(monkeypatch, tmp_path):
    client = _authed_client(monkeypatch, tmp_path)
    session_id = client.post("/api/chat/sessions").json()["session_id"]

    resp = client.patch(f"/api/chat/sessions/{session_id}", json={"title": "   "})

    assert resp.status_code == 400


def test_rename_unknown_session_returns_404(monkeypatch, tmp_path):
    client = _authed_client(monkeypatch, tmp_path)
    resp = client.patch("/api/chat/sessions/does-not-exist", json={"title": "x"})
    assert resp.status_code == 404


def test_rename_session_requires_auth():
    from app.main import app

    with TestClient(app) as client:
        resp = client.patch("/api/chat/sessions/some-id", json={"title": "x"})
    assert resp.status_code == 401
