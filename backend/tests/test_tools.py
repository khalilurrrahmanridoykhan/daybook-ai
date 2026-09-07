"""Tool-registry tests. Each tool is a thin wrapper around daybook_db,
so these mock the DB-layer functions directly rather than a live
Postgres connection (that's what test_daybook_db.py covers)."""

import pytest

from app.services import tools
from app.services.daybook_db import DaybookDbError
from app.services.google_calendar import GoogleCalendarError
from app.services.tools import ToolError, call_tool, current_datetime


def test_current_datetime_is_utc_iso():
    result = current_datetime()
    assert result["utc"] is True
    assert "T" in result["iso"]


def test_current_datetime_also_returns_local_time_for_calendar_use(monkeypatch):
    """Live-relevant bug this guards against: if the model only ever sees
    UTC and computes a calendar event's local time by hand, Asia/Dhaka
    (UTC+6) is exactly the kind of offset that goes silently wrong."""
    monkeypatch.setattr(tools.settings, "local_timezone", "Asia/Dhaka")
    result = current_datetime()
    assert result["local_timezone"] == "Asia/Dhaka"
    assert "T" in result["local_iso"]
    # UTC and local must actually be different clock times, not the same
    # value under two keys.
    assert result["local_iso"][:19] != result["iso"][:19]


def test_list_tasks_wraps_client_result(monkeypatch):
    monkeypatch.setattr(tools.daybook_db, "list_tasks", lambda **kw: [{"id": "t1"}])
    result = tools.list_tasks(status="TODO")
    assert result == {"tasks": [{"id": "t1"}]}


def test_create_task_passes_through_client_dict(monkeypatch):
    monkeypatch.setattr(tools.daybook_db, "create_task", lambda **kw: {"id": "t2", "title": kw["title"]})
    result = tools.create_task(title="Buy milk")
    assert result == {"id": "t2", "title": "Buy milk"}


def test_add_transaction_wraps_client_result(monkeypatch):
    monkeypatch.setattr(tools.daybook_db, "add_transaction", lambda **kw: {"id": "tx1", "amount": kw["amount_minor"]})
    result = tools.add_transaction(amount_minor=5000, category_name="Groceries")
    assert result == {"id": "tx1", "amount": 5000}


def test_get_budget_summary_wraps_client_result(monkeypatch):
    monkeypatch.setattr(tools.daybook_db, "get_budget_summary", lambda **kw: {"month": "2026-09", "summary": {}})
    result = tools.get_budget_summary(month="2026-09")
    assert result == {"month": "2026-09", "summary": {}}


def test_set_allocation_wraps_client_result(monkeypatch):
    monkeypatch.setattr(
        tools.daybook_db,
        "set_allocation",
        lambda **kw: {"month": kw["month"], "categoryId": "c1", "plannedAmount": kw["amount_minor"]},
    )
    result = tools.set_allocation(month="2026-10", amount_minor=500000, category_name="Groceries")
    assert result == {"month": "2026-10", "categoryId": "c1", "plannedAmount": 500000}


def test_set_expected_income_wraps_client_result(monkeypatch):
    monkeypatch.setattr(
        tools.daybook_db, "set_expected_income", lambda **kw: {"month": kw["month"], "expectedIncome": kw["amount_minor"]}
    )
    result = tools.set_expected_income(month="2026-10", amount_minor=800000)
    assert result == {"month": "2026-10", "expectedIncome": 800000}


def test_a_daybook_db_error_becomes_a_tool_error(monkeypatch):
    def boom(**kw):
        raise DaybookDbError("Could not reach the Daybook database")

    monkeypatch.setattr(tools.daybook_db, "list_tasks", boom)
    with pytest.raises(ToolError, match="Could not reach"):
        tools.list_tasks()


def test_list_calendar_events_wraps_client_result(monkeypatch):
    monkeypatch.setattr(tools.google_calendar, "list_events", lambda **kw: [{"id": "e1", "summary": "Dentist"}])
    result = tools.list_calendar_events(time_min="2026-10-01T00:00:00+06:00")
    assert result == {"events": [{"id": "e1", "summary": "Dentist"}]}


def test_create_calendar_event_passes_through_client_dict(monkeypatch):
    monkeypatch.setattr(
        tools.google_calendar, "create_event", lambda **kw: {"id": "e2", "summary": kw["summary"]}
    )
    result = tools.create_calendar_event(summary="Take medicine", start="2026-10-05T20:00:00+06:00")
    assert result == {"id": "e2", "summary": "Take medicine"}


def test_delete_calendar_event_passes_through_client_dict(monkeypatch):
    monkeypatch.setattr(tools.google_calendar, "delete_event", lambda **kw: {"deleted": kw["event_id"]})
    result = tools.delete_calendar_event(event_id="e1")
    assert result == {"deleted": "e1"}


def test_a_google_calendar_error_becomes_a_tool_error(monkeypatch):
    def boom(**kw):
        raise GoogleCalendarError("No Google Calendar token found")

    monkeypatch.setattr(tools.google_calendar, "list_events", boom)
    with pytest.raises(ToolError, match="No Google Calendar token found"):
        tools.list_calendar_events()


def test_send_notification_calls_notify_send(monkeypatch):
    captured = {}
    monkeypatch.setattr(tools.notify, "send", lambda **kw: captured.update(kw))

    result = tools.send_notification(message="Budget alert", title="DayBook AI")

    assert result == {"sent": True}
    assert captured == {"message": "Budget alert", "title": "DayBook AI"}


def test_a_notify_error_becomes_a_tool_error(monkeypatch):
    from app.services.notify import NotifyError

    def boom(**kw):
        raise NotifyError("No ntfy topic configured")

    monkeypatch.setattr(tools.notify, "send", boom)
    with pytest.raises(ToolError, match="No ntfy topic configured"):
        tools.send_notification(message="hi")


def test_call_tool_dispatches_by_name(monkeypatch):
    monkeypatch.setattr(tools.daybook_db, "complete_task", lambda **kw: {"id": kw["task_id"], "status": "DONE"})
    result = call_tool("complete_task", {"task_id": "t1"})
    assert result == {"id": "t1", "status": "DONE"}


def test_call_tool_unknown_name_raises():
    with pytest.raises(ToolError, match="Unknown tool"):
        call_tool("not_a_real_tool", {})
