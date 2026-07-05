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
