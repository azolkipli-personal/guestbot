"""WhatsApp outbound send helper for the guest assistant bot (Task 4).

Posts a text message to a recipient via the Meta WhatsApp Graph API. Reading
env vars is deferred to call time and fully optional — the module imports and
the helper degrade gracefully (returning False) when credentials are absent,
so tests and non-WhatsApp environments never fail.
"""
from __future__ import annotations

import os

import requests

_GRAPH_API_VERSION = "v21.0"
_ENDPOINT = "https://graph.facebook.com/{version}/{phone_number_id}/messages"


def send_whatsapp(to: str, text: str) -> bool:
    """Send ``text`` to ``to`` over WhatsApp. Return True on HTTP 2xx.

    Returns False (without raising) if the ``WHATSAPP_ACCESS_TOKEN`` or
    ``WHATSAPP_PHONE_NUMBER_ID`` env vars are missing, on any non-2xx HTTP
    status, or on a network error.
    """
    token = os.environ.get("WHATSAPP_ACCESS_TOKEN")
    phone_number_id = os.environ.get("WHATSAPP_PHONE_NUMBER_ID")
    if not token or not phone_number_id:
        return False

    url = _ENDPOINT.format(
        version=_GRAPH_API_VERSION,
        phone_number_id=phone_number_id,
    )
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": text},
    }

    try:
        resp = requests.post(url, json=payload, headers=headers)
    except requests.RequestException:
        return False

    return 200 <= resp.status_code < 300
