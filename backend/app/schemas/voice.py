from __future__ import annotations

from pydantic import BaseModel


class VoiceRequest(BaseModel):
    message: str


class VoiceResponse(BaseModel):
    reply: str
