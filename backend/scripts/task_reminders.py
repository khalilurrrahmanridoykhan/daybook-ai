"""Pushes one ntfy notification per still-open task (status != DONE) --
individually, one by one, not a single combined summary (that's what
daily_briefing.py is for). Meant to run twice a day from cron, at
whatever two times you want reminded (e.g. 9:20am and 9:30pm local time)
-- this script itself doesn't know the schedule, it just sends the
reminders whenever it's run.

Usage:
    .venv/bin/python scripts/task_reminders.py

Cron example (9:20am and 9:30pm Asia/Dhaka == 03:20 and 15:30 UTC):
    20 3  * * * cd /home/practice/apps/daybook-ai/backend && .venv/bin/python scripts/task_reminders.py >> task_reminders.log 2>&1
    30 15 * * * cd /home/practice/apps/daybook-ai/backend && .venv/bin/python scripts/task_reminders.py >> task_reminders.log 2>&1
"""

from __future__ import annotations

import sys

sys.path.insert(0, ".")
from app.services import daybook_db, notify  # noqa: E402
from app.services.daybook_db import DaybookDbError  # noqa: E402
from app.services.notify import NotifyError  # noqa: E402


def open_tasks() -> list[dict]:
    return [t for t in daybook_db.list_tasks() if t["status"] != "DONE"]


def format_task_message(task: dict) -> str:
    message = task["title"]
    if task.get("dueAt"):
        message += f" (due {task['dueAt']})"
    return message


def main() -> None:
    try:
        tasks = open_tasks()
    except DaybookDbError as e:
        print(f"Could not list tasks: {e}", file=sys.stderr)
        sys.exit(1)

    if not tasks:
        return  # nothing open -- no notification at all, not even an empty one

    for task in tasks:
        try:
            notify.send(format_task_message(task), title="Task reminder", tags=["memo"])
        except NotifyError as e:
            print(f"Failed to send reminder for task {task['id']}: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
