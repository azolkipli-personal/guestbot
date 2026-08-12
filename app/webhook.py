"""Meta WhatsApp webhook integration (Task 7).

Exposes the inbound webhook endpoint Meta calls for new messages. The
blueprint ``webhook_bp`` is auto-registered by the app factory in
``app/__init__.py``.

Collaborators (``db``, ``llm``, ``wa``, ``admin``) are imported as module
attributes and env vars (``OWNER_PHONE``, ``VERIFY_TOKEN``) are read at call
time via ``os.environ`` so tests can monkeypatch either layer freely.
"""
from __future__ import annotations

import os

from flask import Blueprint, request

from . import admin
from . import db
from . import llm
from . import whatsapp as wa

webhook_bp = Blueprint("webhook", __name__)

AI_PAUSED_REPLY = "AI is currently paused. The host will respond shortly."
KB_UPDATED_REPLY = "Knowledge Base updated."

# Future hardening (optional, out of scope for this task): verify inbound
# request signatures using the ``X-Hub-Signature-256`` header + ``APP_SECRET``
# in a before_request hook before processing any payload.


def _ensure_db() -> None:
    """Make sure the DB is usable before handling a message.

    Uses ``db._ensure_ready()`` (rather than ``db.init_db()``) so that an
    already-initialized connection — such as a test ``:memory:`` DB — is
    preserved instead of being swapped for the default file. In production this
    lazily initializes the default ``DB_PATH`` connection on first use.
    """
    db._ensure_ready()


@webhook_bp.get("/webhook")
def verify_webhook():
    """Answer Meta's webhook subscription verification handshake.

    Meta GETs ``/webhook?hub.mode=subscribe&hub.verify_token=<TOKEN>&
    hub.challenge=<CHALLENGE>``. If the token matches ``VERIFY_TOKEN``, echo the
    challenge back as plain text (HTTP 200); otherwise reject with 403.
    """
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    if mode == "subscribe" and token == os.environ.get("VERIFY_TOKEN"):
        return challenge, 200
    return "Forbidden", 403


@webhook_bp.post("/webhook")
def handle_webhook():
    """Process inbound messages from Meta's WhatsApp Cloud API.

    Valid payloads always return HTTP 200 so Meta won't retry; any unexpected
    error is logged rather than surfaced as a 5xx (which would trigger Meta's
    exponential retries).
    """
    try:
        return _process_payload()
    except Exception as exc:  # noqa: BLE001 - defects must not cause retries
        # WhatsApp expects 200 to avoid retries; log the failure and move on.
        print(f"[webhook] error handling payload: {exc!r}")
        return "ok", 200


def _process_payload():
    """Extract the first inbound message and route it to the right handler."""
    _ensure_db()

    data = request.get_json(silent=True) or {}
    entries = data.get("entry") or []
    if not entries:
        return "ok", 200
    changes = entries[0].get("changes") or []
    if not changes:
        return "ok", 200
    value = changes[0].get("value") or {}
    messages = value.get("messages") or []
    if not messages:
        return "ok", 200

    msg = messages[0]
    phone = msg.get("from")
    if not phone:
        return "ok", 200
    body = (msg.get("text") or {}).get("body", "") or ""

    db.log_message(phone, "user", body)

    owner = os.environ.get("OWNER_PHONE")
    if phone == owner or admin.is_admin_command(body):
        return _handle_admin_message(phone, body)
    return _handle_guest_message(phone, body)


def _handle_admin_message(phone: str, body: str):
    """Route an owner/admin message (or a pending-KB submission)."""
    if admin.expect_kb_update(phone) and not admin.is_admin_command(body):
        # Owner is in the middle of a /updatekb flow: the non-command body is
        # the new Knowledge Base content.
        db.set_kb(body)
        admin.clear_kb_update(phone)
        wa.send_whatsapp(phone, KB_UPDATED_REPLY)
        db.log_message(phone, "bot", KB_UPDATED_REPLY)
        return "ok", 200

    reply = admin.handle_admin(phone, body)
    wa.send_whatsapp(phone, reply)
    db.log_message(phone, "bot", reply)
    return "ok", 200


def _handle_guest_message(phone: str, body: str):
    """Route a guest message through the AI assistant."""
    if not db.ai_enabled():
        wa.send_whatsapp(phone, AI_PAUSED_REPLY)
        return "ok", 200

    if db.is_paused(phone):
        # Host is already handling this guest manually — don't send anything.
        return "ok", 200

    kb = db.get_kb()
    result = llm.ask_gemini(kb, body, history=db.history(phone))
    reply = result["reply"]
    if result["handover"]:
        # Out of scope / handover: pause this guest so the host takes over.
        db.pause(phone)
        # TODO(host-notification): notify the host that a handover is needed —
        # e.g. forward a summary to the owner's phone, or push to a dashboard.
    wa.send_whatsapp(phone, reply)
    db.log_message(phone, "bot", reply)
    return "ok", 200
