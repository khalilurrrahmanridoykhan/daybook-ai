"""Offline tests for the direct-Postgres data layer. A fake connection/
cursor stands in for psycopg -- no real Postgres required, same
"replace the seam, not the logic" pattern as the HTTP-based tests
elsewhere in this suite. Response queues must match the exact order of
fetchone()/fetchall() calls each function makes.
"""

import json
from decimal import Decimal

import pytest

from app.services import daybook_db
from app.services.daybook_db import DaybookDbError


class FakeCursor:
    def __init__(self, responses):
        self._responses = list(responses)
        self.queries = []
        self.rowcount = 0

    def execute(self, query, params=None):
        self.queries.append((query, params))

    def fetchone(self):
        return self._responses.pop(0) if self._responses else None

    def fetchall(self):
        return self._responses.pop(0) if self._responses else []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeConnection:
    def __init__(self, cursor):
        self._cursor = cursor
        self.committed = False

    def cursor(self):
        return self._cursor

    def commit(self):
        self.committed = True

    @property
    def queries(self):
        return self._cursor.queries

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture(autouse=True)
def _reset_user_id_cache():
    daybook_db._user_id_cache = None
    yield
    daybook_db._user_id_cache = None


def _patch_connect(monkeypatch, cursor):
    conn = FakeConnection(cursor)
    monkeypatch.setattr(daybook_db, "_connect", lambda: conn)
    return conn


def test_get_user_id_caches_after_first_lookup(monkeypatch):
    cursor = _patch_connect(monkeypatch, FakeCursor([[{"id": "u1"}]]))
    assert daybook_db.get_user_id() == "u1"
    assert daybook_db.get_user_id() == "u1"  # second call must not query again
    assert len(cursor.queries) == 1


def test_get_user_id_raises_when_no_user_row(monkeypatch):
    _patch_connect(monkeypatch, FakeCursor([[]]))
    with pytest.raises(DaybookDbError, match="create_daybook_user"):
        daybook_db.get_user_id()


def test_get_user_id_raises_when_more_than_one_user_row(monkeypatch):
    _patch_connect(monkeypatch, FakeCursor([[{"id": "u1"}, {"id": "u2"}]]))
    with pytest.raises(DaybookDbError, match="single-user"):
        daybook_db.get_user_id()


def test_list_tasks_filters_by_status_and_due_before(monkeypatch):
    monkeypatch.setattr(daybook_db, "_user_id_cache", "u1")
    cursor = _patch_connect(monkeypatch, FakeCursor([[{"id": "t1", "title": "Buy milk"}]]))

    tasks = daybook_db.list_tasks(status="TODO", due_before="2026-10-01")

    assert tasks == [{"id": "t1", "title": "Buy milk"}]
    query, params = cursor.queries[0]
    assert '"status" = %s' in query
    assert '"dueAt" <= %s' in query
    assert params == ["u1", "TODO", "2026-10-01"]


def test_create_task_assigns_next_sort_order(monkeypatch):
    monkeypatch.setattr(daybook_db, "_user_id_cache", "u1")
    cursor = _patch_connect(
        monkeypatch,
        FakeCursor([{"next": 5}, {"id": "t2", "title": "Call the plumber"}]),
    )

    task = daybook_db.create_task(title="Call the plumber")

    assert task == {"id": "t2", "title": "Call the plumber"}
    insert_query, insert_params = cursor.queries[1]
    assert insert_params[7] == 5  # sortOrder position in the VALUES tuple


def test_complete_task_raises_when_task_not_found(monkeypatch):
    monkeypatch.setattr(daybook_db, "_user_id_cache", "u1")
    _patch_connect(monkeypatch, FakeCursor([None]))
    with pytest.raises(DaybookDbError, match="No task"):
        daybook_db.complete_task("does-not-exist")


def test_get_budget_summary_returns_none_when_month_not_found(monkeypatch):
    monkeypatch.setattr(daybook_db, "_user_id_cache", "u1")
    _patch_connect(monkeypatch, FakeCursor([None]))
    result = daybook_db.get_budget_summary(month="2026-11")
    assert result == {"month": "2026-11", "summary": None}


def test_get_budget_summary_computes_envelope_math_correctly(monkeypatch):
    """The core port-correctness test -- mirrors what summariseMonth() in
    Daybook's own services/budget.ts computes, given the same shape of
    rows: allocated = planned + rolloverIn; spent = expenses - refunds;
    available = allocated - spent."""
    monkeypatch.setattr(daybook_db, "_user_id_cache", "u1")
    _patch_connect(
        monkeypatch,
        FakeCursor(
            [
                {"id": "bm1", "expectedIncome": 800000},  # BudgetMonth lookup
                {"total": 500000},  # income sum
                [  # allocations
                    {"categoryId": "c1", "categoryName": "Groceries", "plannedAmount": 100000, "rolloverIn": 0},
                ],
                [  # transactions: one 40000 expense, one 5000 refund
                    {"categoryId": "c1", "amount": 40000, "direction": "EXPENSE"},
                    {"categoryId": "c1", "amount": 5000, "direction": "REFUND"},
                ],
            ]
        ),
    )

    result = daybook_db.get_budget_summary(month="2026-09")

    envelope = result["summary"]["envelopes"][0]
    assert envelope["categoryName"] == "Groceries"
    assert envelope["allocated"] == 100000
    assert envelope["spent"] == 35000  # 40000 - 5000
    assert envelope["available"] == 65000
    assert envelope["overspent"] is False
    assert result["summary"]["income"] == 500000
    assert result["summary"]["expectedIncome"] == 800000  # distinct from income -- see chat_orchestrator's system prompt
    assert result["summary"]["unallocated"] == 500000 - 100000
    assert result["summary"]["leftToSpend"] == 65000
    assert result["summary"]["overspentCount"] == 0


def test_get_budget_summary_flags_overspent_envelope(monkeypatch):
    monkeypatch.setattr(daybook_db, "_user_id_cache", "u1")
    _patch_connect(
        monkeypatch,
        FakeCursor(
            [
                {"id": "bm1", "expectedIncome": 0},
                {"total": 0},
                [{"categoryId": "c1", "categoryName": "Fun", "plannedAmount": 1000, "rolloverIn": 0}],
                [{"categoryId": "c1", "amount": 5000, "direction": "EXPENSE"}],
            ]
        ),
    )
    result = daybook_db.get_budget_summary(month="2026-09")
    envelope = result["summary"]["envelopes"][0]
    assert envelope["available"] == -4000
    assert envelope["overspent"] is True
    assert result["summary"]["overspentCount"] == 1


def test_get_budget_summary_income_is_json_serializable_even_as_decimal(monkeypatch):
    """Live bug: Postgres promotes SUM(bigint) to numeric to avoid
    overflow, which psycopg maps to Python's Decimal -- not JSON
    serializable, and this flows straight into an SSE tool_result. The
    earlier envelope-math tests used plain ints for the income total and
    never would have caught this; this one uses the real type psycopg
    actually returns."""
    monkeypatch.setattr(daybook_db, "_user_id_cache", "u1")
    _patch_connect(
        monkeypatch,
        FakeCursor(
            [
                {"id": "bm1", "expectedIncome": 0},
                {"total": Decimal("500000")},
                [],
                [],
            ]
        ),
    )

    result = daybook_db.get_budget_summary(month="2026-09")

    assert result["summary"]["income"] == 500000
    assert isinstance(result["summary"]["income"], int)
    json.dumps(result)  # must not raise


def test_set_allocation_creates_category_and_budget_month_when_missing(monkeypatch):
    monkeypatch.setattr(daybook_db, "_user_id_cache", "u1")
    cursor = _patch_connect(
        monkeypatch,
        FakeCursor(
            [
                None,  # category lookup by name -- not found
                {"next": 1},  # next sortOrder for new category
                None,  # budget month lookup -- not found
                {"categoryId": "c-new", "plannedAmount": 500000},  # allocation upsert RETURNING
            ]
        ),
    )

    result = daybook_db.set_allocation(month="2026-10", amount_minor=500000, category_name="Groceries")

    assert result == {"month": "2026-10", "categoryId": "c-new", "plannedAmount": 500000}
    assert cursor.committed


def test_set_expected_income(monkeypatch):
    monkeypatch.setattr(daybook_db, "_user_id_cache", "u1")
    _patch_connect(
        monkeypatch,
        FakeCursor(
            [
                None,  # budget month lookup -- not found, will be created
                {"month": "2026-10", "expectedIncome": 800000},  # update RETURNING
            ]
        ),
    )
    result = daybook_db.set_expected_income(month="2026-10", amount_minor=800000)
    assert result == {"month": "2026-10", "expectedIncome": 800000}


def test_add_transaction_reuses_existing_category_by_name(monkeypatch):
    monkeypatch.setattr(daybook_db, "_user_id_cache", "u1")
    conn = _patch_connect(
        monkeypatch,
        FakeCursor(
            [
                {"id": "c1"},  # category found by name
                {"id": "bm1"},  # budget month found
                # the allocation "ensure exists" insert has no RETURNING,
                # so no fetchone()/fetchall() call consumes a response for it
                {"id": "tx1", "categoryId": "c1", "amount": 5000, "direction": "EXPENSE", "note": None},
            ]
        ),
    )

    tx = daybook_db.add_transaction(amount_minor=5000, category_name="Groceries")

    assert tx["categoryId"] == "c1"
    assert conn.committed


def test_add_transaction_raises_when_wallet_not_found(monkeypatch):
    monkeypatch.setattr(daybook_db, "_user_id_cache", "u1")
    _patch_connect(
        monkeypatch,
        FakeCursor(
            [
                {"id": "c1"},  # category found
                {"id": "bm1"},  # budget month found
                None,  # wallet lookup -- not found
            ]
        ),
    )
    with pytest.raises(DaybookDbError, match="No wallet"):
        daybook_db.add_transaction(amount_minor=5000, category_name="Groceries", wallet_id="missing")
