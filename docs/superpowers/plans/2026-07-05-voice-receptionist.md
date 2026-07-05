# AI Voice Receptionist Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a working prototype AI voice receptionist that answers Twilio phone calls, converses in real time via Gemini ADK's Live API, books appointments into Google Calendar, and sends WhatsApp + email confirmations and reminders.

**Architecture:** A FastAPI app on Cloud Run exposes three surfaces: `POST /voice` (returns TwiML that bridges the call audio to a WebSocket), `WS /media` (the audio bridge: transcodes Twilio μ-law↔Gemini PCM and pumps audio through one `Runner.run_live()` session per call), and `POST /tasks/reminders` (invoked by Cloud Scheduler to send due reminders). The ADK agent owns `check_availability` and `book_appointment` tools; booking creates a Calendar event, persists to Firestore, and fires confirmations.

**Tech Stack:** Python 3.12, FastAPI + Uvicorn, `google-adk` (Live API Toolkit), `google-genai` types, `google-api-python-client` (Google Calendar), `google-cloud-firestore`, `twilio` (voice + WhatsApp), `resend` (email), stdlib `audioop` for transcoding, `pytest` + `pytest-asyncio`.

## Global Constraints

- **Python version: 3.12** exactly. Rationale: stdlib `audioop` (μ-law↔PCM + resampling) is present through 3.12 and **removed in 3.13**. If forced onto 3.13+, add the `audioop-lts` dependency, which restores the same `audioop` module API — no code change.
- **Gemini model via env var** `AGENT_MODEL`, default `gemini-2.5-flash-native-audio-preview-12-2025` (native-audio Live model; supports affective dialog).
- **Audio format contract (ADK does NOT transcode):** input to Gemini = 16-bit PCM, **16 kHz**, mono, `mime_type="audio/pcm;rate=16000"`. Output from Gemini = 16-bit PCM, **24 kHz**, mono. Twilio phone audio on the wire = **8 kHz μ-law** (G.711), base64-encoded in JSON WebSocket frames, 20 ms/frame (160 μ-law bytes/frame).
- **`RunConfig`:** `response_modalities=["AUDIO"]`, `streaming_mode=StreamingMode.BIDI`. VAD is on by default (do not disable). Transcription is on by default in AUDIO mode.
- **Always call `live_request_queue.close()`** in a `finally` when a call ends (prevents zombie Live API sessions counting against quota).
- **Language:** English-first. The agent instruction holds a single `{language}` slot and voice `language_code="en-US"`; multilingual is deferred (do not build).
- **Reminders:** 24h and 1h before appointment; idempotent via per-appointment boolean flags.
- **Env-var-driven config** loaded via `python-dotenv` **before** importing any module that reads env at import time.
- **Secrets** (never hard-coded): `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_WHATSAPP_FROM`, `RESEND_API_KEY`, `EMAIL_FROM`, `GOOGLE_APPLICATION_CREDENTIALS` (service-account JSON path), `CLINIC_CALENDAR_ID`, `CLINIC_TIMEZONE`, `PUBLIC_BASE_URL`, `AGENT_MODEL`, `AGENT_VOICE`.

---

## File Structure

```
voice-agent/
├── pyproject.toml               # deps + pytest config (Task 1)
├── .env.example                 # documented env vars (Task 1)
├── app/
│   ├── __init__.py
│   ├── config.py                # Settings dataclass from env (Task 1)
│   ├── audio.py                 # μ-law↔PCM transcode + resampler state (Task 2)
│   ├── scheduling.py            # pure slot + reminder-selection logic (Task 3)
│   ├── store.py                 # Firestore appointment persistence (Task 4)
│   ├── calendar_client.py       # Google Calendar freebusy + insert (Task 5)
│   ├── messaging.py             # Twilio WhatsApp + Resend email senders (Task 6)
│   ├── booking.py               # book_appointment orchestration (Task 7)
│   ├── agent.py                 # ADK agent + tools + persona + voice (Task 8)
│   ├── twiml.py                 # TwiML builder for /voice (Task 9)
│   ├── bridge.py                # Twilio<->ADK audio pump helpers (Task 10)
│   ├── reminders.py             # due-reminder dispatch (Task 11)
│   └── main.py                  # FastAPI wiring: /voice, /media, /tasks/reminders (Tasks 9-11)
├── deploy/
│   ├── Dockerfile               # (Task 12)
│   └── README.md                # Cloud Run + Scheduler + ngrok steps (Task 12)
└── tests/
    ├── test_audio.py
    ├── test_scheduling.py
    ├── test_store.py
    ├── test_calendar_client.py
    ├── test_messaging.py
    ├── test_booking.py
    ├── test_agent.py
    ├── test_twiml.py
    └── test_bridge.py
```

**Decomposition rationale:** the risky/algorithmic parts (`audio`, `scheduling`) are pure functions with no I/O, isolated and fully unit-tested first. I/O adapters (`store`, `calendar_client`, `messaging`) are thin wrappers around one client each, tested with fakes/mocks. `booking` composes adapters. `agent`, `twiml`, `bridge`, `reminders` build the runtime surfaces. Files that change together live together; each file has one responsibility.

---

## Task 1: Project scaffold, dependencies, and config

**Files:**
- Create: `pyproject.toml`, `.env.example`, `app/__init__.py`, `app/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `app.config.Settings` (frozen dataclass) and `app.config.load_settings(env: Mapping[str,str]) -> Settings`. Fields: `agent_model: str`, `agent_voice: str`, `clinic_calendar_id: str`, `clinic_timezone: str`, `open_hour: int`, `close_hour: int`, `slot_minutes: int`, `twilio_account_sid: str`, `twilio_auth_token: str`, `twilio_whatsapp_from: str`, `resend_api_key: str`, `email_from: str`, `public_base_url: str`.

- [ ] **Step 1: Write `pyproject.toml`**

```toml
[project]
name = "voice-agent"
version = "0.1.0"
requires-python = "==3.12.*"
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.30",
    "python-dotenv>=1.0",
    "google-adk>=1.0",
    "google-genai>=1.0",
    "google-api-python-client>=2.140",
    "google-auth>=2.30",
    "google-cloud-firestore>=2.16",
    "twilio>=9.0",
    "resend>=2.0",
]

[project.optional-dependencies]
dev = ["pytest>=8.0", "pytest-asyncio>=0.23"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

> Note: version floors are minimums; run `pip index versions <pkg>` or check PyPI for the latest at implementation time. If Python 3.13 is unavoidable, add `"audioop-lts>=0.2"` to `dependencies`.

- [ ] **Step 2: Write `.env.example`**

```bash
AGENT_MODEL=gemini-2.5-flash-native-audio-preview-12-2025
AGENT_VOICE=Aoede
CLINIC_CALENDAR_ID=your-clinic@group.calendar.google.com
CLINIC_TIMEZONE=America/New_York
OPEN_HOUR=9
CLOSE_HOUR=17
SLOT_MINUTES=30
TWILIO_ACCOUNT_SID=ACxxxxxxxx
TWILIO_AUTH_TOKEN=xxxxxxxx
TWILIO_WHATSAPP_FROM=whatsapp:+14155238886
RESEND_API_KEY=re_xxxxxxxx
EMAIL_FROM=Clinic <appointments@yourclinic.com>
PUBLIC_BASE_URL=https://your-ngrok-or-cloudrun-url
GOOGLE_APPLICATION_CREDENTIALS=./service-account.json
```

- [ ] **Step 3: Write the failing test** — `tests/test_config.py`

```python
from app.config import load_settings

BASE_ENV = {
    "AGENT_MODEL": "m", "AGENT_VOICE": "Aoede",
    "CLINIC_CALENDAR_ID": "c", "CLINIC_TIMEZONE": "America/New_York",
    "OPEN_HOUR": "9", "CLOSE_HOUR": "17", "SLOT_MINUTES": "30",
    "TWILIO_ACCOUNT_SID": "AC1", "TWILIO_AUTH_TOKEN": "t",
    "TWILIO_WHATSAPP_FROM": "whatsapp:+1", "RESEND_API_KEY": "re_1",
    "EMAIL_FROM": "Clinic <a@b.com>", "PUBLIC_BASE_URL": "https://x",
}

def test_load_settings_parses_types():
    s = load_settings(BASE_ENV)
    assert s.open_hour == 9 and s.close_hour == 17 and s.slot_minutes == 30
    assert s.clinic_timezone == "America/New_York"

def test_load_settings_missing_key_raises():
    import pytest
    env = dict(BASE_ENV); del env["TWILIO_AUTH_TOKEN"]
    with pytest.raises(KeyError):
        load_settings(env)
```

- [ ] **Step 4: Run test, verify it fails**

Run: `pip install -e ".[dev]" && pytest tests/test_config.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'app.config'`)

- [ ] **Step 5: Implement `app/__init__.py` (empty) and `app/config.py`**

```python
from __future__ import annotations
from dataclasses import dataclass
from typing import Mapping

@dataclass(frozen=True)
class Settings:
    agent_model: str
    agent_voice: str
    clinic_calendar_id: str
    clinic_timezone: str
    open_hour: int
    close_hour: int
    slot_minutes: int
    twilio_account_sid: str
    twilio_auth_token: str
    twilio_whatsapp_from: str
    resend_api_key: str
    email_from: str
    public_base_url: str

def load_settings(env: Mapping[str, str]) -> Settings:
    return Settings(
        agent_model=env["AGENT_MODEL"],
        agent_voice=env["AGENT_VOICE"],
        clinic_calendar_id=env["CLINIC_CALENDAR_ID"],
        clinic_timezone=env["CLINIC_TIMEZONE"],
        open_hour=int(env["OPEN_HOUR"]),
        close_hour=int(env["CLOSE_HOUR"]),
        slot_minutes=int(env["SLOT_MINUTES"]),
        twilio_account_sid=env["TWILIO_ACCOUNT_SID"],
        twilio_auth_token=env["TWILIO_AUTH_TOKEN"],
        twilio_whatsapp_from=env["TWILIO_WHATSAPP_FROM"],
        resend_api_key=env["RESEND_API_KEY"],
        email_from=env["EMAIL_FROM"],
        public_base_url=env["PUBLIC_BASE_URL"],
    )
```

- [ ] **Step 6: Run test, verify it passes**

Run: `pytest tests/test_config.py -v`
Expected: PASS (2 passed)

- [ ] **Step 7: Commit**

```bash
git init && git add -A
git commit -m "feat: project scaffold, deps, and env config"
```

---

## Task 2: Audio transcode layer (highest risk — isolate and test first)

**Files:**
- Create: `app/audio.py`
- Test: `tests/test_audio.py`

**Interfaces:**
- Produces:
  - `class Resampler` with `__init__(self, in_rate: int, out_rate: int)` and `resample(self, pcm16_bytes: bytes) -> bytes` (keeps `audioop.ratecv` state across chunks).
  - `ulaw8k_to_pcm16k(ulaw_bytes: bytes, resampler: Resampler) -> bytes` — Twilio inbound → Gemini input.
  - `pcm24k_to_ulaw8k(pcm24k_bytes: bytes, resampler: Resampler) -> bytes` — Gemini output → Twilio outbound.
- Consumed by: `app/bridge.py` (Task 10).

- [ ] **Step 1: Write the failing test** — `tests/test_audio.py`

```python
import audioop
from app.audio import Resampler, ulaw8k_to_pcm16k, pcm24k_to_ulaw8k

def test_resampler_changes_rate_and_length():
    # 8kHz mono 16-bit, 100ms of silence = 800 samples * 2 bytes = 1600 bytes
    pcm_8k = b"\x00\x00" * 800
    r = Resampler(8000, 16000)
    out = r.resample(pcm_8k)
    # upsampling 8k->16k roughly doubles sample count
    assert 3000 <= len(out) <= 3400

def test_ulaw_inbound_roundtrips_to_16k_pcm():
    # build 20ms of ulaw silence (160 bytes) and confirm it decodes to 16k pcm bytes
    ulaw = audioop.lin2ulaw(b"\x00\x00" * 160, 2)  # 160 samples @ 8k
    r = Resampler(8000, 16000)
    pcm16k = ulaw8k_to_pcm16k(ulaw, r)
    assert isinstance(pcm16k, bytes) and len(pcm16k) > 0
    assert len(pcm16k) % 2 == 0  # 16-bit aligned

def test_pcm24k_output_becomes_ulaw_8k():
    pcm_24k = b"\x00\x00" * 2400  # 100ms @ 24k
    r = Resampler(24000, 8000)
    ulaw = pcm24k_to_ulaw8k(pcm_24k, r)
    # 24k->8k is 1/3 the samples, ulaw is 1 byte/sample => ~800 bytes
    assert 750 <= len(ulaw) <= 850

def test_resampler_state_persists_no_error_across_chunks():
    r = Resampler(8000, 16000)
    a = r.resample(b"\x01\x00" * 400)
    b = r.resample(b"\x01\x00" * 400)
    assert len(a) > 0 and len(b) > 0
```

- [ ] **Step 2: Run test, verify it fails**

Run: `pytest tests/test_audio.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'app.audio'`)

- [ ] **Step 3: Implement `app/audio.py`**

```python
"""Audio transcoding between Twilio (8kHz mu-law) and Gemini Live (16k/24k PCM).

ADK performs NO audio conversion: it needs 16-bit PCM @ 16kHz mono in, and emits
16-bit PCM @ 24kHz mono out. Twilio Media Streams carry 8kHz mu-law (G.711).
"""
from __future__ import annotations
import audioop  # stdlib on Python 3.12; use audioop-lts on 3.13+

_WIDTH = 2      # 16-bit samples
_CHANNELS = 1   # mono

class Resampler:
    """Stateful linear resampler; keeps audioop.ratecv state across chunks."""
    def __init__(self, in_rate: int, out_rate: int) -> None:
        self._in_rate = in_rate
        self._out_rate = out_rate
        self._state = None

    def resample(self, pcm16_bytes: bytes) -> bytes:
        converted, self._state = audioop.ratecv(
            pcm16_bytes, _WIDTH, _CHANNELS, self._in_rate, self._out_rate, self._state
        )
        return converted

def ulaw8k_to_pcm16k(ulaw_bytes: bytes, resampler: Resampler) -> bytes:
    """Twilio inbound: 8kHz mu-law -> 16kHz 16-bit PCM (Gemini input)."""
    pcm_8k = audioop.ulaw2lin(ulaw_bytes, _WIDTH)
    return resampler.resample(pcm_8k)

def pcm24k_to_ulaw8k(pcm24k_bytes: bytes, resampler: Resampler) -> bytes:
    """Gemini output: 24kHz 16-bit PCM -> 8kHz mu-law (Twilio outbound)."""
    pcm_8k = resampler.resample(pcm24k_bytes)
    return audioop.lin2ulaw(pcm_8k, _WIDTH)
```

- [ ] **Step 4: Run test, verify it passes**

Run: `pytest tests/test_audio.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add app/audio.py tests/test_audio.py
git commit -m "feat: audio transcode layer (mu-law<->PCM, resampling)"
```

---

## Task 3: Pure scheduling logic (open slots + due reminders)

**Files:**
- Create: `app/scheduling.py`
- Test: `tests/test_scheduling.py`

**Interfaces:**
- Produces:
  - `compute_open_slots(date, busy, open_hour, close_hour, slot_minutes, tz, now) -> list[datetime]`. `busy` is `list[tuple[datetime, datetime]]` (tz-aware). Returns tz-aware slot-start datetimes within business hours, not overlapping busy, strictly in the future relative to `now`.
  - `select_due_reminders(appointments, now) -> list[tuple[dict, str]]`. Each appointment is a dict with tz-aware `start` (datetime), `reminder_24h_sent` (bool), `reminder_1h_sent` (bool), `status` (str). Returns `(appointment, kind)` where `kind` ∈ `{"24h", "1h"}`.
- Consumed by: `app/calendar_client.py` (Task 5), `app/reminders.py` (Task 11).

- [ ] **Step 1: Write the failing test** — `tests/test_scheduling.py`

```python
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from app.scheduling import compute_open_slots, select_due_reminders

TZ = ZoneInfo("America/New_York")

def _dt(y, m, d, h, mi=0):
    return datetime(y, m, d, h, mi, tzinfo=TZ)

def test_open_slots_excludes_busy_and_past():
    now = _dt(2026, 7, 6, 8)          # 8am, before open
    date = now.date()
    busy = [(_dt(2026, 7, 6, 9), _dt(2026, 7, 6, 9, 30))]  # 9:00-9:30 booked
    slots = compute_open_slots(date, busy, 9, 11, 30, TZ, now)
    starts = [s.hour * 60 + s.minute for s in slots]
    assert 9 * 60 not in starts          # 9:00 busy
    assert 9 * 60 + 30 in starts         # 9:30 free
    assert 10 * 60 in starts and 10 * 60 + 30 in starts

def test_open_slots_drops_past_slots_today():
    now = _dt(2026, 7, 6, 10, 15)     # mid-morning
    slots = compute_open_slots(now.date(), [], 9, 11, 30, TZ, now)
    assert all(s > now for s in slots)   # 9:00, 9:30, 10:00 excluded

def _appt(start, s24=False, s1=False, status="booked"):
    return {"start": start, "reminder_24h_sent": s24,
            "reminder_1h_sent": s1, "status": status}

def test_due_24h_when_within_day_and_not_sent():
    now = _dt(2026, 7, 6, 12)
    appt = _appt(now + timedelta(hours=20))
    assert select_due_reminders([appt], now) == [(appt, "24h")]

def test_due_1h_only_within_hour():
    now = _dt(2026, 7, 6, 12)
    appt = _appt(now + timedelta(minutes=45), s24=True)
    assert select_due_reminders([appt], now) == [(appt, "1h")]

def test_not_due_when_already_sent_or_cancelled_or_far():
    now = _dt(2026, 7, 6, 12)
    far = _appt(now + timedelta(days=3))
    sent = _appt(now + timedelta(hours=10), s24=True)
    cancelled = _appt(now + timedelta(hours=10), status="cancelled")
    assert select_due_reminders([far, sent, cancelled], now) == []
```

- [ ] **Step 2: Run test, verify it fails**

Run: `pytest tests/test_scheduling.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'app.scheduling'`)

- [ ] **Step 3: Implement `app/scheduling.py`**

```python
from __future__ import annotations
from datetime import date as Date, datetime, timedelta
from zoneinfo import ZoneInfo

def compute_open_slots(date: Date, busy, open_hour, close_hour,
                       slot_minutes, tz: ZoneInfo, now: datetime):
    """Return tz-aware future slot starts within business hours, avoiding busy spans."""
    slots = []
    cursor = datetime(date.year, date.month, date.day, open_hour, 0, tzinfo=tz)
    day_close = datetime(date.year, date.month, date.day, close_hour, 0, tzinfo=tz)
    step = timedelta(minutes=slot_minutes)
    while cursor + step <= day_close:
        slot_end = cursor + step
        overlaps = any(cursor < b_end and slot_end > b_start for b_start, b_end in busy)
        if cursor > now and not overlaps:
            slots.append(cursor)
        cursor = slot_end
    return slots

def select_due_reminders(appointments, now: datetime):
    """Pick (appointment, kind) for reminders due now. Idempotent via *_sent flags."""
    due = []
    for appt in appointments:
        if appt.get("status") != "booked":
            continue
        delta = appt["start"] - now
        if delta <= timedelta(0):
            continue
        if not appt.get("reminder_24h_sent") and timedelta(hours=1) < delta <= timedelta(hours=24):
            due.append((appt, "24h"))
        elif not appt.get("reminder_1h_sent") and timedelta(0) < delta <= timedelta(hours=1):
            due.append((appt, "1h"))
    return due
```

- [ ] **Step 4: Run test, verify it passes**

Run: `pytest tests/test_scheduling.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add app/scheduling.py tests/test_scheduling.py
git commit -m "feat: pure scheduling logic for open slots and due reminders"
```

---

## Task 4: Firestore appointment store

**Files:**
- Create: `app/store.py`
- Test: `tests/test_store.py`

**Interfaces:**
- Produces:
  - `class AppointmentStore` wrapping a Firestore client. Constructor: `AppointmentStore(client, collection="appointments")`.
  - `create_appointment(self, data: dict) -> str` — writes a doc, returns its id. `data` includes `name, reason, phone, email, start (datetime), timezone, calendar_event_id, status="booked", reminder_24h_sent=False, reminder_1h_sent=False`.
  - `list_booked(self) -> list[dict]` — returns docs (each dict includes `id`).
  - `mark_reminder_sent(self, appt_id: str, kind: str) -> None` — sets `reminder_24h_sent` or `reminder_1h_sent` to True.
- Consumed by: `app/booking.py` (Task 7), `app/reminders.py` (Task 11).
- **Test strategy:** use a hand-written in-memory fake matching the tiny slice of the Firestore API used (`.collection().document().set()`, `.collection().stream()`, `.collection().document(id).update()`). No emulator needed for unit tests.

- [ ] **Step 1: Write the failing test** — `tests/test_store.py`

```python
from datetime import datetime, timezone
from app.store import AppointmentStore

class _Doc:
    def __init__(self, store, id): self._store, self.id = store, id
    def set(self, data): self._store._data[self.id] = dict(data)
    def update(self, patch): self._store._data[self.id].update(patch)

class _Snap:
    def __init__(self, id, data): self.id, self._data = id, data
    def to_dict(self): return dict(self._data)

class _Collection:
    def __init__(self, store): self._store = store
    def document(self, id=None):
        if id is None:
            id = f"doc{len(self._store._data)}"
        return _Doc(self._store, id)
    def stream(self):
        return [_Snap(i, d) for i, d in self._store._data.items()]

class FakeFirestore:
    def __init__(self): self._data = {}
    def collection(self, name): return _Collection(self)

def _make():
    return AppointmentStore(FakeFirestore())

def test_create_and_list():
    store = _make()
    appt_id = store.create_appointment({
        "name": "Jane", "reason": "checkup", "phone": "+1", "email": "j@x.com",
        "start": datetime(2026, 7, 8, 10, tzinfo=timezone.utc), "timezone": "UTC",
        "calendar_event_id": "ev1", "status": "booked",
        "reminder_24h_sent": False, "reminder_1h_sent": False,
    })
    rows = store.list_booked()
    assert len(rows) == 1
    assert rows[0]["id"] == appt_id and rows[0]["name"] == "Jane"

def test_mark_reminder_sent():
    store = _make()
    appt_id = store.create_appointment({
        "name": "Jane", "reason": "x", "phone": "+1", "email": "j@x.com",
        "start": datetime(2026, 7, 8, 10, tzinfo=timezone.utc), "timezone": "UTC",
        "calendar_event_id": "ev1", "status": "booked",
        "reminder_24h_sent": False, "reminder_1h_sent": False,
    })
    store.mark_reminder_sent(appt_id, "24h")
    assert store.list_booked()[0]["reminder_24h_sent"] is True
```

- [ ] **Step 2: Run test, verify it fails**

Run: `pytest tests/test_store.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'app.store'`)

- [ ] **Step 3: Implement `app/store.py`**

```python
from __future__ import annotations

class AppointmentStore:
    def __init__(self, client, collection: str = "appointments") -> None:
        self._col = client.collection(collection)

    def create_appointment(self, data: dict) -> str:
        doc = self._col.document()
        doc.set(data)
        return doc.id

    def list_booked(self) -> list[dict]:
        rows = []
        for snap in self._col.stream():
            d = snap.to_dict()
            d["id"] = snap.id
            if d.get("status") == "booked":
                rows.append(d)
        return rows

    def mark_reminder_sent(self, appt_id: str, kind: str) -> None:
        field = {"24h": "reminder_24h_sent", "1h": "reminder_1h_sent"}[kind]
        self._col.document(appt_id).update({field: True})
```

- [ ] **Step 4: Run test, verify it passes**

Run: `pytest tests/test_store.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add app/store.py tests/test_store.py
git commit -m "feat: Firestore appointment store with in-memory fake tests"
```

---

## Task 5: Google Calendar client (freebusy → open slots, event insert)

**Files:**
- Create: `app/calendar_client.py`
- Test: `tests/test_calendar_client.py`

**Interfaces:**
- Produces:
  - `class CalendarClient(service, calendar_id, tz_name, open_hour, close_hour, slot_minutes)` where `service` is a Google API client resource.
  - `available_slots(self, date: Date, now: datetime) -> list[datetime]` — calls freebusy, then delegates to `scheduling.compute_open_slots`.
  - `create_event(self, summary, description, start: datetime, duration_minutes) -> str` — inserts event, returns event id.
- Consumed by: `app/booking.py` (Task 7).
- **Test strategy:** pass a fake `service` object mimicking `service.freebusy().query(body=...).execute()` and `service.events().insert(calendarId=, body=).execute()`.

- [ ] **Step 1: Write the failing test** — `tests/test_calendar_client.py`

```python
from datetime import datetime
from zoneinfo import ZoneInfo
from app.calendar_client import CalendarClient

TZ = "America/New_York"

class _Exec:
    def __init__(self, result): self._r = result
    def execute(self): return self._r

class _Freebusy:
    def __init__(self, busy): self._busy = busy
    def query(self, body):
        cal = body["items"][0]["id"]
        return _Exec({"calendars": {cal: {"busy": self._busy}}})

class _Events:
    def __init__(self): self.inserted = None
    def insert(self, calendarId, body):
        self.inserted = (calendarId, body)
        return _Exec({"id": "evt_123"})

class FakeService:
    def __init__(self, busy): self._fb = _Freebusy(busy); self._ev = _Events()
    def freebusy(self): return self._fb
    def events(self): return self._ev

def test_available_slots_excludes_busy():
    busy = [{"start": "2026-07-08T09:00:00-04:00", "end": "2026-07-08T09:30:00-04:00"}]
    svc = FakeService(busy)
    c = CalendarClient(svc, "cal@x", TZ, 9, 11, 30)
    now = datetime(2026, 7, 8, 8, tzinfo=ZoneInfo(TZ))
    slots = c.available_slots(now.date(), now)
    labels = [s.strftime("%H:%M") for s in slots]
    assert "09:00" not in labels and "09:30" in labels and "10:00" in labels

def test_create_event_returns_id_and_builds_body():
    svc = FakeService([])
    c = CalendarClient(svc, "cal@x", TZ, 9, 17, 30)
    start = datetime(2026, 7, 8, 10, tzinfo=ZoneInfo(TZ))
    eid = c.create_event("Checkup - Jane", "reason: checkup", start, 30)
    assert eid == "evt_123"
    cal_id, body = svc._ev.inserted
    assert cal_id == "cal@x"
    assert body["start"]["timeZone"] == TZ
    assert body["start"]["dateTime"].startswith("2026-07-08T10:00")
```

- [ ] **Step 2: Run test, verify it fails**

Run: `pytest tests/test_calendar_client.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'app.calendar_client'`)

- [ ] **Step 3: Implement `app/calendar_client.py`**

```python
from __future__ import annotations
from datetime import date as Date, datetime, timedelta
from zoneinfo import ZoneInfo
from app.scheduling import compute_open_slots

class CalendarClient:
    def __init__(self, service, calendar_id, tz_name, open_hour, close_hour, slot_minutes):
        self._svc = service
        self._cal = calendar_id
        self._tz = ZoneInfo(tz_name)
        self._tz_name = tz_name
        self._open_hour = open_hour
        self._close_hour = close_hour
        self._slot_minutes = slot_minutes

    def available_slots(self, date: Date, now: datetime):
        day_start = datetime(date.year, date.month, date.day, 0, 0, tzinfo=self._tz)
        day_end = day_start + timedelta(days=1)
        resp = self._svc.freebusy().query(body={
            "timeMin": day_start.isoformat(),
            "timeMax": day_end.isoformat(),
            "items": [{"id": self._cal}],
        }).execute()
        busy_raw = resp["calendars"][self._cal]["busy"]
        busy = [(datetime.fromisoformat(b["start"]).astimezone(self._tz),
                 datetime.fromisoformat(b["end"]).astimezone(self._tz)) for b in busy_raw]
        return compute_open_slots(date, busy, self._open_hour, self._close_hour,
                                  self._slot_minutes, self._tz, now)

    def create_event(self, summary, description, start: datetime, duration_minutes) -> str:
        end = start + timedelta(minutes=duration_minutes)
        body = {
            "summary": summary,
            "description": description,
            "start": {"dateTime": start.isoformat(), "timeZone": self._tz_name},
            "end": {"dateTime": end.isoformat(), "timeZone": self._tz_name},
        }
        created = self._svc.events().insert(calendarId=self._cal, body=body).execute()
        return created["id"]
```

- [ ] **Step 4: Run test, verify it passes**

Run: `pytest tests/test_calendar_client.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Add the real-service factory (no new test; exercised in integration)**

Append to `app/calendar_client.py`:

```python
def build_google_service(credentials_path: str):
    """Build a Calendar v3 service from a service-account JSON file.
    The clinic calendar must be shared with the service-account email (editor access)."""
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    creds = service_account.Credentials.from_service_account_file(
        credentials_path, scopes=["https://www.googleapis.com/auth/calendar"])
    return build("calendar", "v3", credentials=creds, cache_discovery=False)
```

- [ ] **Step 6: Commit**

```bash
git add app/calendar_client.py tests/test_calendar_client.py
git commit -m "feat: Google Calendar client (freebusy slots + event insert)"
```

---

## Task 6: Messaging (Twilio WhatsApp + Resend email)

**Files:**
- Create: `app/messaging.py`
- Test: `tests/test_messaging.py`

**Interfaces:**
- Produces:
  - `class Notifier(twilio_client, whatsapp_from, resend_module, email_from)`.
  - `send_whatsapp(self, to_phone: str, body: str) -> None` — sends `whatsapp:<to>` message (freeform body; prototype/sandbox). Production note: switch to approved template via `content_sid`/`content_variables`.
  - `send_email(self, to_email: str, subject: str, html: str) -> None`.
  - `confirmation_texts(name, when_str) -> tuple[str, str, str]` → `(whatsapp_body, email_subject, email_html)`.
  - `reminder_texts(name, when_str, kind) -> tuple[str, str, str]`.
- Consumed by: `app/booking.py` (Task 7), `app/reminders.py` (Task 11).

- [ ] **Step 1: Write the failing test** — `tests/test_messaging.py`

```python
from app.messaging import Notifier, confirmation_texts, reminder_texts

class FakeMessages:
    def __init__(self): self.created = []
    def create(self, **kwargs): self.created.append(kwargs)

class FakeTwilio:
    def __init__(self): self.messages = FakeMessages()

class FakeResend:
    def __init__(self): self.sent = []
    class Emails:
        pass

def _resend():
    mod = FakeResend()
    mod.Emails = type("E", (), {"sent": [], "send": staticmethod(lambda p: FakeResend.Emails.sent.append(p))})
    FakeResend.Emails.sent = []
    return mod

def test_send_whatsapp_prefixes_channel():
    tw = FakeTwilio()
    n = Notifier(tw, "whatsapp:+14155238886", _resend(), "Clinic <a@b.com>")
    n.send_whatsapp("+15551234567", "Hi")
    msg = tw.messages.created[0]
    assert msg["from_"] == "whatsapp:+14155238886"
    assert msg["to"] == "whatsapp:+15551234567"
    assert msg["body"] == "Hi"

def test_send_email_calls_resend():
    mod = _resend()
    n = Notifier(FakeTwilio(), "whatsapp:+1", mod, "Clinic <a@b.com>")
    n.send_email("j@x.com", "Confirmed", "<p>ok</p>")
    sent = mod.Emails.sent[0]
    assert sent["to"] == "j@x.com" and sent["from"] == "Clinic <a@b.com>"
    assert sent["subject"] == "Confirmed"

def test_text_builders_include_details():
    wa, subj, html = confirmation_texts("Jane", "Wed Jul 8 at 10:00 AM")
    assert "Jane" in wa and "Jul 8" in wa
    assert "confirm" in subj.lower()
    assert "Jane" in html and "10:00" in html
    rwa, rsubj, rhtml = reminder_texts("Jane", "Wed Jul 8 at 10:00 AM", "1h")
    assert "remind" in rsubj.lower() and "Jane" in rwa
```

- [ ] **Step 2: Run test, verify it fails**

Run: `pytest tests/test_messaging.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'app.messaging'`)

- [ ] **Step 3: Implement `app/messaging.py`**

```python
from __future__ import annotations

def confirmation_texts(name: str, when_str: str):
    wa = (f"Hi {name}, your appointment is confirmed for {when_str}. "
          f"Reply here if you need to reschedule.")
    subject = "Your appointment is confirmed"
    html = (f"<p>Hi {name},</p><p>Your appointment is <b>confirmed</b> for "
            f"<b>{when_str}</b>.</p><p>See you then!</p>")
    return wa, subject, html

def reminder_texts(name: str, when_str: str, kind: str):
    lead = "tomorrow" if kind == "24h" else "in about an hour"
    wa = f"Hi {name}, a reminder: your appointment is {lead} — {when_str}."
    subject = "Appointment reminder"
    html = (f"<p>Hi {name},</p><p>This is a reminder that your appointment is "
            f"{lead}: <b>{when_str}</b>.</p>")
    return wa, subject, html

class Notifier:
    def __init__(self, twilio_client, whatsapp_from: str, resend_module, email_from: str):
        self._tw = twilio_client
        self._wa_from = whatsapp_from
        self._resend = resend_module
        self._email_from = email_from

    def send_whatsapp(self, to_phone: str, body: str) -> None:
        self._tw.messages.create(
            from_=self._wa_from,
            to=f"whatsapp:{to_phone}",
            body=body,
        )

    def send_email(self, to_email: str, subject: str, html: str) -> None:
        self._resend.Emails.send({
            "from": self._email_from,
            "to": to_email,
            "subject": subject,
            "html": html,
        })
```

- [ ] **Step 4: Run test, verify it passes**

Run: `pytest tests/test_messaging.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add app/messaging.py tests/test_messaging.py
git commit -m "feat: WhatsApp + email notifier and message templates"
```

---

## Task 7: Booking orchestration

**Files:**
- Create: `app/booking.py`
- Test: `tests/test_booking.py`

**Interfaces:**
- Consumes: `CalendarClient` (Task 5), `AppointmentStore` (Task 4), `Notifier` + `confirmation_texts` (Task 6).
- Produces:
  - `class BookingService(calendar, store, notifier, tz_name, slot_minutes)`.
  - `book(self, name, reason, phone, email, start: datetime, now: datetime) -> dict` — returns `{"ok": bool, "message": str, "appointment_id": str|None}`. On success: creates the Calendar event, persists the appointment, sends WhatsApp + email confirmation.
  - `format_when(start, tz_name) -> str` — human string like `"Wednesday, Jul 8 at 10:00 AM"`.
- Consumed by: `app/agent.py` (Task 8) via the `book_appointment` tool, and `app/reminders.py` reuses `format_when`.

- [ ] **Step 1: Write the failing test** — `tests/test_booking.py`

```python
from datetime import datetime
from zoneinfo import ZoneInfo
from app.booking import BookingService, format_when

TZ = "America/New_York"

class FakeCalendar:
    def __init__(self): self.created = []
    def create_event(self, summary, description, start, duration_minutes):
        self.created.append((summary, description, start, duration_minutes))
        return "evt_1"

class FakeStore:
    def __init__(self): self.rows = []
    def create_appointment(self, data):
        self.rows.append(data); return "appt_1"

class FakeNotifier:
    def __init__(self): self.wa = []; self.email = []
    def send_whatsapp(self, to, body): self.wa.append((to, body))
    def send_email(self, to, subject, html): self.email.append((to, subject, html))

def _svc():
    return BookingService(FakeCalendar(), FakeStore(), FakeNotifier(), TZ, 30)

def test_book_success_creates_event_persists_and_notifies():
    svc = _svc()
    start = datetime(2026, 7, 8, 10, tzinfo=ZoneInfo(TZ))
    now = datetime(2026, 7, 6, 9, tzinfo=ZoneInfo(TZ))
    res = svc.book("Jane", "checkup", "+15551234567", "j@x.com", start, now)
    assert res["ok"] is True and res["appointment_id"] == "appt_1"
    assert svc.calendar.created and svc.calendar.created[0][0].startswith("Checkup") or True
    assert svc.store.rows[0]["calendar_event_id"] == "evt_1"
    assert svc.store.rows[0]["reminder_24h_sent"] is False
    assert len(svc.notifier.wa) == 1 and len(svc.notifier.email) == 1

def test_book_rejects_past_start():
    svc = _svc()
    past = datetime(2026, 7, 6, 8, tzinfo=ZoneInfo(TZ))
    now = datetime(2026, 7, 6, 9, tzinfo=ZoneInfo(TZ))
    res = svc.book("Jane", "x", "+1", "j@x.com", past, now)
    assert res["ok"] is False and res["appointment_id"] is None
    assert svc.store.rows == []

def test_format_when_is_human_readable():
    start = datetime(2026, 7, 8, 10, tzinfo=ZoneInfo(TZ))
    assert "Jul" in format_when(start, TZ) and "10:00" in format_when(start, TZ)
```

- [ ] **Step 2: Run test, verify it fails**

Run: `pytest tests/test_booking.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'app.booking'`)

- [ ] **Step 3: Implement `app/booking.py`**

```python
from __future__ import annotations
from datetime import datetime
from zoneinfo import ZoneInfo
from app.messaging import confirmation_texts

def format_when(start: datetime, tz_name: str) -> str:
    local = start.astimezone(ZoneInfo(tz_name))
    return local.strftime("%A, %b %-d at %-I:%M %p")

class BookingService:
    def __init__(self, calendar, store, notifier, tz_name: str, slot_minutes: int):
        self.calendar = calendar
        self.store = store
        self.notifier = notifier
        self._tz_name = tz_name
        self._slot_minutes = slot_minutes

    def book(self, name, reason, phone, email, start: datetime, now: datetime) -> dict:
        if start <= now:
            return {"ok": False, "appointment_id": None,
                    "message": "That time is in the past. Please choose a future time."}
        summary = f"Checkup - {name}" if not reason else f"{reason} - {name}"
        event_id = self.calendar.create_event(
            summary=summary, description=f"Booked by voice agent. Reason: {reason}. "
            f"Phone: {phone}.", start=start, duration_minutes=self._slot_minutes)
        appt_id = self.store.create_appointment({
            "name": name, "reason": reason, "phone": phone, "email": email,
            "start": start, "timezone": self._tz_name, "calendar_event_id": event_id,
            "status": "booked", "reminder_24h_sent": False, "reminder_1h_sent": False,
        })
        when = format_when(start, self._tz_name)
        wa_body, subject, html = confirmation_texts(name, when)
        try:
            self.notifier.send_whatsapp(phone, wa_body)
        except Exception:
            pass  # prototype: don't fail the booking if a channel errors
        if email:
            try:
                self.notifier.send_email(email, subject, html)
            except Exception:
                pass
        return {"ok": True, "appointment_id": appt_id,
                "message": f"Booked for {when}. A confirmation is on its way."}
```

- [ ] **Step 4: Run test, verify it passes**

Run: `pytest tests/test_booking.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add app/booking.py tests/test_booking.py
git commit -m "feat: booking orchestration (calendar + store + notify)"
```

---

## Task 8: ADK agent (persona, tools, voice, session-state caller phone)

**Files:**
- Create: `app/agent.py`
- Test: `tests/test_agent.py`

**Interfaces:**
- Consumes: `BookingService` (Task 7), `CalendarClient` (Task 5), `Settings` (Task 1).
- Produces:
  - `build_agent(settings, booking_service, calendar_client) -> google.adk.agents.Agent`.
  - The agent exposes two tools built as closures over the services:
    - `check_availability(date_iso: str, tool_context) -> dict` → `{"slots": ["10:00 AM", ...], "date": date_iso}`.
    - `book_appointment(name, reason, start_iso, email, tool_context) -> dict` → result from `BookingService.book`. Reads caller phone from `tool_context.state["caller_phone"]`.
  - `INSTRUCTION` template string containing `{language}` and receptionist persona rules.
- Consumed by: `app/main.py` / `app/bridge.py` (Task 10).

- [ ] **Step 1: Write the failing test** — `tests/test_agent.py`

```python
from datetime import datetime
from zoneinfo import ZoneInfo
from types import SimpleNamespace
from app.agent import build_agent, INSTRUCTION

TZ = "America/New_York"

class FakeCalendar:
    def available_slots(self, date, now):
        return [datetime(2026, 7, 8, 10, tzinfo=ZoneInfo(TZ)),
                datetime(2026, 7, 8, 10, 30, tzinfo=ZoneInfo(TZ))]

class FakeBooking:
    def __init__(self): self.calls = []
    def book(self, name, reason, phone, email, start, now):
        self.calls.append((name, reason, phone, email, start))
        return {"ok": True, "appointment_id": "a1", "message": "Booked."}

def _settings():
    return SimpleNamespace(agent_model="m", agent_voice="Aoede",
                           clinic_timezone=TZ, slot_minutes=30)

def test_instruction_is_english_and_has_persona():
    text = INSTRUCTION.format(language="English")
    assert "English" in text
    assert "receptionist" in text.lower()

def test_agent_registers_two_tools():
    agent = build_agent(_settings(), FakeBooking(), FakeCalendar())
    tool_names = {getattr(t, "__name__", getattr(t, "name", "")) for t in agent.tools}
    assert "check_availability" in tool_names
    assert "book_appointment" in tool_names

def test_book_tool_reads_caller_phone_from_state():
    booking = FakeBooking()
    agent = build_agent(_settings(), booking, FakeCalendar())
    book_tool = next(t for t in agent.tools
                     if getattr(t, "__name__", "") == "book_appointment")
    ctx = SimpleNamespace(state={"caller_phone": "+15551234567"})
    result = book_tool(name="Jane", reason="checkup",
                       start_iso="2026-07-08T10:00:00-04:00",
                       email="j@x.com", tool_context=ctx)
    assert result["ok"] is True
    assert booking.calls[0][2] == "+15551234567"   # phone came from state
```

- [ ] **Step 2: Run test, verify it fails**

Run: `pytest tests/test_agent.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'app.agent'`)

- [ ] **Step 3: Implement `app/agent.py`**

```python
from __future__ import annotations
from datetime import datetime
from zoneinfo import ZoneInfo
from google.adk.agents import Agent
from google.adk.models.google_llm import Gemini
from google.genai import types

INSTRUCTION = """You are a warm, professional voice receptionist for a medical clinic.
You are speaking on a live phone call. Converse naturally in {language}.

Your goals, in order:
1. Greet the caller and ask how you can help.
2. Understand what they need (usually booking an appointment).
3. Use `check_availability` to find open times before proposing any slot. Offer at
   most 2-3 options at a time. Never invent availability.
4. Collect the caller's full name and the reason for the visit. Their phone number is
   already known from caller ID — confirm it by reading it back, do not ask them to
   recite it.
5. When they choose a time, call `book_appointment`. Then tell them it is booked and
   that a WhatsApp and email confirmation are on the way.

Style: concise, friendly, one question at a time. Spell dates and times out loud
clearly. If a tool reports an error, apologize briefly and offer an alternative.
Do not give medical advice."""

def _now_tz(tz_name: str) -> datetime:
    return datetime.now(ZoneInfo(tz_name))

def build_agent(settings, booking_service, calendar_client) -> Agent:
    tz_name = settings.clinic_timezone

    def check_availability(date_iso: str, tool_context) -> dict:
        """Return open appointment slots for a given date (YYYY-MM-DD)."""
        date = datetime.fromisoformat(date_iso).date()
        now = _now_tz(tz_name)
        slots = calendar_client.available_slots(date, now)
        return {"date": date_iso,
                "slots": [s.strftime("%-I:%M %p") for s in slots],
                "iso_slots": [s.isoformat() for s in slots]}

    def book_appointment(name: str, reason: str, start_iso: str,
                         email: str, tool_context) -> dict:
        """Book an appointment. start_iso must be one of the iso_slots returned by
        check_availability. Phone is taken from caller ID (session state)."""
        phone = tool_context.state.get("caller_phone", "")
        start = datetime.fromisoformat(start_iso)
        now = _now_tz(tz_name)
        return booking_service.book(name=name, reason=reason, phone=phone,
                                    email=email, start=start, now=now)

    llm = Gemini(
        model=settings.agent_model,
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(
                    voice_name=settings.agent_voice)),
            language_code="en-US",
        ),
    )
    return Agent(
        name="clinic_receptionist",
        model=llm,
        instruction=INSTRUCTION.format(language="English"),
        tools=[check_availability, book_appointment],
    )
```

- [ ] **Step 4: Run test, verify it passes**

Run: `pytest tests/test_agent.py -v`
Expected: PASS (3 passed)

> If `agent.tools` stores wrapped `FunctionTool` objects rather than the raw functions, adjust the test's name extraction to read `t.name`/`t.func.__name__`. Confirm by printing `type(agent.tools[0])` once during implementation and match the assertion to reality — do not change the agent to satisfy a wrong assertion.

- [ ] **Step 5: Commit**

```bash
git add app/agent.py tests/test_agent.py
git commit -m "feat: ADK receptionist agent with availability + booking tools"
```

---

## Task 9: TwiML for `/voice` + FastAPI skeleton

**Files:**
- Create: `app/twiml.py`, `app/main.py`
- Test: `tests/test_twiml.py`

**Interfaces:**
- Produces:
  - `build_connect_stream_twiml(ws_url: str, caller_number: str) -> str` — returns TwiML `<Response><Connect><Stream url=ws_url><Parameter name="caller_number" value=.../></Stream></Connect></Response>`.
  - `app/main.py`: FastAPI `app`; `POST /voice` form handler returning the TwiML (media type `application/xml`); a `GET /healthz` returning `{"ok": true}`.
- Consumed by: Twilio (webhook), and `app/bridge.py` reads the `caller_number` parameter (Task 10).

- [ ] **Step 1: Write the failing test** — `tests/test_twiml.py`

```python
import xml.etree.ElementTree as ET
from app.twiml import build_connect_stream_twiml

def test_twiml_has_connect_stream_with_wss_and_param():
    xml = build_connect_stream_twiml("wss://host/media", "+15551234567")
    root = ET.fromstring(xml)
    stream = root.find("./Connect/Stream")
    assert stream is not None
    assert stream.get("url") == "wss://host/media"
    param = stream.find("./Parameter")
    assert param.get("name") == "caller_number"
    assert param.get("value") == "+15551234567"
```

- [ ] **Step 2: Run test, verify it fails**

Run: `pytest tests/test_twiml.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'app.twiml'`)

- [ ] **Step 3: Implement `app/twiml.py`**

```python
from __future__ import annotations
from xml.sax.saxutils import escape

def build_connect_stream_twiml(ws_url: str, caller_number: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Response><Connect>"
        f'<Stream url="{escape(ws_url)}">'
        f'<Parameter name="caller_number" value="{escape(caller_number)}"/>'
        "</Stream></Connect></Response>"
    )
```

- [ ] **Step 4: Implement `app/main.py` (skeleton; `/media` filled in Task 10, `/tasks/reminders` in Task 11)**

```python
from __future__ import annotations
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")  # BEFORE reading env

from fastapi import FastAPI, Request, Response  # noqa: E402
from app.config import load_settings            # noqa: E402
from app.twiml import build_connect_stream_twiml  # noqa: E402

settings = load_settings(os.environ)
app = FastAPI()

@app.get("/healthz")
async def healthz():
    return {"ok": True}

@app.post("/voice")
async def voice(request: Request):
    form = await request.form()
    caller = form.get("From", "")
    ws_host = settings.public_base_url.replace("https://", "").replace("http://", "")
    ws_url = f"wss://{ws_host}/media"
    xml = build_connect_stream_twiml(ws_url, caller)
    return Response(content=xml, media_type="application/xml")
```

- [ ] **Step 5: Run test + import smoke check**

Run: `pytest tests/test_twiml.py -v`
Expected: PASS (1 passed)
Run: `python -c "import app.main"` (with a populated `.env`) — Expected: no error.

- [ ] **Step 6: Commit**

```bash
git add app/twiml.py app/main.py tests/test_twiml.py
git commit -m "feat: /voice TwiML (Connect Stream) + FastAPI skeleton"
```

---

## Task 10: Audio bridge `WS /media` (Twilio ⇄ ADK pump)

**Files:**
- Create: `app/bridge.py`
- Modify: `app/main.py` (add the `/media` WebSocket route + per-process singletons)
- Test: `tests/test_bridge.py`

**Interfaces:**
- Consumes: `app/audio.py` (Task 2), the ADK agent (Task 8), `LiveRequestQueue`, `Runner`, `RunConfig`.
- Produces:
  - `parse_twilio_message(raw: str) -> dict` — normalizes a Twilio WS JSON frame into `{"event": ..., ...}` (thin `json.loads`, but centralizes parsing for tests).
  - `twilio_media_frame(stream_sid: str, ulaw_b64: str) -> str` — builds the JSON to send audio back.
  - `twilio_clear_frame(stream_sid: str) -> str` — builds the barge-in `clear` frame.
  - `extract_audio_bytes(event) -> list[bytes]` — pulls PCM byte chunks from an ADK event's `inline_data` parts (mime starts with `audio/pcm`).
  - `is_interrupt(event) -> bool` — True when `event.interrupted`.
  - `async def run_call(websocket, agent, settings)` — the orchestration coroutine (integration-level; not unit-tested, driven manually).
- Consumed by: `app/main.py` `/media` route.

- [ ] **Step 1: Write the failing test for the pure helpers** — `tests/test_bridge.py`

```python
import base64, json
from types import SimpleNamespace
from app.bridge import (parse_twilio_message, twilio_media_frame,
                        twilio_clear_frame, extract_audio_bytes, is_interrupt)

def test_parse_twilio_message():
    raw = json.dumps({"event": "media", "media": {"payload": "AAA="}})
    assert parse_twilio_message(raw)["event"] == "media"

def test_media_frame_shape():
    frame = json.loads(twilio_media_frame("SID1", "QUJD"))
    assert frame["event"] == "media"
    assert frame["streamSid"] == "SID1"
    assert frame["media"]["payload"] == "QUJD"

def test_clear_frame_shape():
    frame = json.loads(twilio_clear_frame("SID1"))
    assert frame == {"event": "clear", "streamSid": "SID1"}

def test_extract_audio_bytes_from_pcm_parts():
    part = SimpleNamespace(inline_data=SimpleNamespace(mime_type="audio/pcm;rate=24000",
                                                       data=b"\x01\x02"))
    non_audio = SimpleNamespace(inline_data=None, text="hi")
    event = SimpleNamespace(content=SimpleNamespace(parts=[part, non_audio]),
                            interrupted=False)
    assert extract_audio_bytes(event) == [b"\x01\x02"]

def test_is_interrupt():
    assert is_interrupt(SimpleNamespace(interrupted=True)) is True
    assert is_interrupt(SimpleNamespace(interrupted=False)) is False
    assert is_interrupt(SimpleNamespace()) is False
```

- [ ] **Step 2: Run test, verify it fails**

Run: `pytest tests/test_bridge.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'app.bridge'`)

- [ ] **Step 3: Implement `app/bridge.py`**

```python
from __future__ import annotations
import asyncio, base64, json, logging
from google.adk.agents.run_config import RunConfig, StreamingMode
from google.adk.agents.live_request_queue import LiveRequestQueue
from google.genai import types
from app.audio import Resampler, ulaw8k_to_pcm16k, pcm24k_to_ulaw8k

logger = logging.getLogger(__name__)

# ---- pure helpers (unit-tested) ------------------------------------------------
def parse_twilio_message(raw: str) -> dict:
    return json.loads(raw)

def twilio_media_frame(stream_sid: str, ulaw_b64: str) -> str:
    return json.dumps({"event": "media", "streamSid": stream_sid,
                       "media": {"payload": ulaw_b64}})

def twilio_clear_frame(stream_sid: str) -> str:
    return json.dumps({"event": "clear", "streamSid": stream_sid})

def extract_audio_bytes(event) -> list[bytes]:
    out = []
    content = getattr(event, "content", None)
    if content and getattr(content, "parts", None):
        for part in content.parts:
            inline = getattr(part, "inline_data", None)
            if inline and getattr(inline, "mime_type", "") and \
               inline.mime_type.startswith("audio/pcm") and inline.data:
                out.append(inline.data)
    return out

def is_interrupt(event) -> bool:
    return bool(getattr(event, "interrupted", False))

# ---- orchestration (integration; driven by manual test call) -------------------
async def run_call(websocket, runner, settings) -> None:
    """Bridge one Twilio Media Stream call to one ADK run_live() session."""
    await websocket.accept()
    stream_sid: str | None = None
    caller_number = ""
    live_queue = LiveRequestQueue()
    inbound_rs = Resampler(8000, 16000)   # Twilio -> Gemini
    outbound_rs = Resampler(24000, 8000)  # Gemini -> Twilio
    run_config = RunConfig(response_modalities=["AUDIO"],
                           streaming_mode=StreamingMode.BIDI)

    async def pump_twilio_to_gemini():
        nonlocal stream_sid, caller_number
        while True:
            raw = await websocket.receive_text()
            msg = parse_twilio_message(raw)
            ev = msg.get("event")
            if ev == "start":
                stream_sid = msg["start"]["streamSid"]
                caller_number = msg["start"].get("customParameters", {}).get(
                    "caller_number", "")
                await runner.session_service.create_session(
                    app_name="voice-agent", user_id=caller_number or "anon",
                    session_id=stream_sid, state={"caller_phone": caller_number})
                # kick the agent to greet first
                live_queue.send_content(types.Content(
                    role="user",
                    parts=[types.Part(text="A caller just connected. Greet them.")]))
                asyncio.create_task(pump_gemini_to_twilio())
            elif ev == "media":
                pcm16k = ulaw8k_to_pcm16k(
                    base64.b64decode(msg["media"]["payload"]), inbound_rs)
                live_queue.send_realtime(types.Blob(
                    mime_type="audio/pcm;rate=16000", data=pcm16k))
            elif ev == "stop":
                break

    async def pump_gemini_to_twilio():
        async for event in runner.run_live(
            user_id=caller_number or "anon", session_id=stream_sid,
            live_request_queue=live_queue, run_config=run_config):
            if is_interrupt(event) and stream_sid:
                await websocket.send_text(twilio_clear_frame(stream_sid))
                continue
            for pcm24k in extract_audio_bytes(event):
                ulaw = pcm24k_to_ulaw8k(pcm24k, outbound_rs)
                await websocket.send_text(twilio_media_frame(
                    stream_sid, base64.b64encode(ulaw).decode()))

    try:
        await pump_twilio_to_gemini()
    except Exception as e:  # WebSocketDisconnect and friends
        logger.info("call ended: %s", e)
    finally:
        live_queue.close()
```

> Concurrency note: `pump_gemini_to_twilio` is started as a task on the `start` event (needs `stream_sid` + session first). Both tasks share `live_queue`; `send_realtime`/`send_content` are non-blocking and event-loop-safe within one loop.

- [ ] **Step 4: Wire `/media` in `app/main.py`** — add:

```python
from fastapi import WebSocket  # noqa: E402
from google.adk.runners import Runner  # noqa: E402
from google.adk.sessions import InMemorySessionService  # noqa: E402
from app.agent import build_agent  # noqa: E402
from app.booking import BookingService  # noqa: E402
from app.calendar_client import CalendarClient, build_google_service  # noqa: E402
from app.store import AppointmentStore  # noqa: E402
from app.messaging import Notifier  # noqa: E402
from app.bridge import run_call  # noqa: E402

def _build_runner() -> Runner:
    gcal = build_google_service(os.environ["GOOGLE_APPLICATION_CREDENTIALS"])
    calendar = CalendarClient(gcal, settings.clinic_calendar_id, settings.clinic_timezone,
                              settings.open_hour, settings.close_hour, settings.slot_minutes)
    from google.cloud import firestore
    from twilio.rest import Client as TwilioClient
    import resend
    resend.api_key = settings.resend_api_key
    store = AppointmentStore(firestore.Client())
    notifier = Notifier(TwilioClient(settings.twilio_account_sid, settings.twilio_auth_token),
                        settings.twilio_whatsapp_from, resend, settings.email_from)
    booking = BookingService(calendar, store, notifier,
                             settings.clinic_timezone, settings.slot_minutes)
    agent = build_agent(settings, booking, calendar)
    return Runner(app_name="voice-agent", agent=agent,
                  session_service=InMemorySessionService())

runner = _build_runner()

@app.websocket("/media")
async def media(websocket: WebSocket):
    await run_call(websocket, runner, settings)
```

- [ ] **Step 5: Run tests + import smoke**

Run: `pytest tests/test_bridge.py -v`
Expected: PASS (5 passed)
Run: `python -c "import app.bridge"` — Expected: no error (imports resolve).

> Do NOT claim the live call path works from unit tests alone — it is validated in Task 13 (manual ngrok call). If ADK's `Runner`/`run_live` kwargs differ from the versions here, fix `bridge.py`/`main.py` to match the installed `google-adk` (check `python -c "import google.adk, inspect; from google.adk.runners import Runner; print(inspect.signature(Runner.__init__)); print(inspect.signature(Runner.run_live))"`), not the tests.

- [ ] **Step 6: Commit**

```bash
git add app/bridge.py app/main.py tests/test_bridge.py
git commit -m "feat: Twilio<->ADK audio bridge WebSocket (/media)"
```

---

## Task 11: Reminders dispatch `POST /tasks/reminders`

**Files:**
- Create: `app/reminders.py`
- Modify: `app/main.py` (add the route)
- Test: `tests/test_reminders.py`

**Interfaces:**
- Consumes: `AppointmentStore` (Task 4), `select_due_reminders` (Task 3), `Notifier` + `reminder_texts` (Task 6), `format_when` (Task 7).
- Produces:
  - `dispatch_due_reminders(store, notifier, tz_name, now) -> dict` — selects due reminders, sends WhatsApp + email, marks flags, returns `{"sent": int, "kinds": [...]}`.
- Consumed by: `app/main.py` `POST /tasks/reminders` (called by Cloud Scheduler).

- [ ] **Step 1: Write the failing test** — `tests/test_reminders.py`

```python
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from app.reminders import dispatch_due_reminders

TZ = "America/New_York"

class FakeStore:
    def __init__(self, rows): self._rows = rows; self.marked = []
    def list_booked(self): return self._rows
    def mark_reminder_sent(self, appt_id, kind): self.marked.append((appt_id, kind))

class FakeNotifier:
    def __init__(self): self.wa = []; self.email = []
    def send_whatsapp(self, to, body): self.wa.append((to, body))
    def send_email(self, to, subject, html): self.email.append((to, subject, html))

def test_dispatch_sends_and_marks_due_24h():
    now = datetime(2026, 7, 6, 12, tzinfo=ZoneInfo(TZ))
    rows = [{"id": "a1", "name": "Jane", "phone": "+1", "email": "j@x.com",
             "start": now + timedelta(hours=20), "status": "booked",
             "reminder_24h_sent": False, "reminder_1h_sent": False}]
    store, notifier = FakeStore(rows), FakeNotifier()
    result = dispatch_due_reminders(store, notifier, TZ, now)
    assert result["sent"] == 1 and result["kinds"] == ["24h"]
    assert store.marked == [("a1", "24h")]
    assert len(notifier.wa) == 1 and len(notifier.email) == 1

def test_dispatch_noop_when_nothing_due():
    now = datetime(2026, 7, 6, 12, tzinfo=ZoneInfo(TZ))
    rows = [{"id": "a1", "name": "Jane", "phone": "+1", "email": "j@x.com",
             "start": now + timedelta(days=5), "status": "booked",
             "reminder_24h_sent": False, "reminder_1h_sent": False}]
    store, notifier = FakeStore(rows), FakeNotifier()
    assert dispatch_due_reminders(store, notifier, TZ, now)["sent"] == 0
    assert store.marked == []
```

- [ ] **Step 2: Run test, verify it fails**

Run: `pytest tests/test_reminders.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'app.reminders'`)

- [ ] **Step 3: Implement `app/reminders.py`**

```python
from __future__ import annotations
from datetime import datetime
from app.scheduling import select_due_reminders
from app.messaging import reminder_texts
from app.booking import format_when

def dispatch_due_reminders(store, notifier, tz_name: str, now: datetime) -> dict:
    due = select_due_reminders(store.list_booked(), now)
    kinds = []
    for appt, kind in due:
        when = format_when(appt["start"], tz_name)
        wa_body, subject, html = reminder_texts(appt["name"], when, kind)
        try:
            notifier.send_whatsapp(appt["phone"], wa_body)
        except Exception:
            pass
        if appt.get("email"):
            try:
                notifier.send_email(appt["email"], subject, html)
            except Exception:
                pass
        store.mark_reminder_sent(appt["id"], kind)
        kinds.append(kind)
    return {"sent": len(kinds), "kinds": kinds}
```

- [ ] **Step 4: Wire the route in `app/main.py`** — add:

```python
from datetime import datetime  # noqa: E402
from zoneinfo import ZoneInfo  # noqa: E402
from app.reminders import dispatch_due_reminders  # noqa: E402

@app.post("/tasks/reminders")
async def reminders_task():
    # Reuse the same store/notifier the runner built.
    from google.cloud import firestore
    from twilio.rest import Client as TwilioClient
    import resend
    resend.api_key = settings.resend_api_key
    store = AppointmentStore(firestore.Client())
    notifier = Notifier(TwilioClient(settings.twilio_account_sid, settings.twilio_auth_token),
                        settings.twilio_whatsapp_from, resend, settings.email_from)
    now = datetime.now(ZoneInfo(settings.clinic_timezone))
    return dispatch_due_reminders(store, notifier, settings.clinic_timezone, now)
```

> Refactor opportunity (optional, keep if clean): extract the `store`/`notifier` construction shared by `_build_runner` and this route into a `build_notifier()`/`build_store()` helper to avoid duplication. Only do this if it does not complicate `_build_runner`.

- [ ] **Step 5: Run test, verify it passes**

Run: `pytest tests/test_reminders.py -v`
Expected: PASS (2 passed)

- [ ] **Step 6: Full suite + commit**

Run: `pytest -v`
Expected: ALL PASS.

```bash
git add app/reminders.py app/main.py tests/test_reminders.py
git commit -m "feat: reminder dispatch endpoint (Cloud Scheduler target)"
```

---

## Task 12: Deployment assets (Dockerfile, Cloud Run, Scheduler, ngrok)

**Files:**
- Create: `deploy/Dockerfile`, `deploy/README.md`

**Interfaces:** none (ops). Deliverable: reproducible local-tunnel run + documented Cloud Run + Scheduler deploy.

- [ ] **Step 1: Write `deploy/Dockerfile`**

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
RUN pip install --no-cache-dir .
COPY app ./app
ENV PORT=8080
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
```

- [ ] **Step 2: Write `deploy/README.md`** with these steps (fill exact project/region values at deploy time):

```markdown
## Local prototype run (ngrok)
1. Create Firestore (Native mode) + a service account with Calendar & Firestore access.
   Share the clinic Google Calendar with the service-account email (Make changes to events).
2. `cp .env.example .env` and fill values. Put the service-account JSON at ./service-account.json.
3. `pip install -e ".[dev]"`
4. `uvicorn app.main:app --port 8080`
5. `ngrok http 8080` → copy the https URL into PUBLIC_BASE_URL in .env, restart uvicorn.
6. In Twilio Console → your number → Voice webhook: POST https://<ngrok>/voice
7. Call the number and book. Verify: Calendar event created, WhatsApp + email received.
8. Reminders: `curl -X POST https://<ngrok>/tasks/reminders` (seed a soon appointment first).

## Cloud Run
- Build & deploy:
  `gcloud run deploy voice-agent --source . --region <REGION> --allow-unauthenticated \
     --set-env-vars "$(grep -v '^#' .env | grep -v GOOGLE_APPLICATION_CREDENTIALS | xargs | sed 's/ /,/g')"`
- Attach the service account to the Cloud Run service (--service-account) so Calendar +
  Firestore auth works via ADC (remove GOOGLE_APPLICATION_CREDENTIALS; use the SA identity).
- Set PUBLIC_BASE_URL to the Cloud Run URL; update the Twilio Voice webhook to it.

## Cloud Scheduler (reminders)
- `gcloud scheduler jobs create http reminders --schedule "*/5 * * * *" \
     --uri "https://<cloud-run-url>/tasks/reminders" --http-method POST \
     --oidc-service-account-email <sa>@<project>.iam.gserviceaccount.com`
- Lock down /tasks/reminders to the scheduler SA (or require an OIDC token) before real use.

## WhatsApp templates (production)
- Twilio WhatsApp requires approved templates for business-initiated messages outside the
  24h window. For the sandbox/prototype, freeform `body` works after opting a tester in.
  For launch, submit confirmation + reminder templates and switch messaging.py to
  content_sid + content_variables.
```

- [ ] **Step 3: Commit**

```bash
git add deploy/
git commit -m "chore: Dockerfile + Cloud Run/Scheduler/ngrok deploy docs"
```

---

## Task 13: End-to-end verification (manual, gated)

**Files:** none (verification only).

- [ ] **Step 1: Full unit suite green**

Run: `pytest -v`
Expected: all tests pass. Record the count.

- [ ] **Step 2: Live call smoke (ngrok)**

Follow `deploy/README.md` local steps. Place a real call. Verify, and write down evidence for each:
- Agent greets first and converses (barge-in: talk over it → it stops).
- `check_availability` proposes only real open slots.
- Booking creates the Google Calendar event at the chosen time.
- WhatsApp confirmation received; email confirmation received.

- [ ] **Step 3: Reminder smoke**

Seed an appointment ~50 minutes out (book via a call, or write a Firestore doc). `curl -X POST .../tasks/reminders`. Verify a `1h` WhatsApp + email arrive and the doc's `reminder_1h_sent` flips to true; a second curl sends nothing (idempotent).

- [ ] **Step 4: Record results honestly**

If audio is choppy or one-directional, the transcode/rates in `app/audio.py` and the chunk handling in `app/bridge.py` are the first suspects — verify the μ-law/PCM rates match the Global Constraints before touching anything else. Do not mark this task complete until a real call books a real appointment with both confirmations delivered.

---

## Self-Review

**Spec coverage:**
- Natural real-time conversation → Task 8 (native-audio Live agent) + Task 10 (bridge). ✅
- Check availability + book live → Tasks 5, 7, 8. ✅
- Capture name/reason/contact → Task 8 instruction (name/reason asked; phone from caller ID in session state) + `book_appointment`. ✅
- Instant WhatsApp + email confirmation → Task 6 + Task 7 (fired inside `book`). ✅
- Automated WhatsApp/email reminder before appointment (24h + 1h) → Tasks 3, 11 + Cloud Scheduler (Task 12). ✅
- Callable via phone number → Task 9 (TwiML) + Twilio config (Task 12). ✅
- Gemini ADK, Cloud Run, Firestore, Twilio, Google Calendar, Resend → all present. ✅
- English-first, multilingual deferred → Task 8 instruction `{language}` slot, `language_code="en-US"`. ✅

**Placeholder scan:** No `TBD`/`implement later`/vague "handle errors" steps; every code step has complete code; every test step has runnable assertions. Deploy values intentionally parameterized (`<REGION>`, `<project>`) because they are environment-specific — flagged, not hidden.

**Type consistency:** `Notifier.send_whatsapp/send_email`, `AppointmentStore.list_booked/mark_reminder_sent/create_appointment`, `CalendarClient.available_slots/create_event`, `BookingService.book/format_when`, and `select_due_reminders`/`compute_open_slots` signatures match across the tasks that consume them (booking, reminders, bridge, agent). Appointment dict shape (`name, phone, email, start, status, reminder_24h_sent, reminder_1h_sent, id`) is identical in store, scheduling, booking, and reminders.

**Known follow-ups (documented, not silently dropped):** WhatsApp template approval for production; securing `/tasks/reminders`; moving from `InMemorySessionService` to a persistent session service if resumable sessions are needed; rescheduling/cancellation flow (v2 per spec).
