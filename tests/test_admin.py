"""Tests for the owner admin command parser (Task 6)."""
import pytest

from app import admin, db


@pytest.fixture(autouse=True)
def clean_db():
    """Reset the module-level DB connection to a clean :memory: before each test."""
    db._reset_for_tests()
    db.init_db(":memory:")


def test_is_admin_command_status():
    assert admin.is_admin_command("/status") is True


def test_is_admin_command_hello():
    assert admin.is_admin_command("hello") is False


def test_is_admin_command_help_with_spaces():
    # Leading whitespace is ignored, command parsed case-insensitively.
    assert admin.is_admin_command("/  help") is True
    assert admin.is_admin_command("  /HELP  ") is True


def test_help_lists_all_commands():
    reply = admin.handle_admin("+60OWNER", "/help")
    assert "/status" in reply
    assert "/resume" in reply
    assert "/updatekb" in reply
    assert "/pause" in reply
    assert "/history" in reply
    assert "/list" in reply
    assert "/ai" in reply
    assert "/viewkb" in reply
    assert "/help" in reply


def test_status_no_paused():
    reply = admin.handle_admin("+60OWNER", "/status")
    assert "AI: ON" in reply
    assert "Paused (0)" in reply


def test_status_with_paused():
    db.pause("+601111")
    reply = admin.handle_admin("+60OWNER", "/status")
    assert "Paused (1)" in reply
    assert "+601111" in reply


def test_pause_phone():
    reply = admin.handle_admin("+60OWNER", "/pause +60999")
    assert "+60999" in reply
    assert db.is_paused("+60999") is True


def test_pause_no_arg_usage():
    reply = admin.handle_admin("+60OWNER", "/pause")
    assert "/pause" in reply


def test_resume_phone():
    db.pause("+60999")
    reply = admin.handle_admin("+60OWNER", "/resume +60999")
    assert db.is_paused("+60999") is False
    assert "+60999" in reply


def test_history_contains_bodies_and_roles():
    db.log_message("+60abc", "user", "How much?")
    db.log_message("+60abc", "bot", "RM 100 per night.")
    reply = admin.handle_admin("+60OWNER", "/history +60abc")
    assert "How much?" in reply
    assert "RM 100 per night." in reply
    assert "user" in reply
    assert "bot" in reply


def test_list_contains_two_phones():
    db.log_message("+60A", "user", "hi A")
    db.log_message("+60B", "user", "hi B")
    reply = admin.handle_admin("+60OWNER", "/list")
    assert "+60A" in reply
    assert "+60B" in reply


def test_ai_off_then_on():
    reply_off = admin.handle_admin("+60OWNER", "/ai off")
    assert db.ai_enabled() is False
    assert "off" in reply_off.lower()

    reply_on = admin.handle_admin("+60OWNER", "/ai on")
    assert db.ai_enabled() is True


def test_viewkb_returns_kb():
    db.set_kb("custom knowledge base")
    reply = admin.handle_admin("+60OWNER", "/viewkb")
    assert reply == db.get_kb()
    assert reply == "custom knowledge base"


def test_updatekb_flows_to_kb_update_state():
    reply = admin.handle_admin("+60OWNER", "/updatekb")
    assert admin.expect_kb_update("+60OWNER") is True
    assert "Knowledge Base" in reply

    # A different phone is not awaiting an update.
    assert admin.expect_kb_update("+60OTHERS") is False

    # After the caller stores the new KB and clears the flag…
    db.set_kb("brand new kb")
    admin.clear_kb_update("+60OWNER")
    assert admin.expect_kb_update("+60OWNER") is False


def test_unknown_command():
    reply = admin.handle_admin("+60OWNER", "/foo")
    assert "unknown" in reply
