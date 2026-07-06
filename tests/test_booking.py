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
    # a calendar event was created and its summary names the caller
    assert svc.calendar.created
    assert "Jane" in svc.calendar.created[0][0]
    assert svc.store.rows[0]["calendar_event_id"] == "evt_1"
    assert svc.store.rows[0]["reminder_24h_sent"] is False
    assert len(svc.notifier.wa) == 1 and len(svc.notifier.email) == 1


def test_book_defers_confirmations_to_background():
    svc = _svc()
    jobs = []
    svc._background = lambda fn: jobs.append(fn)   # defer instead of running inline
    start = datetime(2026, 7, 8, 10, tzinfo=ZoneInfo(TZ))
    now = datetime(2026, 7, 6, 9, tzinfo=ZoneInfo(TZ))
    res = svc.book("Jane", "checkup", "+15551234567", "j@x.com", start, now)
    # booking (calendar + persist) happened synchronously and returned ok...
    assert res["ok"] is True
    assert svc.calendar.created and svc.store.rows
    # ...but confirmations have NOT been sent yet — they're queued for the background
    assert svc.notifier.wa == [] and svc.notifier.email == []
    # running the backgrounded job sends them
    for job in jobs:
        job()
    assert len(svc.notifier.wa) == 1 and len(svc.notifier.email) == 1


def test_whatsapp_disabled_still_emails():
    # email is the primary channel; WhatsApp off must not affect it
    svc = BookingService(FakeCalendar(), FakeStore(), FakeNotifier(), TZ, 30,
                         email_enabled=True, whatsapp_enabled=False)
    start = datetime(2026, 7, 8, 10, tzinfo=ZoneInfo(TZ))
    now = datetime(2026, 7, 6, 9, tzinfo=ZoneInfo(TZ))
    svc.book("Jane", "checkup", "+15551234567", "j@x.com", start, now)
    assert svc.notifier.wa == []                 # WhatsApp skipped
    assert len(svc.notifier.email) == 1          # email still sent


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
