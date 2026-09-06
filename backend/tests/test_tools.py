"""Tool-registry tests. Each tool is a thin wrapper around daybook_client,
so these mock the client functions directly rather than the HTTP layer
underneath them (that's what test_daybook_client.py covers)."""

import pytest

from app.services import tools
from app.services.daybook_client import DaybookApiError
from app.services.tools import ToolError, call_tool, current_datetime


def test_current_datetime_is_utc_iso():
    result = current_datetime()
    assert result["utc"] is True
    assert "T" in result["iso"]


def test_list_tasks_wraps_client_result(monkeypatch):
    monkeypatch.setattr(tools.daybook_client, "list_tasks", lambda **kw: [{"id": "t1"}])
    result = tools.list_tasks(status="TODO")
    assert result == {"tasks": [{"id": "t1"}]}


def test_create_task_passes_through_client_dict(monkeypatch):
    monkeypatch.setattr(tools.daybook_client, "create_task", lambda **kw: {"id": "t2", "title": kw["title"]})
    result = tools.create_task(title="Buy milk")
    assert result == {"id": "t2", "title": "Buy milk"}


def test_add_transaction_wraps_client_result(monkeypatch):
    monkeypatch.setattr(tools.daybook_client, "add_transaction", lambda **kw: {"id": "tx1", "amount": kw["amount_minor"]})
    result = tools.add_transaction(amount_minor=5000, category_name="Groceries")
    assert result == {"id": "tx1", "amount": 5000}


def test_get_budget_summary_wraps_client_result(monkeypatch):
    monkeypatch.setattr(tools.daybook_client, "get_budget_summary", lambda **kw: {"month": "2026-09", "summary": {}})
    result = tools.get_budget_summary(month="2026-09")
    assert result == {"month": "2026-09", "summary": {}}


def test_a_daybook_api_error_becomes_a_tool_error(monkeypatch):
    def boom(**kw):
        raise DaybookApiError("Daybook is unreachable")

    monkeypatch.setattr(tools.daybook_client, "list_tasks", boom)
    with pytest.raises(ToolError, match="unreachable"):
        tools.list_tasks()


def test_call_tool_dispatches_by_name(monkeypatch):
    monkeypatch.setattr(tools.daybook_client, "complete_task", lambda **kw: {"id": kw["task_id"], "status": "DONE"})
    result = call_tool("complete_task", {"task_id": "t1"})
    assert result == {"id": "t1", "status": "DONE"}


def test_call_tool_unknown_name_raises():
    with pytest.raises(ToolError, match="Unknown tool"):
        call_tool("not_a_real_tool", {})
