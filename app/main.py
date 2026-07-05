from __future__ import annotations
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")  # BEFORE reading env

from fastapi import FastAPI, Request, Response, WebSocket  # noqa: E402
from app.config import load_settings            # noqa: E402
from app.twiml import build_connect_stream_twiml  # noqa: E402
from app.bridge import run_call                 # noqa: E402

settings = load_settings(os.environ)
app = FastAPI()

# Runtime (ADK runner + session service) is built lazily on first use so the module
# stays importable without live credentials (CI, Docker build, tests).
_runtime = None


def _build_runtime():
    """Construct the ADK runner + session service and their external clients."""
    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService
    from google.cloud import firestore
    from twilio.rest import Client as TwilioClient
    import resend
    from app.agent import build_agent
    from app.booking import BookingService
    from app.calendar_client import CalendarClient, build_google_service
    from app.store import AppointmentStore
    from app.messaging import Notifier

    resend.api_key = settings.resend_api_key
    gcal = build_google_service(os.environ["GOOGLE_APPLICATION_CREDENTIALS"])
    calendar = CalendarClient(gcal, settings.clinic_calendar_id, settings.clinic_timezone,
                              settings.open_hour, settings.close_hour, settings.slot_minutes)
    store = AppointmentStore(firestore.Client())
    notifier = Notifier(TwilioClient(settings.twilio_account_sid, settings.twilio_auth_token),
                        settings.twilio_whatsapp_from, resend, settings.email_from)
    booking = BookingService(calendar, store, notifier,
                             settings.clinic_timezone, settings.slot_minutes)
    agent = build_agent(settings, booking, calendar)
    session_service = InMemorySessionService()
    runner = Runner(app_name="voice-agent", agent=agent, session_service=session_service)
    return runner, session_service


def get_runtime():
    global _runtime
    if _runtime is None:
        _runtime = _build_runtime()
    return _runtime


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


@app.websocket("/media")
async def media(websocket: WebSocket):
    runner, session_service = get_runtime()
    await run_call(websocket, runner, session_service, settings)
