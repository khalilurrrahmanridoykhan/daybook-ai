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
