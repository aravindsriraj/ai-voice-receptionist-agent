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
