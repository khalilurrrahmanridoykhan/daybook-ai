"""API-level tests for the dashboard's Tasks tab routes -- request/
response wiring and auth, exercised via TestClient the same way
test_api_chat.py does. The underlying daybook_db.py logic itself is
covered in test_daybook_db.py; these mock at that boundary.
"""

from fastapi.testclient import TestClient

from app.services.auth import hash_password
from app.services.daybook_db import DaybookDbError


def _authed_client(monkeypatch) -> TestClient:
    monkeypatch.setattr("app.api.auth.settings.admin_username", "admin")
    monkeypatch.setattr("app.api.auth.settings.admin_password_hash", hash_password("realpassword"))
    monkeypatch.setattr("app.services.auth.settings.session_secret", "test-secret")

    from app.main import app

    client = TestClient(app, base_url="https://testserver")
    resp = client.post("/api/auth/login", json={"username": "admin", "password": "realpassword"})
    assert resp.status_code == 200
    return client


def test_list_tasks_requires_auth():
    from app.main import app

    with TestClient(app) as client:
        resp = client.get("/api/tasks")
    assert resp.status_code == 401


def test_list_tasks_returns_data_layer_result(monkeypatch):
    import app.api.tasks as tasks_api

    monkeypatch.setattr(tasks_api.daybook_db, "list_tasks", lambda **kw: [{"id": "t1", "title": "Buy milk"}])
    client = _authed_client(monkeypatch)

    resp = client.get("/api/tasks")

    assert resp.status_code == 200
    assert resp.json() == [{"id": "t1", "title": "Buy milk"}]


def test_create_task_passes_body_through(monkeypatch):
    import app.api.tasks as tasks_api

    captured = {}
    monkeypatch.setattr(tasks_api.daybook_db, "create_task", lambda **kw: captured.update(kw) or {"id": "t2", **kw})
    client = _authed_client(monkeypatch)

    resp = client.post("/api/tasks", json={"title": "Call the plumber"})

    assert resp.status_code == 200
    assert captured["title"] == "Call the plumber"


def test_update_task_marks_done(monkeypatch):
    import app.api.tasks as tasks_api

    captured = {}
    monkeypatch.setattr(tasks_api.daybook_db, "update_task", lambda task_id, **kw: captured.update(id=task_id, **kw) or {"id": task_id, "status": "DONE"})
    client = _authed_client(monkeypatch)

    resp = client.patch("/api/tasks/t1", json={"status": "DONE"})

    assert resp.status_code == 200
    assert captured == {"id": "t1", "title": None, "details": None, "priority": None, "due_at": None, "status": "DONE"}


def test_update_task_returns_404_when_not_found(monkeypatch):
    import app.api.tasks as tasks_api

    def boom(task_id, **kw):
        raise DaybookDbError(f"No task with id {task_id}")

    monkeypatch.setattr(tasks_api.daybook_db, "update_task", boom)
    client = _authed_client(monkeypatch)

    resp = client.patch("/api/tasks/does-not-exist", json={"title": "x"})

    assert resp.status_code == 404


def test_delete_task_returns_404_when_not_found(monkeypatch):
    import app.api.tasks as tasks_api

    def boom(task_id):
        raise DaybookDbError(f"No task with id {task_id}")

    monkeypatch.setattr(tasks_api.daybook_db, "delete_task", boom)
    client = _authed_client(monkeypatch)

    resp = client.delete("/api/tasks/does-not-exist")

    assert resp.status_code == 404


def test_delete_task_succeeds(monkeypatch):
    import app.api.tasks as tasks_api

    monkeypatch.setattr(tasks_api.daybook_db, "delete_task", lambda task_id: {"deleted": True})
    client = _authed_client(monkeypatch)

    resp = client.delete("/api/tasks/t1")

    assert resp.status_code == 200
    assert resp.json() == {"deleted": True}


def test_a_connection_error_becomes_a_502_not_a_404(monkeypatch):
    import app.api.tasks as tasks_api

    def boom(**kw):
        raise DaybookDbError("Could not reach the Daybook database -- is Postgres running?")

    monkeypatch.setattr(tasks_api.daybook_db, "list_tasks", boom)
    client = _authed_client(monkeypatch)

    resp = client.get("/api/tasks")

    assert resp.status_code == 502
