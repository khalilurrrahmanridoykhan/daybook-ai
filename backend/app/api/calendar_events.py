"""Direct CRUD for the dashboard's Schedule tab -- separate from the
chat's tool-calling path (app/services/tools.py), which calls the same
google_calendar.py functions but through the LLM.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.errors import to_http_error
from app.schemas.calendar_events import EventCreate, EventUpdate
from app.services import google_calendar
from app.services.google_calendar import GoogleCalendarError

router = APIRouter()


@router.get("/calendar/events")
def list_events(time_min: str | None = None, time_max: str | None = None, max_results: int = 20) -> list[dict]:
    try:
        return google_calendar.list_events(time_min=time_min, time_max=time_max, max_results=max_results)
    except GoogleCalendarError as e:
        raise to_http_error(e) from e


@router.post("/calendar/events")
def create_event(body: EventCreate) -> dict:
    try:
        return google_calendar.create_event(
            summary=body.summary,
            start=body.start,
            end=body.end,
            description=body.description,
            reminder_minutes_before=body.reminder_minutes_before,
        )
    except GoogleCalendarError as e:
        raise to_http_error(e) from e


@router.patch("/calendar/events/{event_id}")
def update_event(event_id: str, body: EventUpdate) -> dict:
    try:
        return google_calendar.update_event(
            event_id, summary=body.summary, start=body.start, end=body.end, description=body.description
        )
    except GoogleCalendarError as e:
        raise to_http_error(e) from e


@router.delete("/calendar/events/{event_id}")
def delete_event(event_id: str) -> dict:
    try:
        return google_calendar.delete_event(event_id)
    except GoogleCalendarError as e:
        raise to_http_error(e) from e
