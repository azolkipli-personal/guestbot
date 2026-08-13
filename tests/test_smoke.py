"""Smoke test — the app boots; /healthz serves {"ok": true}."""
from app import create_app


def test_health_route():
    client = create_app().test_client()
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.get_json() == {"ok": True}


def test_app_factory():
    app = create_app()
    assert app is not None
