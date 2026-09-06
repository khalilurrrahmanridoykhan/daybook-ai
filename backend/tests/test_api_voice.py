"""Tests for /api/voice/ask -- the non-streaming endpoint a Siri Shortcut
calls, protected by its own static bearer token rather than the web app's
cookie session (a Shortcut has no browser to hold a cookie in).
"""

from fastapi.testclient import TestClient

from app.services import memory


def _client(monkeypatch, tmp_path) -> TestClient:
    monkeypatch.setattr("app.api.voice.settings.voice_api_key", "test-voice-key")
    monkeypatch.setattr(memory.settings, "memory_db_path", str(tmp_path / "test.sqlite3"))

    from app.main import app

    return TestClient(app)


def test_ask_requires_a_bearer_token(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    resp = client.post("/api/voice/ask", json={"message": "hi"})
    assert resp.status_code == 401


def test_ask_rejects_the_wrong_token(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    resp = client.post(
        "/api/voice/ask", json={"message": "hi"}, headers={"Authorization": "Bearer wrong-key"}
    )
    assert resp.status_code == 401


def test_ask_returns_the_assistants_reply(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)

    def fake_stream_chat_turn(session_id, message):
        yield {"type": "delta", "content": "Hello "}
        yield {"type": "delta", "content": "there."}
        yield {"type": "tool_call", "name": "current_datetime", "arguments": {}}
        yield {"type": "done"}

    monkeypatch.setattr("app.api.voice.stream_chat_turn", fake_stream_chat_turn)

    resp = client.post(
        "/api/voice/ask", json={"message": "hi"}, headers={"Authorization": "Bearer test-voice-key"}
    )

    assert resp.status_code == 200
    assert resp.json() == {"reply": "Hello there."}


def test_ask_reuses_the_same_voice_session_across_calls(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)

    def fake_stream_chat_turn(session_id, message):
        yield {"type": "delta", "content": "ok"}

    monkeypatch.setattr("app.api.voice.stream_chat_turn", fake_stream_chat_turn)
    headers = {"Authorization": "Bearer test-voice-key"}

    client.post("/api/voice/ask", json={"message": "first"}, headers=headers)
    client.post("/api/voice/ask", json={"message": "second"}, headers=headers)

    voice_sessions = [s for s in memory.list_sessions(db_path=str(tmp_path / "test.sqlite3")) if s["title"] == "Voice (Siri)"]
    assert len(voice_sessions) == 1
