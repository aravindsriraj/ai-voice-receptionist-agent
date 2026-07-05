# AI Voice Receptionist — Design Spec

**Date:** 2026-07-05
**Status:** Approved (pending written-spec review)
**Scope:** Working prototype

## Context

Clinics and other appointment-based businesses need to answer inbound calls, hold a
natural conversation, and book appointments without a human receptionist. This project
builds an AI voice receptionist that:

- Answers real phone calls and holds a natural, professional, real-time conversation.
- Checks calendar availability and books appointments live.
- Accurately captures caller details (name, reason for visit, contact number).
- Sends instant WhatsApp + email confirmation on booking.
- Sends automated WhatsApp + email reminders before the appointment.

The goal of this first build is a **working prototype** that proves the end-to-end flow
with real calls, real bookings, and real confirmations — not a hardened multi-tenant
product.

## Technology Decisions

| Concern        | Choice                                              |
|----------------|-----------------------------------------------------|
| Agent framework| **Gemini ADK** — Live API Toolkit (`run_live`)      |
| Voice model    | Gemini Live **native-audio** model                  |
| Telephony      | **Twilio** (phone number, Media Streams over WS)    |
| Calendar       | **Google Calendar API** (freebusy + events.insert)  |
| WhatsApp       | **Twilio WhatsApp** (approved templates)            |
| Email          | **Resend**                                          |
| Data store     | **Firestore** (appointments + reminder state)       |
| Reminders      | **Cloud Scheduler** → polling endpoint              |
| Hosting        | **Cloud Run** (Python / FastAPI)                    |
| Language       | English-first; prompt structured for later multilingual |

## Architecture

```
Caller ──dials──> Twilio Number
                     │  (TwiML: <Connect><Stream url=wss://.../media>)
                     ▼
        ┌─────────────────────────────────┐
        │  Cloud Run service (FastAPI)     │
        │                                  │
        │  POST /voice   → TwiML response  │
        │  WS   /media   → Audio Bridge ───┼──► ADK Runner.run_live()
        │                   (μ-law↔PCM)    │        Gemini Live (native audio)
        │  POST /tasks/reminders           │        + FunctionTools:
        │        (Cloud Scheduler)         │          - check_availability
        └───────┬──────────────────────────┘         - book_appointment
                │                                    │
                ▼                                    ▼
          Firestore  ◄──────── Google Calendar / Twilio WhatsApp / Resend
        (appointments,
         reminder state)
```

## Components

### 1. Audio Bridge (`app/audio_bridge.py`) — highest risk

A FastAPI WebSocket endpoint that Twilio Media Streams connects to. Per call:

- Starts one ADK `Runner.run_live()` session with a `LiveRequestQueue`.
- **Inbound:** decode Twilio base64 **μ-law 8 kHz** → PCM → resample to **16 kHz PCM
  mono** → `queue.send_realtime(Blob(mime_type="audio/pcm;rate=16000", data=...))`.
- **Outbound:** consume ADK events; take Gemini's **24 kHz PCM** output → resample to
  **8 kHz** → encode **μ-law** → base64 → send over the Twilio WS `media` message.
- Handles **barge-in**: on ADK interruption events, send Twilio `clear` to flush queued
  playback.
- Handles call start (`start` event → capture `From`/`callSid`) and teardown (`stop`).

**Key constraint (confirmed in ADK docs):** ADK performs *no* audio format conversion.
Input must be 16-bit PCM / 16 kHz / mono; output is 24 kHz PCM. All transcoding lives in
this bridge. Python's `audioop` (or `audioop-lts` on Python 3.13+) provides μ-law↔PCM
(`ulaw2lin`/`lin2ulaw`) and resampling (`ratecv`).

Reference implementation for the ADK side:
`https://github.com/google/adk-samples/tree/main/python/agents/bidi-demo`
(swap its browser-mic client for Twilio's Media Stream format).

### 2. Agent (`app/agent.py`)

- ADK `LlmAgent` on the Gemini Live native-audio model.
- Persona: professional clinic receptionist; concise, warm, confirms details back.
- English-first; instruction template holds a `language` variable so additional
  languages can be enabled later without restructuring.
- Caller phone number from Twilio `From` is injected into ADK **session state** so the
  agent confirms rather than asks for it.

### 3. Tools

- **`app/tools/calendar.py`**
  - `check_availability(date, time_preference) -> list[slot]` — Google Calendar
    freebusy query, returns open slots for the clinic calendar.
  - `create_event(...)` — Calendar `events.insert`.
- **`app/tools/booking.py`**
  - `book_appointment(name, reason, phone, start_datetime) -> result` — validates the
    slot is still free, creates the Calendar event, persists to Firestore, then triggers
    confirmations. Returns success/failure so the agent can speak the outcome.

### 4. Messaging

- **`app/messaging/whatsapp.py`** — Twilio WhatsApp send (approved template for
  confirmation and reminder).
- **`app/messaging/email.py`** — Resend send (confirmation + reminder templates).

### 5. Persistence (`app/store.py`)

Firestore `appointments` collection. Document fields:

- `name`, `reason`, `phone`, `email` (if captured), `start_datetime`, `timezone`
- `calendar_event_id`
- `status` (`booked` | `cancelled`)
- `reminder_24h_sent` (bool), `reminder_1h_sent` (bool)
- `created_at`

### 6. Reminders (`app/reminders.py` + `POST /tasks/reminders`)

- **Cloud Scheduler** invokes `POST /tasks/reminders` every few minutes.
- Query Firestore for appointments where a **24h** or **1h** reminder is due and its flag
  is unset; send WhatsApp + email; set the flag.
- **Idempotent** via the sent-flags → safe against overlapping/duplicate scheduler runs
  and Cloud Run retries.
- Chosen over an in-process scheduler because Cloud Run scales to zero; chosen over Cloud
  Tasks for prototype simplicity (timing imprecision of a few minutes is fine for 24h/1h).

## Data Flow: Call → Booking → Confirmation → Reminder

1. Caller dials the Twilio number → Twilio requests `POST /voice` → returns TwiML
   `<Connect><Stream>` pointing at `wss://.../media`.
2. Twilio opens the Media Stream WS; the Audio Bridge starts an ADK live session and
   stores the caller's `From` number in session state.
3. Real-time conversation: agent greets, understands intent, calls `check_availability`,
   proposes slots, collects **name, reason, contact number** (number pre-filled from
   caller ID and confirmed verbally).
4. On confirmation, agent calls `book_appointment`:
   - Re-validate slot free → create Google Calendar event → write Firestore doc.
   - Send WhatsApp (Twilio template) + email (Resend) confirmation **immediately**.
   - Return outcome; agent speaks confirmation and closes the call.
5. Cloud Scheduler-driven `/tasks/reminders` later sends the **24h** and **1h** reminders
   and marks their flags.

## Project Structure

```
voice-agent/
├── app/
│   ├── main.py              # FastAPI: /voice, /media (WS), /tasks/reminders
│   ├── audio_bridge.py      # μ-law↔PCM transcode + Twilio↔ADK pumping
│   ├── agent.py             # ADK LlmAgent + persona + tools wiring
│   ├── tools/
│   │   ├── calendar.py      # Google Calendar freebusy + event create
│   │   └── booking.py       # book_appointment orchestration
│   ├── messaging/
│   │   ├── whatsapp.py      # Twilio WhatsApp send
│   │   └── email.py         # Resend send
│   ├── store.py             # Firestore appointment persistence
│   └── reminders.py         # due-reminder query + dispatch
├── deploy/                  # Dockerfile, Cloud Run + Cloud Scheduler config
├── docs/superpowers/specs/  # this spec
└── tests/
```

## Configuration / Secrets

Environment / Secret Manager: Twilio SID + auth token + phone/WhatsApp numbers, Google
service-account credentials (Calendar + Firestore), Resend API key, Gemini/Vertex
credentials, clinic calendar ID, clinic timezone, public base URL.

## Testing Strategy

- **Unit**
  - Audio transcode round-trip: μ-law 8 kHz → PCM 16 kHz → PCM 8 kHz → μ-law; assert
    format/rate and acceptable fidelity.
  - Calendar / WhatsApp / email / store with mocked clients.
  - Reminder due-selection: 24h and 1h boundary conditions + idempotency (flag already
    set → no resend).
- **Integration**
  - Local FastAPI + `ngrok`; configure Twilio number webhook; place a real test call
    end-to-end; verify Calendar event + WhatsApp + email arrive.
  - Invoke `POST /tasks/reminders` against seeded Firestore docs and verify sends + flags.

## Scope Boundaries (YAGNI — deferred to v2)

- Single clinic / single calendar (no multi-tenant).
- Single timezone.
- English conversation only (multilingual path preserved in prompt, not built).
- No payments / insurance capture.
- No rescheduling or cancellation flow (bookings only).

## Open Risks

1. **Audio bridge fidelity/latency** — telephony 8 kHz μ-law ↔ Gemini 16/24 kHz PCM
   round-trip is the main technical unknown; validate early with a spike.
2. **WhatsApp template approval** — Twilio/Meta template approval can take time; may need
   to start template submission before end-to-end testing.
3. **Barge-in behavior** — interruption handling across the Twilio↔ADK boundary needs
   real-call validation.
