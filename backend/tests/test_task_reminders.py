"""Tests for the twice-daily task-reminder script -- one ntfy
notification per still-open task, individually, not a combined summary.
"""

from scripts import task_reminders
from app.services.daybook_db import DaybookDbError
from app.services.notify import NotifyError


def test_open_tasks_excludes_done_ones(monkeypatch):
    monkeypatch.setattr(
        task_reminders.daybook_db,
        "list_tasks",
        lambda: [
            {"id": "t1", "title": "Buy milk", "status": "TODO"},
            {"id": "t2", "title": "Finished thing", "status": "DONE"},
            {"id": "t3", "title": "In progress", "status": "DOING"},
        ],
    )
    result = task_reminders.open_tasks()
    assert [t["id"] for t in result] == ["t1", "t3"]


def test_format_task_message_includes_due_date_when_present():
    message = task_reminders.format_task_message({"title": "Pay rent", "dueAt": "2026-10-01T00:00:00"})
    assert message == "Pay rent (due 2026-10-01T00:00:00)"


def test_format_task_message_omits_due_date_when_absent():
    message = task_reminders.format_task_message({"title": "Buy milk", "dueAt": None})
    assert message == "Buy milk"


def test_main_sends_one_notification_per_open_task(monkeypatch):
    monkeypatch.setattr(
        task_reminders,
        "open_tasks",
        lambda: [{"id": "t1", "title": "Buy milk", "dueAt": None}, {"id": "t2", "title": "Pay rent", "dueAt": None}],
    )
    sent = []
    monkeypatch.setattr(task_reminders.notify, "send", lambda message, **kw: sent.append(message))

    task_reminders.main()

    assert sent == ["Buy milk", "Pay rent"]


def test_main_sends_nothing_when_no_open_tasks(monkeypatch):
    monkeypatch.setattr(task_reminders, "open_tasks", lambda: [])
    called = []
    monkeypatch.setattr(task_reminders.notify, "send", lambda *a, **kw: called.append(True))

    task_reminders.main()

    assert called == []


def test_main_continues_past_one_failed_notification(monkeypatch):
    """One task's notification failing to send must not stop the rest --
    each is independent, same principle as daily_briefing.py's sections."""
    monkeypatch.setattr(
        task_reminders,
        "open_tasks",
        lambda: [{"id": "t1", "title": "Buy milk", "dueAt": None}, {"id": "t2", "title": "Pay rent", "dueAt": None}],
    )
    sent = []

    def flaky_send(message, **kw):
        if message == "Buy milk":
            raise NotifyError("ntfy returned 500")
        sent.append(message)

    monkeypatch.setattr(task_reminders.notify, "send", flaky_send)

    task_reminders.main()

    assert sent == ["Pay rent"]


def test_main_exits_nonzero_when_the_database_is_unreachable(monkeypatch):
    def boom():
        raise DaybookDbError("Could not reach the Daybook database")

    monkeypatch.setattr(task_reminders, "open_tasks", boom)

    try:
        task_reminders.main()
        assert False, "expected SystemExit"
    except SystemExit as e:
        assert e.code != 0
