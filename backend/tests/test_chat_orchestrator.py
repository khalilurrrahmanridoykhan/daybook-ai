"""Tests for the chat orchestrator's tool-use loop, including the
fallback parser for models (qwen2.5-coder:7b included, verified live
against this project's own Ollama instance) that emit a tool call as
plain JSON text instead of Ollama's structured tool_calls field.
"""

from app.rag.embeddings import LocalHashingEmbedder
from app.rag.store import Document, InMemoryVectorStore, ScoredDocument
from app.services import chat_orchestrator, memory, tools
from app.services.chat_orchestrator import (
    _build_system_prompt,
    _is_smalltalk,
    _parse_fallback_tool_call,
    _parse_fallback_tool_calls,
)


def test_parse_fallback_tool_call_recognizes_valid_shape():
    call = _parse_fallback_tool_call('{"name": "create_task", "arguments": {"title": "Buy milk"}}')
    assert call == {"function": {"name": "create_task", "arguments": {"title": "Buy milk"}}}


def test_parse_fallback_tool_call_rejects_unknown_tool_name():
    assert _parse_fallback_tool_call('{"name": "not_a_tool", "arguments": {}}') is None


def test_parse_fallback_tool_call_rejects_non_json():
    assert _parse_fallback_tool_call("This is just a normal answer.") is None


def test_parse_fallback_tool_call_rejects_json_missing_arguments():
    assert _parse_fallback_tool_call('{"name": "current_datetime"}') is None


def test_parse_fallback_tool_call_rejects_trailing_prose():
    # Must be the *whole* trimmed content, not JSON embedded in a longer answer.
    assert _parse_fallback_tool_call('{"name": "current_datetime", "arguments": {}} and that is the answer') is None


def test_parse_fallback_tool_call_recognizes_markdown_fenced_json():
    # Live-observed variant: the model wraps the same JSON shape in a
    # ```json ... ``` fence instead of emitting it bare.
    fenced = '```json\n{"name": "get_budget_summary", "arguments": {}}\n```'
    call = _parse_fallback_tool_call(fenced)
    assert call == {"function": {"name": "get_budget_summary", "arguments": {}}}


def test_parse_fallback_tool_call_recognizes_bare_fence_without_json_tag():
    fenced = '```\n{"name": "get_budget_summary", "arguments": {}}\n```'
    call = _parse_fallback_tool_call(fenced)
    assert call == {"function": {"name": "get_budget_summary", "arguments": {}}}


def test_parse_fallback_tool_calls_recognizes_multiple_newline_separated_calls():
    # Live-observed: asked to set a budget, the model emitted three
    # separate tool-call-shaped JSON objects, one per line, in a single
    # message instead of one call or Ollama's structured tool_calls array.
    content = (
        '{"name": "set_expected_income", "arguments": {"month": "2026-10", "amount_minor": 5000000}}\n'
        '{"name": "get_budget_summary", "arguments": {"month": "2026-10"}}\n'
        '{"name": "get_budget_summary", "arguments": {"month": "2026-10"}}'
    )
    calls = _parse_fallback_tool_calls(content)
    assert calls == [
        {"function": {"name": "set_expected_income", "arguments": {"month": "2026-10", "amount_minor": 5000000}}},
        {"function": {"name": "get_budget_summary", "arguments": {"month": "2026-10"}}},
        {"function": {"name": "get_budget_summary", "arguments": {"month": "2026-10"}}},
    ]


def test_parse_fallback_tool_calls_returns_single_item_list_for_one_call():
    calls = _parse_fallback_tool_calls('{"name": "current_datetime", "arguments": {}}')
    assert calls == [{"function": {"name": "current_datetime", "arguments": {}}}]


def test_parse_fallback_tool_calls_rejects_multiline_prose():
    # A genuine multi-line answer must never be misread as a batch of calls.
    content = "Here's what I found:\nYour budget looks good this month."
    assert _parse_fallback_tool_calls(content) is None


def test_parse_fallback_tool_calls_rejects_mixed_valid_and_invalid_lines():
    # If even one line isn't a valid call, the whole thing is rejected --
    # no partial execution of a batch that might not really be one.
    content = '{"name": "current_datetime", "arguments": {}}\nand then I will explain further'
    assert _parse_fallback_tool_calls(content) is None


def test_parse_fallback_tool_call_rejects_fenced_code_that_is_not_a_tool_call():
    fenced = '```json\n{"foo": "bar"}\n```'
    assert _parse_fallback_tool_call(fenced) is None


def test_is_smalltalk_matches_common_greetings_case_and_punctuation_insensitive():
    for message in ["hi", "Hi!", "HELLO", "  hey  ", "Thanks!", "good morning", "How are you?"]:
        assert _is_smalltalk(message) is True


def test_is_smalltalk_does_not_match_real_questions():
    for message in ["hi, what's due today?", "add a task to call the plumber", "how much is left for groceries"]:
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
                [{"message": {"content": '{"name": "current_datetime", "arguments": {}}'}, "done": True}],
                # Round 2: model uses the tool result to answer for real.
                [{"message": {"content": "It's currently 2026-09-06."}, "done": True}],
            ]
        ),
    )

    session_id = memory.create_session()
    events = list(chat_orchestrator.stream_chat_turn(session_id, "what's today's date?"))

    # The raw JSON blob from round 1 must never appear as a delta.
    deltas = "".join(e["content"] for e in events if e["type"] == "delta")
    assert deltas == "It's currently 2026-09-06."
    assert '{"name"' not in deltas

    tool_calls = [e for e in events if e["type"] == "tool_call"]
    assert tool_calls == [{"type": "tool_call", "name": "current_datetime", "arguments": {}}]

    tool_results = [e for e in events if e["type"] == "tool_result"]
    assert tool_results[0]["result"]["utc"] is True


def test_stream_chat_turn_executes_markdown_fenced_fallback_tool_call(monkeypatch, tmp_path):
    """The exact bug observed live: the model answers "tell me about my
    budget" by emitting the tool call wrapped in a ```json fence instead
    of bare JSON or structured tool_calls. Must be caught and executed,
    not shown to the user as a literal code block."""
    _empty_knowledge_store(monkeypatch)
    monkeypatch.setattr(chat_orchestrator.settings, "memory_db_path", str(tmp_path / "mem.sqlite3"))
    monkeypatch.setattr(tools.daybook_db, "get_budget_summary", lambda **kw: {"month": "2026-09", "summary": {"spent": 12000}})
    monkeypatch.setattr(
        chat_orchestrator.ollama_client,
        "chat_stream",
        _fake_chat_stream(
            [
                [
                    {
                        "message": {"content": '```json\n{"name": "get_budget_summary", "arguments": {}}\n```'},
                        "done": True,
                    }
                ],
                [{"message": {"content": "You've spent 120.00 so far this month."}, "done": True}],
            ]
        ),
    )

    session_id = memory.create_session()
    events = list(chat_orchestrator.stream_chat_turn(session_id, "tell me about my budget"))

    deltas = "".join(e["content"] for e in events if e["type"] == "delta")
    assert deltas == "You've spent 120.00 so far this month."
    assert "```" not in deltas
    assert '{"name"' not in deltas

    tool_calls = [e for e in events if e["type"] == "tool_call"]
    assert tool_calls == [{"type": "tool_call", "name": "get_budget_summary", "arguments": {}}]


def test_stream_chat_turn_flushes_fenced_code_that_is_not_a_tool_call(monkeypatch, tmp_path):
    _empty_knowledge_store(monkeypatch)
    monkeypatch.setattr(chat_orchestrator.settings, "memory_db_path", str(tmp_path / "mem.sqlite3"))
    monkeypatch.setattr(
        chat_orchestrator.ollama_client,
        "chat_stream",
        _fake_chat_stream([[{"message": {"content": '```python\nprint("hi")\n```'}, "done": True}]]),
    )

    session_id = memory.create_session()
    events = list(chat_orchestrator.stream_chat_turn(session_id, "show me a hello world in python"))

    deltas = "".join(e["content"] for e in events if e["type"] == "delta")
    assert deltas == '```python\nprint("hi")\n```'
    assert [e["type"] for e in events if e["type"] == "tool_call"] == []


def test_stream_chat_turn_executes_multiple_newline_separated_fallback_calls(monkeypatch, tmp_path):
    """Live bug, same chat as the markdown-fence one: asked to set a
    budget, the model emitted three tool calls as separate JSON lines in
    one message. All three must execute, in order, and none of the raw
    JSON may leak to the user."""
    _empty_knowledge_store(monkeypatch)
    monkeypatch.setattr(chat_orchestrator.settings, "memory_db_path", str(tmp_path / "mem.sqlite3"))
    monkeypatch.setattr(tools.daybook_db, "set_expected_income", lambda **kw: {"month": kw["month"], "expectedIncome": kw["amount_minor"]})
    monkeypatch.setattr(tools.daybook_db, "get_budget_summary", lambda **kw: {"month": kw["month"], "summary": None})
    monkeypatch.setattr(
        chat_orchestrator.ollama_client,
        "chat_stream",
        _fake_chat_stream(
            [
                [
                    {
                        "message": {
                            "content": (
                                '{"name": "set_expected_income", "arguments": {"month": "2026-10", "amount_minor": 5000000}}\n'
                                '{"name": "get_budget_summary", "arguments": {"month": "2026-10"}}'
                            )
                        },
                        "done": True,
                    }
                ],
                [{"message": {"content": "Set October's income to 50,000."}, "done": True}],
            ]
        ),
    )

    session_id = memory.create_session()
    events = list(chat_orchestrator.stream_chat_turn(session_id, "set my October 2026 income to 50000"))

    deltas = "".join(e["content"] for e in events if e["type"] == "delta")
    assert deltas == "Set October's income to 50,000."
    assert '{"name"' not in deltas

    tool_calls = [e["name"] for e in events if e["type"] == "tool_call"]
    assert tool_calls == ["set_expected_income", "get_budget_summary"]


def test_stream_chat_turn_executes_a_real_daybook_tool_via_structured_tool_calls(monkeypatch, tmp_path):
    """End-to-end through the full orchestrator loop, using Ollama's
    well-behaved structured tool_calls field (not the fallback parser)
    and a real Daybook tool -- create_task -- with daybook_db mocked
    at the HTTP boundary it would otherwise cross."""
    _empty_knowledge_store(monkeypatch)
    monkeypatch.setattr(chat_orchestrator.settings, "memory_db_path", str(tmp_path / "mem.sqlite3"))
    monkeypatch.setattr(
        tools.daybook_db,
        "create_task",
        lambda **kw: {"id": "t1", "title": kw["title"], "status": "TODO"},
    )
    monkeypatch.setattr(
        chat_orchestrator.ollama_client,
        "chat_stream",
        _fake_chat_stream(
            [
                [
                    {
                        "message": {
                            "content": "",
                            "tool_calls": [{"function": {"name": "create_task", "arguments": {"title": "Call the plumber"}}}],
                        },
                        "done": True,
                    }
                ],
                [{"message": {"content": "Added 'Call the plumber' to your tasks."}, "done": True}],
            ]
        ),
    )

    session_id = memory.create_session()
    events = list(chat_orchestrator.stream_chat_turn(session_id, "add a task to call the plumber"))

    deltas = "".join(e["content"] for e in events if e["type"] == "delta")
    assert deltas == "Added 'Call the plumber' to your tasks."

    tool_calls = [e for e in events if e["type"] == "tool_call"]
    assert tool_calls == [{"type": "tool_call", "name": "create_task", "arguments": {"title": "Call the plumber"}}]

    tool_results = [e for e in events if e["type"] == "tool_result"]
    assert tool_results[0]["result"] == {"id": "t1", "title": "Call the plumber", "status": "TODO"}


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
