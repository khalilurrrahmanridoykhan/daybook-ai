from __future__ import annotations

from fastapi import APIRouter, HTTPException, UploadFile

from app.services.speech_to_text import TranscriptionError, transcribe

router = APIRouter()


@router.post("/speech/transcribe")
async def transcribe_audio(file: UploadFile) -> dict[str, str]:
    audio_bytes = await file.read()
    try:
        text = transcribe(audio_bytes)
    except TranscriptionError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"text": text}
