from __future__ import annotations

from pydantic import BaseModel


class EventCreate(BaseModel):
    summary: str
    start: str
    end: str | None = None
    description: str | None = None
    reminder_minutes_before: int | None = None


class EventUpdate(BaseModel):
    """Every field optional -- a PATCH, not a PUT."""

    summary: str | None = None
    start: str | None = None
    end: str | None = None
    description: str | None = None
