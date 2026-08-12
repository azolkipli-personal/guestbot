# WhatsApp Guest Assistant (GuestBot)

A ready-to-deploy WhatsApp AI assistant for any homestay, B&B, guesthouse or villa. It answers common guest questions (in English **and** Bahasa Melayu) straight from your **Knowledge Base** — check-in times, amenities, house rules, directions and more. When a guest wants to book, the bot sends your booking link; when a question is outside what it knows, it politely hands the conversation over to you, the host.

The code is fully **property-agnostic**: the same app deploys to any small accommodation business. You configure the property name and point it at your own Knowledge Base, and it just works.

> **Working example / test data:** `kb_seed.md` ships pre-filled with a real listing (Arau House, a homestay in Perlis, Malaysia) so you can see the whole thing run end-to-end. When you're ready to use it for your own property, copy `kb.example.md` and fill it in (see section 8).

---

## 1. What this is

A small, self-hosted web app that plugs into WhatsApp (via Meta's WhatsApp Cloud API) and uses Google's **Gemini Flash** to answer guest messages. Everything it says comes from a single Knowledge Base document that **you** control — so the bot never invents prices, rules or amenities. You can update that Knowledge Base anytime, right from your own WhatsApp, using an admin command.

---

## 2. Architecture

It's a single, simple Flask app. WhatsApp (Meta's Cloud API) sends guest messages to a webhook endpoint on your app; the app checks whether the sender is **you** (the host) or a guest. Host messages are treated as admin commands; guest messages are sent to Gemini (grounded on your Knowledge Base), which decides whether to answer, redirect to booking, or hand over to you. The reply is sent back through the WhatsApp Graph API. Conversations, pause state and the Knowledge Base are stored in a small SQLite database. Gunicorn runs the app as the WSGI server for local and cloud (Render) deployment.

```
Guest message ──► WhatsApp Cloud API ──► POST /webhook ──► Flask app
                                                          │
                                     host message? ──────► admin commands
                                     guest message? ────► Gemini Flash (grounded on KB)
                                                          │
                                                          ▼
                          reply / booking link / handover ──► WhatsApp Graph API ──► guest
```

The single environment configuration below ties it together.

---

## 3. Environment variables

Create a `.env` file from `.env.example` and fill in your own values. **Never commit your real `.env`** — it's your secrets.

| Variable | Required? | What it is |
|---|---|---|
| `GEMINI_API_KEY` | ✅ Yes | API key for Google Gemini, used to generate guest replies. Get one at https://aistudio.google.com |
| `WHATSAPP_ACCESS_TOKEN` | ✅ Yes | The long-lived Meta access token for your WhatsApp Cloud API app, used to send messages. |
| `WHATSAPP_PHONE_NUMBER_ID` | ✅ Yes | The phone-number ID of your WhatsApp test (or business) number in the Meta app dashboard. |
| `OWNER_PHONE` | ✅ Yes | **Your** phone number (with country code, e.g. `+60123456789`). Only this number can run admin commands. |
| `VERIFY_TOKEN` | ✅ Yes | A secret string you choose. Must match exactly in both `.env` and the Meta webhook config (see step 6). |
| `APP_SECRET` | No | Meta app secret. Used to validate the webhook signature. Recommended once you own the app. |
| `PROPERTY_NAME` | No | Your property's name, used to greet guests (e.g. `Arau House`). Defaults to a generic "the property". |
| `PORT` | No | Port the app listens on. Defaults to `10000` (Render's default). |
| `KB_PATH` | No | Path to the Knowledge Base markdown file. Defaults to `kb_seed.md`. |
| `DB_PATH` | No | Path to the SQLite database file. Defaults to `homestay.db`. |

---

## 4. Local setup + run

Run everything with Python 3.11+.

```bash
# 1. Get the code (copy the project folder, or clone it)
cd guestbot

# 2. Create a virtual environment (only once)
python3 -m venv .venv

# 3. Install dependencies
.venv/bin/pip install -r requirements.txt

# 4. Create your .env from the example and fill in your values
cp .env.example .env
#   ...then edit .env and set GEMINI_API_KEY, WHATSAPP_ACCESS_TOKEN,
#       WHATSAPP_PHONE_NUMBER_ID, OWNER_PHONE and VERIFY_TOKEN (at minimum).

# 5. Run the test suite (should stay green)
.venv/bin/python -m pytest

# 6. Start the server
.venv/bin/gunicorn wsgi:app --timeout 120
#   (or, for development without Gunicorn: python3 wsgi.py)

# 7. Check the health endpoint
#   Open http://localhost:10000/ in your browser, or:
curl http://localhost:10000/
#   → {"ok": true}
```

---

## 5. Deploy to Render

Deploying to Render is free-tier friendly and gives you a public HTTPS URL that WhatsApp can reach.

1. **Push your code to GitHub** (create a repo, then `git push`).
2. Go to **render.com** → **New** → **Web Service** and **connect your GitHub repo**.
3. Render will auto-detect (or let you set) the settings — if not filled in, use:
   - **Build command:** `pip install -r requirements.txt`
   - **Start command:** `gunicorn wsgi:app --timeout 120`
4. In the **Environment** section, add the variables from `.env.example` (`GEMINI_API_KEY`, `WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, `OWNER_PHONE`, `VERIFY_TOKEN`, and optionally `APP_SECRET`). Values **must** match the ones on your machine if you want the bot to behave the same way.
5. Click **Deploy** and wait for the first deploy to finish.
6. Copy your service URL — it will look like `https://your-app.onrender.com`. You'll need this for the WhatsApp webhook below.

---

## 6. WhatsApp / Meta webhook setup

This connects your deployed app to WhatsApp.

1. Go to **https://developers.facebook.com** and create (or use) a **Meta Business** account and app.
2. In your app, add the **WhatsApp** product. The dashboard will show a **test number** (a WhatsApp number you can send messages to/from app).
3. In the WhatsApp dashboard, copy three things and put them in your `.env` / Render env:
   - The **access token** → `WHATSAPP_ACCESS_TOKEN`
   - The **phone number ID** → `WHATSAPP_PHONE_NUMBER_ID`
   - The **test number** (used to message yourself)
4. In your app's **WhatsApp → Configuration → Webhook**, set up the callback:
   - **Callback URL:** `<your-render-url>/webhook` — e.g. `https://your-app.onrender.com/webhook`
   - **Verify token:** the same value you put in `VERIFY_TOKEN`
   - **Subscribe to the `messages` field** (turn on the webhook for message events).
5. The **GET /webhook** verification is handled automatically by the app — just use the two fields above and save. Meta will ping your URL and, if the token matches, the subscription activates.
6. From your phone, **message the WhatsApp test number**. The bot should reply from your Knowledge Base.

> **A note on limits:** WhatsApp Cloud API's free tier covers **1,000 service conversations per month**, plus there's a **24-hour free-form customer-service window** after a guest messages you first. The test number also lets you try things for free during development. For production-scale use, check Meta's current pricing and business-messaging rules — these figures can change.

---

## 7. Owner admin commands

Only messages from `OWNER_PHONE` are treated as commands. Send these to your bot's WhatsApp number.

| Command | What it does |
|---|---|
| `/help` | Lists all available owner commands. |
| `/status` | Shows whether the AI is on/off and which guests are paused. |
| `/pause <phone>` | Pause the AI for one guest (stops auto-replies; hands off to you). Used with a phone number, e.g. `/pause +60123456789`. |
| `/resume <phone>` | Resume AI replies for a previously paused guest. |
| `/history <phone>` | Show the past conversation history for a guest. |
| `/list` | List everyone who has messaged the bot (marking who is paused). |
| `/ai on` / `/ai off` | Turn the AI's auto-answering on or off. |
| `/viewkb` | View the current Knowledge Base content the bot is using. |
| `/updatekb` | Update the Knowledge Base: the bot asks you to paste the new content, then saves it instantly. |

---

## 8. Updating the Knowledge Base

**From WhatsApp (recommended, no redeploy):**

1. Send `/updatekb` to the bot.
2. The bot replies "Please send the new Knowledge Base content:".
3. Paste your new KB markdown as a single message.
4. It's saved instantly — the bot answers guests from the new content right away.

**From the code:**

Edit `kb_seed.md` (the seed Knowledge Base in the repo), then redeploy on Render. On startup the app loads that file as the default KB.

The bot answers **only** from the Knowledge Base, so keep rates, amenities, rules and the booking link accurate there.

### Onboarding a new property (the 3-step quickstart)

1. **Copy the template:** `cp kb.example.md kb_seed.md` (or any filename).
2. **Fill in your property's details** — overview, rates, amenities, check-in/out, house rules, booking link.
3. **Set env:** `PROPERTY_NAME` to your property's name, and (if you used a different filename) `KB_PATH` to point at it. Redeploy.

The bot then answers guests entirely from **your** Knowledge Base — no code changes needed. The bundled `kb_seed.md` (Arau House) is just sample data; remove or replace it with your own when you go live.

---

## 9. Project structure

- `app/__init__.py` — the Flask app factory (`create_app()`); wires the webhook blueprint and `/` health route (`{"ok": true}`).
- `app/webhook.py` — the `/webhook` endpoint: `GET` answers Meta's webhook verification, `POST` processes inbound messages (routing host vs guest).
- `app/kb.py` — loads and parses the Knowledge Base (booking link, sections).
- `app/lang.py` — detects whether a message is English or Malay so replies match the guest's language.
- `app/llm.py` — the Gemini wrapper: decides reply vs booking vs handover, grounded on the KB.
- `app/whatsapp.py` — sends outgoing messages via the WhatsApp Graph API.
- `app/db.py` — SQLite persistence: conversations, pause state, AI on/off, and the live Knowledge Base.
- `app/admin.py` — parses and runs the owner `/` admin commands.
- `wsgi.py` — WSGI entrypoint for Gunicorn/Render (`gunicorn wsgi:app`).
- `tests/` — the full pytest suite.
- `Procfile` + `render.yaml` — deployment configuration for Render.
- `requirements.txt` — Python dependencies.
- `.env.example` — template for your environment variables.
- `kb_seed.md` — sample Knowledge Base (Arau House test data). Deploy with your own for production.
- `kb.example.md` — blank template you can copy and fill in for any new property.
