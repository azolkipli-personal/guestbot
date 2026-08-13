"""
WhatsApp Guest Assistant (GuestBot).

Flask application package. Exposes the application factory `create_app()`.
"""
from __future__ import annotations

import os

from dotenv import load_dotenv
from flask import Flask, jsonify


def create_app() -> Flask:
    """Application factory — build and configure the Flask app."""
    load_dotenv()

    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    @app.get("/healthz")
    def health():
        """Health check for uptime monitors and deployment verification."""
        return jsonify({"ok": True}), 200

    # Webhook blueprint is registered in Task 7; guard so the factory stays
    # runnable before that module exists.
    try:
        from .webhook import webhook_bp

        app.register_blueprint(webhook_bp)
    except ImportError:
        pass

    # Self-service web portal (onboarding + configuration) — powers the
    # root landing page and tenant dashboard.
    try:
        from .portal import portal_bp

        app.register_blueprint(portal_bp)
    except ImportError:
        pass

    return app
