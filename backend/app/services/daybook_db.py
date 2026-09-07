"""Direct Postgres access to Daybook's own data -- the self-hosted
alternative to daybook_client.py's HTTP bridge, used while Daybook itself
has no separate deployment: this backend and its database both live on
the same VPS.

The schema is exactly Daybook's own Prisma schema (table/column names
included, e.g. "userId", "dueAt") applied here from the same migration
SQL the daybook repo generates -- see
scripts/init_daybook_db.sql. This makes the data forward-compatible with
a real Daybook deployment pointed at the same database later, which is
the whole point of matching it exactly rather than inventing a simpler
schema of our own.

One deliberate difference from Prisma: ids here are uuid4 hex strings,
not cuid()s, since there's no Node runtime on this side to generate
those. Equally opaque, equally unique -- Daybook's own schema treats
`id` as a plain TEXT primary key, so this is a drop-in.

Single-user only: _get_user_id() assumes (and asserts) exactly one row
in "User", matching this whole project's single-user design -- see
scripts/create_daybook_user.py, which is what creates that one row.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Any

import psycopg
from psycopg.rows import dict_row

from app.config import settings


class DaybookDbError(RuntimeError):
    """Raised for anything Daybook-database-related that isn't a normal
    query result -- connection failure, or a referenced row that doesn't
    exist. Callers (tools.py) surface this as a tool error, never a bare
    crash."""


def _connect() -> psycopg.Connection:
    try:
        return psycopg.connect(settings.database_url, row_factory=dict_row)
    except psycopg.OperationalError as e:
        raise DaybookDbError(f"Could not reach the Daybook database -- is Postgres running? ({e})") from e


def _new_id() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _current_month() -> str:
    d = date.today()
    return f"{d.year}-{d.month:02d}"


_user_id_cache: str | None = None


def get_user_id() -> str:
    global _user_id_cache
    if _user_id_cache is not None:
        return _user_id_cache
    with _connect() as conn, conn.cursor() as cur:
        cur.execute('SELECT id FROM "User" LIMIT 2')
        rows = cur.fetchall()
    if not rows:
        raise DaybookDbError('No row in "User" -- run scripts/create_daybook_user.py first.')
    if len(rows) > 1:
        raise DaybookDbError('More than one row in "User" -- this backend only supports single-user mode.')
    _user_id_cache = rows[0]["id"]
    return _user_id_cache


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------

def list_tasks(status: str | None = None, due_before: str | None = None) -> list[dict]:
    user_id = get_user_id()
    clauses = ['"userId" = %s']
    params: list[Any] = [user_id]
    if status:
        clauses.append('"status" = %s')
        params.append(status)
    if due_before:
        clauses.append('"dueAt" <= %s')
        params.append(due_before)

    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            f'SELECT id, title, details, status, priority, "dueAt", tags, "completedAt" '
            f'FROM "Task" WHERE {" AND ".join(clauses)} ORDER BY "dueAt" ASC NULLS LAST, "sortOrder" ASC LIMIT 100',
            params,
        )
        return cur.fetchall()


def create_task(
    title: str,
    details: str | None = None,
    priority: str | None = None,
    due_at: str | None = None,
    tags: list[str] | None = None,
) -> dict:
    user_id = get_user_id()
    task_id = _new_id()
    now = _now()
    with _connect() as conn, conn.cursor() as cur:
        cur.execute('SELECT COALESCE(MAX("sortOrder"), 0) + 1 AS next FROM "Task" WHERE "userId" = %s', (user_id,))
        sort_order = cur.fetchone()["next"]
        cur.execute(
            'INSERT INTO "Task" (id, "userId", title, details, priority, "dueAt", tags, "sortOrder", "createdAt", "updatedAt") '
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
            'RETURNING id, title, details, status, priority, "dueAt", tags',
            (task_id, user_id, title, details, priority or "MEDIUM", due_at, tags or [], sort_order, now, now),
        )
        row = cur.fetchone()
        conn.commit()
        return row


def _update_task(task_id: str, **fields: Any) -> dict:
    user_id = get_user_id()
    set_clauses = ", ".join(f'"{k}" = %s' for k in fields)
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            f'UPDATE "Task" SET {set_clauses}, "updatedAt" = %s WHERE id = %s AND "userId" = %s '
            'RETURNING id, title, details, status, priority, "dueAt", tags, "completedAt"',
            (*fields.values(), _now(), task_id, user_id),
        )
        row = cur.fetchone()
        if row is None:
            raise DaybookDbError(f"No task with id {task_id}")
        conn.commit()
        return row


def complete_task(task_id: str) -> dict:
    return _update_task(task_id, status="DONE", completedAt=_now())


def reschedule_task(task_id: str, due_at: str) -> dict:
    return _update_task(task_id, dueAt=due_at)


def update_task(
    task_id: str,
    title: str | None = None,
    details: str | None = None,
    priority: str | None = None,
    due_at: str | None = None,
    status: str | None = None,
) -> dict:
    """General-purpose edit -- the one path both the dashboard's edit form
    and its status-checkbox toggle use, so "mark done" is never a
    separately-maintained code path from a full edit."""
    fields: dict[str, Any] = {}
    if title is not None:
        fields["title"] = title
    if details is not None:
        fields["details"] = details
    if priority is not None:
        fields["priority"] = priority
    if due_at is not None:
        fields["dueAt"] = due_at
    if status is not None:
        fields["status"] = status
        fields["completedAt"] = _now() if status == "DONE" else None
    if not fields:
        raise DaybookDbError("No fields given to update")
    return _update_task(task_id, **fields)


def delete_task(task_id: str) -> dict:
    user_id = get_user_id()
    with _connect() as conn, conn.cursor() as cur:
        cur.execute('DELETE FROM "Task" WHERE id = %s AND "userId" = %s', (task_id, user_id))
        deleted = cur.rowcount > 0
        conn.commit()
    if not deleted:
        raise DaybookDbError(f"No task with id {task_id}")
    return {"deleted": True}


# ---------------------------------------------------------------------------
# Notes
# ---------------------------------------------------------------------------

def create_note(body: str, title: str | None = None) -> dict:
    user_id = get_user_id()
    note_id = _new_id()
    now = _now()
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            'INSERT INTO "Note" (id, "userId", title, body, "createdAt", "updatedAt") '
            "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id, title, body, pinned",
            (note_id, user_id, title or "", body, now, now),
        )
        row = cur.fetchone()
        conn.commit()
        return row


def search_notes(query: str | None = None) -> list[dict]:
    user_id = get_user_id()
    with _connect() as conn, conn.cursor() as cur:
        if query:
            cur.execute(
                'SELECT id, title, body, pinned FROM "Note" '
                'WHERE "userId" = %s AND "archivedAt" IS NULL AND (title ILIKE %s OR body ILIKE %s) '
                'ORDER BY pinned DESC, "updatedAt" DESC LIMIT 50',
                (user_id, f"%{query}%", f"%{query}%"),
            )
        else:
            cur.execute(
                'SELECT id, title, body, pinned FROM "Note" WHERE "userId" = %s AND "archivedAt" IS NULL '
                'ORDER BY pinned DESC, "updatedAt" DESC LIMIT 50',
                (user_id,),
            )
        return cur.fetchall()


def pin_note(note_id: str, pinned: bool = True) -> dict:
    user_id = get_user_id()
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            'UPDATE "Note" SET pinned = %s, "updatedAt" = %s WHERE id = %s AND "userId" = %s '
            "RETURNING id, title, body, pinned",
            (pinned, _now(), note_id, user_id),
        )
        row = cur.fetchone()
        if row is None:
            raise DaybookDbError(f"No note with id {note_id}")
        conn.commit()
        return row


# ---------------------------------------------------------------------------
# Budget
# ---------------------------------------------------------------------------

def _get_or_create_budget_month(cur: psycopg.Cursor, user_id: str, month: str) -> str:
    cur.execute('SELECT id FROM "BudgetMonth" WHERE "userId" = %s AND month = %s', (user_id, month))
    row = cur.fetchone()
    if row:
        return row["id"]
    budget_month_id = _new_id()
    now = _now()
    cur.execute(
        'INSERT INTO "BudgetMonth" (id, "userId", month, "createdAt", "updatedAt") VALUES (%s, %s, %s, %s, %s)',
        (budget_month_id, user_id, month, now, now),
    )
    return budget_month_id


def _resolve_or_create_category(cur: psycopg.Cursor, user_id: str, category_name: str | None, category_id: str | None) -> str:
    if category_id:
        cur.execute('SELECT id FROM "Category" WHERE id = %s AND "userId" = %s', (category_id, user_id))
        row = cur.fetchone()
        if not row:
            raise DaybookDbError(f"No category with id {category_id}")
        return row["id"]

    cur.execute('SELECT id FROM "Category" WHERE "userId" = %s AND name ILIKE %s', (user_id, category_name))
    row = cur.fetchone()
    if row:
        return row["id"]

    new_id = _new_id()
    now = _now()
    cur.execute('SELECT COALESCE(MAX("sortOrder"), 0) + 1 AS next FROM "Category" WHERE "userId" = %s', (user_id,))
    sort_order = cur.fetchone()["next"]
    cur.execute(
        'INSERT INTO "Category" (id, "userId", name, "sortOrder", "createdAt", "updatedAt") '
        "VALUES (%s, %s, %s, %s, %s, %s)",
        (new_id, user_id, category_name, sort_order, now, now),
    )
    return new_id


def get_budget_summary(month: str | None = None) -> dict:
    user_id = get_user_id()
    month = month or _current_month()

    with _connect() as conn, conn.cursor() as cur:
        cur.execute('SELECT id, "expectedIncome" FROM "BudgetMonth" WHERE "userId" = %s AND month = %s', (user_id, month))
        budget_month = cur.fetchone()
        if not budget_month:
            return {"month": month, "summary": None}
        budget_month_id = budget_month["id"]
        expected_income = budget_month["expectedIncome"]

        # Postgres promotes SUM(bigint) to numeric (to avoid overflow),
        # which psycopg maps to Decimal -- not JSON-serializable, and this
        # value flows straight into an SSE tool_result. Cast back to int
        # here at the data layer's boundary, not further up where a
        # Decimal would otherwise silently leak into a JSON response.
        cur.execute('SELECT COALESCE(SUM(amount), 0) AS total FROM "IncomeEntry" WHERE "budgetMonthId" = %s', (budget_month_id,))
        income = int(cur.fetchone()["total"])

        cur.execute(
            'SELECT a."categoryId", c.name AS "categoryName", a."plannedAmount", a."rolloverIn" '
            'FROM "Allocation" a JOIN "Category" c ON c.id = a."categoryId" WHERE a."budgetMonthId" = %s',
            (budget_month_id,),
        )
        allocations = cur.fetchall()

        cur.execute(
            'SELECT "categoryId", amount, direction FROM "Transaction" WHERE "budgetMonthId" = %s',
            (budget_month_id,),
        )
        transactions = cur.fetchall()

    spent_by_category: dict[str, int] = {}
    for t in transactions:
        signed = -t["amount"] if t["direction"] == "REFUND" else t["amount"]
        spent_by_category[t["categoryId"]] = spent_by_category.get(t["categoryId"], 0) + signed

    envelopes = []
    for a in allocations:
        allocated = a["plannedAmount"] + a["rolloverIn"]
        spent = spent_by_category.get(a["categoryId"], 0)
        available = allocated - spent
        envelopes.append(
            {
                "categoryId": a["categoryId"],
                "categoryName": a["categoryName"],
                "planned": a["plannedAmount"],
                "rolloverIn": a["rolloverIn"],
                "allocated": allocated,
                "spent": spent,
                "available": available,
                "overspent": available < 0,
            }
        )

    planned_total = sum(e["planned"] for e in envelopes)
    return {
        "month": month,
        "summary": {
            # Two genuinely different things: expectedIncome is the
            # planned/expected figure set via set_expected_income;
            # income is the sum of actually-recorded IncomeEntry rows.
            # A plain "what's my budget" question is almost always
            # asking about expectedIncome.
            "expectedIncome": expected_income,
            "income": income,
            "planned": planned_total,
            "allocated": sum(e["allocated"] for e in envelopes),
            "spent": sum(e["spent"] for e in envelopes),
            "unallocated": income - planned_total,
            "leftToSpend": sum(e["available"] for e in envelopes),
            "envelopes": envelopes,
            "overspentCount": sum(1 for e in envelopes if e["overspent"]),
        },
    }


def set_allocation(month: str, amount_minor: int, category_name: str | None = None, category_id: str | None = None) -> dict:
    user_id = get_user_id()
    with _connect() as conn, conn.cursor() as cur:
        resolved_category_id = _resolve_or_create_category(cur, user_id, category_name, category_id)
        budget_month_id = _get_or_create_budget_month(cur, user_id, month)
        cur.execute(
            'INSERT INTO "Allocation" (id, "budgetMonthId", "categoryId", "plannedAmount") VALUES (%s, %s, %s, %s) '
            'ON CONFLICT ("budgetMonthId", "categoryId") DO UPDATE SET "plannedAmount" = EXCLUDED."plannedAmount" '
            'RETURNING id, "categoryId", "plannedAmount"',
            (_new_id(), budget_month_id, resolved_category_id, amount_minor),
        )
        row = cur.fetchone()
        conn.commit()
        return {"month": month, "categoryId": row["categoryId"], "plannedAmount": row["plannedAmount"]}


def set_expected_income(month: str, amount_minor: int) -> dict:
    user_id = get_user_id()
    with _connect() as conn, conn.cursor() as cur:
        budget_month_id = _get_or_create_budget_month(cur, user_id, month)
        cur.execute(
            'UPDATE "BudgetMonth" SET "expectedIncome" = %s, "updatedAt" = %s WHERE id = %s '
            'RETURNING month, "expectedIncome"',
            (amount_minor, _now(), budget_month_id),
        )
        row = cur.fetchone()
        conn.commit()
        return dict(row)


def list_wallets() -> list[dict]:
    user_id = get_user_id()
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            'SELECT id, name, type, "openingBalance" FROM "Wallet" WHERE "userId" = %s AND "archivedAt" IS NULL '
            'ORDER BY "sortOrder" ASC',
            (user_id,),
        )
        return cur.fetchall()


def add_transaction(
    amount_minor: int,
    category_name: str | None = None,
    category_id: str | None = None,
    direction: str = "EXPENSE",
    wallet_id: str | None = None,
    note: str | None = None,
) -> dict:
    user_id = get_user_id()
    month = _current_month()
    now = _now()

    with _connect() as conn, conn.cursor() as cur:
        resolved_category_id = _resolve_or_create_category(cur, user_id, category_name, category_id)
        budget_month_id = _get_or_create_budget_month(cur, user_id, month)

        if wallet_id:
            cur.execute('SELECT id FROM "Wallet" WHERE id = %s AND "userId" = %s', (wallet_id, user_id))
            if not cur.fetchone():
                raise DaybookDbError(f"No wallet with id {wallet_id}")

        # A transaction against a category with no allocation yet for this
        # month would otherwise be invisible in get_budget_summary (which
        # only iterates existing Allocation rows, matching Daybook's own
        # envelope-summary logic) -- ensure a (possibly zero-planned) one
        # exists so a spend logged in conversation shows up immediately
        # without a separate "set my budget" step first.
        cur.execute(
            'INSERT INTO "Allocation" (id, "budgetMonthId", "categoryId") VALUES (%s, %s, %s) '
            'ON CONFLICT ("budgetMonthId", "categoryId") DO NOTHING',
            (_new_id(), budget_month_id, resolved_category_id),
        )

        transaction_id = _new_id()
        cur.execute(
            'INSERT INTO "Transaction" (id, "userId", "budgetMonthId", "categoryId", "walletId", amount, direction, note, "spentAt", "createdAt", "updatedAt") '
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
            'RETURNING id, "categoryId", amount, direction, note',
            (transaction_id, user_id, budget_month_id, resolved_category_id, wallet_id, amount_minor, direction, note, now, now, now),
        )
        row = cur.fetchone()
        conn.commit()
        return row


def list_transactions(month: str | None = None) -> list[dict]:
    user_id = get_user_id()
    month = month or _current_month()
    with _connect() as conn, conn.cursor() as cur:
        cur.execute('SELECT id FROM "BudgetMonth" WHERE "userId" = %s AND month = %s', (user_id, month))
        budget_month = cur.fetchone()
        if not budget_month:
            return []
        cur.execute(
            'SELECT t.id, t."categoryId", c.name AS "categoryName", t."walletId", t.amount, t.direction, t.note, t."spentAt" '
            'FROM "Transaction" t JOIN "Category" c ON c.id = t."categoryId" '
            'WHERE t."budgetMonthId" = %s ORDER BY t."spentAt" DESC LIMIT 200',
            (budget_month["id"],),
        )
        return cur.fetchall()


def delete_transaction(transaction_id: str) -> dict:
    user_id = get_user_id()
    with _connect() as conn, conn.cursor() as cur:
        cur.execute('DELETE FROM "Transaction" WHERE id = %s AND "userId" = %s', (transaction_id, user_id))
        deleted = cur.rowcount > 0
        conn.commit()
    if not deleted:
        raise DaybookDbError(f"No transaction with id {transaction_id}")
    return {"deleted": True}
