"""Generates the one login for this backend's standalone session auth.

Usage:
    .venv/bin/python scripts/create_admin.py [username]

Prints a generated password and its bcrypt hash once, to stdout only.
The hash goes into ADMIN_PASSWORD_HASH in .env; the plaintext password
is never stored anywhere -- copy it now. Also prints a generated
SESSION_SECRET if one isn't already set, since both are one-time setup.
"""

from __future__ import annotations

import secrets
import sys

import bcrypt


def generate_password() -> str:
    return secrets.token_urlsafe(18)  # 24 URL-safe chars, no ambiguous punctuation


def main() -> None:
    username = sys.argv[1] if len(sys.argv) > 1 else "admin"
    password = generate_password()
    password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12)).decode()
    session_secret = secrets.token_urlsafe(32)

    print("")
    print("──────────────────────────────────────────────")
    print(f"  ADMIN_USERNAME={username}")
    print(f"  Password (login with this): {password}")
    print("")
    print("  Put these in .env:")
    print(f"  ADMIN_USERNAME={username}")
    print(f"  ADMIN_PASSWORD_HASH={password_hash}")
    print(f"  SESSION_SECRET={session_secret}")
    print("──────────────────────────────────────────────")
    print("The plaintext password is shown once and is not stored anywhere else. Copy it now.")


if __name__ == "__main__":
    main()
