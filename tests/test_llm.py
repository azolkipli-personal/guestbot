"""Tests for the Gemini LLM wrapper (Task 3).

These tests NEVER hit the real Gemini API. A fake genai client is injected
via pytest ``monkeypatch`` on ``app.llm._get_client``.
"""
import pytest

from app import lang
from app import llm

BOOKING_URL = "https://www.booking.com/Share-gtWXR5"


class _FakeResponse:
    """Mimics ``genai.types.GenerateContentResponse``: has a `.text`."""

    def __init__(self, text: str):
        self.text = text


class _FakeModels:
    """Mimics ``genai.types.GenerativeModel`` so ``.models.generate_content`` works."""

    def __init__(self, client):
        self._client = client

    def generate_content(self, model, contents, **kwargs):
        self._client.calls.append((model, contents))
        return self._client._reply


class _FakeClient:
    """Mimics ``genai.Client``: only ``.models.generate_content`` is used."""

    def __init__(self):
        self.calls = []  # list of (model, contents)
        self.models = _FakeModels(self)

    def set_reply(self, text: str):
        """Define the canned response the fake client should return."""
        self._reply = _FakeResponse(text)


@pytest.fixture()
def fake_client(monkeypatch):
    client = _FakeClient()
    client.set_reply("dummy")
    # Inject the seam so llm uses the fake and never touches the real API.
    monkeypatch.setattr(llm, "_get_client", lambda: client)
    monkeypatch.setattr(llm, "client", client)
    return client


def _last_contents(client):
    assert client.calls, "generate_content was never called"
    return client.calls[-1][1]


def test_reply_false_handover_en(fake_client):
    fake_client.set_reply("Check-in is at 15:00")
    result = llm.ask_gemini("KB text", "What time is check-in?")
    assert result == {
        "reply": "Check-in is at 15:00",
        "handover": False,
        "language": "en",
    }


def test_handover_marker_stripped(fake_client):
    fake_client.set_reply("I do not know that [[HANDOVER]]")
    result = llm.ask_gemini("KB text", "What is the wifi password?")
    assert result["handover"] is True
    assert "[[HANDOVER]]" not in result["reply"]
    assert result["reply"] == "I do not know that"
    assert result["language"] == "en"


def test_empty_reply_handover(fake_client):
    fake_client.set_reply("")
    result = llm.ask_gemini("KB text", "Where is the pool?")
    assert result["handover"] is True
    assert result["reply"] == ""


def test_booking_link_substitution(fake_client):
    fake_client.set_reply("Here is the booking link [[BOOKING]]")
    result = llm.ask_gemini(f"## Booking\n{BOOKING_URL}", "Can I book?")
    assert BOOKING_URL in result["reply"]
    assert "[[BOOKING]]" not in result["reply"]


def test_malay_language_detection(fake_client):
    fake_client.set_reply("Harga adalah RM350 semalam.")
    result = llm.ask_gemini("KB text", "Berapa harga?")
    assert result["language"] == "ms"


def test_prompt_grounded_in_kb(fake_client):
    kb_text = "Check-in is at 15:00. Check-out is at 12:00."
    llm.ask_gemini(kb_text, "What time is check-in?")
    contents = _last_contents(fake_client)
    # The KB text must be embedded in the prompt sent to the model.
    assert kb_text in contents


def test_prompt_uses_configured_property_name(fake_client, monkeypatch):
    monkeypatch.setenv("PROPERTY_NAME", "Bintang Homestay")
    llm.ask_gemini("KB", "hi")
    contents = _last_contents(fake_client)
    assert "Bintang Homestay's friendly WhatsApp assistant" in contents


def test_prompt_default_property_name(fake_client, monkeypatch):
    monkeypatch.delenv("PROPERTY_NAME", raising=False)
    llm.ask_gemini("KB", "hi")
    contents = _last_contents(fake_client)
    assert "the property's friendly WhatsApp assistant" in contents
