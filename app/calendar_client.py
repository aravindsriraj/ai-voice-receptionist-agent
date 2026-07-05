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


def build_google_service(credentials_path: str):
    """Build a Calendar v3 service from a service-account JSON file.
    The clinic calendar must be shared with the service-account email (editor access)."""
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    creds = service_account.Credentials.from_service_account_file(
        credentials_path, scopes=["https://www.googleapis.com/auth/calendar"])
    return build("calendar", "v3", credentials=creds, cache_discovery=False)
