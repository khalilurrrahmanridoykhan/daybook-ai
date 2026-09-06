"""Offline tests for the speech-to-text service -- _get_model() is
monkeypatched to a fake model so these never download or run a real
Whisper model."""

import pytest

from app.services.speech_to_text import TranscriptionError, transcribe


class _FakeSegment:
    def __init__(self, text: str) -> None:
        self.text = text


class _FakeModel:
    def __init__(self, segments: list[_FakeSegment]) -> None:
        self._segments = segments

    def transcribe(self, audio, beam_size=1):
        return iter(self._segments), {"language": "en"}


class _BrokenModel:
    def transcribe(self, audio, beam_size=1):
        raise RuntimeError("could not decode audio")


def test_transcribe_joins_segment_texts(monkeypatch):
    monkeypatch.setattr(
        "app.services.speech_to_text._get_model",
        lambda: _FakeModel([_FakeSegment(" Hello "), _FakeSegment("world.")]),
    )
    assert transcribe(b"fake-audio-bytes") == "Hello world."


def test_transcribe_skips_blank_segments(monkeypatch):
    monkeypatch.setattr(
        "app.services.speech_to_text._get_model",
        lambda: _FakeModel([_FakeSegment("  "), _FakeSegment("Actual speech.")]),
    )
    assert transcribe(b"fake-audio-bytes") == "Actual speech."


def test_transcribe_rejects_empty_audio():
    with pytest.raises(TranscriptionError, match="No audio data"):
        transcribe(b"")


def test_transcribe_wraps_decode_failure(monkeypatch):
    monkeypatch.setattr("app.services.speech_to_text._get_model", lambda: _BrokenModel())
    with pytest.raises(TranscriptionError, match="Could not transcribe"):
        transcribe(b"garbage-not-audio")
