"""Standalone session auth for this backend -- previously absent entirely
(main.py had no auth dependency; chat.py/speech.py were open behind CORS
only). Necessary now that the assistant has read/write access to real
personal data. Deliberately independent of Daybook's own Auth.js session:
cross-origin cookie sharing between a Vercel origin and this VPS origin
isn't worth the complexity for one personal user.

A signed, httpOnly cookie holding a JWT is the whole mechanism -- one
hardcoded username/password (bcrypt-hashed, checked here), no
registration, no user table.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app.config import settings

COOKIE_NAME = "daybook_ai_session"
_ALGORITHM = "HS256"


def verify_password(password: str, password_hash: str) -> bool:
    if not password_hash:
        return False
    return bcrypt.checkpw(password.encode(), password_hash.encode())


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12)).decode()


def create_session_token(username: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": username,
        "iat": now,
        "exp": now + timedelta(hours=settings.session_max_age_hours),
    }
    return jwt.encode(payload, settings.session_secret, algorithm=_ALGORITHM)


def verify_session_token(token: str) -> str | None:
    """Returns the username if the token is valid and unexpired, else None
    -- never raises, so callers can treat any failure mode identically."""
    try:
        payload = jwt.decode(token, settings.session_secret, algorithms=[_ALGORITHM])
    except jwt.PyJWTError:
        return None
    return payload.get("sub")
