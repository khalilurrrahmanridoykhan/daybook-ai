"""Offline tests for the ntfy push-notification client -- a MockTransport
stands in for the real ntfy server, same seam pattern as
test_ollama_client.py.
"""

import httpx
import pytest

from app.services import notify
from app.services.notify import NotifyError


def _patched_client(monkeypatch, handler):
    def fake_client():
        return httpx.Client(base_url="http://fake-ntfy", transport=httpx.MockTransport(handler))

    monkeypatch.setattr(notify, "_client", fake_client)


def test_send_posts_message_to_the_configured_topic(monkeypatch):
    monkeypatch.setattr(notify.settings, "ntfy_topic", "my-secret-topic")
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["body"] = request.content.decode()
        captured["headers"] = dict(request.headers)
        return httpx.Response(200)

    _patched_client(monkeypatch, handler)

    notify.send("Budget alert: 85% of Groceries spent")

    assert captured["path"] == "/my-secret-topic"
    assert captured["body"] == "Budget alert: 85% of Groceries spent"


def test_send_sets_title_priority_and_tags_headers_when_given(monkeypatch):
    monkeypatch.setattr(notify.settings, "ntfy_topic", "my-secret-topic")
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["headers"] = dict(request.headers)
        return httpx.Response(200)

    _patched_client(monkeypatch, handler)

    notify.send("Overspent!", title="Budget", priority=5, tags=["warning", "moneybag"])

    assert captured["headers"]["title"] == "Budget"
    assert captured["headers"]["priority"] == "5"
    assert captured["headers"]["tags"] == "warning,moneybag"


def test_send_raises_when_no_topic_configured(monkeypatch):
    monkeypatch.setattr(notify.settings, "ntfy_topic", "")
    with pytest.raises(NotifyError, match="No ntfy topic configured"):
        notify.send("hi")


def test_send_raises_notify_error_on_non_2xx(monkeypatch):
    monkeypatch.setattr(notify.settings, "ntfy_topic", "my-secret-topic")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="forbidden")

    _patched_client(monkeypatch, handler)

    with pytest.raises(NotifyError, match="403"):
        notify.send("hi")


def test_send_raises_notify_error_on_connect_failure(monkeypatch):
    monkeypatch.setattr(notify.settings, "ntfy_topic", "my-secret-topic")

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    _patched_client(monkeypatch, handler)

    with pytest.raises(NotifyError, match="Could not reach ntfy"):
        notify.send("hi")
