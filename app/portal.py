"""Self-service web portal (onboarding + configuration).

A minimal browser UI so a non-developer homestay owner can set up and manage
their own bot without touching env vars, the terminal, or the Meta dashboard
beyond the one-time "Connect WhatsApp" OAuth click.

Routes
------
``GET  /``                     → landing page (signup / show setup form)
``POST /setup``                → create a tenant (name, email, KB, property)
``GET  /portal``               → tenant dashboard (after login via email link)
``POST /portal/kb``            → save the tenant's Knowledge Base
``POST /portal/toggle``        → turn AI on/off
``GET  /oauth/meta``           → start Meta "Connect WhatsApp" OAuth flow
``GET  /oauth/meta/callback``  → Meta OAuth callback (exchange code for token)

Login is intentionally simple: the owner enters their email; we email them a
magic link containing a per-tenant token. No passwords to manage.
"""
from __future__ import annotations

import os
import secrets

from flask import Blueprint, redirect, render_template_string, request, url_for

from . import db

portal_bp = Blueprint("portal", __name__)

# Markup for the dashboard (kept here so this module is self-contained).
_DASHBOARD = """<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{{ tenant.name }} — GuestBot</title>
<style>
 body{font-family:system-ui,sans-serif;max-width:760px;margin:2rem auto;padding:0 1rem;color:#222}
 h1{font-size:1.4rem} h2{font-size:1.1rem;margin-top:2rem}
 label{display:block;font-weight:600;margin:.8rem 0 .3rem}
 input,textarea{width:100%;padding:.5rem;border:1px solid #ccc;border-radius:6px;box-sizing:border-box}
 textarea{min-height:240px;font-family:monospace;font-size:.85rem}
 button{padding:.6rem 1.2rem;border:0;border-radius:6px;background:#075E54;color:#fff;font-weight:600;cursor:pointer}
 .muted{color:#666;font-size:.85rem} .ok{color:#1a7f37} .err{color:#d1242f}
 .card{border:1px solid #ddd;border-radius:10px;padding:1rem;margin:1rem 0}
 .tag{display:inline-block;padding:.15rem .6rem;border-radius:99px;font-size:.75rem;font-weight:700}
 .tag.on{background:#d3f9d8;color:#1a7f37} .tag.off{background:#ffe3e3;color:#d1242f}
</style></head><body>
 <h1>⚡ {{ tenant.property_name or tenant.name }}</h1>
 <p class="muted">WhatsApp phone number ID: <code>{{ tenant.phone_number_id or '— connect WhatsApp first' }}</code></p>

 <div class="card">
   <h2>Connect WhatsApp</h2>
   {% if tenant.access_token and tenant.phone_number_id %}
     <span class="tag on">Connected</span>
   {% else %}
     <a href="{{ url_for('portal.meta_oauth_start') }}"><button type="button">Connect with WhatsApp</button></a>
     <p class="muted">You'll log in with Meta/Facebook and grant the bot access to your WhatsApp Business number. Done once.</p>
   {% endif %}
 </div>

 <form method="post" action="{{ url_for('portal.save_kb') }}">
   <h2>Knowledge Base</h2>
   <input type="hidden" name="tk" value="{{ tenant.verify_token }}">
   <p class="muted">Everything the bot knows. Keep rates, amenities, rules, and booking link accurate here.</p>
   <label for="kb">Knowledge Base (markdown)</label>
   <textarea id="kb" name="kb">{{ tenant.kb or '' }}</textarea>
   <button style="margin-top:.8rem" type="submit">Save</button>
 </form>

 <div class="card">
   <h2>AI assistant</h2>
   <span class="tag {{ 'on' if tenant.ai_enabled else 'off' }}">{{ 'ON' if tenant.ai_enabled else 'OFF' }}</span>
   <form method="post" action="{{ url_for('portal.toggle_ai') }}" style="margin-top:.6rem">
     <input type="hidden" name="tk" value="{{ tenant.verify_token }}">
     <button type="submit">{{ 'Turn OFF' if tenant.ai_enabled else 'Turn ON' }}</button>
   </form>
 </div>

 <p class="muted" style="margin-top:2rem">
   Owner phone: <code>{{ tenant.owner_phone or '—' }}</code> ·
   Email: <code>{{ tenant.email }}</code><br>
   <a href="{{ url_for('portal.logout') }}">Sign out</a>
 </p>
</body></html>"""


def _render(html: str, **ctx):
    return render_template_string(html, **ctx)


@portal_bp.get("/")
def landing():
    return _render(
        """<!doctype html><html><head><meta charset="utf-8">
<title>GuestBot — set up your WhatsApp assistant</title>
<style>.wrap{max-width:520px;margin:3rem auto;padding:0 1rem;font-family:system-ui}
label{display:block;font-weight:600;margin:.8rem 0 .3rem}
input,textarea{width:100%;padding:.5rem;border:1px solid #ccc;border-radius:6px;box-sizing:border-box}
textarea{min-height:180px;font-family:monospace}
button{padding:.6rem 1.4rem;border:0;border-radius:6px;background:#075E54;color:#fff;font-weight:600;cursor:pointer}
.muted{color:#666;font-size:.9rem}</style></head><body><div class="wrap">
<h1>Set up your WhatsApp guest assistant</h1>
<p class="muted">Answer check-in questions, share your booking link, and hand off to you when needed — automatically, in Malay and English.</p>
<form method="post" action="{{ url_for('portal.setup') }}">
 <label>Homestay / property name</label>
 <input name="name" required placeholder="e.g. Arau House">
 <label>Your email (for login link &amp; alerts)</label>
 <input type="email" name="email" required placeholder="you@example.com">
 <label>Your WhatsApp number (host/admin)</label>
 <input name="owner_phone" required placeholder="+60123456789">
 <label>Knowledge Base (paste your property details in markdown)</label>
 <textarea name="kb" required placeholder="## Overview&#10;...&#10;## Rates&#10;...&#10;## Check-in / Check-out&#10;...&#10;## Amenities&#10;...&#10;## House rules&#10;...&#10;## Booking&#10;https://..."></textarea>
 <button style="margin-top:1rem" type="submit">Create assistant →</button>
</form>
<p class="muted">After this you'll be asked to <b>Connect with WhatsApp</b> (one Meta login). No code, no terminal.</p>
</div></body></html>"""
    )


@portal_bp.post("/setup")
def setup():
    name = (request.form.get("name") or "").strip()
    email = (request.form.get("email") or "").strip()
    owner_phone = (request.form.get("owner_phone") or "").strip()
    kb = (request.form.get("kb") or "").strip()

    if not (name and email and owner_phone and kb):
        return _render(
            '<h2>Missing fields</h2><p class="muted">Please fill in everything.</p>',
            title="Error",
        ), 400

    tenant = db.create_tenant(
        name=name,
        email=email,
        owner_phone=owner_phone,
        kb=kb,
    )

    # Email a magic login link with the tenant's verify_token (see mail.py).
    try:
        from . import mail

        mail.send_magic_link(tenant)
    except Exception as exc:  # noqa: BLE001 - email failure shouldn't block signup
        print(f"[portal] magic link email failed: {exc!r}")

    return redirect(url_for("portal.portal", tk=tenant["verify_token"]))


@portal_bp.get("/portal")
def portal():
    token = request.args.get("tk") or ""
    tenant = db.tenant_by_token(token)
    if tenant is None:
        return "Invalid or expired link. Please re-enter your email to get a new one.", 401
    return _render(_DASHBOARD, tenant=tenant)


@portal_bp.post("/portal/kb")
def save_kb():
    tenant = _require_tenant()
    if tenant is None:
        return "Unauthorized", 401
    kb = (request.form.get("kb") or "").strip()
    db.set_kb(kb, tenant)
    return redirect(url_for("portal.portal", tk=tenant["verify_token"]))


@portal_bp.post("/portal/toggle")
def toggle_ai():
    tenant = _require_tenant()
    if tenant is None:
        return "Unauthorized", 401
    db.set_ai(not db.ai_enabled(tenant), tenant)
    return redirect(url_for("portal.portal", tk=tenant["verify_token"]))


@portal_bp.get("/portal/logout")
def logout():
    return redirect(url_for("portal.landing"))


def _require_tenant():
    """Resolve tenant from the ``tk`` query param (magic login link token)."""
    token = request.args.get("tk") or request.form.get("tk") or ""
    return db.tenant_by_token(token)


# ---------------------------------------------------------------------------
# Meta "Connect WhatsApp" OAuth (scaffold)
#
# NOTE: this requires a Meta App (App ID + Client Secret) and the Meta Graph
# API ``whatsapp_business_messaging`` / ``whatsapp_business_management``
# permissions approved for it. Those app credentials are infrastructure owned
# by whoever runs the service, set via env: META_APP_ID, META_APP_SECRET.
# ---------------------------------------------------------------------------


@portal_bp.get("/oauth/meta")
def meta_oauth_start():
    tenant = _require_tenant()
    if tenant is None:
        return "Unauthorized", 401

    app_id = os.environ.get("META_APP_ID")
    if not app_id:
        return (
            "Meta OAuth is not configured yet (missing META_APP_ID). "
            "The service operator must create a Meta App first.",
            501,
        )

    # Persist the intended tenant so the callback can attribute the token.
    state = secrets.token_urlsafe(24)
    db.set_oauth_state(tenant["id"], state)
    redirect_uri = url_for("portal.meta_oauth_callback", _external=True)
    scope = "whatsapp_business_messaging,whatsapp_business_management"
    return redirect(
        "https://www.facebook.com/v20.0/dialog/oauth"
        f"?client_id={app_id}"
        f"&redirect_uri={redirect_uri}"
        f"&state={state}"
        f"&scope={scope}"
    )


@portal_bp.get("/oauth/meta/callback")
def meta_oauth_callback():
    """Exchange the OAuth code (and optionally a long-lived token) for the
    tenant's WhatsApp credentials, then store them on the tenant."""
    error = request.args.get("error")
    if error:
        return f"Connection failed: {error}", 400

    code = request.args.get("code")
    state = request.args.get("state")
    if not code:
        return "Missing code.", 400

    tenant = db.tenant_by_oauth_state(state or "")
    if tenant is None:
        return "Invalid or expired session. Please reconnect from your dashboard.", 401

    # TODO: exchange ``code`` for a long-lived access token via
    #  POST https://graph.facebook.com/v20.0/oauth/access_token
    #  then call the Graph API to fetch the connected phone_number_id and
    #  persist: db.update_tenant_by_id(tenant["id"], access_token="..."
    #  phone_number_id="..."). Placeholder below returns to the dashboard.
    db.update_tenant_by_id(tenant["id"], oauth_state=None)
    return redirect(url_for("portal.portal", tk=tenant["verify_token"]))
