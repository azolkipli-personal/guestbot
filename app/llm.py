"""Gemini LLM wrapper for the WhatsApp guest assistant bot.

Wraps Google Gemini Flash via the ``google-genai`` library. The client is
lazily initialized so the module stays importable (and testable) without a
``GEMINI_API_KEY``; tests monkeypatch ``_get_client`` to inject a fake.

Functions are focused and pure-ish: ``ask_gemini`` returns a plain dict.
"""
from __future__ import annotations

import os

from . import kb as kb_mod
from . import lang as lang_mod

# Lazily-created module-level client (only on real calls). Tests may set this
# directly or (preferred) monkeypatch ``_get_client``.
client = None

# Default model; override via GEMINI_MODEL for cheap/fast experiments.
DEFAULT_MODEL = "gemini-2.5-flash"

HANDOVER_MARKER = "[[HANDOVER]]"
BOOKING_MARKER = "[[BOOKING]]"

# Branding; override via PROPERTY_NAME env (e.g. "Arau House"). Keeps the same
# codebase deployable to any homestay/B&B.
def _property_name() -> str:
    return os.environ.get("PROPERTY_NAME", "the property")


def _get_client():
    """Return the module client, creating the real one on first use.

    Falls back to a fresh ``google.genai.Client`` constructed from the
    ``GEMINI_API_KEY`` environment variable if ``client`` is not already set.
    """
    global client
    if client is not None:
        return client
    from google import genai

    client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY", ""))
    return client


def _system_prompt() -> str:
    """Build the system prompt, using the configured property name."""
    name = _property_name()
    return (
        f"You are {name}'s friendly WhatsApp assistant. Answer ONLY from the "
        "provided knowledge base (KB); never invent facts. Keep answers short "
        "and friendly. Detect the guest's language (English or Bahasa Malaysia) "
        "and reply in the same language.\n"
        "If the guest asks about booking, pricing, or availability, include the "
        f"booking marker {BOOKING_MARKER} in your reply where the booking link should go.\n"
        f"If the question is OUT OF SCOPE (cannot be answered from the KB), end "
        f"your reply with the marker {HANDOVER_MARKER}.\n"
    )


def _build_prompt(kb: str, history: list[dict] | None, message: str) -> str:
    """Assemble the model input: system instructions + KB + history + message."""
    parts = [_system_prompt(), "\n=== KNOWLEDGE BASE ===\n", kb]
    if history:
        parts.append("\n=== CONVERSATION HISTORY ===")
        for turn in history:
            role = turn.get("role", "user")
            content = turn.get("content", "")
            parts.append(f"{role}: {content}")
    parts.append("\n=== CURRENT GUEST MESSAGE ===")
    parts.append(message)
    parts.append(
        "\n=== REPLY ==="
        "\n(Reply in the guest's language, grounded only in the KB above.)"
    )
    return "\n".join(parts)


def _substitute_booking(reply: str, kb: str) -> str:
    """Replace ``[[BOOKING]]`` with the real booking link from the KB."""
    link = kb_mod.extract_booking_link(kb)
    if BOOKING_MARKER in reply:
        reply = reply.replace(BOOKING_MARKER, link or "")
    return reply


def ask_gemini(kb: str, message: str, history: list[dict] | None = None) -> dict:
    """Ask the Gemini model and return ``{"reply", "handover", "language"}``.

    ``kb`` grounds the answer, ``message`` is the guest's latest message, and
    ``history`` (optional) is a list of ``{"role": ..., "content": ...}`` turns.

    ``language`` is always derived from ``message`` via
    ``app.lang.detect_language``. ``handover`` is True when the model emits the
    ``[[HANDOVER]]`` marker, or when the reply is empty.
    """
    prompt = _build_prompt(kb, history, message)
    gen = _get_client().models.generate_content(
        model=os.environ.get("GEMINI_MODEL", DEFAULT_MODEL),
        contents=prompt,
    )
    reply = getattr(gen, "text", "") or ""

    handover = False
    if HANDOVER_MARKER in reply:
        handover = True
        reply = reply.replace(HANDOVER_MARKER, "").strip()

    reply = _substitute_booking(reply, kb)

    if not reply:
        handover = True

    language = lang_mod.detect_language(message)

    return {"reply": reply, "handover": handover, "language": language}
