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


def test_build_system_prompt_includes_the_real_current_local_time(monkeypatch):
    """Structural fix for a live-caught bug: asked to set a reminder, the
    model invented a date over two years in the past instead of ever
    calling current_datetime. Making the current time a passive fact in
    every system prompt -- not something the model has to remember to
    fetch -- closes that failure mode regardless of the model's own
    tool-calling reliability."""
    monkeypatch.setattr(chat_orchestrator.settings, "local_timezone", "Asia/Dhaka")
    monkeypatch.setattr(chat_orchestrator, "get_knowledge_store", lambda: _ExplodingStore())

    prompt, _ = _build_system_prompt("hi")

    now = tools.current_datetime()
    # Compare down to the minute, not the exact second -- the two calls
    # to current_datetime() aren't guaranteed to land in the same second.
    assert now["local_iso"][:16] in prompt
    assert "Asia/Dhaka" in prompt


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


def _capturing_chat_stream(rounds, captured_tools):
    """Same as _fake_chat_stream but also records the `tools` argument
    each call received, so a test can assert on it."""
    calls = iter(rounds)

    def fake(messages, tools=None, model=None):
        captured_tools.append(tools)
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


def test_stream_chat_turn_omits_tool_schemas_for_smalltalk(monkeypatch, tmp_path):
    """Option 1 of the latency fix: a greeting never needs a tool call, so
    the ~5,000-character TOOL_SCHEMAS payload must not even be sent to
    Ollama -- not just have RAG retrieval skipped alongside it. Live-
    measured: this was still the dominant cost of a 1m42s "hi" reply even
    after RAG's own smalltalk skip was already in place."""
    _empty_knowledge_store(monkeypatch)
    monkeypatch.setattr(chat_orchestrator.settings, "memory_db_path", str(tmp_path / "mem.sqlite3"))
    captured_tools: list = []
    monkeypatch.setattr(
        chat_orchestrator.ollama_client,
        "chat_stream",
        _capturing_chat_stream([[{"message": {"content": "Hello there."}, "done": True}]], captured_tools),
    )

    session_id = memory.create_session()
    list(chat_orchestrator.stream_chat_turn(session_id, "hi"))

    assert captured_tools == [None]


def test_stream_chat_turn_still_sends_tool_schemas_for_real_questions(monkeypatch, tmp_path):
    _empty_knowledge_store(monkeypatch)
    monkeypatch.setattr(chat_orchestrator.settings, "memory_db_path", str(tmp_path / "mem.sqlite3"))
    captured_tools: list = []
    monkeypatch.setattr(
        chat_orchestrator.ollama_client,
        "chat_stream",
        _capturing_chat_stream(
            [[{"message": {"content": "You have 3 tasks due today."}, "done": True}]], captured_tools
        ),
    )

    session_id = memory.create_session()
    list(chat_orchestrator.stream_chat_turn(session_id, "what's on my task list today?"))

    assert captured_tools == [tools.TOOL_SCHEMAS]


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


def test_stream_chat_turn_executes_a_calendar_reminder_via_structured_tool_calls(monkeypatch, tmp_path):
    """End-to-end through the full orchestrator loop for a 'remind me'
    request -- google_calendar mocked at the API boundary it would
    otherwise cross, same pattern as the Daybook create_task test above."""
    _empty_knowledge_store(monkeypatch)
    monkeypatch.setattr(chat_orchestrator.settings, "memory_db_path", str(tmp_path / "mem.sqlite3"))
    monkeypatch.setattr(
        tools.google_calendar,
        "create_event",
        lambda **kw: {"id": "e1", "summary": kw["summary"], "start": kw["start"], "end": kw["start"]},
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
                            "tool_calls": [
                                {
                                    "function": {
                                        "name": "create_calendar_event",
                                        "arguments": {
                                            "summary": "Take medicine",
                                            "start": "2026-10-05T20:00:00+06:00",
                                            "reminder_minutes_before": 10,
                                        },
                                    }
                                }
                            ],
                        },
                        "done": True,
                    }
                ],
                [{"message": {"content": "Reminder set for 8pm on October 5th."}, "done": True}],
            ]
        ),
    )

    session_id = memory.create_session()
    events = list(chat_orchestrator.stream_chat_turn(session_id, "remind me to take medicine at 8pm on october 5th"))

    deltas = "".join(e["content"] for e in events if e["type"] == "delta")
    assert deltas == "Reminder set for 8pm on October 5th."

    tool_calls = [e for e in events if e["type"] == "tool_call"]
    assert tool_calls == [
        {
            "type": "tool_call",
            "name": "create_calendar_event",
            "arguments": {
                "summary": "Take medicine",
                "start": "2026-10-05T20:00:00+06:00",
                "reminder_minutes_before": 10,
            },
        }
    ]

    tool_results = [e for e in events if e["type"] == "tool_result"]
    assert tool_results[0]["result"]["id"] == "e1"


def test_stream_chat_turn_gives_a_fallback_reply_when_tool_rounds_are_exhausted(monkeypatch, tmp_path):
    """Live-caught bug: asked to set a reminder, the model called
    create_calendar_event with an invalid placeholder start, got back a
    tool error, and just repeated the identical broken call for every one
    of MAX_TOOL_ROUNDS instead of adjusting -- so the model never gave a
    plain-text answer at all, and the user got a silent, empty 'done'
    with no reply. Must fall back to a real message instead."""
    _empty_knowledge_store(monkeypatch)
    monkeypatch.setattr(chat_orchestrator.settings, "memory_db_path", str(tmp_path / "mem.sqlite3"))

    def boom(**kw):
        raise tools.GoogleCalendarError(
            "start='{{current_datetime.local_iso}}T21:00:00' is not a real ISO 8601 datetime"
        )

    monkeypatch.setattr(tools.google_calendar, "create_event", boom)

    bad_round = [
        {
            "message": {
                "content": "",
                "tool_calls": [
                    {
                        "function": {
                            "name": "create_calendar_event",
                            "arguments": {"summary": "x", "start": "{{current_datetime.local_iso}}T21:00:00"},
                        }
                    }
                ],
            },
            "done": True,
        }
    ]
    monkeypatch.setattr(
        chat_orchestrator.ollama_client,
        "chat_stream",
        _fake_chat_stream([bad_round, bad_round, bad_round]),
    )

    session_id = memory.create_session()
    events = list(chat_orchestrator.stream_chat_turn(session_id, "remind me to test this at 9pm"))

    deltas = "".join(e["content"] for e in events if e["type"] == "delta")
    assert "couldn't complete" in deltas
    assert "not a real ISO 8601 datetime" in deltas

    tool_calls = [e for e in events if e["type"] == "tool_call"]
    assert len(tool_calls) == 3  # one per MAX_TOOL_ROUNDS -- it never gave up early

    assert events[-1]["type"] == "done"


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


def test_stream_chat_turn_retries_when_model_falsely_claims_a_task_was_added(monkeypatch, tmp_path):
    """Live-caught bug: asked to add a task, the model replied 'Task
    added: X' in plain prose -- twice, in the same real conversation --
    without ever calling create_task. Neither the structured tool_calls
    field nor the fallback JSON parser catches this, since there's no
    JSON at all, just confident, false prose. Confirmed live: the task
    never existed in the database despite the confident reply."""
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
                # Round 1: a false claim, no tool_calls at all.
                [{"message": {"content": "Task added: Make the GeoAI Models Building."}, "done": True}],
                # Round 2 (the forced retry): this time it actually calls the tool.
                [
                    {
                        "message": {
                            "content": "",
                            "tool_calls": [
                                {"function": {"name": "create_task", "arguments": {"title": "Make the GeoAI Models Building"}}}
                            ],
                        },
                        "done": True,
                    }
                ],
                # Round 3: the model's real answer, now that the tool result exists.
                [{"message": {"content": "Done -- I've added that task for real this time."}, "done": True}],
            ]
        ),
    )

    session_id = memory.create_session()
    events = list(chat_orchestrator.stream_chat_turn(session_id, "Add a task to Make the GeoAI Models Building."))

    deltas = "".join(e["content"] for e in events if e["type"] == "delta")
    assert "Task added: Make the GeoAI Models Building." in deltas  # the false claim is visible, not hidden
    assert "wasn't actually done yet" in deltas  # the visible self-correction
    assert deltas.endswith("Done -- I've added that task for real this time.")

    tool_calls = [e for e in events if e["type"] == "tool_call"]
    assert tool_calls == [{"type": "tool_call", "name": "create_task", "arguments": {"title": "Make the GeoAI Models Building"}}]


def test_stream_chat_turn_only_retries_once_for_a_false_claim(monkeypatch, tmp_path):
    """If the retry itself doesn't call a tool either, that answer goes
    through as-is rather than looping forever."""
    _empty_knowledge_store(monkeypatch)
    monkeypatch.setattr(chat_orchestrator.settings, "memory_db_path", str(tmp_path / "mem.sqlite3"))
    monkeypatch.setattr(
        chat_orchestrator.ollama_client,
        "chat_stream",
        _fake_chat_stream(
            [
                [{"message": {"content": "Task added: X."}, "done": True}],
                [{"message": {"content": "Task added: X, for real this time."}, "done": True}],
            ]
        ),
    )

    session_id = memory.create_session()
    events = list(chat_orchestrator.stream_chat_turn(session_id, "add a task"))

    assert events[-1]["type"] == "done"
    assert [e["type"] for e in events if e["type"] == "tool_call"] == []


def test_stream_chat_turn_does_not_retry_when_a_tool_was_already_called(monkeypatch, tmp_path):
    """The false-claim pattern can appear in a perfectly legitimate final
    answer too, e.g. reporting the result of a tool call that really did
    happen -- must not trigger a spurious retry in that case."""
    _empty_knowledge_store(monkeypatch)
    monkeypatch.setattr(chat_orchestrator.settings, "memory_db_path", str(tmp_path / "mem.sqlite3"))
    monkeypatch.setattr(tools.daybook_db, "create_task", lambda **kw: {"id": "t1", "title": kw["title"]})
    monkeypatch.setattr(
        chat_orchestrator.ollama_client,
        "chat_stream",
        _fake_chat_stream(
            [
                [
                    {
                        "message": {
                            "content": "",
                            "tool_calls": [{"function": {"name": "create_task", "arguments": {"title": "Buy milk"}}}],
                        },
                        "done": True,
                    }
                ],
                [{"message": {"content": "Task added: Buy milk."}, "done": True}],
            ]
        ),
    )

    session_id = memory.create_session()
    events = list(chat_orchestrator.stream_chat_turn(session_id, "add a task to buy milk"))

    deltas = "".join(e["content"] for e in events if e["type"] == "delta")
    assert deltas == "Task added: Buy milk."  # no self-correction appended
    tool_calls = [e for e in events if e["type"] == "tool_call"]
    assert len(tool_calls) == 1  # not retried a second time
