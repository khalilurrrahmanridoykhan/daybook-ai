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

    # DayBook (the real Next.js app, on Vercel) -- kept for when a real
    # Daybook deployment exists separately from this backend. Currently
    # unused: see database_url below for the self-hosted-now path, where
    # this backend and the data both live on the same VPS.
    daybook_api_base_url: str = "http://127.0.0.1:3000"
    daybook_ai_secret: str = ""

    # Self-hosted Postgres, applied from Daybook's own Prisma migration SQL
    # (see scripts/init_daybook_db.sql) -- this backend reads/writes it
    # directly via app/services/daybook_db.py while there's no separate
    # Daybook deployment to bridge to over HTTP.
    database_url: str = ""

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

    # Shared by current_datetime (tools.py) and google_calendar.py -- one
    # setting, not two, so "what time is it" and "what timezone does a new
    # calendar event get created in" can never silently drift apart.
    local_timezone: str = "Asia/Dhaka"

    # Google Calendar -- OAuth via a one-time local script
    # (scripts/setup_google_calendar.py), not an in-app login flow. See
    # that script's docstring for the Google Cloud Console setup steps.
    google_client_id: str = ""
    google_client_secret: str = ""
    google_token_path: str = "data/google_token.json"
    google_calendar_id: str = "primary"

    # A static bearer token for /api/voice/ask -- separate from the admin
    # login's cookie session, since a Siri Shortcut can't hold a browser
    # session. Generate with scripts/create_voice_api_key.py.
    voice_api_key: str = ""

    # Push notifications (Mac + iPhone) via ntfy -- a plain HTTP POST to a
    # topic URL, no account or SDK. The topic name is the only thing
    # standing between "private" and "anyone who guesses it" on the free
    # public server, so it should be long and random, not a plain word.
    ntfy_base_url: str = "https://ntfy.sh"
    ntfy_topic: str = ""


settings = Settings()
