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
