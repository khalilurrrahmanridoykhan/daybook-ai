"""Direct CRUD for the dashboard's Expenses tab -- separate from the
chat's tool-calling path (app/services/tools.py), which calls the same
daybook_db.py functions but through the LLM.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.errors import to_http_error
from app.schemas.budget import TransactionCreate
from app.services import daybook_db
from app.services.daybook_db import DaybookDbError

router = APIRouter()


@router.get("/budget/summary")
def get_budget_summary(month: str | None = None) -> dict:
    try:
        return daybook_db.get_budget_summary(month=month)
    except DaybookDbError as e:
        raise to_http_error(e) from e


@router.get("/budget/transactions")
def list_transactions(month: str | None = None) -> list[dict]:
    try:
        return daybook_db.list_transactions(month=month)
    except DaybookDbError as e:
        raise to_http_error(e) from e


@router.post("/budget/transactions")
def add_transaction(body: TransactionCreate) -> dict:
    try:
        return daybook_db.add_transaction(
            amount_minor=body.amount_minor,
            category_name=body.category_name,
            category_id=body.category_id,
            direction=body.direction,
            wallet_id=body.wallet_id,
            note=body.note,
        )
    except DaybookDbError as e:
        raise to_http_error(e) from e


@router.delete("/budget/transactions/{transaction_id}")
def delete_transaction(transaction_id: str) -> dict:
    try:
        return daybook_db.delete_transaction(transaction_id)
    except DaybookDbError as e:
        raise to_http_error(e) from e


@router.get("/budget/wallets")
def list_wallets() -> list[dict]:
    try:
        return daybook_db.list_wallets()
    except DaybookDbError as e:
        raise to_http_error(e) from e
