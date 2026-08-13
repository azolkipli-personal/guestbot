"""Tests for the Meta WhatsApp webhook integration (Task 7).

These tests exercise the Flask routes in ``app.webhook``. The outbound
WhatsApp send, the Gemini LLM, and admin parsing are all mocked via
``monkeypatch`` so no network, LLM API, or real WhatsApp calls happen.
"""
import pytest

from app import create_app
from app import admin
from app import db
from app import webhook

VERIFY_TOKEN = "test_verify_token_123"
OWNER_PHONE = "+60OWNERPHONE"
GUEST_PHONE = "+60123456789"


@pytest.fixture(autouse=True)
def clean_db():
    """Reset the module-level DB connection to a clean :memory: before each test."""
    db._reset_for_tests()
    db.init_db(":memory:")


@pytest.fixture
def client():
    """A Flask test client with the webhook blueprint mounted."""
    return create_app().test_client()


@pytest.fixture
def fake_send():
    """A callable stub that records each ``send_whatsapp`` call.

    Use it as ``monkeypatch.setattr(webhook.wa, "send_whatsapp", fake_send)``;
    inspect recorded calls via ``fake_send.calls``.
    """
    calls = []

    def _send(to, text):
        calls.append((to, text))
        return True

    _send.calls = calls
    return _send


# ---------------------------------------------------------------- helpers


def _meta_payload(phone: str, body: str) -> dict:
    """Build a Meta-style POST body for one inbound text message."""
    return {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {"from": phone, "text": {"body": body}}
                            ]
                        }
                    }
                ]
            }
        ]
    }


def _config(monkeypatch):
    """Set the env vars the webhook depends on."""
    monkeypatch.setenv("VERIFY_TOKEN", VERIFY_TOKEN)
    monkeypatch.setenv("OWNER_PHONE", OWNER_PHONE)


# ------------------------------------------------------------- GET verify


def test_verify_success(monkeypatch, client):
    _config(monkeypatch)
    resp = client.get(
        "/webhook?hub.mode=subscribe"
        f"&hub.verify_token={VERIFY_TOKEN}"
        "&hub.challenge=12345"
    )
    assert resp.status_code == 200
    assert resp.data.decode() == "12345"


def test_verify_wrong_token(monkeypatch, client):
    _config(monkeypatch)
    resp = client.get(
        "/webhook?hub.mode=subscribe"
        "&hub.verify_token=WRONG"
        "&hub.challenge=1"
    )
    assert resp.status_code == 403


def test_verify_no_params(monkeypatch, client):
    _config(monkeypatch)
    resp = client.get("/webhook")
    assert resp.status_code == 403


# ------------------------------------------------------------ POST guest


def test_post_guest_success(monkeypatch, client, fake_send):
    _config(monkeypatch)
    monkeypatch.setattr(webhook.wa, "send_whatsapp", fake_send)
    monkeypatch.setattr(
        webhook.llm,
        "ask_gemini",
        lambda kb, msg, history=None: {
            "reply": "Check-in 15:00",
            "handover": False,
            "language": "en",
        },
    )

    resp = client.post(
        "/webhook",
        json=_meta_payload(GUEST_PHONE, "What time is check-in?"),
    )
    assert resp.status_code == 200
    assert fake_send.calls == [(GUEST_PHONE, "Check-in 15:00")]

    # The inbound message and bot reply were both logged.
    hist = db.history(GUEST_PHONE)
    bodies = [row["body"] for row in hist]
    assert "What time is check-in?" in bodies
    assert "Check-in 15:00" in bodies


def test_post_guest_handover(monkeypatch, client, fake_send):
    _config(monkeypatch)
    monkeypatch.setattr(webhook.wa, "send_whatsapp", fake_send)
    monkeypatch.setattr(
        webhook.llm,
        "ask_gemini",
        lambda kb, msg, history=None: {
            "reply": "let me connect you",
            "handover": True,
            "language": "en",
        },
    )

    resp = client.post(
        "/webhook",
        json=_meta_payload(GUEST_PHONE, "Can I book a boat?"),
    )
    assert resp.status_code == 200
    # Guest gets the bot's reply, AND the owner is notified of the handover.
    assert fake_send.calls == [
        (GUEST_PHONE, "let me connect you"),
        (OWNER_PHONE, "⚠️ A guest needs your help (out of scope).\n\nGuest: +60123456789\nThey asked: Can I book a boat?"),
    ]
    # Handover marks the guest as paused so the host takes over manually.
    assert db.is_paused(GUEST_PHONE) is True


def test_post_paused_guest_sends_nothing(monkeypatch, client, fake_send):
    _config(monkeypatch)
    monkeypatch.setattr(webhook.wa, "send_whatsapp", fake_send)
    monkeypatch.setattr(
        webhook.llm,
        "ask_gemini",
        lambda kb, msg, history=None: {
            "reply": "should not be sent",
            "handover": False,
            "language": "en",
        },
    )
    db.pause(GUEST_PHONE)

    resp = client.post(
        "/webhook",
        json=_meta_payload(GUEST_PHONE, "Hello?"),
    )
    assert resp.status_code == 200
    assert fake_send.calls == []  # nothing sent while paused


def test_post_ai_off(monkeypatch, client, fake_send):
    _config(monkeypatch)
    monkeypatch.setattr(webhook.wa, "send_whatsapp", fake_send)

    def _boom(*a, **k):
        raise AssertionError("ask_gemini must not be called when AI is off")

    monkeypatch.setattr(webhook.llm, "ask_gemini", _boom)
    db.set_ai(False)

    resp = client.post(
        "/webhook",
        json=_meta_payload(GUEST_PHONE, "What is check-in time?"),
    )
    assert resp.status_code == 200
    assert fake_send.calls == [
        (GUEST_PHONE, "AI is currently paused. The host will respond shortly.")
    ]


# ------------------------------------------------------------ POST owner


def test_post_owner_status_command(monkeypatch, client, fake_send):
    _config(monkeypatch)
    monkeypatch.setattr(webhook.wa, "send_whatsapp", fake_send)

    resp = client.post("/webhook", json=_meta_payload(OWNER_PHONE, "/status"))
    assert resp.status_code == 200
    assert len(fake_send.calls) == 1
    to, text = fake_send.calls[0]
    assert to == OWNER_PHONE
    # The owner got a plain (non-command) reply describing bot status.
    assert not text.strip().startswith("/")
    assert "AI:" in text

    # The owner message + admin reply are logged.
    hist = db.history(OWNER_PHONE)
    assert any(row["body"] == "/status" for row in hist)


def test_post_owner_updatekb_pending(monkeypatch, client, fake_send):
    _config(monkeypatch)
    monkeypatch.setattr(webhook.wa, "send_whatsapp", fake_send)
    # Owner is awaiting new KB content (e.g. after sending /updatekb).
    db.query(
        "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
        (f"pending_kb:{OWNER_PHONE}", "1"),
    )
    assert admin.expect_kb_update(OWNER_PHONE) is True

    resp = client.post(
        "/webhook",
        json=_meta_payload(OWNER_PHONE, "new kb"),
    )
    assert resp.status_code == 200
    assert db.get_kb() == "new kb"
    assert admin.expect_kb_update(OWNER_PHONE) is False
    assert fake_send.calls == [(OWNER_PHONE, "Knowledge Base updated.")]


def test_post_owner_sets_kb_flag_cleared_on_command(monkeypatch, client, fake_send):
    """A /command while pending an update routes to admin, not KB storage."""
    _config(monkeypatch)
    monkeypatch.setattr(webhook.wa, "send_whatsapp", fake_send)
    db.query(
        "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
        (f"pending_kb:{OWNER_PHONE}", "1"),
    )

    resp = client.post("/webhook", json=_meta_payload(OWNER_PHONE, "/status"))
    assert resp.status_code == 200
    # KB was NOT overwritten by the command text.
    assert db.get_kb() != "/status"
