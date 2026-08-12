# WhatsApp AI Guest Assistant (Arau House) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. TDD: write the failing test first, watch it fail, then implement.

**Goal:** A Flask app that runs a WhatsApp AI guest assistant for Arau House — answering EN/BM FAQs from a Knowledge Base, redirecting booking requests, and handing over to the host — all controllable by the host via admin WhatsApp commands.

**Architecture:** Single Flask app. Inbound `POST /webhook` from WhatsApp Cloud API → Gemini Flash (grounded on the KB) decides reply/handover → outbound reply via Graph API. `GET /webhook` verifies the webhook. SQLite persists conversations + pause state + KB. Admin commands parsed when the sender is the owner's number. Gunicorn as the WSGI server for Render/Railway.

**Tech Stack:** Python 3.11+, Flask, Gunicorn, `google-genai` (Gemini Flash), `requests` (Meta Graph API), SQLite (`sqlite3` stdlib), `pytest` for tests, `python-dotenv` for local env.

## Global Constraints

- Python >= 3.11; use `pip` + `requirements.txt`.
- Env-driven secrets: `GEMINI_API_KEY`, `WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, `OWNER_PHONE`, `VERIFY_TOKEN`, `APP_SECRET` (optional), `PORT` (default 10000 for Render).
- Answer ONLY from the KB document. Never invent rates/rules/amenities.
- Auto-detect EN/BM and reply in the same language. No Mandarin.
- Booking intent → send booking link (from `KNOWLEDGE_BASE.md` `## Booking` section), keep brief.
- Out-of-scope → handover: pause the guest, notify host, do not auto-reply to that guest until `/resume`.
- Commands execute ONLY for the owner's phone number (env `OWNER_PHONE`).
- No web dashboard, no multi-property, no payments, no Mandarin (per spec).
- Copy `KNOWLEDGE_BASE.md` into the repo as the seed KB.

---

## Task 0 — Project scaffold + failing baseline

**Deliverable:** Repo structure with a trivial Flask app that returns 200 on `/`, and a pytest setup that runs (one trivial passing test) so the harness is green.

- [ ] Create app directory: `app/` package with `__init__.py`, `webhook.py`, `kb.py`, `llm.py`, `whatsapp.py`, `admin.py`, `db.py`.
- [ ] Add `requirements.txt` (flask, gunicorn, google-genai, requests, python-dotenv, pytest).
- [ ] Add minimal `app.py` entrypoint creating the Flask app and a `/` health route returning `{"ok": true}`.
- [ ] Copy `KNOWLEDGE_BASE.md` → `kb_seed.md` in repo root (seed content).
- [ ] Add `.env.example` listing all env vars.
- [ ] Add `tests/test_smoke.py` asserting `client.get("/")` returns 200 + `{"ok": true}`.
- [ ] Run `pytest` — green. Run `flask`/`app.py` smoke (server starts).
- [ ] Commit.

## Task 1 — KB loader (unit-tested)

**Deliverable:** A `kb.py` module that loads KB text and exposes helper lookups + booking link extraction (no DB yet).

- [ ] Write failing tests `tests/test_kb.py`:
  - [ ] `load_kb()` returns non-empty string from seed file.
  - [ ] `extract_booking_link(kb)` returns the Booking.com URL present under `## Booking`.
  - [ ] `kb_has_sections(kb)` lists markdown `##` section titles.
- [ ] Run tests — confirm they fail (no module yet).
- [ ] Implement `app/kb.py` reading `kb_seed.md` (path from `KB_PATH` env, default `kb_seed.md`).
- [ ] Run tests — green.
- [ ] Commit.

## Task 2 — Language detection (unit-tested)

**Deliverable:** `llm.py`-independent helper `detect_language(text)` → `en` or `ms`, used to choose reply language.

- [ ] Write failing tests `tests/test_lang.py`:
  - [ ] English message ("What time is check-in?") → `en`.
  - [ ] Malay message ("Berapa harga homestay?") → `ms`.
  - [ ] Mixed/neutral → default `en`.
- [ ] Implement `detect_language` (simple keyword/Latin-script heuristic) in `app/llm.py` or `app/lang.py`.
- [ ] Tests green. Commit.

## Task 3 — Gemini LLM wrapper (unit-tested, mocked)

**Deliverable:** `llm.py` function `ask_gemini(kb, message)` that returns `{"reply": str, "handover": bool}` using Gemini Flash, with a deterministic fake for tests.

- [ ] Define `ask_gemini(kb, message)` calling Gemini Flash via `google-genai` with a structured prompt (answer only from KB; detect language; booking intent → short reply + link; out of scope → handover=True).
- [ ] Write failing tests `tests/test_llm.py` using a monkeypatched fake client:
  - [ ] In-scope KB answer returns reply, handover=False.
  - [ ] Handover path returns handover=True.
  - [ ] Booking-intent path returns reply containing booking link.
- [ ] Implement. Tests green. Commit.

## Task 4 — WhatsApp send helper (unit-tested, mocked)

**Deliverable:** `whatsapp.py` function `send_whatsapp(to, text)` POSTing to Meta Graph API, with signature/keyrefs for tests (no real network).

- [ ] Write failing tests `tests/test_whatsapp.py` (mock `requests.post`):
  - [ ] `send_whatsapp("+60...", "hi")` posts to correct URL with access token + payload `{"messaging_product":"whatsapp","to":..., "text":{"body":...}}`.
  - [ ] Non-2xx response raises/logs and returns False.
- [ ] Implement using `WHATSAPP_PHONE_NUMBER_ID` + `WHATSAPP_ACCESS_TOKEN` env.
- [ ] Tests green. Commit.

## Task 5 — DB state store (unit-tested)

**Deliverable:** `db.py` handling SQLite: conversations log, paused set, kb storage, global `ai_enabled`.

- [ ] Schema: `messages(id, phone, role, body, ts)`, `paused(phone PRIMARY KEY, ts)`, `settings(key PRIMARY KEY, value)`.
- [ ] Write failing tests `tests/test_db.py` (in-memory sqlite via fixture):
  - [ ] `log_message(phone, role, body)` inserts; `history(phone)` returns ordered list.
  - [ ] `pause(phone)` / `is_paused(phone)` / `unpause(phone)`.
  - [ ] `get_kb()` / `set_kb(text)` (seeded from `kb_seed.md` on first init).
  - [ ] `ai_enabled()` / `set_ai(bool)`.
- [ ] Implement. Tests green. Commit.

## Task 6 — Admin command parser (unit-tested)

**Deliverable:** `admin.py` function `handle_admin(phone, text) -> reply_text` responding to `/status`, `/pause`, `/resume`, `/history`, `/list`, `/ai on`, `/ai off`, `/viewkb`, `/updatekb` (multi-step), `/help`.

- [ ] Write failing tests `tests/test_admin.py` (uses db fixture):
  - [ ] `/help` lists commands.
  - [ ] `/status` summarises paused + ai_enabled.
  - [ ] `/pause +6012...` pauses; `/resume +6012...` unpauses.
  - [ ] `/history +6012...` shows messages.
  - [ ] `/list` lists recent phones + paused.
  - [ ] `/ai off` disables; `/ai on` enables.
  - [ ] `/viewkb` returns KB; `/updatekb` enters wait state, next message becomes KB.
- [ ] Implement (multi-step `/updatekb` via a `pending_kb_update=phone` row). Tests green. Commit.

## Task 7 — Webhook route + request handler (integration-tested)

**Deliverable:** `webhook.py` with `GET /webhook` (verify) and `POST /webhook` orchestrating: signature check → handle_admin if owner → else guest flow (paused? / ai off? → Gemini → send / handover).

- [ ] Write failing tests `tests/test_webhook.py` (Flask test client, mock LLM + WhatsApp + admin):
  - [ ] `GET /webhook` with correct `hub.verify_token` returns the challenge.
  - [ ] `GET /webhook` with wrong token returns 403.
  - [ ] `POST` for owner's phone routes to admin handler, sends reply.
  - [ ] `POST` guest message (not paused, ai on) → Gemini answer sent.
  - [ ] Guest handover → paused, host notified, no auto-reply.
  - [ ] Paused guest → no reply sent (ignored).
  - [ ] `ai off` → guarded message, no Gemini.
- [ ] Implement signature verify + handler dispatch. Tests green. Commit.

## Task 8 — Main app wiring + health + run config

**Deliverable:** `app.py`/`wsgi.py` registers the webhook blueprint, health route, and gunicorn config; `.env` support via `python-dotenv`. Local `flask run` boots.

- [ ] Register blueprints/routes in app factory.
- [ ] Add `wsgi.py` and `render.yaml` (optional) / `Procfile` (`web: gunicorn app:app`).
- [ ] Add `tests/test_app.py` asserting app factory + `/` and `/webhook` mounted.
- [ ] Manual: run `python -m flask --app app run` boots and `/` returns `{"ok":true}`.
- [ ] Tests green. Commit.

## Task 9 — KB seed + README + deploy notes

**Deliverable:** Repo self-documenting with seed KB and env setup instructions for Render.

- [ ] Ensure `kb_seed.md` present (copy of `KNOWLEDGE_BASE.md`).
- [ ] Write `README.md`: setup, env vars, local run, test command, Render deploy steps, how to set webhook.
- [ ] Add `requirements.txt` final; verify `pip install -r requirements.txt` + `pytest` green in a fresh venv.
- [ ] Commit.

---

## Definition of Done (whole-branch review)

- [ ] `pytest` green across all tasks.
- [ ] App boots locally; `/` OK.
- [ ] KB, language detection, Gemini, WhatsApp send, DB, admin, webhook each unit/integration tested.
- [ ] README documents env setup + Render deploy.
- [ ] No secrets committed (`.env` gitignored).
