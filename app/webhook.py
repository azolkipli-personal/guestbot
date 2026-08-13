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


def _wa_creds(tenant: dict | None = None) -> dict:
    """Return per-tenant (or env fallback) WhatsApp send credentials."""
    if tenant:
        return {
            "phone_number_id": tenant.get("phone_number_id"),
            "access_token": tenant.get("access_token"),
        }
    return {}


def _send(to: str, text: str, tenant: dict | None = None) -> bool:
    return wa.send_whatsapp(to, text, **_wa_creds(tenant))

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
    hub.challenge=<CHALLENGE>``. If the token matches a tenant's ``verify_token``
    (or the legacy global ``VERIFY_TOKEN``), echo the challenge back as plain
    text (HTTP 200); otherwise reject with 403.
    """
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    if mode == "subscribe" and (
        token == os.environ.get("VERIFY_TOKEN") or db.tenant_by_token(token or "") is not None
    ):
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
    """Extract the first inbound message and route it to the right tenant.

    The phone number ID the message arrived on (``value.metadata.phone_number_id``)
    identifies the tenant. Falls back to the legacy single-tenant path when no
    tenant owns that number (e.g. demo/":memory:" mode).
    """
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

    # Which Meta phone number received this? Resolves the tenant.
    meta_phone_id = (value.get("metadata") or {}).get("phone_number_id")
    tenant = db.tenant_row(meta_phone_id) if meta_phone_id else None
    tenant_id = tenant["id"] if tenant else None

    body = (msg.get("text") or {}).get("body", "") or ""
    db.log_message(phone, "user", body, tenant_id=tenant_id)

    owner = (tenant or {}).get("owner_phone") or os.environ.get("OWNER_PHONE")
    if phone == owner or admin.is_admin_command(body):
        return _handle_admin_message(phone, body, tenant)
    return _handle_guest_message(phone, body, tenant)


def _handle_admin_message(phone: str, body: str, tenant: dict | None = None):
    """Route an owner/admin message (or a pending-KB submission)."""
    if admin.expect_kb_update(phone) and not admin.is_admin_command(body):
        # Owner is in the middle of a /updatekb flow: the non-command body is
        # the new Knowledge Base content.
        db.set_kb(body, tenant)
        admin.clear_kb_update(phone)
        _send(phone, KB_UPDATED_REPLY, tenant)
        db.log_message(phone, "bot", KB_UPDATED_REPLY, tenant_id=tenant["id"] if tenant else None)
        return "ok", 200

    reply = admin.handle_admin(phone, body, tenant)
    _send(phone, reply, tenant)
    db.log_message(phone, "bot", reply, tenant_id=tenant["id"] if tenant else None)
    return "ok", 200


def _handle_guest_message(phone: str, body: str, tenant: dict | None = None):
    """Route a guest message through the AI assistant (tenant-scoped)."""
    if not db.ai_enabled(tenant):
        _send(phone, AI_PAUSED_REPLY, tenant)
        return "ok", 200

    tenant_id = tenant["id"] if tenant else None
    if db.is_paused(phone, tenant_id):
        # Host is already handling this guest manually — don't send anything.
        return "ok", 200

    kb = db.get_kb(tenant)
    result = llm.ask_gemini(kb, body, history=db.history(phone, tenant_id=tenant_id))
    reply = result["reply"]
    if result["handover"]:
        # Out of scope / handover: pause this guest so the host takes over.
        db.pause(phone, tenant_id)
    _send(phone, reply, tenant)
    db.log_message(phone, "bot", reply, tenant_id=tenant_id)
    if result["handover"]:
        # Ping the host after the guest gets their reply, so they're told
        # a manual takeover is needed.
        _notify_host_handover(phone, body, tenant)
    return "ok", 200


def _notify_host_handover(guest_phone: str, question: str, tenant: dict | None = None):
    """Message the host that a guest needs manual takeover.

    Uses the tenant's ``owner_phone`` (or the legacy ``OWNER_PHONE`` env
    fallback). Sends the guest's number + their last question so the host can
    jump into the conversation. Best-effort: a failed notification must never
    break the webhook, so failures are logged and swallowed.
    """
    owner_phone = (tenant or {}).get("owner_phone") or os.environ.get("OWNER_PHONE")
    if not owner_phone:
        return
    text = (
        "⚠️ A guest needs your help (out of scope).\n\n"
        f"Guest: {guest_phone}\n"
        f"They asked: {question[:200]}"
    )
    try:
        _send(owner_phone, text, tenant)
    except Exception as exc:  # noqa: BLE001 - never break the webhook on notify
        print(f"[webhook] handover notification failed: {exc!r}")

    # Optional: also email the host (only when a per-tenant email exists).
    try:
        from . import mail

        mail.notify_handover(tenant, guest_phone, question)
    except Exception as exc:  # noqa: BLE001
        print(f"[webhook] handover email failed: {exc!r}")
