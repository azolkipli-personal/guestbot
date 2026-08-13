"""Owner admin command parser (Task 6).

Implements the ``/``-prefixed admin commands the owner sends to the bot.
Parsing is intentionally small and stdlib-only (``re`` + the
``app.db`` state store). The ``handle_admin`` function returns the reply text
for a command; multi-step state (the pending ``/updatekb`` flow) is stored in
the DB settings table under ``pending_kb:<phone>=1``.
"""
from __future__ import annotations

import re

from . import db


def _pending_kb_key(phone: str) -> str:
    """Settings key used to flag that ``phone`` is awaiting new KB content."""
    return f"pending_kb:{phone}"


def is_admin_command(text: str) -> bool:
    """Return True if ``text`` starts with a trimmed ``/`` command word."""
    return text.strip().startswith("/")


def expect_kb_update(phone: str) -> bool:
    """Return True if ``phone`` is currently awaiting new KB content."""
    row = db.query(
        "SELECT value FROM settings WHERE key = ?",
        (_pending_kb_key(phone),),
        fetch=True,
    )
    if not row:
        return False
    return row[0]["value"] == "1"


def clear_kb_update(phone: str) -> None:
    """Clear the pending-KB flag for ``phone``."""
    db.query(
        "DELETE FROM settings WHERE key = ?",
        (_pending_kb_key(phone),),
    )


def _set_kb_pending(phone: str) -> None:
    db.query(
        "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
        (_pending_kb_key(phone), "1"),
    )


def _help_text() -> str:
    return (
        "Owner commands:\n"
        "/status\n"
        "/pause <phone>\n"
        "/resume <phone>\n"
        "/history <phone>\n"
        "/list\n"
        "/ai on|off\n"
        "/viewkb\n"
        "/updatekb\n"
        "/help"
    )


def _status_text(tenant: dict | None = None) -> str:
    ai = "ON" if db.ai_enabled(tenant) else "OFF"
    paused = [r["phone"] for r in db.list_all(tenant) if r["paused"]]
    if not paused:
        return f"AI: {ai}\nPaused (0)"
    lines = [f"AI: {ai}\nPaused ({len(paused)}):"]
    for phone in paused:
        lines.append(f"- {phone}")
    return "\n".join(lines)


def _history_text(phone: str, tenant: dict | None = None) -> str:
    hist = db.history(phone, tenant_id=tenant["id"] if tenant else None)
    if not hist:
        return f"No history for {phone}"
    lines = []
    for row in hist:
        role = row["role"]
        body = row["body"] if row["body"] is not None else ""
        lines.append(f"{role}: {body}")
    return "\n".join(lines)


def _list_text(tenant: dict | None = None) -> str:
    rows = db.list_all(tenant)
    if not rows:
        return "No users yet"
    lines = []
    for row in rows:
        marker = " (paused)" if row["paused"] else ""
        lines.append(f"{row['phone']}{marker}")
    return "\n".join(lines)


def handle_admin(phone: str, text: str, tenant: dict | None = None) -> str:
    """Parse and execute an owner admin command, returning the reply string.

    ``phone`` is used as the key for the pending ``/updatekb`` state (not the
    command argument). Pass a ``tenant`` dict to scope KB/AI state to that
    owner; ``None`` falls back to the legacy single-tenant store. Unknown
    ``/`` commands get a short "unknown command" reply with a ``/help`` hint.
    Expects the caller to gate on ``is_admin_command`` before routing here.
    """
    stripped = text.strip()
    # Split on whitespace; first token is the command word.
    parts = stripped.split()
    cmd = parts[0].lstrip("/").lower()
    arg = parts[1] if len(parts) > 1 else ""

    if cmd == "help":
        return _help_text()
    if cmd == "status":
        return _status_text(tenant)
    if cmd == "pause":
        if not arg:
            return "Usage: /pause <phone>"
        db.pause(arg, tenant["id"] if tenant else None)
        return f"Paused {arg}"
    if cmd == "resume":
        if not arg:
            return "Usage: /resume <phone>"
        db.unpause(arg)
        return f"Resumed {arg}"
    if cmd == "history":
        if not arg:
            return "Usage: /history <phone>"
        return _history_text(arg, tenant)
    if cmd == "list":
        return _list_text(tenant)
    if cmd == "ai":
        if arg and arg.lower() in ("on", "off"):
            enabled = arg.lower() == "on"
            db.set_ai(enabled, tenant)
            return "AI: ON" if enabled else "AI: OFF"
        return "Usage: /ai on|off"
    if cmd == "viewkb":
        return db.get_kb(tenant)
    if cmd == "updatekb":
        _set_kb_pending(phone)
        return "Please send the new Knowledge Base content:"

    return "unknown command. Type /help for available commands."
