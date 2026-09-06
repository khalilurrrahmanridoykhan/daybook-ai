"""Endpoint-level tests for /api/speech/transcribe -- speech_to_text.transcribe
is monkeypatched so this never touches a real Whisper model. The
require_session dependency is overridden (not bypassed by omission) so
these tests exercise the endpoint's own logic, not the auth gate --
test_auth.py covers the gate itself, including that this router requires
a session at all."""

import pytest
from fastapi.testclient import TestClient

from app.api.auth import require_session
from app.main import app


@pytest.fixture(autouse=True)
def _authenticated():
    app.dependency_overrides[require_session] = lambda: "admin"
    yield
    app.dependency_overrides.pop(require_session, None)


def test_transcribe_endpoint_returns_text(monkeypatch):
    monkeypatch.setattr("app.api.speech.transcribe", lambda audio_bytes: "hello there")

    with TestClient(app) as client:
        resp = client.post(
            "/api/speech/transcribe",
            files={"file": ("clip.webm", b"fake-audio-bytes", "audio/webm")},
        )

    assert resp.status_code == 200
    assert resp.json() == {"text": "hello there"}


def test_transcribe_endpoint_returns_400_on_transcription_error(monkeypatch):
    from app.services.speech_to_text import TranscriptionError

    def _raise(audio_bytes):
        raise TranscriptionError("Could not transcribe audio: bad format")

    monkeypatch.setattr("app.api.speech.transcribe", _raise)

    with TestClient(app) as client:
        resp = client.post(
            "/api/speech/transcribe",
            files={"file": ("clip.webm", b"garbage", "audio/webm")},
        )

    assert resp.status_code == 400
    assert "Could not transcribe" in resp.json()["detail"]
