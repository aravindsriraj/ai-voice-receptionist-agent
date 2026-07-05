# Voice Receptionist Web App — Design Spec

**Date:** 2026-07-05
**Status:** Approved (pending written-spec review)
**Builds on:** the existing voice-receptionist prototype (`app/`), reusing the Gemini
agent, tools, booking, calendar, messaging, and outbound-call flow.

## Context

The phone-only prototype works but has friction: reaching it requires an (often
international) PSTN call, and the agent captures the caller's email by voice — which is
error-prone (it once recorded `example.com`). This project turns the prototype into a
**web app with accounts**, so a logged-in user can either **talk to the agent in the
browser** or have the **agent call their mobile**, and confirmations are sent to the
**email and mobile on file** — eliminating voice capture of contact details entirely.

## Decisions (locked)

| Concern | Choice |
|---|---|
| Interfaces (v1) | **Both**: browser voice **and** "call me" |
| Frontend | **Vanilla HTML/CSS/JS**, served by FastAPI (no build step) |
| Auth | **Email + password** (bcrypt), signed session cookie; **no** email/OTP verification |
| Registration fields | **name, email, password, mobile (with country code)** |
| Identity → agent | account name/email/mobile injected into ADK session state |
| Email confirmations | **Re-enabled** (address comes from the account, not voice) |
| Hosting (dev) | **Local + ngrok** (HTTPS required for mic) |

## Architecture

```
Browser (authenticated session cookie)
  ├─ app.html: "Talk"   → mic → AudioWorklet (16k PCM) ──WS /ws/talk──┐
  └─ app.html: "Call me"→ POST /api/call-me ───────────┐             │
                                                        │             ▼
FastAPI                                                 │       run_live() session
  ├─ GET  /, /login, /register (static pages)           │       state = {caller_name,
  ├─ POST /register, /login, /logout (SessionMiddleware)│              caller_email,
  ├─ POST /api/call-me  → Twilio calls user's mobile ───┘              caller_phone}
  │        → /voice → /media (EXISTING Twilio bridge, untouched)       │
  ├─ WS   /ws/talk  (NEW browser PCM bridge) ─────────────────────────►│
  └─ Firestore: users, appointments                                    ▼
                                            Gemini agent + tools
                    book_appointment → Calendar + WhatsApp + email (to account details)
```

The **existing inbound-dial path** (`/voice` + `/media`) stays working. Its **audio
transport is unchanged**; the only addition is that the bridge's session setup now
looks up the caller in Firestore by phone to enrich state with name/email when a matching
account exists (see Identity flow). A direct dial with no matching account behaves exactly
as today (asks for the name by voice).

## Bridge structuring (chosen approach)

**Parallel endpoints.** Keep `/media` (Twilio μ-law) exactly as-is. Add `/ws/talk` for the
browser, which needs **no μ-law transcoding** — the browser captures 16 kHz PCM (what
Gemini wants) and plays 24 kHz PCM (what Gemini emits) directly. The two transports stay
independent; only session setup + the "greeting kickoff" message construction are shared.

## Components

### 1. Auth + user store (`app/auth.py`)
- Firestore `users` collection, **doc id = lowercased email**. Fields: `name`, `mobile`
  (normalized **E.164**), `password_hash` (bcrypt via `passlib`), `created_at`.
- `register(name, email, password, country_code, mobile)`: validate, normalize mobile to
  E.164, reject duplicate email, hash password, store.
- `authenticate(email, password) -> user | None`: verify hash.
- `current_user(request)`: read `user_email` from the signed session; load the user.
- `require_user`: FastAPI dependency that 401/redirects when not logged in; guards
  `/api/call-me`, `/ws/talk`, and `app.html`.
- E.164 normalization helper: `country_code + national number → +<cc><number>` (strip
  spaces/dashes; validate digits). Pure function, unit-tested.

### 2. Web + API routes (`app/web.py`, `APIRouter` included by `main.py`)
- `GET /` → redirect to `/app` if logged in else `/login`.
- `GET /login`, `GET /register` → serve static pages.
- `POST /register`, `POST /login` (set session), `POST /logout` (clear session).
- `GET /app` → serve `app.html` (guarded).
- `POST /api/call-me` (guarded) → `twilio.calls.create(to=user.mobile,
  from_=TWILIO_NUMBER, url=<base>/voice)`; returns the call SID/status. Reuses the proven
  outbound flow. Stores a short-lived mapping so `/voice`/`/media` can attach the account
  email to the session (see Identity flow).
- `SessionMiddleware` added in `main.py` with `SESSION_SECRET` from env.

### 3. Browser voice bridge (`app/browser_bridge.py`, `WS /ws/talk`)
- Guarded by session. On connect: load the user, create an ADK session with
  `state={caller_name, caller_email, caller_phone}`, send the greeting kickoff (includes
  the known identity), run `run_live`.
- Inbound: browser sends **binary 16 kHz PCM** frames → `queue.send_realtime(Blob(
  mime_type="audio/pcm;rate=16000"))` (no transcode).
- Outbound: for each audio event, send the **raw 24 kHz PCM** bytes as binary frames to
  the browser; on `interrupted`, send a small JSON control message (`{"type":"interrupt"}`)
  so the client flushes its playback buffer. Transcription events → JSON text frames for
  the on-screen transcript.
- Reuses `run_live`, the agent, tools, and booking unchanged.

### 4. Identity flow (the key win)
- Browser path: identity comes straight from the logged-in account → session state.
- Call-me path: when Twilio calls the user, the account's mobile is the `To` number. The
  Twilio bridge's session setup **looks up the user in Firestore by that phone number**
  (E.164) and sets `state = {caller_name, caller_email, caller_phone}`. No extra
  server-side mapping store is needed. If no matching user is found (e.g. legacy
  inbound-dial), only `caller_phone` is set and the agent asks for the name by voice.
- `book_appointment` reads `caller_phone`, `caller_email`, `caller_name` from state; the
  tool's `name`/`email` params become **optional overrides** (default to state). So the
  agent no longer needs to capture email or phone by voice.

### 5. Agent changes (`app/agent.py`)
- Greeting kickoff (built per session) includes the known identity, e.g. *"You're speaking
  with Aravindan (phone +91…, email a@b.com on file). Greet them by name…"*.
- Instruction updated: if the caller's name is known, greet by it and don't ask; only
  collect **reason** and **time**. If unknown (legacy phone path), ask for the name.
- `book_appointment(reason, start_iso, tool_context, name="", email="")` — name/email
  fall back to session state; phone always from state.

### 6. Confirmations
- Set `EMAIL_ENABLED=true`. On booking: WhatsApp to account mobile + email to account
  email. Reliable now because both come from registration, not voice.

### 7. Frontend (`app/static/`)
- `login.html`, `register.html` (name/email/password/country-code+mobile), `app.html`
  (Talk button with mic permission + live transcript panel, Call-me button, logout).
- `js/audio-recorder.js` + `js/pcm-recorder-processor.js` (16 kHz capture) and
  `js/audio-player.js` + `js/pcm-player-processor.js` (24 kHz playback) — following the
  ADK reference demo. `js/app.js` wires the WS, buttons, and transcript.

## Data model

`users/{email_lower}`: `{ name, email, mobile (E.164), password_hash, created_at }`
`appointments/*`: unchanged (already stores name/phone/email/start/flags).

## Security

- Passwords hashed with bcrypt (`passlib`); never stored/logged in plaintext.
- Signed session cookie via `SessionMiddleware` (`SESSION_SECRET`, httponly, `secure`
  under HTTPS, `samesite=lax`).
- `/ws/talk` and `/api/call-me` require an authenticated session.
- `/api/call-me` calls only the **account's own** mobile (no arbitrary numbers), limiting
  abuse. (Mobile is unverified in v1 — noted as a follow-up.)

## Testing

- **Unit:** E.164 normalization (valid/invalid, spaces/dashes, country code); password
  hash/verify; `register` (happy, duplicate email, weak/empty password); `authenticate`
  (right/wrong password); `require_user` guard (allow/deny); `/api/call-me` builds correct
  Twilio params (mocked client) and only dials the account mobile; `book_appointment`
  falls back to state for name/email/phone; `/ws/talk` identity→state wiring (fake WS +
  fake runner, mirroring the existing bridge test).
- **Manual (local + ngrok, HTTPS):** register → login → **Talk** in browser → book →
  verify Calendar event + WhatsApp + email to the account; then **Call me** → agent calls
  the account mobile → book → same verifications. Logout blocks `/app` and `/ws/talk`.

## Scope boundaries (YAGNI — deferred)

Patient users only (no admin/clinic roles), no password reset, no email/OTP verification,
no rescheduling/cancellation, single clinic calendar, English only. Legacy inbound-dial
path kept but not extended.

## New dependencies

- `passlib[bcrypt]` — password hashing.
- Starlette `SessionMiddleware` (already available via FastAPI) — signed session cookie.
- New env: `SESSION_SECRET` (random string); `EMAIL_ENABLED=true`.

## Risks / open items

1. **Browser audio worklets** are the fiddliest new piece (mic permissions, sample rates,
   buffering) — validate early against the ADK reference implementation.
2. **Mobile unverified** — someone could register another person's number; acceptable for
   the prototype, flagged for v2 (Twilio Verify OTP).
3. **Resend quota** is very low on the current account — raise limits before real email
   volume.
4. `/ws/talk` must share the running server's session service with the runner (same
   pattern already used for `/media`).
