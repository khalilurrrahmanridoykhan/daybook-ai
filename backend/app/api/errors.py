"""Maps a data-layer error to the right HTTP status -- shared by the
tasks/calendar_events/budget routers, which call daybook_db.py and
google_calendar.py directly rather than through tools.py's ToolError
translation (the chat orchestrator's path)."""

from __future__ import annotations

from fastapi import HTTPException


def to_http_error(e: Exception) -> HTTPException:
    # Every "not found by id" DaybookDbError/GoogleCalendarError message
    # contains "with id" by convention (see daybook_db.py/
    # google_calendar.py's delete_task/delete_transaction/update_event
    # etc.). Live-caught bug: matching on a bare "No " prefix instead was
    # too broad -- it also caught "No Google Calendar token found", a
    # not-configured-yet backend problem, and wrongly reported it as a
    # 404 rather than the 502 it actually is.
    if "with id" in str(e):
        return HTTPException(status_code=404, detail=str(e))
    return HTTPException(status_code=502, detail=str(e))
