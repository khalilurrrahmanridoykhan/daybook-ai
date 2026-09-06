"""SQLite-backed conversation memory -- sessions and messages persisted
across restarts, the part that makes this a real assistant rather than a
stateless wrapper around Ollama. Plain stdlib sqlite3, no ORM: two tables
and every query here is simple enough that an ORM would add ceremony, not
clarity.
"""

from __future__ import annotations

import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from app.config import settings

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(id),
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id);
"""


@contextmanager
def _connect(db_path: str | None = None):
    path = db_path or settings.memory_db_path
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(_SCHEMA)
        yield conn
        conn.commit()
    finally:
        conn.close()


def create_session(db_path: str | None = None, title: str = "") -> str:
    session_id = str(uuid.uuid4())
    with _connect(db_path) as conn:
        conn.execute(
            "INSERT INTO sessions (id, title, created_at) VALUES (?, ?, ?)",
            (session_id, title, datetime.now(timezone.utc).isoformat()),
        )
    return session_id


def session_exists(session_id: str, db_path: str | None = None) -> bool:
    with _connect(db_path) as conn:
        row = conn.execute("SELECT 1 FROM sessions WHERE id = ?", (session_id,)).fetchone()
    return row is not None


def append_message(session_id: str, role: str, content: str, db_path: str | None = None) -> None:
    with _connect(db_path) as conn:
        exists = conn.execute("SELECT 1 FROM sessions WHERE id = ?", (session_id,)).fetchone()
        if exists is None:
            raise ValueError(f"No session with id {session_id}")
        conn.execute(
            "INSERT INTO messages (session_id, role, content, created_at) VALUES (?, ?, ?, ?)",
            (session_id, role, content, datetime.now(timezone.utc).isoformat()),
        )


def get_history(session_id: str, db_path: str | None = None) -> list[dict]:
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT role, content, created_at FROM messages WHERE session_id = ? ORDER BY id ASC",
            (session_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def list_sessions(db_path: str | None = None) -> list[dict]:
    with _connect(db_path) as conn:
        rows = conn.execute("SELECT id, title, created_at FROM sessions ORDER BY created_at DESC").fetchall()
    return [dict(r) for r in rows]
