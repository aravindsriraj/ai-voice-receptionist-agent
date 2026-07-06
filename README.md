# AI Voice Receptionist Agent

A real-time **AI voice receptionist** for clinics and appointment-based businesses. Callers
talk to it naturally — by **phone** or **in the browser** — and it checks live calendar
availability, books the appointment, and sends instant **email** (and optional WhatsApp)
confirmations plus reminders before the visit.

Built with **Google Gemini (ADK Live API)** for real-time voice, **Twilio** for telephony,
**Google Calendar** for scheduling, and **FastAPI** for the web app and audio bridges.

---

## What it does

- 🎙️ **Natural real-time voice** — sub-second, interruptible conversation (Gemini native-audio).
- 📅 **Live booking** — checks Google Calendar availability and books the appointment during the call.
- 🧑‍⚕️ **Accurate details** — name, reason, and contact come from the caller's account, not error-prone voice capture.
- ✉️ **Instant confirmation** — email on booking (WhatsApp optional when a sender is configured).
- ⏰ **Reminders** — automated 24-hour and 1-hour reminders before the appointment.
- ☎️ **Two ways to talk** — call the agent in the browser (mic), or have the agent call your phone.
- 🔚 **Knows when to hang up** — the agent ends the call itself once you're done.

## How it works

```
                 ┌──────────────────────── FastAPI app ────────────────────────┐
Browser mic ─────┤  WS /ws/talk   ─┐                                            │
(16 kHz PCM)     │                 ├─► run_live() ─► Gemini Live (native audio) │
Phone call ──────┤  POST /voice    │      + tools: check_availability,          │
(Twilio Media    │  WS  /media  ───┘                book_appointment, end_call  │
 Streams, μ-law) │                                                              │
                 │  Auth (bcrypt + session cookie) · POST /api/call-me          │
                 │  POST /tasks/reminders  (cron)                               │
                 └───────┬───────────────────────────────┬─────────────────────┘
                         │                                │
                   Google Calendar                 Firestore (users,
                   (freebusy + events)              appointments)
                         │
              Email (Resend) · WhatsApp (Twilio, optional)
```

- The **audio bridge** transcodes between telephony audio (8 kHz μ-law) and Gemini
  (16 kHz in / 24 kHz out); the browser path uses PCM directly.
- Booking runs on the critical path (so "booked" is always truthful); confirmations are
  sent in the **background** so the agent replies immediately.

## Tech stack

Python 3.12 · FastAPI + Uvicorn · Google ADK (Gemini Live) · Google Calendar API ·
Google Cloud Firestore · Twilio (voice + optional WhatsApp) · Resend (email) ·
bcrypt + Starlette sessions · vanilla HTML/JS + Web Audio worklets.

## Getting started (local)

**Prerequisites:** Python 3.12, a Google Cloud project (Firestore + Calendar API),
a Gemini API key, a Twilio account, a Resend account, and [ngrok](https://ngrok.com)
for a public HTTPS URL.

```bash
# 1. Environment (Python 3.12 is required — stdlib audioop)
uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -e ".[dev]"
#    or: python3.12 -m venv .venv && ./.venv/bin/pip install -e ".[dev]"

# 2. Configuration
cp .env.example .env          # then fill in your keys (see below)
#    place your Google service-account key at ./service-account.json
#    share your clinic Google Calendar with the service-account email (editor)

# 3. Run
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8080
ngrok http 8080               # put the https URL in PUBLIC_BASE_URL, restart uvicorn

# 4. Use it
#    open https://<ngrok>/register  → sign up → Talk in the browser or "Call my phone"
#    (phone dial-in: point your Twilio number's Voice webhook at https://<ngrok>/voice)
```

### Environment variables

See [`.env.example`](.env.example) for the full list. Key ones:

| Variable | Purpose |
|---|---|
| `GOOGLE_API_KEY` | Gemini (Developer API) auth |
| `GOOGLE_APPLICATION_CREDENTIALS` | Service-account JSON for Calendar + Firestore |
| `CLINIC_CALENDAR_ID`, `CLINIC_TIMEZONE` | Which calendar, and the timezone (e.g. `Asia/Kolkata`) |
| `OPEN_HOUR`, `CLOSE_HOUR`, `SLOT_MINUTES` | Business hours + slot length |
| `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_CALLER_NUMBER` | Twilio auth + the number the agent calls from |
| `TWILIO_WHATSAPP_FROM`, `WHATSAPP_ENABLED` | WhatsApp sender + on/off (email works without it) |
| `RESEND_API_KEY`, `EMAIL_FROM`, `EMAIL_ENABLED` | Email confirmations |
| `SESSION_SECRET`, `PUBLIC_BASE_URL` | Session cookie signing + public URL |

## Testing

```bash
.venv/bin/python -m pytest
```

## Project structure

```
app/
  main.py            FastAPI app: routes, WebSockets, wiring
  agent.py           Gemini agent: persona, tools (availability, booking, end_call)
  bridge.py          Twilio ⇄ Gemini audio bridge (μ-law ↔ PCM)
  browser_bridge.py  Browser ⇄ Gemini audio bridge (PCM)
  audio.py           G.711 μ-law ↔ PCM transcoding + resampling
  calendar_client.py Google Calendar (freebusy + event insert)
  booking.py         Booking orchestration + confirmations
  scheduling.py      Slot + due-reminder logic (pure)
  store.py / auth.py Firestore appointments + users (bcrypt)
  web.py             Auth routes + /api/call-me
  messaging.py       WhatsApp (Twilio) + email (Resend)
  reminders.py       Due-reminder dispatch (cron target)
  static/            Login/register/app pages + audio worklets
deploy/              Dockerfile + deployment notes
tests/               Unit tests
```

## Deployment

Containerized (see [`deploy/Dockerfile`](deploy/Dockerfile)) and designed for **Google
Cloud Run** (WebSockets supported), with **Cloud Scheduler** hitting `/tasks/reminders`
to fire reminders. In production, use the Cloud Run service's attached service account
for Calendar/Firestore, store secrets in Secret Manager, and point `PUBLIC_BASE_URL` +
the Twilio webhook at the Cloud Run URL.

## Notes & limitations

- On a **Twilio trial** account, outbound calls only reach **verified** numbers and
  WhatsApp requires the **sandbox** (recipients must opt in). Upgrading Twilio removes
  the calling restriction; a real WhatsApp Business sender removes the sandbox limit.
- **Email is the primary channel** and reaches any registered user; WhatsApp is optional.
- Prototype scope: single clinic/calendar, English, no reschedule/cancel yet.
