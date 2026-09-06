"""Env-driven settings, pydantic-settings pattern -- same shape as the
AMR Stewardship Briefing API's app/config.py."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    assistant_name: str = "DayBook AI"

    # Self-hosted only: no cloud LLM provider is ever called by this app.
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen2.5-coder:7b"
    ollama_embedding_model: str = "nomic-embed-text"

    # Self-hosted speech-to-text (faster-whisper, CPU int8) -- "base.en"
    # is the balance point on a 2-core CPU box: noticeably more accurate
    # than "tiny.en" without the latency of "small.en" or larger.
    whisper_model_size: str = "base.en"

    # Falls back to a dependency-free local hashing embedder when true --
    # lets the RAG pipeline run and be tested with no Ollama daemon at all
    # (e.g. on a laptop that doesn't have it installed).
    use_local_embedder: bool = False

    memory_db_path: str = "data/daybook_ai.sqlite3"
    knowledge_base_dir: str = "data/knowledge"

    # Retrieved documents below this cosine-similarity score are treated as
    # "nothing relevant found" rather than stuffed into the prompt -- keeps
    # a plain "hi" from dragging in unrelated knowledge-base chunks (which
    # both confuses the reply and adds real prompt-eval latency on a
    # CPU-only box). 0.35 is a starting point tuned against nomic-embed-text
    # scores observed in this project's own real usage, not a guess.
    rag_relevance_threshold: float = 0.35

    cors_origins: str = "http://localhost:3300"

    # DayBook (the real Next.js app, on Vercel) -- the only place this
    # backend ever reads or writes real task/note/budget data. Never a
    # direct database connection: the bridge is Daybook's own /api/ai/*
    # routes, authenticated with this shared secret, so Daybook's own
    # validation and business logic is always what runs, never a Python
    # reimplementation of it.
    daybook_api_base_url: str = "http://127.0.0.1:3000"
    daybook_ai_secret: str = ""

    # This backend has no auth of its own until now (previously wide open
    # behind CORS only) -- necessary once it gains read/write access to
    # real personal data instead of a demo knowledge base. Standalone
    # login, independent of Daybook's own Auth.js session: cross-origin
    # cookie sharing between a Vercel origin and this VPS origin isn't
    # worth the complexity for one personal user.
    admin_username: str = "admin"
    admin_password_hash: str = ""
    session_secret: str = ""
    session_max_age_hours: int = 24 * 30


settings = Settings()
