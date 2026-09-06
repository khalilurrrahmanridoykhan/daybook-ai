from __future__ import annotations

from pydantic import BaseModel


class ChatRequest(BaseModel):
    message: str


class SessionSummary(BaseModel):
    id: str
    title: str
    created_at: str


class RenameSessionRequest(BaseModel):
    title: str
