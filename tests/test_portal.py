"""Tests for the self-service web portal (onboarding + conversation view)."""
import pytest
from unittest import mock

from app import create_app
from app import db


@pytest.fixture(autouse=True)
def clean_db():
    db._reset_for_tests()
    db.init_db(":memory:")


def _make_tenant(cred=False):
    kw = dict(
        name="Arau House",
        email="host@example.com",
        owner_phone="+60129775626",
        kb="## Overview\nNice house",
        property_name="Arau House",
    )
    if cred:
        kw["phone_number_id"] = "1329230323602009"
        kw["access_token"] = "TESTTOKENPLACEHOLDER123"
    return db.create_tenant(**kw)


def _client():
    return create_app().test_client()


def test_conversation_view_shows_guest_and_messages():
    t = _make_tenant()
    c = _client()
    db.log_message("60123456789", "user", "berapa harga?", tenant_id=t["id"])
    db.log_message("60123456789", "bot", "RM 200", tenant_id=t["id"])

    resp = c.get(f"/portal/conversation?tk={t['verify_token']}&guest=60123456789")
    assert resp.status_code == 200
    assert "berapa harga?".encode() in resp.data
    assert "RM 200".encode() in resp.data


def test_conversation_requires_auth():
    t = _make_tenant()
    c = _client()
    resp = c.get(f"/portal/conversation?tk=WRONG&guest=60123456789")
    assert resp.status_code == 401


def test_portal_reply_sends_and_logs():
    t = _make_tenant(cred=True)
    c = _client()
    db.log_message("60123456789", "user", "ada bilik tak?", tenant_id=t["id"])

    with mock.patch("app.portal.wa.send_whatsapp", return_value=True) as send:
        resp = c.post(
            "/portal/reply",
            data={"tk": t["verify_token"], "guest": "60123456789", "message": "Ada!"},
        )
    assert resp.status_code == 302
    assert send.called
    args = send.call_args
    assert args[0] == ("60123456789", "Ada!")
    assert args[1]["phone_number_id"] == "1329230323602009"
    hist = db.history("60123456789", tenant_id=t["id"])
    assert any(row["body"] == "Ada!" and row["role"] == "bot" for row in hist)


def test_portal_reply_requires_whatsapp_connected():
    t = _make_tenant(cred=False)
    c = _client()
    resp = c.post(
        "/portal/reply",
        data={"tk": t["verify_token"], "guest": "60123456789", "message": "hi"},
    )
    assert resp.status_code == 409


def test_portal_toggle_pause():
    t = _make_tenant()
    c = _client()
    assert db.is_paused("60123456789", t["id"]) is False
    c.post(
        "/portal/toggle-pause",
        data={"tk": t["verify_token"], "guest": "60123456789"},
    )
    assert db.is_paused("60123456789", t["id"]) is True
    c.post(
        "/portal/toggle-pause",
        data={"tk": t["verify_token"], "guest": "60123456789"},
    )
    assert db.is_paused("60123456789", t["id"]) is False
