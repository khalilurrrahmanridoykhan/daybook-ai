from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import chat
from app.config import settings

app = FastAPI(
    title=f"{settings.assistant_name} backend",
    description=(
        "Self-hosted personal AI assistant -- streaming chat over a "
        "locally-run Ollama model, grounded by a small RAG knowledge base "
        "and a tool-use loop. No conversation data is ever sent to a "
        "third-party AI provider."
    ),
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat.router, prefix="/api")


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "assistant_name": settings.assistant_name}
