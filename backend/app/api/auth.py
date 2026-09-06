from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from app.config import settings
from app.services.auth import COOKIE_NAME, create_session_token, verify_password, verify_session_token

router = APIRouter()


class LoginRequest(BaseModel):
    username: str
    password: str


@router.post("/auth/login")
def login(body: LoginRequest, response: Response) -> dict[str, bool]:
    if body.username != settings.admin_username or not verify_password(body.password, settings.admin_password_hash):
        raise HTTPException(status_code=401, detail="Wrong username or password.")

    token = create_session_token(body.username)
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=settings.session_max_age_hours * 3600,
    )
    return {"ok": True}


@router.post("/auth/logout")
def logout(response: Response) -> dict[str, bool]:
    response.delete_cookie(COOKIE_NAME)
    return {"ok": True}


@router.get("/auth/me")
def me(request: Request) -> dict[str, str | None]:
    token = request.cookies.get(COOKIE_NAME)
    username = verify_session_token(token) if token else None
    return {"username": username}


def require_session(request: Request) -> str:
    """FastAPI dependency guarding the chat/speech routers -- applied in
    main.py, not to this router or /api/health."""
    token = request.cookies.get(COOKIE_NAME)
    username = verify_session_token(token) if token else None
    if username is None:
        raise HTTPException(status_code=401, detail="Not logged in.")
    return username
