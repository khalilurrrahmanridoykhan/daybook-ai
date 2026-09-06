"""Thin client around Ollama's native API (/api/chat, /api/embed) -- the
only place in this codebase that knows Ollama's specific request/response
shape. chat_stream() yields one parsed JSON object per streamed line so
the API layer can re-emit them as SSE without buffering the whole
response in memory.

_client() is a seam, not an abstraction for its own sake: tests
monkeypatch it to return an httpx.Client wired to a MockTransport, so
chat_stream()/embed()'s parsing and error-handling logic is fully
exercised without a live Ollama daemon.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import httpx

from app.config import settings


class OllamaError(RuntimeError):
    """Raised for anything Ollama-related that isn't a normal streamed
    response -- connection failure, non-2xx status, or an unparseable
    line. Callers surface this as a 502, never as a silently empty
    answer."""


def _client(timeout: float = 120.0) -> httpx.Client:
    return httpx.Client(base_url=settings.ollama_base_url, timeout=timeout)


def chat_stream(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
    model: str | None = None,
) -> Iterator[dict[str, Any]]:
    payload: dict[str, Any] = {
        "model": model or settings.ollama_model,
        "messages": messages,
        "stream": True,
    }
    if tools:
        payload["tools"] = tools

    try:
        with _client() as client, client.stream("POST", "/api/chat", json=payload) as response:
            if response.status_code != 200:
                response.read()
                raise OllamaError(f"Ollama /api/chat returned {response.status_code}: {response.text}")
            for line in response.iter_lines():
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError as e:
                    raise OllamaError(f"Malformed line from Ollama: {line!r}") from e
    except httpx.ConnectError as e:
        raise OllamaError(f"Could not reach Ollama at {settings.ollama_base_url} -- is it running? ({e})") from e


def embed(texts: list[str], model: str | None = None) -> list[list[float]]:
    payload = {"model": model or settings.ollama_embedding_model, "input": texts}
    try:
        with _client(timeout=60.0) as client:
            resp = client.post("/api/embed", json=payload)
    except httpx.ConnectError as e:
        raise OllamaError(f"Could not reach Ollama at {settings.ollama_base_url} -- is it running? ({e})") from e
    if resp.status_code != 200:
        raise OllamaError(f"Ollama /api/embed returned {resp.status_code}: {resp.text}")
    return resp.json()["embeddings"]
