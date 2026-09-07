from __future__ import annotations

from pydantic import BaseModel


class TaskCreate(BaseModel):
    title: str
    details: str | None = None
    priority: str | None = None
    due_at: str | None = None
    tags: list[str] | None = None


class TaskUpdate(BaseModel):
    """Every field optional -- a PATCH, not a PUT. Powers both the
    dashboard's edit form and its status-checkbox toggle (set only
    `status`), never two separately-maintained code paths."""

    title: str | None = None
    details: str | None = None
    priority: str | None = None
    due_at: str | None = None
    status: str | None = None
