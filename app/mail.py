"""Email delivery for the GuestBot self-service portal.

Currently implements a NO-OP / console logger and a pluggable hook so the
magic-login link and notifications can go to a real email provider. The
service operator wires one of the ``send_via_*`` options (or another) via
env: EMAIL_PROVIDER=console|sendgrid|resend|smtp.

Because the app must never block signup on email, every send is best-effort
and swallows exceptions at the call site (see portal.setup).
"""
from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage


def _provider() -> str:
    return os.environ.get("EMAIL_PROVIDER", "console").strip().lower()


def _sender() -> str:
    return os.environ.get("EMAIL_FROM", "GuestBot <no-reply@guestbot.app>")


def send_magic_link(tenant: dict) -> bool:
    """Email the owner a magic login link for their dashboard.

    The link is the tenant's per-tenant ``verify_token``, which doubles as the
    portal log-in token (``/portal?tk=...``).
    """
    token = tenant.get("verify_token")
    base = os.environ.get("PUBLIC_BASE_URL", "http://localhost:10000").rstrip("/")
    link = f"{base}/portal?tk={token}"
    subject = "Your GuestBot dashboard"
    body = (
        f"Hi {tenant.get('name', 'there')},\n\n"
        "Here's the link to manage your WhatsApp guest assistant:\n\n"
        f"{link}\n\n"
        "Keep it private — anyone with this link can manage your bot."
    )
    return _send(tenant.get("email"), subject, body)


def notify_handover(tenant: dict, guest_phone: str, question: str) -> bool:
    """Email the owner that a guest needs manual takeover."""
    subject = f"Guest needs your help: {guest_phone}"
    body = (
        "A guest asked something outside the bot's knowledge base:\n\n"
        f"Guest: {guest_phone}\n"
        f"Asked: {question[:500]}\n\n"
        "Reply to them directly on WhatsApp, then /resume them so the bot "
        "can help again."
    )
    return _send(tenant.get("email"), subject, body)


def _send(to: str, subject: str, body: str) -> bool:
    """Route to the configured provider. Returns True on success."""
    if not to:
        return False
    provider = _provider()
    try:
        if provider == "sendgrid":
            return _send_sendgrid(to, subject, body)
        if provider == "resend":
            return _send_resend(to, subject, body)
        if provider == "smtp":
            return _send_smtp(to, subject, body)
        return _send_console(to, subject, body)
    except Exception as exc:  # noqa: BLE001 - never let email break the app
        print(f"[mail] send failed ({provider}): {exc!r}")
        return False


def _send_console(to: str, subject: str, body: str) -> bool:
    """Default: log to stdout (dev). Real providers below are ready to wire."""
    print(f"\n=== [mail:console] to={to} subject={subject} ===\n{body}\n")
    return True


def _send_sendgrid(to: str, subject: str, body: str) -> bool:
    import requests  # type: ignore[import-not-found]

    api_key = os.environ.get("SENDGRID_API_KEY")
    if not api_key:
        return False
    resp = requests.post(
        "https://api.sendgrid.com/v3/mail/send",
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "personalizations": [{"to": [{"email": to}]}],
            "from": {"email": _sender()},
            "subject": subject,
            "content": [{"type": "text/plain", "value": body}],
        },
    )
    return resp.status_code < 300


def _send_resend(to: str, subject: str, body: str) -> bool:
    import requests  # type: ignore[import-not-found]

    api_key = os.environ.get("RESEND_API_KEY")
    if not api_key:
        return False
    resp = requests.post(
        "https://api.resend.com/emails",
        headers={"Authorization": f"Bearer {api_key}"},
        json={"from": _sender(), "to": [to], "subject": subject, "text": body},
    )
    return resp.status_code < 300


def _send_smtp(to: str, subject: str, body: str) -> bool:
    host = os.environ.get("SMTP_HOST")
    user = os.environ.get("SMTP_USER")
    pw = os.environ.get("SMTP_PASS")
    if not host:
        return False
    msg = EmailMessage()
    msg["From"] = _sender()
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    with smtplib.SMTP(host, int(os.environ.get("SMTP_PORT", "587"))) as server:
        if os.environ.get("SMTP_TLS", "1").lower() in ("1", "true", "yes"):
            server.starttls()
        if user:
            server.login(user, pw or "")
        server.send_message(msg)
    return True
