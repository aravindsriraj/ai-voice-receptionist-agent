from __future__ import annotations
import os
import uuid
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")  # BEFORE reading env

from fastapi import FastAPI, Request, Response, WebSocket  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from starlette.middleware.sessions import SessionMiddleware  # noqa: E402
from app.config import load_settings            # noqa: E402
from app.twiml import build_connect_stream_twiml  # noqa: E402
from app.bridge import run_call, APP_NAME       # noqa: E402
from app.web import make_router                 # noqa: E402
from app.browser_bridge import run_browser_call  # noqa: E402

settings = load_settings(os.environ)

# Ensure our app.* INFO logs (tool calls, transcripts, confirmation results) reach
# stdout even when running under uvicorn, which only configures its own loggers.
import logging  # noqa: E402
_applog = logging.getLogger("app")
if not _applog.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(levelname)s:%(name)s: %(message)s"))
    _applog.addHandler(_h)
    _applog.setLevel(logging.INFO)
    _applog.propagate = False

app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key=settings.session_secret,
                   https_only=True, same_site="lax")
_STATIC = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=str(_STATIC)), name="static")

# Runtime (ADK runner + session service) is built lazily on first use so the module
# stays importable without live credentials (CI, Docker build, tests).
_runtime = None
_user_store = None


def _build_store():
    from google.cloud import firestore
    from app.store import AppointmentStore
    return AppointmentStore(firestore.Client())


def get_user_store():
    global _user_store
    if _user_store is None:
        from google.cloud import firestore
        from app.auth import UserStore
        _user_store = UserStore(firestore.Client())
    return _user_store


def get_twilio():
    from twilio.rest import Client as TwilioClient
    return TwilioClient(settings.twilio_account_sid, settings.twilio_auth_token)


def _build_notifier():
    from twilio.rest import Client as TwilioClient
    import resend
    from app.messaging import Notifier
    resend.api_key = settings.resend_api_key
    return Notifier(TwilioClient(settings.twilio_account_sid, settings.twilio_auth_token),
                    settings.twilio_whatsapp_from, resend, settings.email_from)


def _build_runtime():
    """Construct the ADK runner + session service and their external clients."""
    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService
    from app.agent import build_agent
    from app.booking import BookingService
    from app.calendar_client import CalendarClient, build_google_service

    gcal = build_google_service(os.environ["GOOGLE_APPLICATION_CREDENTIALS"])
    calendar = CalendarClient(gcal, settings.clinic_calendar_id, settings.clinic_timezone,
                              settings.open_hour, settings.close_hour, settings.slot_minutes)
    booking = BookingService(calendar, _build_store(), _build_notifier(),
                             settings.clinic_timezone, settings.slot_minutes,
                             email_enabled=settings.email_enabled)
    agent = build_agent(settings, booking, calendar)
    session_service = InMemorySessionService()
    runner = Runner(app_name=APP_NAME, agent=agent, session_service=session_service)
    return runner, session_service


def get_runtime():
    global _runtime
    if _runtime is None:
        _runtime = _build_runtime()
    return _runtime


app.include_router(make_router(get_user_store, get_twilio, settings, str(_STATIC)))


@app.get("/healthz")
async def healthz():
    return {"ok": True}


def select_caller(direction: str, from_: str, to: str) -> str:
    """The human party's number. Twilio-initiated (outbound) calls put the human in
    'To'; inbound calls put them in 'From'."""
    return (to if (direction or "").startswith("outbound") else from_) or ""


@app.post("/voice")
async def voice(request: Request):
    form = await request.form()
    caller = select_caller(form.get("Direction", "inbound"),
                           form.get("From", ""), form.get("To", ""))
    ws_host = settings.public_base_url.replace("https://", "").replace("http://", "")
    ws_url = f"wss://{ws_host}/media"
    xml = build_connect_stream_twiml(ws_url, caller)
    return Response(content=xml, media_type="application/xml")


@app.websocket("/media")
async def media(websocket: WebSocket):
    runner, session_service = get_runtime()
    await run_call(websocket, runner, session_service, store=get_user_store())


@app.websocket("/ws/talk")
async def ws_talk(websocket: WebSocket):
    email = websocket.session.get("user_email")
    user = get_user_store().get(email) if email else None
    if not user:
        await websocket.close(code=1008)
        return
    runner, session_service = get_runtime()
    await run_browser_call(websocket, runner, session_service, user,
                           session_id=uuid.uuid4().hex)


@app.post("/tasks/reminders")
async def reminders_task():
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from app.reminders import dispatch_due_reminders
    now = datetime.now(ZoneInfo(settings.clinic_timezone))
    return dispatch_due_reminders(_build_store(), _build_notifier(),
                                  settings.clinic_timezone, now,
                                  email_enabled=settings.email_enabled)
