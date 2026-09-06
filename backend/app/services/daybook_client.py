"""Client for Daybook's own /api/ai/* bridge routes -- the only place this
backend ever touches real task/note/budget data. Same _client() seam as
ollama_client.py: tests monkeypatch it to a MockTransport, so every
function here is exercised without a live Daybook deployment.

Daybook's money.ts installs a global BigInt.prototype.toJSON returning a
string, so every amount in these responses arrives as a numeric *string*
(e.g. "450000" poisha), never a native JSON number -- _minor() below is
the one place that gets parsed back into an int, so a model reasoning
over these tool results always sees a plain integer, not a string it
might mis-handle.
"""

from __future__ import annotations

from typing import Any

import httpx

from app.config import settings


class DaybookApiError(RuntimeError):
    """Raised for anything Daybook-bridge-related that isn't a normal
    response -- connection failure or non-2xx status. Callers (tools.py)
    surface this as a tool error, never a bare crash."""


def _client(timeout: float = 30.0) -> httpx.Client:
    return httpx.Client(
        base_url=settings.daybook_api_base_url,
        headers={"Authorization": f"Bearer {settings.daybook_ai_secret}"},
        timeout=timeout,
    )


def _minor(value: Any) -> int:
    """Parses a Daybook money field (a numeric string) into an int. Passes
    through an already-int value unchanged, since some fields (e.g. a
    plannedPercent) are genuinely native numbers, not BigInt-backed."""
    return int(value) if value is not None else 0


def _request(method: str, path: str, **kwargs: Any) -> dict[str, Any]:
    try:
        with _client() as client:
            resp = client.request(method, path, **kwargs)
    except httpx.ConnectError as e:
        raise DaybookApiError(f"Could not reach Daybook at {settings.daybook_api_base_url} -- is it running? ({e})") from e
    if resp.status_code >= 400:
        raise DaybookApiError(f"Daybook {method} {path} returned {resp.status_code}: {resp.text}")
    return resp.json()


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------

def list_tasks(status: str | None = None, due_before: str | None = None) -> list[dict]:
    params = {k: v for k, v in {"status": status, "dueBefore": due_before}.items() if v}
    return _request("GET", "/api/ai/tasks", params=params)["tasks"]


def create_task(
    title: str,
    details: str | None = None,
    priority: str | None = None,
    due_at: str | None = None,
    tags: list[str] | None = None,
) -> dict:
    body = {"title": title, "details": details, "priority": priority, "dueAt": due_at, "tags": tags}
    return _request("POST", "/api/ai/tasks", json={k: v for k, v in body.items() if v is not None})["task"]


def complete_task(task_id: str) -> dict:
    return _request("PATCH", f"/api/ai/tasks/{task_id}", json={"status": "DONE"})["task"]


def reschedule_task(task_id: str, due_at: str) -> dict:
    return _request("PATCH", f"/api/ai/tasks/{task_id}", json={"dueAt": due_at})["task"]


def delete_task(task_id: str) -> dict:
    return _request("PATCH", f"/api/ai/tasks/{task_id}", json={"delete": True})


# ---------------------------------------------------------------------------
# Notes
# ---------------------------------------------------------------------------

def create_note(body: str, title: str | None = None) -> dict:
    payload = {"body": body, "title": title} if title else {"body": body}
    return _request("POST", "/api/ai/notes", json=payload)["note"]


def search_notes(query: str | None = None) -> list[dict]:
    params = {"q": query} if query else {}
    return _request("GET", "/api/ai/notes", params=params)["notes"]


def pin_note(note_id: str, pinned: bool = True) -> dict:
    return _request("PATCH", f"/api/ai/notes/{note_id}", json={"pinned": pinned})["note"]


# ---------------------------------------------------------------------------
# Budget
# ---------------------------------------------------------------------------

def _convert_summary_money(summary: dict) -> dict:
    money_fields = ("income", "planned", "allocated", "spent", "unallocated", "leftToSpend")
    out = {**summary, **{f: _minor(summary[f]) for f in money_fields if f in summary}}
    if "envelopes" in summary:
        envelope_fields = ("planned", "rolloverIn", "allocated", "spent", "available")
        out["envelopes"] = [
            {**e, **{f: _minor(e[f]) for f in envelope_fields if f in e}} for e in summary["envelopes"]
        ]
    return out


def get_budget_summary(month: str | None = None) -> dict:
    params = {"month": month} if month else {}
    data = _request("GET", "/api/ai/budget/summary", params=params)
    if data.get("summary"):
        data["summary"] = _convert_summary_money(data["summary"])
    return data


def list_wallets() -> list[dict]:
    wallets = _request("GET", "/api/ai/budget/wallets")["wallets"]
    return [{**w, "openingBalance": _minor(w.get("openingBalance"))} for w in wallets]


def add_transaction(
    amount_minor: int,
    category_name: str | None = None,
    category_id: str | None = None,
    direction: str = "EXPENSE",
    wallet_id: str | None = None,
    note: str | None = None,
) -> dict:
    body = {
        "amount": amount_minor,
        "categoryName": category_name,
        "categoryId": category_id,
        "direction": direction,
        "walletId": wallet_id,
        "note": note,
    }
    data = _request("POST", "/api/ai/budget/transactions", json={k: v for k, v in body.items() if v is not None})
    transaction = data["transaction"]
    transaction["amount"] = _minor(transaction.get("amount"))
    return transaction
