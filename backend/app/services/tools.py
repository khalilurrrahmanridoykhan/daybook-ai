"""A tiny, explicit tool registry -- each tool is a plain Python function
plus a JSON-Schema description Ollama presents to the model for function
calling. No dynamic discovery or decorator magic: adding a tool means
adding one entry below, so the full set of things the model can actually
do is always visible in one place.

Every tool here (except current_datetime) is a thin wrapper around either
daybook_db, which talks directly to a self-hosted Postgres database using
Daybook's own schema, or google_calendar, for reminders/events on the
user's real Google Calendar. daybook_client.py (an HTTP bridge to a real
Daybook deployment) still exists, tested and ready, for when a real
Daybook app is deployed separately and this backend no longer owns the
database directly.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable
from zoneinfo import ZoneInfo

from app.config import settings
from app.services import daybook_db, google_calendar
from app.services.daybook_db import DaybookDbError
from app.services.google_calendar import GoogleCalendarError


class ToolError(RuntimeError):
    """Raised for a bad tool name or arguments the model provided, or a
    DaybookDbError/GoogleCalendarError translated into a tool-facing
    message -- sent back to the model as a tool result so it can react,
    never raised as an unhandled 500."""


def current_datetime() -> dict[str, Any]:
    """Useful for resolving relative dates the model is asked to act on
    ('remind me tomorrow', 'what's due this week'). Returns both UTC and
    local wall-clock time -- Daybook data uses UTC, but a calendar event's
    start/end must be given in local time (settings.local_timezone) since
    that's the timeZone Google is told to interpret it in. Without both,
    the model would have to convert UTC-to-local by arithmetic itself
    every time it books an event -- an easy, silent way to end up 6 hours
    off in a timezone like Asia/Dhaka (UTC+6)."""
    now_utc = datetime.now(timezone.utc)
    now_local = now_utc.astimezone(ZoneInfo(settings.local_timezone))
    return {
        "iso": now_utc.isoformat(),
        "utc": True,
        "local_iso": now_local.isoformat(),
        "local_timezone": settings.local_timezone,
    }


def _wrap(fn: Callable[..., Any], **kwargs: Any) -> dict[str, Any]:
    try:
        result = fn(**kwargs)
    except DaybookDbError as e:
        raise ToolError(str(e)) from e
    return result if isinstance(result, dict) else {"result": result}


def _wrap_calendar(fn: Callable[..., Any], **kwargs: Any) -> dict[str, Any]:
    try:
        result = fn(**kwargs)
    except GoogleCalendarError as e:
        raise ToolError(str(e)) from e
    return result if isinstance(result, dict) else {"result": result}


def list_tasks(status: str | None = None, due_before: str | None = None) -> dict[str, Any]:
    return {"tasks": _wrap(daybook_db.list_tasks, status=status, due_before=due_before)["result"]}


def create_task(
    title: str,
    details: str | None = None,
    priority: str | None = None,
    due_at: str | None = None,
    tags: list[str] | None = None,
) -> dict[str, Any]:
    return _wrap(daybook_db.create_task, title=title, details=details, priority=priority, due_at=due_at, tags=tags)


def complete_task(task_id: str) -> dict[str, Any]:
    return _wrap(daybook_db.complete_task, task_id=task_id)


def reschedule_task(task_id: str, due_at: str) -> dict[str, Any]:
    return _wrap(daybook_db.reschedule_task, task_id=task_id, due_at=due_at)


def delete_task(task_id: str) -> dict[str, Any]:
    return _wrap(daybook_db.delete_task, task_id=task_id)


def create_note(body: str, title: str | None = None) -> dict[str, Any]:
    return _wrap(daybook_db.create_note, body=body, title=title)


def search_notes(query: str | None = None) -> dict[str, Any]:
    return {"notes": _wrap(daybook_db.search_notes, query=query)["result"]}


def pin_note(note_id: str, pinned: bool = True) -> dict[str, Any]:
    return _wrap(daybook_db.pin_note, note_id=note_id, pinned=pinned)


def get_budget_summary(month: str | None = None) -> dict[str, Any]:
    return _wrap(daybook_db.get_budget_summary, month=month)


def list_wallets() -> dict[str, Any]:
    return {"wallets": _wrap(daybook_db.list_wallets)["result"]}


def add_transaction(
    amount_minor: int,
    category_name: str | None = None,
    category_id: str | None = None,
    direction: str = "EXPENSE",
    wallet_id: str | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    return _wrap(
        daybook_db.add_transaction,
        amount_minor=amount_minor,
        category_name=category_name,
        category_id=category_id,
        direction=direction,
        wallet_id=wallet_id,
        note=note,
    )


def set_allocation(
    month: str,
    amount_minor: int,
    category_name: str | None = None,
    category_id: str | None = None,
) -> dict[str, Any]:
    return _wrap(daybook_db.set_allocation, month=month, amount_minor=amount_minor, category_name=category_name, category_id=category_id)


def set_expected_income(month: str, amount_minor: int) -> dict[str, Any]:
    return _wrap(daybook_db.set_expected_income, month=month, amount_minor=amount_minor)


def list_calendar_events(
    time_min: str | None = None,
    time_max: str | None = None,
    max_results: int = 10,
) -> dict[str, Any]:
    return {
        "events": _wrap_calendar(
            google_calendar.list_events, time_min=time_min, time_max=time_max, max_results=max_results
        )["result"]
    }


def create_calendar_event(
    summary: str,
    start: str,
    end: str | None = None,
    description: str | None = None,
    reminder_minutes_before: int | None = None,
) -> dict[str, Any]:
    return _wrap_calendar(
        google_calendar.create_event,
        summary=summary,
        start=start,
        end=end,
        description=description,
        reminder_minutes_before=reminder_minutes_before,
    )


def delete_calendar_event(event_id: str) -> dict[str, Any]:
    return _wrap_calendar(google_calendar.delete_event, event_id=event_id)


TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "current_datetime",
            "description": "Get the current date and time, both in UTC and in the user's local timezone. Use this to resolve relative dates like 'tomorrow' or 'next Friday' before calling a tool that needs an exact ISO date -- use local_iso (not iso) as the basis for a calendar event's start/end, since events are created in local time.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_tasks",
            "description": "List the user's tasks, optionally filtered by status or a due-before date.",
            "parameters": {
                "type": "object",
                "properties": {
                    "status": {"type": "string", "enum": ["TODO", "DOING", "DONE"]},
                    "due_before": {"type": "string", "description": "ISO 8601 datetime"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_task",
            "description": "Create a new task.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "details": {"type": "string"},
                    "priority": {"type": "string", "enum": ["LOW", "MEDIUM", "HIGH"]},
                    "due_at": {"type": "string", "description": "ISO 8601 datetime"},
                    "tags": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["title"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "complete_task",
            "description": "Mark a task as done.",
            "parameters": {"type": "object", "properties": {"task_id": {"type": "string"}}, "required": ["task_id"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "reschedule_task",
            "description": "Change a task's due date.",
            "parameters": {
                "type": "object",
                "properties": {"task_id": {"type": "string"}, "due_at": {"type": "string", "description": "ISO 8601 datetime"}},
                "required": ["task_id", "due_at"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_task",
            "description": "Permanently delete a task.",
            "parameters": {"type": "object", "properties": {"task_id": {"type": "string"}}, "required": ["task_id"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_note",
            "description": "Create a new note.",
            "parameters": {
                "type": "object",
                "properties": {"body": {"type": "string"}, "title": {"type": "string"}},
                "required": ["body"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_notes",
            "description": "Search the user's notes by text, or list recent ones if no query is given.",
            "parameters": {"type": "object", "properties": {"query": {"type": "string"}}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "pin_note",
            "description": "Pin or unpin a note.",
            "parameters": {
                "type": "object",
                "properties": {"note_id": {"type": "string"}, "pinned": {"type": "boolean"}},
                "required": ["note_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_budget_summary",
            "description": "Get the budget envelope summary (income, allocated, spent, left to spend per category, each category's name) for a month. Defaults to the current month.",
            "parameters": {"type": "object", "properties": {"month": {"type": "string", "description": "YYYY-MM"}}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_wallets",
            "description": "List the user's wallets (cash, bank, mobile) and their opening balances.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_transaction",
            "description": "Log an expense or refund against a budget category, for the current month. Give category_name for a plain-language category (created automatically if it doesn't exist yet, along with a zero-planned allocation so it shows up in the budget summary) -- category_id only if you already looked it up.",
            "parameters": {
                "type": "object",
                "properties": {
                    "amount_minor": {"type": "integer", "description": "Amount in minor units (e.g. poisha for BDT, cents for USD) -- multiply a major-unit amount by 100."},
                    "category_name": {"type": "string"},
                    "category_id": {"type": "string"},
                    "direction": {"type": "string", "enum": ["EXPENSE", "REFUND"]},
                    "wallet_id": {"type": "string"},
                    "note": {"type": "string"},
                },
                "required": ["amount_minor"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_allocation",
            "description": "Set (or update) how much is budgeted for one category in one month -- e.g. 'set my Groceries budget for October 2026 to 5000 taka'. Works for past, current, or future months; creates the category if it doesn't exist yet.",
            "parameters": {
                "type": "object",
                "properties": {
                    "month": {"type": "string", "description": "YYYY-MM"},
                    "amount_minor": {"type": "integer", "description": "Planned amount in minor units -- multiply a major-unit amount by 100."},
                    "category_name": {"type": "string"},
                    "category_id": {"type": "string"},
                },
                "required": ["month", "amount_minor"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_expected_income",
            "description": "Set the expected total income for a whole month -- use this for a general 'set my budget for October to X' request that doesn't name a specific category. Works for past, current, or future months.",
            "parameters": {
                "type": "object",
                "properties": {
                    "month": {"type": "string", "description": "YYYY-MM"},
                    "amount_minor": {"type": "integer", "description": "Amount in minor units -- multiply a major-unit amount by 100."},
                },
                "required": ["month", "amount_minor"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_calendar_events",
            "description": "List upcoming events/reminders on the user's Google Calendar between two times. Defaults to the next 10 upcoming events if no range is given.",
            "parameters": {
                "type": "object",
                "properties": {
                    "time_min": {"type": "string", "description": "ISO 8601 datetime, inclusive lower bound"},
                    "time_max": {"type": "string", "description": "ISO 8601 datetime, exclusive upper bound"},
                    "max_results": {"type": "integer"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_calendar_event",
            "description": "Create a calendar event or reminder on the user's Google Calendar. For a plain point-in-time reminder with no duration, omit `end` -- it defaults to `start`, a normal zero-length event. Add reminder_minutes_before for a popup alert before the event.",
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {"type": "string"},
                    "start": {"type": "string", "description": "ISO 8601 datetime, in local time (see current_datetime's local_iso)"},
                    "end": {"type": "string", "description": "ISO 8601 datetime, local time; defaults to `start` for a point-in-time reminder"},
                    "description": {"type": "string"},
                    "reminder_minutes_before": {"type": "integer", "description": "Minutes before the event to show a popup alert"},
                },
                "required": ["summary", "start"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_calendar_event",
            "description": "Delete an event from the user's Google Calendar by its id.",
            "parameters": {"type": "object", "properties": {"event_id": {"type": "string"}}, "required": ["event_id"]},
        },
    },
]

TOOL_FUNCTIONS: dict[str, Callable[..., dict[str, Any]]] = {
    "current_datetime": current_datetime,
    "list_tasks": list_tasks,
    "create_task": create_task,
    "complete_task": complete_task,
    "reschedule_task": reschedule_task,
    "delete_task": delete_task,
    "create_note": create_note,
    "search_notes": search_notes,
    "pin_note": pin_note,
    "get_budget_summary": get_budget_summary,
    "list_wallets": list_wallets,
    "add_transaction": add_transaction,
    "set_allocation": set_allocation,
    "set_expected_income": set_expected_income,
    "list_calendar_events": list_calendar_events,
    "create_calendar_event": create_calendar_event,
    "delete_calendar_event": delete_calendar_event,
}


def call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    func = TOOL_FUNCTIONS.get(name)
    if func is None:
        raise ToolError(f"Unknown tool: {name}")
    return func(**arguments)
