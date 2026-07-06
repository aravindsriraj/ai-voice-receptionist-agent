from __future__ import annotations
from datetime import date as Date, datetime, timedelta
from zoneinfo import ZoneInfo
from app.scheduling import compute_open_slots

_SCOPES = ["https://www.googleapis.com/auth/calendar"]


class CalendarClient:
    """Calendar access that builds a FRESH service (fresh HTTP connection) per call.

    google-api-python-client uses httplib2, which is not thread-safe and reuses a single
    socket. A long-lived service on a warm instance gets its idle socket closed by Google
    and then fails with BrokenPipeError on reuse. `service_factory()` returns a fresh
    service each call to avoid that (credentials/token are cached inside the factory).
    """

    def __init__(self, service_factory, calendar_id, tz_name, open_hour, close_hour, slot_minutes):
        self._service_factory = service_factory
        self._cal = calendar_id
        self._tz = ZoneInfo(tz_name)
        self._tz_name = tz_name
        self._open_hour = open_hour
        self._close_hour = close_hour
        self._slot_minutes = slot_minutes

    def available_slots(self, date: Date, now: datetime):
        day_start = datetime(date.year, date.month, date.day, 0, 0, tzinfo=self._tz)
        day_end = day_start + timedelta(days=1)
        resp = self._service_factory().freebusy().query(body={
            "timeMin": day_start.isoformat(),
            "timeMax": day_end.isoformat(),
            "items": [{"id": self._cal}],
        }).execute(num_retries=2)
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
        created = self._service_factory().events().insert(
            calendarId=self._cal, body=body).execute(num_retries=2)
        return created["id"]


def _load_credentials(credentials_path: str | None):
    if credentials_path:
        from google.oauth2 import service_account
        return service_account.Credentials.from_service_account_file(
            credentials_path, scopes=_SCOPES)
    import google.auth
    creds, _ = google.auth.default(scopes=_SCOPES)
    return creds


def calendar_service_factory(credentials_path: str | None = None):
    """Return a callable that builds a fresh Calendar service on each call, reusing a
    single cached Credentials object (so the OAuth token is cached, but the HTTP socket
    is always fresh — avoiding httplib2 stale-connection BrokenPipeError)."""
    from googleapiclient.discovery import build
    creds = _load_credentials(credentials_path)

    def factory():
        return build("calendar", "v3", credentials=creds, cache_discovery=False)

    return factory


def build_google_service(credentials_path: str | None = None):
    """Build a single Calendar v3 service (used by the factory and by one-off scripts)."""
    from googleapiclient.discovery import build
    return build("calendar", "v3", credentials=_load_credentials(credentials_path),
                 cache_discovery=False)
