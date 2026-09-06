# DayBook AI

A self-hosted, open-weight personal AI assistant for [Daybook](https://github.com/khalilurrrahmanridoykhan/daybook) -- the user's own tasks, notes, and envelope-budgeting app. Streaming chat, persistent memory, RAG grounding, voice, and a tool-use loop that actually creates and reads real tasks, notes, and budget entries -- running entirely on your own infrastructure. No conversation data, and no Daybook data, is ever sent to Anthropic, OpenAI, Google, or any other third-party AI provider; the only "brain" involved is a locally-run [Ollama](https://ollama.com) model.

Single-user, login-gated. This isn't a public demo -- it's a real daily-use tool with read/write access to real personal data.

## Why this exists

Claude, GPT, and Gemini are products of companies with billions of dollars in training compute -- no individual reproduces that. What's actually buildable is **your own AI product**: your own UI, your own memory, your own retrieval-grounded knowledge, your own tool-use guardrails, sitting on top of an open-weight model you run yourself, wired into a real app you actually use. The model underneath is a swappable implementation detail (`OLLAMA_MODEL` in `.env`); everything else here is the part that's actually yours.

## Architecture

- **`backend/`** -- FastAPI. One orchestrator (`app/services/chat_orchestrator.py`) ties together:
  - **Memory** -- SQLite-backed conversation sessions, persisted across restarts (`app/services/memory.py`).
  - **RAG** -- a small in-memory vector store built from markdown files in `data/knowledge/` (envelope-budgeting concepts, example phrasings), embedded via Ollama's real `nomic-embed-text` model by default, with a dependency-free local hashing embedder as an offline-testable fallback.
  - **Tool-use** -- an explicit registry (`app/services/tools.py`) of Daybook capabilities: list/create/complete/reschedule/delete tasks, create/search/pin notes, budget summary, wallets, and logging transactions -- each a thin wrapper around `app/services/daybook_client.py`, which talks to Daybook's own `/api/ai/*` bridge routes over HTTPS. **The business logic lives in Daybook's Next.js app, never reimplemented here** -- this backend only ever calls Daybook's API, never touches its database directly.
  - **Google Calendar** (`app/services/google_calendar.py`) -- reminders and events on the user's real Google Calendar (list/create/delete), authorized once via a local OAuth script (`scripts/setup_google_calendar.py`), not an in-app login flow. See "Connecting Google Calendar" below.
  - **The Ollama client** (`app/services/ollama_client.py`) -- the one place that knows Ollama's request/response shape.
  - **Speech-to-text** (`app/services/speech_to_text.py`) -- self-hosted via [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (CTranslate2, CPU int8, no PyTorch, no cloud speech API).
  - **Auth** (`app/services/auth.py`, `app/api/auth.py`) -- a signed httpOnly-cookie session, checked against one bcrypt-hashed username/password. No registration, no user table. Independent of Daybook's own Auth.js session on purpose: cross-origin cookie sharing between a Vercel origin and this VPS origin isn't worth the complexity for one personal user. Guards the chat and speech routers; `/api/auth/*` and `/api/health` stay open.
- **`frontend/`** -- Next.js. A login page, then a streaming chat page reading Server-Sent Events off the backend by hand (no `EventSource`, since it doesn't support POST bodies). A mic button records a voice message and sends it to `/api/speech/transcribe`; replies are read aloud with the browser's built-in `SpeechSynthesis` (toggleable).

## The bridge to Daybook

This backend never touches Daybook's Postgres database directly. Instead, Daybook's own Next.js app exposes authenticated routes under `/api/ai/*` (in the [`daybook`](https://github.com/khalilurrrahmanridoykhan/daybook) repo) -- the same bearer-secret pattern Daybook already used for its Vercel Cron routes, plus one more guarantee: the AI always acts as one specific hardcoded account (`AI_BOUND_USER_EMAIL` on Daybook's side), never a userId this backend supplies, so a leaked secret can only ever touch that one account.

Money is the one real wrinkle: Daybook stores amounts as `BigInt` minor units and serializes them as numeric *strings* over JSON (`"450000"`, not `450000`) -- `daybook_client.py` is the one place that parses those back into plain ints before a tool result is ever shown to the model.

## Two real, live-verified findings

**qwen2.5-coder:7b doesn't always populate Ollama's structured `tool_calls` field.** Verified directly against this project's own Ollama instance: asked to call a tool, the model sometimes produces the *correct* JSON as plain `message.content` text instead of Ollama's `tool_calls` array. `chat_orchestrator._parse_fallback_tool_call()` recognizes that exact shape and executes the tool anyway, holding back the live stream until the round resolves so the raw JSON never reaches the user disguised as an answer. Covered by `tests/test_chat_orchestrator.py`.

**Speech-to-text is fast; accuracy is the honest trade-off of a small model.** 1.2 seconds steady-state on this hardware once `base.en` is loaded -- well under the LLM's reply time. But given real spoken audio saying an uncommon term, it can still mis-hear it; `WHISPER_MODEL_SIZE=small.en` trades latency/RAM for accuracy if that matters more for your vocabulary.

## Running it

```bash
# Ollama must already be running locally with a model pulled:
#   ollama pull qwen2.5-coder:7b   (or any tool-use-capable model)
#   ollama pull nomic-embed-text

cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in DAYBOOK_API_BASE_URL, DAYBOOK_AI_SECRET, and the admin login (see below)
uvicorn app.main:app --reload --port 8300

# separate terminal
cd frontend
npm install
cp .env.example .env.local
npm run dev   # http://localhost:3300 -- redirects to /login
```

### Creating the login

```bash
cd backend
.venv/bin/python scripts/create_admin.py <username>
```

Prints a generated password once, plus the `ADMIN_USERNAME`/`ADMIN_PASSWORD_HASH`/`SESSION_SECRET` values to put in `.env`. The plaintext password is never stored anywhere else -- copy it immediately.

`DAYBOOK_AI_SECRET` must match `AI_BACKEND_SECRET` in Daybook's own `.env` (same value, different variable name because it's a different codebase).

## Connecting Google Calendar

Reminders and events go through the real Google Calendar API, not a Daybook feature. One-time setup, on a machine with a browser (not the headless VPS):

1. In [console.cloud.google.com](https://console.cloud.google.com), create/select a project, enable the **Google Calendar API**, then under OAuth consent screen add your own Google account as a **test user** (staying in "Testing" mode is normal and expected for a single personal account -- no Google review needed).
2. Create an OAuth client ID, application type **Desktop app**, and put its Client ID/Secret into `backend/.env` as `GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET`.
3. `cd backend && .venv/bin/python scripts/setup_google_calendar.py` -- opens a Google consent screen in your browser, then writes a refresh token to `GOOGLE_TOKEN_PATH` (default `data/google_token.json`).
4. Copy that one token file to the same path on the VPS and restart the backend there.

The token file is a live credential (already covered by `.gitignore`) -- never commit it. `LOCAL_TIMEZONE` (default `Asia/Dhaka`) is the one setting both `current_datetime` and new calendar events use, so the two can't silently drift apart.

## Adding to its knowledge

Drop a `.md` or `.txt` file into `backend/data/knowledge/` and restart the backend -- paragraphs are chunked (max ~800 chars, never split mid-paragraph) and embedded automatically.

## Tests

```bash
cd backend
USE_LOCAL_EMBEDDER=true pytest tests/ -v
```

112 tests, all offline (mocked HTTP transport for the Ollama client and the Daybook bridge client, a fake Google Calendar service object, a local hashing embedder for RAG, an in-memory SQLite DB for memory) -- no live Ollama daemon, Daybook deployment, or Google account required to run the suite.

## Deployment notes (this project's own VPS deployment)

**Live at [ai.krrkhan.com](https://ai.krrkhan.com).**

Deployed to a shared VPS that also runs unrelated production services (a separate CommuniPlan/BRAC malaria-surveillance system) -- deliberately isolated from them: its own directory (`~/apps/daybook-ai`), its own ports (backend 8300, frontend 3300), and its own single nginx site file that was added without opening or editing any of the box's other eight site configs. The only thing shared is the box's pre-existing Ollama daemon, used strictly through its HTTP API.

Public routing: nginx terminates TLS (Let's Encrypt, auto-renewing) at `ai.krrkhan.com` and proxies `/api/` to the backend, everything else to the frontend -- both on the same origin, so the login cookie and every fetch stay same-site with no CORS needed. `proxy_buffering off` on the `/api/` location is a deliberate, necessary choice: without it, nginx would buffer the whole SSE response and release it all at once instead of streaming token-by-token.

Given the VPS's 2 shared CPU cores (no GPU), a full RAG-grounded chat turn on `qwen2.5-coder:7b` takes roughly 15-45 seconds depending on context size and whether the model is already warm. That's the honest tradeoff of genuinely self-hosted inference on modest hardware, not a bug.

**HTTPS is not cosmetic here** -- the browser's microphone API (`getUserMedia`) only works on a secure context, so TLS was a functional requirement for voice input to work publicly.

## License

MIT
