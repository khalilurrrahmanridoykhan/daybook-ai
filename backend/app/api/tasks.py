"""Direct CRUD for the dashboard's Tasks tab -- separate from the chat's
tool-calling path (app/services/tools.py), which calls the same
daybook_db.py functions but through the LLM. This is the fast, no-model-
involved path a real list UI needs.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.errors import to_http_error
from app.schemas.tasks import TaskCreate, TaskUpdate
from app.services import daybook_db
from app.services.daybook_db import DaybookDbError

router = APIRouter()


@router.get("/tasks")
def list_tasks(status: str | None = None, due_before: str | None = None) -> list[dict]:
    try:
        return daybook_db.list_tasks(status=status, due_before=due_before)
    except DaybookDbError as e:
        raise to_http_error(e) from e


@router.post("/tasks")
def create_task(body: TaskCreate) -> dict:
    try:
        return daybook_db.create_task(
            title=body.title, details=body.details, priority=body.priority, due_at=body.due_at, tags=body.tags
        )
    except DaybookDbError as e:
        raise to_http_error(e) from e


@router.patch("/tasks/{task_id}")
def update_task(task_id: str, body: TaskUpdate) -> dict:
    try:
        return daybook_db.update_task(
            task_id, title=body.title, details=body.details, priority=body.priority, due_at=body.due_at, status=body.status
        )
    except DaybookDbError as e:
        raise to_http_error(e) from e


@router.delete("/tasks/{task_id}")
def delete_task(task_id: str) -> dict:
    try:
        return daybook_db.delete_task(task_id)
    except DaybookDbError as e:
        raise to_http_error(e) from e
