"""Speech-to-text via faster-whisper (a CTranslate2 reimplementation of
OpenAI's Whisper) -- fully self-hosted, CPU int8 inference, no PyTorch
and no cloud speech API. The model weights download once from Hugging
Face on first use and are cached on disk after that; nothing about a
specific recording is ever sent anywhere once the model is present.

_get_model() is a seam, same pattern as ollama_client._client(): tests
monkeypatch it to return a fake model, so transcribe()'s segment-joining
logic is exercised without downloading or running a real model.
"""

from __future__ import annotations

import io

from app.config import settings

_model = None


class TranscriptionError(RuntimeError):
    """Raised when audio can't be decoded or transcribed -- surfaced by
    the endpoint as a 400/502, not a silent empty transcript."""


def _get_model():
    global _model
    if _model is None:
        from faster_whisper import WhisperModel

        _model = WhisperModel(settings.whisper_model_size, device="cpu", compute_type="int8")
    return _model


def transcribe(audio_bytes: bytes) -> str:
    if not audio_bytes:
        raise TranscriptionError("No audio data received.")

    model = _get_model()
    try:
        segments, _info = model.transcribe(io.BytesIO(audio_bytes), beam_size=1)
        text = " ".join(seg.text.strip() for seg in segments if seg.text.strip())
    except Exception as e:  # noqa: BLE001 -- faster-whisper/PyAV raise a range of decode errors we don't want to enumerate
        raise TranscriptionError(f"Could not transcribe audio: {e}") from e

    return text.strip()
