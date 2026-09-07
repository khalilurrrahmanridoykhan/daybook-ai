"""Pushes a morning briefing -- today's tasks, today's calendar events,
and this month's budget status -- via ntfy. Meant to run once a day from
a cron entry or systemd timer, not from inside a chat turn.

Uses the same data-layer functions the chat orchestrator's tools use, so
the numbers here always match what DayBook AI would tell you if asked
directly -- never a separately-maintained "summary" implementation that
could drift out of sync.

Each section (tasks / calendar / budget) fails independently: if Google
Calendar isn't connected yet, or the database is briefly unreachable,
the other sections still get sent rather than losing the whole briefing.

Usage:
    .venv/bin/python scripts/daily_briefing.py

Cron example (8am local time daily):
    0 8 * * * cd /home/practice/apps/daybook-ai/backend && .venv/bin/python scripts/daily_briefing.py
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

sys.path.insert(0, ".")
from app.config import settings  # noqa: E402
from app.services import daybook_db, google_calendar, notify  # noqa: E402
from app.services.daybook_db import DaybookDbError  # noqa: E402
from app.services.google_calendar import GoogleCalendarError  # noqa: E402
from app.services.notify import NotifyError  # noqa: E402


def _major_units(minor: int) -> str:
    # Matches the system prompt's own minor-to-major convention (divide
    # by 100) -- good enough for a briefing line, not a precise currency
    # formatter.
    return f"{minor / 100:,.2f}"


def tasks_section() -> str | None:
    try:
        todo = daybook_db.list_tasks(status="TODO")
    except DaybookDbError as e:
        return f"Tasks: couldn't check ({e})"
    if not todo:
        return "Tasks: nothing outstanding \U0001f389"
    titles = ", ".join(t["title"] for t in todo[:5])
    more = f" (+{len(todo) - 5} more)" if len(todo) > 5 else ""
    return f"Tasks: {len(todo)} open -- {titles}{more}"


def calendar_section() -> str | None:
    now_local = datetime.now(ZoneInfo(settings.local_timezone))
    start_of_day = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    end_of_day = start_of_day + timedelta(days=1)
    try:
        events = google_calendar.list_events(
            time_min=start_of_day.isoformat(), time_max=end_of_day.isoformat(), max_results=10
        )
    except GoogleCalendarError:
        return None  # not connected yet, or a transient API issue -- skip, don't fail the whole briefing
    if not events:
        return "Calendar: nothing scheduled today"
    summaries = ", ".join(e["summary"] or "(untitled)" for e in events)
    return f"Calendar: {len(events)} event(s) today -- {summaries}"


def budget_section() -> str | None:
    try:
        result = daybook_db.get_budget_summary()
    except DaybookDbError as e:
        return f"Budget: couldn't check ({e})"
    summary = result["summary"]
    if summary is None:
        return f"Budget: nothing set for {result['month']} yet"
    line = f"Budget ({result['month']}): {_major_units(summary['spent'])} spent, {_major_units(summary['leftToSpend'])} left"
    if summary["overspentCount"] > 0:
        line += f" -- {summary['overspentCount']} categor{'y is' if summary['overspentCount'] == 1 else 'ies are'} overspent"
    return line


def main() -> None:
    lines = [s for s in (tasks_section(), calendar_section(), budget_section()) if s]
    if not lines:
        return  # nothing to say at all -- e.g. every section errored; skip rather than send a blank push
    message = "\n".join(lines)
    try:
        notify.send(message, title=f"{settings.assistant_name} morning briefing", tags=["sunrise"])
    except NotifyError as e:
        print(f"Failed to send briefing: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
