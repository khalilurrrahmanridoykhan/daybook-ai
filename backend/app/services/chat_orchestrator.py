"""Orchestrates one chat turn: persist the user's message, retrieve
grounding context from the knowledge base, run the model against Ollama
with tool-use enabled, execute any tool calls the model makes, and stream
the final answer back as a sequence of typed events. This is the one
place that ties memory + RAG + tools + the Ollama client together --
each of those stays a plain, independently testable module.

Event types yielded to the API layer (and re-emitted as SSE):
  {"type": "citations", "citations": [...]}   -- once, if RAG found anything
  {"type": "delta", "content": "..."}         -- streamed answer text
  {"type": "tool_call", "name": ..., "arguments": {...}}
  {"type": "tool_result", "name": ..., "result": {...}}
  {"type": "done"}
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from typing import Any

from app.config import settings
from app.rag.knowledge_base import get_knowledge_store
from app.services import memory, ollama_client
from app.services.tools import TOOL_FUNCTIONS, TOOL_SCHEMAS, ToolError, call_tool

SYSTEM_PROMPT_TEMPLATE = """You are {assistant_name}, a personal AI assistant for Daybook -- the \
user's own tasks, notes, and envelope-budgeting app. You run entirely on self-hosted, open-weight \
infrastructure; this conversation is never sent to Anthropic, OpenAI, Google, or any other \
third-party AI provider.

You can actually act on the user's real Daybook data through tools -- list, create, complete, and \
reschedule tasks; create and search notes; check the budget summary, list wallets, and log \
transactions. Always call the relevant tool rather than guessing what's in their tasks/notes/budget \
or telling them to check the app themselves -- you have direct access, so use it. Call \
current_datetime first whenever you need to resolve a relative date ("tomorrow", "next Friday") \
before passing an exact ISO date to another tool.

Money in Daybook is minor units (e.g. poisha for BDT, cents for USD) -- when the user says an amount \
in everyday terms ("500 taka", "$12.50"), convert it to minor units yourself (multiply by 100) \
before calling add_transaction; when you report a summary back to the user, convert minor units back \
to major units for a normal-sounding sentence.

context_documents below is a small knowledge base explaining Daybook's own concepts (envelope \
budgeting, rollover, categories) -- use it if the user asks what a term means. If it says "(no \
relevant documents found)", that just means this message didn't need it -- do NOT mention the \
knowledge base or apologize for lacking information unless the user actually asked something it \
should have answered.

For a greeting or small talk, just reply naturally and briefly -- do not treat every message as a \
task. Be direct and concise otherwise too. Never claim to be a product of Anthropic, OpenAI, or \
Google -- you are a self-hosted open-weight model wrapped in {assistant_name}'s own application, and \
you should say so if asked.

context_documents:
{context_block}
"""

MAX_TOOL_ROUNDS = 3

# Measured, not assumed: retrieval scores for "hi" (0.43-0.51 against this
# project's actual knowledge base, via real nomic-embed-text embeddings)
# overlap with scores for genuinely relevant questions (0.43-0.66) too much
# for a score threshold to separate them on a corpus this small. A ~1000
# token system prompt (mostly RAG context most of which turned out
# irrelevant) then costs ~60-80s of CPU-only prompt-eval before the model
# says a single word -- measured live on this project's own VPS. Rather
# than chase an unreliable embedding-score cutoff, small talk is
# recognized explicitly and skips retrieval entirely: cheaper, and every
# case is a visible, testable string in _SMALLTALK_PATTERNS instead of a
# tuned float nobody can explain.
_SMALLTALK_PATTERNS = {
    "hi", "hi!", "hello", "hello!", "hey", "hey!", "hiya", "yo",
    "thanks", "thank you", "thanks!", "thank you!",
    "ok", "okay", "ok!", "okay!",
    "bye", "goodbye", "bye!", "goodbye!", "see ya", "see you",
    "good morning", "good afternoon", "good evening", "good night",
    "how are you", "how are you?", "what's up", "what's up?", "sup",
}


def _is_smalltalk(message: str) -> bool:
    return message.strip().lower() in _SMALLTALK_PATTERNS


_CODE_FENCE_RE = re.compile(r"^```(?:json)?\s*\n?(.*?)\n?```$", re.DOTALL)


def _strip_code_fence(text: str) -> str:
    """Strips a single wrapping ```/```json ... ``` fence, if present.
    Live-observed variant of the fallback-tool-call shape: the model
    sometimes wraps its {"name": ..., "arguments": {...}} JSON in a
    markdown code block instead of emitting it bare."""
    match = _CODE_FENCE_RE.match(text.strip())
    return match.group(1).strip() if match else text


def _looks_like_a_tool_call_attempt(text: str) -> bool:
    """Cheap, pre-parse check used to decide whether to hold a response
    back from the live stream -- both shapes _parse_fallback_tool_call can
    turn into a real tool call start this way."""
    stripped = text.lstrip()
    return stripped.startswith("{") or stripped.startswith("```")


def _parse_fallback_tool_call(content: str) -> dict[str, Any] | None:
    """Some models (qwen2.5-coder:7b included, as run by this Ollama
    install) understand a tool-use request correctly but emit the call as
    plain JSON text -- {"name": ..., "arguments": {...}}, sometimes wrapped
    in a markdown code fence -- instead of populating Ollama's structured
    message.tool_calls field. Verified directly against this instance's
    raw /api/chat response, not assumed.

    Rather than silently treating that as a normal text answer (which
    would make tool-use appear broken even though the model clearly
    intended to call a tool), this recognizes that shape and synthesizes
    the same structure a well-behaved tool_calls response would have had.
    Deliberately strict: once any wrapping fence is stripped, the whole
    remaining text must parse as a JSON object with a "name" naming a real
    tool and an "arguments" object -- so an ordinary text answer (fenced
    code example included) is never misread as a call.
    """
    stripped = _strip_code_fence(content)
    if not (stripped.startswith("{") and stripped.endswith("}")):
        return None
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    name = parsed.get("name")
    arguments = parsed.get("arguments")
    if name not in TOOL_FUNCTIONS or not isinstance(arguments, dict):
        return None
    return {"function": {"name": name, "arguments": arguments}}


def _build_system_prompt(user_message: str) -> tuple[str, list[dict[str, Any]]]:
    if _is_smalltalk(user_message):
        retrieved = []
    else:
        store = get_knowledge_store()
        # Below the threshold, a chunk is nearest-neighbor noise, not a
        # real match -- retrieval always returns its top k regardless of
        # how weak the match is, so this is the step that turns "closest
        # of a bad lot" into "actually nothing relevant." A coarser net
        # than _is_smalltalk() above: this catches weak matches on genuine
        # questions, not greetings (those never reach this branch at all).
        retrieved = [r for r in store.search(user_message, k=3) if r.score >= settings.rag_relevance_threshold]

    context_block = (
        "\n\n".join(f"[{r.document.id}] {r.document.title}\n{r.document.text}" for r in retrieved)
        or "(no relevant documents found)"
    )
    citations = [{"document_id": r.document.id, "title": r.document.title, "score": round(r.score, 3)} for r in retrieved]
    prompt = SYSTEM_PROMPT_TEMPLATE.format(assistant_name=settings.assistant_name, context_block=context_block)
    return prompt, citations


def stream_chat_turn(session_id: str, user_message: str) -> Iterator[dict[str, Any]]:
    memory.append_message(session_id, "user", user_message)

    system_prompt, citations = _build_system_prompt(user_message)
    history = memory.get_history(session_id)
    messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
    messages.extend({"role": m["role"], "content": m["content"]} for m in history)

    if citations:
        yield {"type": "citations", "citations": citations}

    final_text_parts: list[str] = []

    for _round in range(MAX_TOOL_ROUNDS):
        assistant_content = ""
        tool_calls: list[dict[str, Any]] = []
        # A response that opens with '{' or a markdown code fence might
        # turn out to be a plain-text-disguised tool call (see
        # _parse_fallback_tool_call) -- held back from the live stream
        # until the round finishes and we know which it was, so a raw
        # JSON blob never gets shown to the user as if it were a real
        # answer. Anything else streams live as it arrives, same as before.
        suppress_streaming = False

        for chunk in ollama_client.chat_stream(messages, tools=TOOL_SCHEMAS):
            message = chunk.get("message", {})
            delta = message.get("content", "")
            if delta:
                was_first_delta = assistant_content == ""
                assistant_content += delta
                if was_first_delta:
                    suppress_streaming = _looks_like_a_tool_call_attempt(assistant_content)
                if not suppress_streaming:
                    final_text_parts.append(delta)
                    yield {"type": "delta", "content": delta}
            if message.get("tool_calls"):
                tool_calls.extend(message["tool_calls"])
            if chunk.get("done"):
                break

        if not tool_calls:
            fallback_call = _parse_fallback_tool_call(assistant_content)
            if fallback_call:
                tool_calls = [fallback_call]

        if not tool_calls:
            if suppress_streaming:
                # Looked like it might become a tool call but didn't parse
                # as one -- an ordinary answer that just happens to start
                # with '{' or a code fence (e.g. a real code example).
                # Flush it now, since nothing was streamed live.
                final_text_parts.append(assistant_content)
                yield {"type": "delta", "content": assistant_content}
            break

        messages.append({"role": "assistant", "content": assistant_content, "tool_calls": tool_calls})
        for call in tool_calls:
            name = call["function"]["name"]
            arguments = call["function"].get("arguments", {})
            yield {"type": "tool_call", "name": name, "arguments": arguments}
            try:
                result = call_tool(name, arguments)
            except ToolError as e:
                result = {"error": str(e)}
            yield {"type": "tool_result", "name": name, "result": result}
            messages.append({"role": "tool", "content": str(result)})
        # Loop again so the model gets a fresh turn to use the tool result(s)
        # in its real answer instead of stopping at the tool call itself.

    final_text = "".join(final_text_parts)
    memory.append_message(session_id, "assistant", final_text)
    yield {"type": "done"}
