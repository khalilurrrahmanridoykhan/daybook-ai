from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import auth, chat, speech, voice
from app.api.auth import require_session
from app.config import settings

app = FastAPI(
    title=f"{settings.assistant_name} backend",
    description=(
        "Self-hosted personal AI assistant for Daybook -- streaming chat over a "
        "locally-run Ollama model, grounded by a small RAG knowledge base, a "
        "tool-use loop acting on real Daybook tasks/notes/budget data, and a "
        "single-user login. No conversation data is ever sent to a "
        "third-party AI provider."
    ),
    version="0.2.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
    allow_credentials=True,  # the session cookie must survive cross-origin requests during local/tunnel dev
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api")
app.include_router(chat.router, prefix="/api", dependencies=[Depends(require_session)])
app.include_router(speech.router, prefix="/api", dependencies=[Depends(require_session)])
# Its own bearer-token auth (see require_voice_key), not the cookie
# session above -- a Siri Shortcut can't hold a browser session.
app.include_router(voice.router, prefix="/api")


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "assistant_name": settings.assistant_name}
