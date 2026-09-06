"""A single-shot, non-streaming endpoint for voice clients -- specifically
an iOS/macOS Shortcut triggered via "Hey Siri, <custom phrase>" -- that
can't easily consume Server-Sent Events or hold a browser login cookie.

Protected by its own static bearer token (VOICE_API_KEY), not the
cookie-based session auth the web app uses: a Shortcut can send a fixed
header on every request, but has no browser to keep a session cookie in.
"""

from __future__ import annotations

import hmac

from fastapi import APIRouter, Depends, HTTPException, Request

from app.config import settings
from app.schemas.voice import VoiceRequest, VoiceResponse
from app.services import memory
from app.services.chat_orchestrator import stream_chat_turn

router = APIRouter()

# All voice questions land in one persistent, well-known session rather
# than a fresh one per call -- so a follow-up question has the prior
# exchange as context, and so what you asked Siri is visible in the same
# chat history sidebar as everything else, not a separate hidden log.
_VOICE_SESSION_TITLE = "Voice (Siri)"


def require_voice_key(request: Request) -> None:
    auth = request.headers.get("authorization", "")
    scheme, _, token = auth.partition(" ")
    if scheme.lower() != "bearer" or not settings.voice_api_key or not hmac.compare_digest(token, settings.voice_api_key):
        raise HTTPException(status_code=401, detail="Missing or invalid voice API key")


def _get_or_create_voice_session() -> str:
    for s in memory.list_sessions():
        if s["title"] == _VOICE_SESSION_TITLE:
            return s["id"]
    return memory.create_session(title=_VOICE_SESSION_TITLE)


@router.post("/voice/ask", dependencies=[Depends(require_voice_key)])
def ask(req: VoiceRequest) -> VoiceResponse:
    session_id = _get_or_create_voice_session()
    # stream_chat_turn is a generator built for SSE -- consuming it fully
    # here just runs one whole turn synchronously and collects the answer,
    # same underlying orchestrator as the web app, no logic duplicated.
    reply = "".join(
        event["content"] for event in stream_chat_turn(session_id, req.message) if event["type"] == "delta"
    )
    return VoiceResponse(reply=reply)
