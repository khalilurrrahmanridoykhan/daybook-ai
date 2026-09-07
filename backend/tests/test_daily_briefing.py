"""Tests for the daily briefing script's section builders -- each is
independently testable logic wrapping the same daybook_db/google_calendar
functions the chat tools use, so the briefing's numbers can never drift
from what DayBook AI would say if asked directly.
"""

from scripts import daily_briefing as briefing
from app.services.daybook_db import DaybookDbError
from app.services.google_calendar import GoogleCalendarError


def test_tasks_section_lists_titles(monkeypatch):
    monkeypatch.setattr(briefing.daybook_db, "list_tasks", lambda **kw: [{"title": f"Task {i}"} for i in range(3)])
    assert briefing.tasks_section() == "Tasks: 3 open -- Task 0, Task 1, Task 2"


def test_tasks_section_truncates_and_counts_the_rest(monkeypatch):
    monkeypatch.setattr(briefing.daybook_db, "list_tasks", lambda **kw: [{"title": f"Task {i}"} for i in range(7)])
    assert briefing.tasks_section().endswith("(+2 more)")


def test_tasks_section_reports_nothing_outstanding(monkeypatch):
    monkeypatch.setattr(briefing.daybook_db, "list_tasks", lambda **kw: [])
    assert "nothing outstanding" in briefing.tasks_section()


def test_tasks_section_reports_db_error_without_raising(monkeypatch):
    def boom(**kw):
        raise DaybookDbError("Could not reach the Daybook database")

    monkeypatch.setattr(briefing.daybook_db, "list_tasks", boom)
    assert "couldn't check" in briefing.tasks_section()


def test_calendar_section_returns_none_when_not_connected(monkeypatch):
    """Not-yet-connected is a common, expected state (before
    setup_google_calendar.py has ever been run) -- must not fail the
    whole briefing forever, unlike a genuine DB error."""

    def boom(**kw):
        raise GoogleCalendarError("No Google Calendar token found")

    monkeypatch.setattr(briefing.google_calendar, "list_events", boom)
    assert briefing.calendar_section() is None


def test_calendar_section_reports_no_events(monkeypatch):
    monkeypatch.setattr(briefing.google_calendar, "list_events", lambda **kw: [])
    assert "nothing scheduled" in briefing.calendar_section()


def test_calendar_section_lists_todays_events(monkeypatch):
    monkeypatch.setattr(
        briefing.google_calendar, "list_events", lambda **kw: [{"summary": "Dentist"}, {"summary": "Standup"}]
    )
    result = briefing.calendar_section()
    assert "2 event(s)" in result
    assert "Dentist" in result and "Standup" in result


def test_budget_section_reports_nothing_set(monkeypatch):
    monkeypatch.setattr(briefing.daybook_db, "get_budget_summary", lambda **kw: {"month": "2026-09", "summary": None})
    assert "nothing set" in briefing.budget_section()


def test_budget_section_reports_spent_and_left(monkeypatch):
    monkeypatch.setattr(
        briefing.daybook_db,
        "get_budget_summary",
        lambda **kw: {"month": "2026-09", "summary": {"spent": 500000, "leftToSpend": 300000, "overspentCount": 0}},
    )
    result = briefing.budget_section()
    assert "5,000.00 spent" in result
    assert "3,000.00 left" in result
    assert "overspent" not in result


def test_budget_section_mentions_overspent_categories_pluralized(monkeypatch):
    monkeypatch.setattr(
        briefing.daybook_db,
        "get_budget_summary",
        lambda **kw: {"month": "2026-09", "summary": {"spent": 0, "leftToSpend": 0, "overspentCount": 2}},
    )
    assert "2 categories are overspent" in briefing.budget_section()


def test_budget_section_singular_for_one_overspent_category(monkeypatch):
    monkeypatch.setattr(
        briefing.daybook_db,
        "get_budget_summary",
        lambda **kw: {"month": "2026-09", "summary": {"spent": 0, "leftToSpend": 0, "overspentCount": 1}},
    )
    assert "1 category is overspent" in briefing.budget_section()


def test_main_sends_a_combined_message(monkeypatch):
    monkeypatch.setattr(briefing, "tasks_section", lambda: "Tasks: none")
    monkeypatch.setattr(briefing, "calendar_section", lambda: "Calendar: nothing")
    monkeypatch.setattr(briefing, "budget_section", lambda: "Budget: fine")
    captured = {}
    monkeypatch.setattr(briefing.notify, "send", lambda message, **kw: captured.update(message=message, **kw))

    briefing.main()

    assert captured["message"] == "Tasks: none\nCalendar: nothing\nBudget: fine"
    assert "tags" in captured


def test_main_sends_nothing_when_every_section_is_empty(monkeypatch):
    monkeypatch.setattr(briefing, "tasks_section", lambda: None)
    monkeypatch.setattr(briefing, "calendar_section", lambda: None)
    monkeypatch.setattr(briefing, "budget_section", lambda: None)
    called = []
    monkeypatch.setattr(briefing.notify, "send", lambda *a, **kw: called.append(True))

    briefing.main()

    assert called == []
