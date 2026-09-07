"""API-level tests for the dashboard's Expenses tab routes -- the
underlying daybook_db.py logic is covered in test_daybook_db.py; these
check the request/response wiring, auth, and error-status mapping.
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


def test_budget_summary_requires_auth():
    from app.main import app

    with TestClient(app) as client:
        resp = client.get("/api/budget/summary")
    assert resp.status_code == 401


def test_budget_summary_returns_data_layer_result(monkeypatch):
    import app.api.budget as budget_api

    monkeypatch.setattr(budget_api.daybook_db, "get_budget_summary", lambda **kw: {"month": "2026-09", "summary": None})
    client = _authed_client(monkeypatch)

    resp = client.get("/api/budget/summary")

    assert resp.status_code == 200
    assert resp.json() == {"month": "2026-09", "summary": None}


def test_list_transactions_returns_data_layer_result(monkeypatch):
    import app.api.budget as budget_api

    monkeypatch.setattr(budget_api.daybook_db, "list_transactions", lambda **kw: [{"id": "tx1", "amount": 5000}])
    client = _authed_client(monkeypatch)

    resp = client.get("/api/budget/transactions")

    assert resp.status_code == 200
    assert resp.json() == [{"id": "tx1", "amount": 5000}]


def test_add_transaction_passes_body_through(monkeypatch):
    import app.api.budget as budget_api

    captured = {}
    monkeypatch.setattr(budget_api.daybook_db, "add_transaction", lambda **kw: captured.update(kw) or {"id": "tx2", **kw})
    client = _authed_client(monkeypatch)

    resp = client.post("/api/budget/transactions", json={"amount_minor": 5000, "category_name": "Groceries"})

    assert resp.status_code == 200
    assert captured["amount_minor"] == 5000
    assert captured["direction"] == "EXPENSE"  # schema default


def test_delete_transaction_returns_404_when_not_found(monkeypatch):
    import app.api.budget as budget_api

    def boom(transaction_id):
        raise DaybookDbError(f"No transaction with id {transaction_id}")

    monkeypatch.setattr(budget_api.daybook_db, "delete_transaction", boom)
    client = _authed_client(monkeypatch)

    resp = client.delete("/api/budget/transactions/does-not-exist")

    assert resp.status_code == 404


def test_list_wallets_returns_data_layer_result(monkeypatch):
    import app.api.budget as budget_api

    monkeypatch.setattr(budget_api.daybook_db, "list_wallets", lambda: [{"id": "w1", "name": "Cash"}])
    client = _authed_client(monkeypatch)

    resp = client.get("/api/budget/wallets")

    assert resp.status_code == 200
    assert resp.json() == [{"id": "w1", "name": "Cash"}]
