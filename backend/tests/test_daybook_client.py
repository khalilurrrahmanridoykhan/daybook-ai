"""Offline tests for the Daybook bridge client -- a MockTransport stands
in for a live Daybook deployment, same pattern as test_ollama_client.py."""

import json

import httpx
import pytest

from app.services import daybook_client
from app.services.daybook_client import DaybookApiError


def _patched_client(monkeypatch, handler):
    def fake_client(**kwargs):
        return httpx.Client(base_url="http://fake-daybook", transport=httpx.MockTransport(handler))

    monkeypatch.setattr(daybook_client, "_client", fake_client)


def test_client_includes_bearer_auth_header(monkeypatch):
    # Unlike the tests below, this checks the real _client() (not a
    # replacement), since that's the one place the auth header is set.
    monkeypatch.setattr(daybook_client.settings, "daybook_ai_secret", "shh")
    client = daybook_client._client()
    assert client.headers["authorization"] == "Bearer shh"


def test_list_tasks_sends_correct_path_and_query_params(monkeypatch):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["params"] = dict(request.url.params)
        return httpx.Response(200, json={"tasks": [{"id": "t1", "title": "Buy milk"}]})

    _patched_client(monkeypatch, handler)

    tasks = daybook_client.list_tasks(status="TODO")

    assert captured["path"] == "/api/ai/tasks"
    assert captured["params"] == {"status": "TODO"}
    assert tasks == [{"id": "t1", "title": "Buy milk"}]


def test_create_task_posts_json_body(monkeypatch):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(201, json={"task": {"id": "t2", "title": "Call the plumber"}})

    _patched_client(monkeypatch, handler)

    task = daybook_client.create_task(title="Call the plumber", priority="HIGH")

    assert captured["body"] == {"title": "Call the plumber", "priority": "HIGH"}
    assert task == {"id": "t2", "title": "Call the plumber"}


def test_get_budget_summary_parses_money_strings_to_int(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "month": "2026-09",
                "summary": {
                    "income": "500000",
                    "planned": "300000",
                    "allocated": "300000",
                    "spent": "120000",
                    "unallocated": "200000",
                    "leftToSpend": "180000",
                    "envelopes": [
                        {
                            "categoryId": "c1",
                            "planned": "100000",
                            "rolloverIn": "0",
                            "allocated": "100000",
                            "spent": "40000",
                            "available": "60000",
                            "overspent": False,
                        }
                    ],
                    "overspentCount": 0,
                },
            },
        )

    _patched_client(monkeypatch, handler)

    data = daybook_client.get_budget_summary(month="2026-09")

    assert data["summary"]["income"] == 500000
    assert isinstance(data["summary"]["income"], int)
    assert data["summary"]["envelopes"][0]["available"] == 60000


def test_list_wallets_parses_opening_balance(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"wallets": [{"id": "w1", "name": "Cash", "openingBalance": "50000"}]})

    _patched_client(monkeypatch, handler)

    wallets = daybook_client.list_wallets()
    assert wallets[0]["openingBalance"] == 50000


def test_add_transaction_parses_amount(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(201, json={"transaction": {"id": "tx1", "amount": "5000"}})

    _patched_client(monkeypatch, handler)

    tx = daybook_client.add_transaction(amount_minor=5000, category_name="Groceries")
    assert tx["amount"] == 5000


def test_raises_daybook_api_error_on_non_2xx(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="not found")

    _patched_client(monkeypatch, handler)

    with pytest.raises(DaybookApiError, match="404"):
        daybook_client.list_tasks()


def test_raises_daybook_api_error_on_connect_failure(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    _patched_client(monkeypatch, handler)

    with pytest.raises(DaybookApiError, match="is it running"):
        daybook_client.list_tasks()
