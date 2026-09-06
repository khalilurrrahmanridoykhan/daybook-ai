"""Creates the single "User" row this backend's data belongs to --
daybook_db.py's get_user_id() asserts exactly one row exists and fails
loudly otherwise. Idempotent: re-running with the same email updates
that row instead of creating a duplicate (the schema's real Daybook
scripts would use Auth.js registration for this; there's no such flow
here, since this backend owns the database directly).

Usage:
    .venv/bin/python scripts/create_daybook_user.py <email>
"""

from __future__ import annotations

import sys
import uuid
from datetime import datetime, timezone

import psycopg

sys.path.insert(0, ".")
from app.config import settings  # noqa: E402


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: .venv/bin/python scripts/create_daybook_user.py <email>", file=sys.stderr)
        sys.exit(1)
    email = sys.argv[1]

    if not settings.database_url:
        print("DATABASE_URL is not set in .env", file=sys.stderr)
        sys.exit(1)

    now = datetime.now(timezone.utc)
    with psycopg.connect(settings.database_url) as conn, conn.cursor() as cur:
        cur.execute('SELECT id FROM "User" WHERE email = %s', (email,))
        row = cur.fetchone()
        if row:
            print(f"User already exists: {email} (id={row[0]})")
            return

        cur.execute('SELECT count(*) FROM "User"')
        (existing_count,) = cur.fetchone()
        if existing_count > 0:
            print(
                f"Refusing to create a second user -- {existing_count} row(s) already exist in \"User\" "
                "and this backend only supports single-user mode.",
                file=sys.stderr,
            )
            sys.exit(1)

        user_id = uuid.uuid4().hex
        cur.execute(
            'INSERT INTO "User" (id, email, "createdAt", "updatedAt") VALUES (%s, %s, %s, %s)',
            (user_id, email, now, now),
        )
        conn.commit()
        print(f"Created user: {email} (id={user_id})")


if __name__ == "__main__":
    main()
