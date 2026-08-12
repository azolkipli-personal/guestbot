# WhatsApp AI Guest Assistant — Arau House — Design Spec

**Date:** 2026-08-12
**Status:** Approved by Ammar (concept + KB confirmed 2026-08-12)
**Source docs:** `homestay-chatbot-proposal.html`, `homestay-chatbot-plan.html`, `homestay-chatbot-wireframes.html`, `KNOWLEDGE_BASE.md`

## Goal

A WhatsApp AI chatbot that handles guest inquiries 24/7 for Arau House (Perlis), answering from a Knowledge Base, redirecting booking requests to the booking link, and handing over to the host when out of scope. The host controls everything via WhatsApp commands to a separate admin bot.

**Primary intent (Ammar):** working prototype, cheap/free, hosted (not on NUC), EN + BM only.

## Scope (this spec)

- Flask backend, hosted on Render free tier (or Railway $5).
- WhatsApp Cloud API inbound webhook + outbound replies.
- Gemini Flash (free tier) as the LLM, grounded on the KB.
- Language auto-detect (EN/BM), booking-link redirect.
- Handover logic (guest paused, host replies manually, `/resume`).
- Owner admin command bot (`/status`, `/pause`, `/resume`, `/history`, `/list`, `/ai on/off`, `/viewkb`, `/updatekb`, `/help`).
- SQLite for conversation + pause state. Telegram/WhatsApp handover alert.
- KB stored as editable document, updatable via `/updatekb`.

## Non-goals (YAGNI)

- No web dashboard (WhatsApp-only owner control — per Ammar).
- No multi-property support yet (architecture leaves room, not built now).
- No payments / availability management (redirects to Booking.com).
- No Mandarin (per Ammar; host manages EN + BM only).
- No voice-to-text in v1 (handover on voice messages).
- No auto schedule on/off (manual `/ai off` `/ai on` is enough for v1).

## Architecture

```
Guest (WhatsApp) ──► WhatsApp Cloud API ──► Flask webhook ──► Gemini (KB-grounded)
                                                        │
        reply to guest ◄───────────────────────────────┘
        handover → pause guest → notify host → host replies manually on WhatsApp
        host done → /resume [phone] on admin bot → AI resumes that guest
```

- **Backend:** Python Flask + Gunicorn, single app.
- **DB:** SQLite (file, committed/synced to hosting). Tables: `conversations`, `paused`, `kb`, `settings`.
- **LLM:** Google Gemini Flash via `google-genai` SDK. Prompt = KB content + guest message; instruct to answer only from KB, detect language, redirect booking intent, and output a "HANDOVER" flag when out of scope.
- **WhatsApp:** Meta WhatsApp Cloud API. Webhook endpoint `POST /webhook` (verify with `GET /webhook`), send via Graph API to `PHONE_NUMBER_ID`. Template-free via free-form message API for conversations started by user (24h window).
- **Admin bot:** Same Flask app, recognises the owner's phone number; parses `/commands`. Admin phone configured in env (owner's real number).

## Data flow

1. Guest messages guest-facing number.
2. WhatsApp → `POST /webhook`. Backend verifies HMAC/signature.
3. If sender is paused → ignore (host is handling manually).
4. Else: load KB + settings, call Gemini with (KB, message).
5. Gemini returns `{reply, language, handover?}`.
   - If handover or booking-link intent → craft reply (booking links as interactive message or links in text).
   - If handover (out of scope) → set paused for sender, send handover message, notify host on admin channel.
6. Send reply via Graph API.

## Admin commands

Owner sends to admin bot any of: `/status`, `/pause [phone]`, `/resume [phone]`, `/history [phone]`, `/list`, `/ai on`, `/ai off`, `/viewkb`, `/updatekb` (then next message = new KB), `/help`. All implemented in one admin-handler module.

## Error handling

- Invalid webhook signature → 403.
- WhatsApp API send failure → log, retry once, else alert host.
- Gemini failure → reply with graceful "please try again / host will help", do not crash.
- Rate limiting via simple in-memory per-sender throttle.

## Testing

- Pytest unit tests for: KB loader, language detection, booking-link intent, handover detection (Gemini-mocked), admin command parser, pause/resume logic, webhook signature verification.
- Integration test of the `/webhook` route with mocked Gemini + mocked WhatsApp send.
- Manual E2E via Meta Webhook tester + pointing at deployed Render URL.

## Success criteria

- A guest message → correct EN/BM answer from KB.
- Booking intent → booking link sent.
- Out-of-scope → handover, host notified, guest paused.
- `/resume` re-enables AI.
- Host can update KB via WhatsApp.
- Deploys on Render free tier; works without the NUC.
