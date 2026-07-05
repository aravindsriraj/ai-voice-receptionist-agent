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
