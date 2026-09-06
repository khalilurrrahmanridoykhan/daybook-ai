from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.schemas.chat import ChatRequest, SessionSummary
from app.services import memory
from app.services.chat_orchestrator import stream_chat_turn

router = APIRouter()


@router.post("/chat/sessions")
def create_session() -> dict[str, str]:
    return {"session_id": memory.create_session()}


@router.get("/chat/sessions")
def list_sessions() -> list[SessionSummary]:
    return [SessionSummary(**row) for row in memory.list_sessions()]


@router.get("/chat/sessions/{session_id}/messages")
def get_messages(session_id: str) -> list[dict]:
    return memory.get_history(session_id)


@router.post("/chat/sessions/{session_id}/messages/stream")
def stream_message(session_id: str, req: ChatRequest) -> StreamingResponse:
    # Checked before the StreamingResponse is constructed, not inside the
    # generator: once streaming has started, raising HTTPException can no
    # longer produce a clean 404 -- headers are already committed.
    if not memory.session_exists(session_id):
        raise HTTPException(status_code=404, detail=f"No session with id {session_id}")

    def event_source():
        try:
            for event in stream_chat_turn(session_id, req.message):
                yield f"data: {json.dumps(event)}\n\n"
        except Exception as e:  # noqa: BLE001 -- surfaced as an SSE error event, not a bare mid-stream 500
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(event_source(), media_type="text/event-stream")
