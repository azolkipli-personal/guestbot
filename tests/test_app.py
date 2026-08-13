"""Task 8 — app factory + routing wiring tests."""

import pytest

from app import create_app


@pytest.fixture()
def app():
    """Build a fresh Flask app via the factory for each test."""
    return create_app()


def test_create_app_returns_flask_app(app):
    """The factory must return a valid Flask application."""
    assert app is not None
    # Flask.name is set; duck-type enough to confirm a real app object.
    assert hasattr(app, "url_map")
    assert hasattr(app, "test_client")


def test_health_route_mounted(app):
    """'/healthz' must be mounted in the URL map."""
    rules = {rule.rule for rule in app.url_map.iter_rules()}
    assert "/healthz" in rules


def test_root_landing_mounted(app):
    """The portal landing page is mounted at '/'."""
    rules = {rule.rule for rule in app.url_map.iter_rules()}
    assert "/" in rules


def test_webhook_route_mounted(app):
    """The webhook blueprint's '/webhook' endpoint must be mounted."""
    rules = {rule.rule for rule in app.url_map.iter_rules()}
    assert "/webhook" in rules


def test_health_endpoint_returns_ok(app):
    """GET /healthz must return 200 with a JSON {'ok': true} payload."""
    client = app.test_client()
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.get_json() == {"ok": True}
