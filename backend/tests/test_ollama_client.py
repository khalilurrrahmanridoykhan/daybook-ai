"""Offline tests for the Ollama client -- a MockTransport stands in for
the real daemon so chat_stream()/embed()'s parsing and error handling is
fully exercised with no live Ollama process required."""

import httpx
import pytest

from app.services import ollama_client


def _patched_client(monkeypatch, handler, timeout_param_name="timeout"):
    def fake_client(**kwargs):
        return httpx.Client(base_url="http://fake-ollama", transport=httpx.MockTransport(handler))

    monkeypatch.setattr(ollama_client, "_client", fake_client)


def test_chat_stream_yields_parsed_json_lines(monkeypatch):
    body = (
        b'{"message": {"role": "assistant", "content": "Hel"}, "done": false}\n'
        b'{"message": {"role": "assistant", "content": "lo"}, "done": false}\n'
        b'{"message": {"role": "assistant", "content": ""}, "done": true}\n'
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/chat"
        return httpx.Response(200, content=body)

    _patched_client(monkeypatch, handler)

    chunks = list(ollama_client.chat_stream([{"role": "user", "content": "hi"}]))
    assert [c["message"]["content"] for c in chunks] == ["Hel", "lo", ""]
    assert chunks[-1]["done"] is True


def test_chat_stream_includes_tools_in_payload_when_given(monkeypatch):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json as _json

        captured["payload"] = _json.loads(request.content)
        return httpx.Response(200, content=b'{"message": {"content": "ok"}, "done": true}\n')

    _patched_client(monkeypatch, handler)

    tools = [{"type": "function", "function": {"name": "calculate"}}]
    list(ollama_client.chat_stream([{"role": "user", "content": "hi"}], tools=tools))
    assert captured["payload"]["tools"] == tools


def test_chat_stream_raises_on_non_200(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="internal error")

    _patched_client(monkeypatch, handler)

    with pytest.raises(ollama_client.OllamaError, match="500"):
        list(ollama_client.chat_stream([{"role": "user", "content": "hi"}]))


def test_chat_stream_raises_on_malformed_line(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not json\n")

    _patched_client(monkeypatch, handler)

    with pytest.raises(ollama_client.OllamaError, match="Malformed line"):
        list(ollama_client.chat_stream([{"role": "user", "content": "hi"}]))


def test_chat_stream_raises_ollama_error_on_connect_failure(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    _patched_client(monkeypatch, handler)

    with pytest.raises(ollama_client.OllamaError, match="is it running"):
        list(ollama_client.chat_stream([{"role": "user", "content": "hi"}]))


def test_embed_returns_embeddings_list(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/embed"
        return httpx.Response(200, json={"embeddings": [[0.1, 0.2], [0.3, 0.4]]})

    _patched_client(monkeypatch, handler)

    result = ollama_client.embed(["a", "b"])
    assert result == [[0.1, 0.2], [0.3, 0.4]]


def test_embed_raises_on_non_200(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="model not found")

    _patched_client(monkeypatch, handler)

    with pytest.raises(ollama_client.OllamaError, match="404"):
        ollama_client.embed(["a"])
