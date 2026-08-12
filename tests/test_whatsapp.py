"""Tests for the WhatsApp outbound send helper (Task 4).

These tests NEVER hit the network. ``requests.post`` is replaced with a fake
via pytest ``monkeypatch`` so we can assert the exact URL, headers, and JSON
body that ``app.whatsapp.send_whatsapp`` would send to the Meta Graph API.
"""
import requests

from app import whatsapp

TOKEN = "EAA_TEST_TOKEN_123"
PHONE_NUMBER_ID = "1234567890123456"
RECIPIENT = "+60123456789"
MESSAGE = "hi"


class _FakeResponse:
    """Mimics ``requests.Response`` minimally: ``.status_code`` and ``.json()``."""

    def __init__(self, status_code: int):
        self.status_code = status_code

    def json(self):
        return {}


class _FakePost:
    """Replaces ``requests.post``; records each call's (url, json=, headers=)."""

    def __init__(self, status_code: int = 200, raise_exc: bool = False):
        self.status_code = status_code
        self.raise_exc = raise_exc
        self.calls = []  # list of (url, json, headers)

    def __call__(self, url, json=None, headers=None, **kwargs):
        self.calls.append((url, json, headers))
        if self.raise_exc:
            raise requests.RequestException("network down")
        return _FakeResponse(self.status_code)


def _install_fake(monkeypatch, **kwargs) -> _FakePost:
    """Patch env vars to known values and swap in the fake ``requests.post``."""
    monkeypatch.setenv("WHATSAPP_ACCESS_TOKEN", TOKEN)
    monkeypatch.setenv("WHATSAPP_PHONE_NUMBER_ID", PHONE_NUMBER_ID)
    fake = _FakePost(**kwargs)
    monkeypatch.setattr(requests, "post", fake)
    return fake


def test_posts_once_with_correct_url_headers_body(monkeypatch):
    fake = _install_fake(monkeypatch)
    whatsapp.send_whatsapp(RECIPIENT, MESSAGE)

    assert len(fake.calls) == 1
    url, body, headers = fake.calls[0]

    # URL must route to the Meta Graph API using the env phone-number-id.
    assert f"/v21.0/{PHONE_NUMBER_ID}/messages" in url
    assert "graph.facebook.com" in url

    # Auth + content-type headers.
    assert headers["Authorization"].startswith("Bearer ")
    assert TOKEN in headers["Authorization"]
    assert headers["Content-Type"] == "application/json"

    # JSON body shape.
    assert body["messaging_product"] == "whatsapp"
    assert body["to"] == RECIPIENT
    assert body["type"] == "text"
    assert body["text"]["body"] == MESSAGE


def test_returns_true_on_200(monkeypatch):
    _install_fake(monkeypatch, status_code=200)
    assert whatsapp.send_whatsapp(RECIPIENT, MESSAGE) is True


def test_returns_true_on_201(monkeypatch):
    _install_fake(monkeypatch, status_code=201)
    assert whatsapp.send_whatsapp(RECIPIENT, MESSAGE) is True


def test_returns_false_on_400(monkeypatch):
    _install_fake(monkeypatch, status_code=400)
    assert whatsapp.send_whatsapp(RECIPIENT, MESSAGE) is False


def test_returns_false_on_network_error(monkeypatch):
    _install_fake(monkeypatch, raise_exc=True)
    assert whatsapp.send_whatsapp(RECIPIENT, MESSAGE) is False


def test_returns_false_when_token_missing(monkeypatch):
    monkeypatch.delenv("WHATSAPP_ACCESS_TOKEN", raising=False)
    monkeypatch.setenv("WHATSAPP_PHONE_NUMBER_ID", PHONE_NUMBER_ID)
    fake = _FakePost()
    monkeypatch.setattr(requests, "post", fake)
    assert whatsapp.send_whatsapp(RECIPIENT, MESSAGE) is False
    assert fake.calls == []  # no network call attempted


def test_returns_false_when_phone_number_id_missing(monkeypatch):
    monkeypatch.setenv("WHATSAPP_ACCESS_TOKEN", TOKEN)
    monkeypatch.delenv("WHATSAPP_PHONE_NUMBER_ID", raising=False)
    assert whatsapp.send_whatsapp(RECIPIENT, MESSAGE) is False
