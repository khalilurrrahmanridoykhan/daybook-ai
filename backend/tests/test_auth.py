"""Tests for the standalone session auth -- password verification and
JWT session tokens, plus the require_session dependency's rejection
paths, entirely offline."""

from datetime import datetime, timedelta, timezone

import jwt
from fastapi.testclient import TestClient

from app.services.auth import (
    COOKIE_NAME,
    create_session_token,
    hash_password,
    verify_password,
    verify_session_token,
)


def test_hash_and_verify_password_round_trip():
    hashed = hash_password("correct horse battery staple")
    assert verify_password("correct horse battery staple", hashed) is True
    assert verify_password("wrong password", hashed) is False


def test_verify_password_rejects_empty_hash():
    assert verify_password("anything", "") is False


def test_create_and_verify_session_token(monkeypatch):
    monkeypatch.setattr("app.services.auth.settings.session_secret", "test-secret")
    token = create_session_token("admin")
    assert verify_session_token(token) == "admin"


def test_verify_session_token_rejects_garbage(monkeypatch):
    monkeypatch.setattr("app.services.auth.settings.session_secret", "test-secret")
    assert verify_session_token("not-a-real-token") is None


def test_verify_session_token_rejects_wrong_secret(monkeypatch):
    monkeypatch.setattr("app.services.auth.settings.session_secret", "secret-a")
    token = create_session_token("admin")
    monkeypatch.setattr("app.services.auth.settings.session_secret", "secret-b")
    assert verify_session_token(token) is None


def test_verify_session_token_rejects_expired_token(monkeypatch):
    monkeypatch.setattr("app.services.auth.settings.session_secret", "test-secret")
    now = datetime.now(timezone.utc)
    expired = jwt.encode(
        {"sub": "admin", "iat": now - timedelta(hours=2), "exp": now - timedelta(hours=1)},
        "test-secret",
        algorithm="HS256",
    )
    assert verify_session_token(expired) is None


def test_login_endpoint_rejects_wrong_password(monkeypatch):
    from app.main import app

    monkeypatch.setattr("app.api.auth.settings.admin_username", "admin")
    monkeypatch.setattr("app.api.auth.settings.admin_password_hash", hash_password("realpassword"))

    with TestClient(app) as client:
        resp = client.post("/api/auth/login", json={"username": "admin", "password": "wrong"})
    assert resp.status_code == 401


def test_login_endpoint_accepts_correct_password_and_sets_cookie(monkeypatch):
    from app.main import app

    monkeypatch.setattr("app.api.auth.settings.admin_username", "admin")
    monkeypatch.setattr("app.api.auth.settings.admin_password_hash", hash_password("realpassword"))
    monkeypatch.setattr("app.services.auth.settings.session_secret", "test-secret")

    with TestClient(app) as client:
        resp = client.post("/api/auth/login", json={"username": "admin", "password": "realpassword"})
        assert resp.status_code == 200
        assert COOKIE_NAME in resp.cookies


def test_chat_endpoint_requires_session(monkeypatch):
    from app.main import app

    with TestClient(app) as client:
        resp = client.post("/api/chat/sessions")
    assert resp.status_code == 401


def test_speech_endpoint_requires_session(monkeypatch):
    from app.main import app

    with TestClient(app) as client:
        resp = client.post("/api/speech/transcribe", files={"file": ("clip.webm", b"x", "audio/webm")})
    assert resp.status_code == 401


def test_health_endpoint_does_not_require_session():
    from app.main import app

    with TestClient(app) as client:
        resp = client.get("/api/health")
    assert resp.status_code == 200
