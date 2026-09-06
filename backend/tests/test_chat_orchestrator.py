"""Tests for the chat orchestrator's tool-use loop, including the
fallback parser for models (qwen2.5-coder:7b included, verified live
against this project's own Ollama instance) that emit a tool call as
plain JSON text instead of Ollama's structured tool_calls field.
"""

from app.rag.embeddings import LocalHashingEmbedder
from app.rag.store import Document, InMemoryVectorStore, ScoredDocument
from app.services import chat_orchestrator, memory
from app.services.chat_orchestrator import _build_system_prompt, _is_smalltalk, _parse_fallback_tool_call


def test_parse_fallback_tool_call_recognizes_valid_shape():
    call = _parse_fallback_tool_call('{"name": "calculate", "arguments": {"expression": "2+2"}}')
    assert call == {"function": {"name": "calculate", "arguments": {"expression": "2+2"}}}


def test_parse_fallback_tool_call_rejects_unknown_tool_name():
    assert _parse_fallback_tool_call('{"name": "not_a_tool", "arguments": {}}') is None


def test_parse_fallback_tool_call_rejects_non_json():
    assert _parse_fallback_tool_call("This is just a normal answer.") is None


def test_parse_fallback_tool_call_rejects_json_missing_arguments():
    assert _parse_fallback_tool_call('{"name": "calculate"}') is None


def test_parse_fallback_tool_call_rejects_trailing_prose():
    # Must be the *whole* trimmed content, not JSON embedded in a longer answer.
    assert _parse_fallback_tool_call('{"name": "calculate", "arguments": {}} and that is the answer') is None


def test_is_smalltalk_matches_common_greetings_case_and_punctuation_insensitive():
    for message in ["hi", "Hi!", "HELLO", "  hey  ", "Thanks!", "good morning", "How are you?"]:
        assert _is_smalltalk(message) is True


def test_is_smalltalk_does_not_match_real_questions():
    for message in ["hi, what is Bangladesh EWARS?", "What is 384 times 27?", "tell me about Ridoy's projects"]:
        assert _is_smalltalk(message) is False


class _ExplodingStore:
    """Fails the test if retrieval is ever attempted -- used to prove
    small talk skips the knowledge base (and its embedding calls)
    entirely, not just filters its results down to nothing."""

    def search(self, query: str, k: int = 4):
        raise AssertionError("retrieval should have been skipped for small talk")


def test_build_system_prompt_skips_retrieval_entirely_for_smalltalk(monkeypatch):
    monkeypatch.setattr(chat_orchestrator, "get_knowledge_store", lambda: _ExplodingStore())

    prompt, citations = _build_system_prompt("hi")

    assert citations == []
    assert "(no relevant documents found)" in prompt


class _StubStore:
    """Returns a fixed, pre-scored result set regardless of query -- lets
    _build_system_prompt's threshold filtering be tested without a real
    embedder or corpus."""

    def __init__(self, results: list[ScoredDocument]) -> None:
        self._results = results

    def search(self, query: str, k: int = 4) -> list[ScoredDocument]:
        return self._results[:k]


def test_build_system_prompt_filters_out_low_relevance_matches(monkeypatch):
    strong = ScoredDocument(document=Document(id="strong", source_type="knowledge", title="strong", text="relevant text"), score=0.6)
    weak = ScoredDocument(document=Document(id="weak", source_type="knowledge", title="weak", text="barely related"), score=0.1)
    monkeypatch.setattr(chat_orchestrator, "get_knowledge_store", lambda: _StubStore([strong, weak]))

    prompt, citations = _build_system_prompt("some question")

    assert citations == [{"document_id": "strong", "title": "strong", "score": 0.6}]
    assert "relevant text" in prompt
    assert "barely related" not in prompt


def test_build_system_prompt_says_no_relevant_documents_when_everything_is_below_threshold(monkeypatch):
    weak = ScoredDocument(document=Document(id="weak", source_type="knowledge", title="weak", text="barely related"), score=0.1)
    monkeypatch.setattr(chat_orchestrator, "get_knowledge_store", lambda: _StubStore([weak]))

    prompt, citations = _build_system_prompt("tell me something obscure and unrelated")

    assert citations == []
    assert "(no relevant documents found)" in prompt


def _empty_knowledge_store(monkeypatch):
    monkeypatch.setattr(
        chat_orchestrator, "get_knowledge_store", lambda: InMemoryVectorStore(embedder=LocalHashingEmbedder())
    )


def _fake_chat_stream(rounds):
    """rounds: list of lists-of-chunks, one list per call to chat_stream."""
    calls = iter(rounds)

    def fake(messages, tools=None, model=None):
        return iter(next(calls))

    return fake


def test_stream_chat_turn_answers_directly_when_no_tool_call(monkeypatch, tmp_path):
    _empty_knowledge_store(monkeypatch)
    monkeypatch.setattr(chat_orchestrator.settings, "memory_db_path", str(tmp_path / "mem.sqlite3"))
    monkeypatch.setattr(
        chat_orchestrator.ollama_client,
        "chat_stream",
        _fake_chat_stream([[{"message": {"content": "Hello there."}, "done": True}]]),
    )

    session_id = memory.create_session()
    events = list(chat_orchestrator.stream_chat_turn(session_id, "hi"))

    deltas = "".join(e["content"] for e in events if e["type"] == "delta")
    assert deltas == "Hello there."
    assert events[-1]["type"] == "done"
    assert [e["type"] for e in events if e["type"] == "tool_call"] == []


def test_stream_chat_turn_executes_fallback_json_tool_call(monkeypatch, tmp_path):
    _empty_knowledge_store(monkeypatch)
    monkeypatch.setattr(chat_orchestrator.settings, "memory_db_path", str(tmp_path / "mem.sqlite3"))
    monkeypatch.setattr(
        chat_orchestrator.ollama_client,
        "chat_stream",
        _fake_chat_stream(
            [
                # Round 1: model emits the tool call as plain JSON text (the
                # exact qwen2.5-coder:7b behavior observed live).
                [{"message": {"content": '{"name": "calculate", "arguments": {"expression": "384 * 27"}}'}, "done": True}],
                # Round 2: model uses the tool result to answer for real.
                [{"message": {"content": "384 times 27 is 10368."}, "done": True}],
            ]
        ),
    )

    session_id = memory.create_session()
    events = list(chat_orchestrator.stream_chat_turn(session_id, "What is 384 times 27?"))

    # The raw JSON blob from round 1 must never appear as a delta.
    deltas = "".join(e["content"] for e in events if e["type"] == "delta")
    assert deltas == "384 times 27 is 10368."
    assert '{"name"' not in deltas

    tool_calls = [e for e in events if e["type"] == "tool_call"]
    assert tool_calls == [{"type": "tool_call", "name": "calculate", "arguments": {"expression": "384 * 27"}}]

    tool_results = [e for e in events if e["type"] == "tool_result"]
    assert tool_results[0]["result"]["result"] == 10368


def test_stream_chat_turn_flushes_brace_prefixed_answer_that_is_not_a_tool_call(monkeypatch, tmp_path):
    _empty_knowledge_store(monkeypatch)
    monkeypatch.setattr(chat_orchestrator.settings, "memory_db_path", str(tmp_path / "mem.sqlite3"))
    monkeypatch.setattr(
        chat_orchestrator.ollama_client,
        "chat_stream",
        _fake_chat_stream([[{"message": {"content": "{not actually json}"}, "done": True}]]),
    )

    session_id = memory.create_session()
    events = list(chat_orchestrator.stream_chat_turn(session_id, "say something odd"))

    deltas = "".join(e["content"] for e in events if e["type"] == "delta")
    assert deltas == "{not actually json}"
    assert [e["type"] for e in events if e["type"] == "tool_call"] == []
