import pytest

from app.services import memory


def test_create_session_and_append_and_get_history(tmp_path):
    db_path = str(tmp_path / "test.sqlite3")
    session_id = memory.create_session(db_path=db_path)
    memory.append_message(session_id, "user", "hello", db_path=db_path)
    memory.append_message(session_id, "assistant", "hi there", db_path=db_path)

    history = memory.get_history(session_id, db_path=db_path)
    assert [(m["role"], m["content"]) for m in history] == [("user", "hello"), ("assistant", "hi there")]


def test_session_exists(tmp_path):
    db_path = str(tmp_path / "test.sqlite3")
    session_id = memory.create_session(db_path=db_path)
    assert memory.session_exists(session_id, db_path=db_path) is True
    assert memory.session_exists("does-not-exist", db_path=db_path) is False


def test_append_message_to_unknown_session_raises(tmp_path):
    db_path = str(tmp_path / "test.sqlite3")
    with pytest.raises(ValueError, match="No session"):
        memory.append_message("does-not-exist", "user", "hi", db_path=db_path)


def test_list_sessions_orders_newest_first(tmp_path):
    db_path = str(tmp_path / "test.sqlite3")
    s1 = memory.create_session(db_path=db_path, title="first")
    s2 = memory.create_session(db_path=db_path, title="second")

    ids = [s["id"] for s in memory.list_sessions(db_path=db_path)]
    assert ids.index(s2) < ids.index(s1)


def test_get_history_on_unknown_session_returns_empty_list(tmp_path):
    db_path = str(tmp_path / "test.sqlite3")
    assert memory.get_history("does-not-exist", db_path=db_path) == []


def test_first_user_message_auto_titles_the_session(tmp_path):
    """Same behavior as Claude/ChatGPT: a brand-new session is titled from
    its first user message, not left blank forever."""
    db_path = str(tmp_path / "test.sqlite3")
    session_id = memory.create_session(db_path=db_path)
    memory.append_message(session_id, "user", "What's my budget for October 2026?", db_path=db_path)

    sessions = {s["id"]: s["title"] for s in memory.list_sessions(db_path=db_path)}
    assert sessions[session_id] == "What's my budget for October 2026?"


def test_long_first_message_is_truncated_for_the_title(tmp_path):
    db_path = str(tmp_path / "test.sqlite3")
    session_id = memory.create_session(db_path=db_path)
    long_message = "x" * 100
    memory.append_message(session_id, "user", long_message, db_path=db_path)

    sessions = {s["id"]: s["title"] for s in memory.list_sessions(db_path=db_path)}
    assert sessions[session_id] == "x" * 60 + "…"


def test_second_user_message_does_not_overwrite_the_title(tmp_path):
    db_path = str(tmp_path / "test.sqlite3")
    session_id = memory.create_session(db_path=db_path)
    memory.append_message(session_id, "user", "first message", db_path=db_path)
    memory.append_message(session_id, "user", "second message", db_path=db_path)

    sessions = {s["id"]: s["title"] for s in memory.list_sessions(db_path=db_path)}
    assert sessions[session_id] == "first message"


def test_a_session_created_with_an_explicit_title_is_not_overwritten(tmp_path):
    db_path = str(tmp_path / "test.sqlite3")
    session_id = memory.create_session(db_path=db_path, title="Renamed by the user")
    memory.append_message(session_id, "user", "hi", db_path=db_path)

    sessions = {s["id"]: s["title"] for s in memory.list_sessions(db_path=db_path)}
    assert sessions[session_id] == "Renamed by the user"


def test_delete_session_removes_it_and_its_messages(tmp_path):
    db_path = str(tmp_path / "test.sqlite3")
    session_id = memory.create_session(db_path=db_path)
    memory.append_message(session_id, "user", "hello", db_path=db_path)

    memory.delete_session(session_id, db_path=db_path)

    assert memory.session_exists(session_id, db_path=db_path) is False
    assert memory.get_history(session_id, db_path=db_path) == []
    assert session_id not in [s["id"] for s in memory.list_sessions(db_path=db_path)]


def test_delete_unknown_session_raises(tmp_path):
    db_path = str(tmp_path / "test.sqlite3")
    with pytest.raises(ValueError, match="No session"):
        memory.delete_session("does-not-exist", db_path=db_path)


def test_rename_session_updates_the_title(tmp_path):
    db_path = str(tmp_path / "test.sqlite3")
    session_id = memory.create_session(db_path=db_path, title="original")

    memory.rename_session(session_id, "  Budget planning  ", db_path=db_path)

    sessions = {s["id"]: s["title"] for s in memory.list_sessions(db_path=db_path)}
    assert sessions[session_id] == "Budget planning"  # stored trimmed


def test_rename_unknown_session_raises(tmp_path):
    db_path = str(tmp_path / "test.sqlite3")
    with pytest.raises(ValueError, match="No session"):
        memory.rename_session("does-not-exist", "x", db_path=db_path)


def test_renamed_session_title_survives_a_later_user_message(tmp_path):
    """A rename must permanently clear the 'still blank, eligible for
    auto-titling' state -- not just happen to look non-empty until the
    next message arrives."""
    db_path = str(tmp_path / "test.sqlite3")
    session_id = memory.create_session(db_path=db_path)
    memory.rename_session(session_id, "My custom title", db_path=db_path)
    memory.append_message(session_id, "user", "hello", db_path=db_path)

    sessions = {s["id"]: s["title"] for s in memory.list_sessions(db_path=db_path)}
    assert sessions[session_id] == "My custom title"
