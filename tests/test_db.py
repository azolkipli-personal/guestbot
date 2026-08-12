"""Tests for the SQLite state store (Task 5)."""
import pytest

from app import db


@pytest.fixture(autouse=True)
def clean_db():
    """Reset the module-level DB connection to a clean :memory: before each test."""
    db._reset_for_tests()


def test_init_db_creates_tables():
    db.init_db(":memory:")
    rows = db.query("SELECT name FROM sqlite_master WHERE type='table'", fetch=True)
    names = {r["name"] for r in rows}
    assert {"messages", "paused", "settings"} <= names


def test_log_message_and_history_roundtrip():
    db.init_db(":memory:")
    db.log_message("+60123456789", "user", "Hello")
    db.log_message("+60123456789", "assistant", "Hi there!")
    hist = db.history("+60123456789")

    assert len(hist) == 2
    assert hist[0] == {
        "phone": "+60123456789",
        "role": "user",
        "body": "Hello",
        "ts": hist[0]["ts"],  # keep key, value checked below
    }
    assert hist[1]["role"] == "assistant"
    assert hist[1]["body"] == "Hi there!"

    # Roles/bodies correct regardless of ts.
    assert [h["role"] for h in hist] == ["user", "assistant"]
    assert [h["body"] for h in hist] == ["Hello", "Hi there!"]
    # Oldest -> newest ordering by id.
    assert hist[0]["ts"] <= hist[1]["ts"]


def test_history_separates_phones():
    db.init_db(":memory:")
    db.log_message("+60A", "user", "from A")
    db.log_message("+60B", "user", "from B")
    db.log_message("+60A", "assistant", "reply to A")

    hist_a = db.history("+60A")
    assert [h["body"] for h in hist_a] == ["from A", "reply to A"]

    hist_b = db.history("+60B")
    assert [h["body"] for h in hist_b] == ["from B"]

    assert db.history("+60ZZZ") == []


def test_pause_unpause_is_paused():
    db.init_db(":memory:")
    phone = "+60123456789"
    assert db.is_paused(phone) is False

    db.pause(phone)
    assert db.is_paused(phone) is True

    db.unpause(phone)
    assert db.is_paused(phone) is False


def test_list_all_returns_phones_with_paused_flags():
    db.init_db(":memory:")
    db.log_message("+60A", "user", "hi A")
    db.log_message("+60B", "user", "hi B")
    db.pause("+60B")

    rows = db.list_all()
    by_phone = {r["phone"]: r["paused"] for r in rows}

    assert by_phone.get("+60A") is False
    assert by_phone.get("+60B") is True


def test_get_kb_seeded_from_kb_seed_md():
    db.init_db(":memory:")
    kb = db.get_kb()
    assert isinstance(kb, str)
    assert len(kb) > 0


def test_set_kb_then_get_kb():
    db.init_db(":memory:")
    db.set_kb("new content")
    assert db.get_kb() == "new content"


def test_seed_kb_not_overwritten_when_already_set():
    db.init_db(":memory:")
    db.set_kb("custom persisted")
    # Re-init should not clobber an existing stored KB.
    db.init_db(":memory:")
    assert db.get_kb() == "custom persisted"


def test_ai_enabled_default_and_toggle():
    db.init_db(":memory:")
    assert db.ai_enabled() is True

    db.set_ai(False)
    assert db.ai_enabled() is False

    db.set_ai(True)
    assert db.ai_enabled() is True


def test_history_limit_default():
    db.init_db(":memory:")
    for i in range(60):
        db.log_message("+60A", "user", f"msg-{i}")
    hist = db.history("+60A")
    assert len(hist) == 50
    # Returns the most recent 50, oldest->newest.
    assert hist[0]["body"] == "msg-10"
    assert hist[-1]["body"] == "msg-59"
