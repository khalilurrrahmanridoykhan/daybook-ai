from __future__ import annotations

from pydantic import BaseModel


class TransactionCreate(BaseModel):
    amount_minor: int
    category_name: str | None = None
    category_id: str | None = None
    direction: str = "EXPENSE"
    wallet_id: str | None = None
    note: str | None = None
