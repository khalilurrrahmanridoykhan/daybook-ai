# Ridoy AI

A self-hosted, open-weight personal AI assistant. Streaming chat, persistent memory, RAG grounding over a small knowledge base, and a tool-use loop -- running entirely on your own infrastructure. No conversation data is ever sent to Anthropic, OpenAI, Google, or any other third-party AI provider; the only "brain" involved is a locally-run [Ollama](https://ollama.com) model.

## Why this exists

Claude, GPT, and Gemini are products of companies with billions of dollars in training compute -- no individual reproduces that. What's actually buildable, and what this is, is **your own AI product**: your own UI, your own memory, your own retrieval-grounded knowledge, your own tool-use guardrails, sitting on top of an open-weight model you run yourself. The model underneath is a swappable implementation detail (`OLLAMA_MODEL` in `.env`); everything else here is the part that's actually yours.

## Architecture

- **`backend/`** -- FastAPI. One orchestrator (`app/services/chat_orchestrator.py`) ties together:
  - **Memory** -- SQLite-backed conversation sessions, persisted across restarts (`app/services/memory.py`).
  - **RAG** -- a small in-memory vector store (`app/rag/store.py`) built from markdown files in `data/knowledge/`, embedded via Ollama's real `nomic-embed-text` model by default, with a dependency-free local hashing embedder as an offline-testable fallback (`app/rag/embeddings.py`).
  - **Tool-use** -- a tiny, explicit tool registry (`app/services/tools.py`: `calculate`, `current_datetime`) called through Ollama's native `/api/chat` tools mechanism.
  - **The Ollama client** (`app/services/ollama_client.py`) -- the one place that knows Ollama's request/response shape; everything else talks to it through plain Python types.
  - **Speech-to-text** (`app/services/speech_to_text.py`) -- self-hosted via [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (CTranslate2, CPU int8, no PyTorch, no cloud speech API).
- **`frontend/`** -- Next.js. A single streaming chat page reading Server-Sent Events off the backend by hand (no `EventSource`, since it doesn't support POST bodies). A mic button records a voice message and sends it to `/api/speech/transcribe`; replies are read aloud with the browser's built-in `SpeechSynthesis` (toggleable) -- local to the browser/OS, not a network call, consistent with the rest of this project even though the voice itself sounds more robotic than a cloud TTS API would.

## A real, live-verified finding: qwen2.5-coder:7b doesn't populate Ollama's structured `tool_calls` field

Verified directly against this project's own Ollama instance, not assumed: asked to call `calculate`, the model produces the *correct* JSON -- `{"name": "calculate", "arguments": {"expression": "384 * 27"}}` -- but as plain `message.content` text, not in the `tool_calls` array Ollama's API defines for well-behaved tool-calling models. A naive integration would silently show that raw JSON to the user as if it were the answer.

`chat_orchestrator._parse_fallback_tool_call()` fixes this: it recognizes that exact shape and executes the tool anyway, and the streaming loop holds back any response starting with `{` from the live stream until the round finishes and it's clear whether that's a disguised tool call or just an answer that happens to start with a brace -- so nothing fabricated-looking ever reaches the user. Covered by `tests/test_chat_orchestrator.py`, including the case where a brace-prefixed response is *not* a tool call and needs to be flushed as a normal answer instead.

## Voice, tested with real spoken audio, not a canned sample

Speech-to-text is fast on this hardware -- **1.2 seconds steady-state** once the `base.en` model is loaded (measured live on this project's own VPS), well under the LLM reply time, so listening is never the bottleneck. Accuracy is the honest trade-off of a small model: given real spoken audio saying *"What is Bangladesh EWARS?"*, it transcribed *"What is Bangladesh U.S.?"* -- `base.en` doesn't reliably catch uncommon acronyms outside its training vocabulary. `WHISPER_MODEL_SIZE=small.en` trades some latency and RAM for meaningfully better accuracy on domain-specific terms, if that matters more than speed for your use.

## Running it

```bash
# Ollama must already be running locally with a model pulled:
#   ollama pull qwen2.5-coder:7b   (or any tool-use-capable model)
#   ollama pull nomic-embed-text

cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload --port 8300

# separate terminal
cd frontend
npm install
cp .env.example .env.local
npm run dev   # http://localhost:3300
```

## Adding to its knowledge

Drop a `.md` or `.txt` file into `backend/data/knowledge/` and restart the backend -- paragraphs are chunked (max ~800 chars, never split mid-paragraph) and embedded automatically. No ingestion pipeline, because a personal assistant's knowledge base doesn't need one at this scale.

## Tests

```bash
cd backend
USE_LOCAL_EMBEDDER=true pytest tests/ -v
```

36 tests, all offline (mocked HTTP transport for the Ollama client, a local hashing embedder for RAG, an in-memory SQLite DB for memory) -- no live Ollama daemon required to run the suite.

## Deployment notes (this project's own VPS deployment)

Deployed to a shared VPS that also runs unrelated production services (a separate CommuniPlan/BRAC malaria-surveillance system) -- deliberately isolated from them: its own directory (`~/apps/ridoy-ai`), its own ports (backend 8300, frontend 3300, chosen clear of every port already in use on that box), no changes to that system's nginx config, systemd units, or database. The only thing shared is the box's pre-existing Ollama daemon, used strictly through its HTTP API -- no changes to its systemd service or already-pulled models.

Given the VPS's 2 shared CPU cores (no GPU), a full RAG-grounded chat turn on `qwen2.5-coder:7b` takes roughly 15-45 seconds depending on context size and whether the model is already warm. That's the honest tradeoff of genuinely self-hosted inference on modest hardware, not a bug -- a faster response means either a smaller model (`qwen2.5:3b` runs noticeably faster, at some quality cost) or better hardware, both a one-line `OLLAMA_MODEL` change away.

**Currently running via `setsid`, not systemd** -- survives the SSH session ending, but not a reboot. Promoting to a proper `systemd` unit (matching the pattern of this VPS's other services) needs root, which this session didn't have a password for; that's the next concrete step, not a hidden gap.

**Not yet exposed publicly** -- reachable only via `127.0.0.1` on the VPS itself, or through an SSH tunnel:
```bash
ssh -L 3300:127.0.0.1:3300 -L 8300:127.0.0.1:8300 practice@<vps-ip>
# then open http://localhost:3300 locally
```
Adding a real subdomain + nginx vhost + TLS is a deliberate follow-up decision, not done here, to avoid touching the existing production nginx configuration without an explicit go-ahead.

## License

MIT
