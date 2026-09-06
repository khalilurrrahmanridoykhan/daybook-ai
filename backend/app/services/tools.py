"""A tiny, explicit tool registry -- each tool is a plain Python function
plus a JSON-Schema description Ollama presents to the model for function
calling. No dynamic discovery or decorator magic: adding a tool means
adding one entry below, so the full set of things the model can actually
do is always visible in one place.

Every tool here (except current_datetime) is a thin wrapper around
daybook_db, which talks directly to a self-hosted Postgres database using
Daybook's own schema. This is the self-hosted-now path -- daybook_client.py
(an HTTP bridge to a real Daybook deployment) still exists, tested and
ready, for when a real Daybook app is deployed separately and this
backend no longer owns the database directly.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

from app.services import daybook_db
from app.services.daybook_db import DaybookDbError


class ToolError(RuntimeError):
    """Raised for a bad tool name or arguments the model provided, or a
    DaybookDbError translated into a tool-facing message -- sent back to
    the model as a tool result so it can react, never raised as an
    unhandled 500."""


def current_datetime() -> dict[str, Any]:
    """Useful for resolving relative dates the model is asked to act on
    ('remind me tomorrow', 'what's due this week')."""
    now = datetime.now(timezone.utc)
    return {"iso": now.isoformat(), "utc": True}


def _wrap(fn: Callable[..., Any], **kwargs: Any) -> dict[str, Any]:
    try:
        result = fn(**kwargs)
    except DaybookDbError as e:
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


TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "current_datetime",
            "description": "Get the current date and time in UTC. Use this to resolve relative dates like 'tomorrow' or 'next Friday' before calling a tool that needs an exact ISO date.",
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
}


def call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    func = TOOL_FUNCTIONS.get(name)
    if func is None:
        raise ToolError(f"Unknown tool: {name}")
    return func(**arguments)
