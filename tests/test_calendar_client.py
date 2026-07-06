from datetime import datetime
from zoneinfo import ZoneInfo
from app.calendar_client import CalendarClient

TZ = "America/New_York"


class _Exec:
    def __init__(self, result): self._r = result
    def execute(self, **kwargs): return self._r   # accepts num_retries=


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
    c = CalendarClient(lambda: svc, "cal@x", TZ, 9, 11, 30)
    now = datetime(2026, 7, 8, 8, tzinfo=ZoneInfo(TZ))
    slots = c.available_slots(now.date(), now)
    labels = [s.strftime("%H:%M") for s in slots]
    assert "09:00" not in labels and "09:30" in labels and "10:00" in labels


def test_create_event_returns_id_and_builds_body():
    svc = FakeService([])
    c = CalendarClient(lambda: svc, "cal@x", TZ, 9, 17, 30)
    start = datetime(2026, 7, 8, 10, tzinfo=ZoneInfo(TZ))
    eid = c.create_event("Checkup - Jane", "reason: checkup", start, 30)
    assert eid == "evt_123"
    cal_id, body = svc._ev.inserted
    assert cal_id == "cal@x"
    assert body["start"]["timeZone"] == TZ
    assert body["start"]["dateTime"].startswith("2026-07-08T10:00")
