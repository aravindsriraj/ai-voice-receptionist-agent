from __future__ import annotations
import logging
from datetime import datetime
from app.scheduling import select_due_reminders
from app.messaging import reminder_texts
from app.booking import format_when

logger = logging.getLogger(__name__)


def dispatch_due_reminders(store, notifier, tz_name: str, now: datetime,
                           email_enabled: bool = True) -> dict:
    due = select_due_reminders(store.list_booked(), now)
    kinds = []
    for appt, kind in due:
        when = format_when(appt["start"], tz_name)
        wa_body, subject, html = reminder_texts(appt["name"], when, kind)
        try:
            notifier.send_whatsapp(appt["phone"], wa_body)
            logger.info("whatsapp %s reminder sent to %s", kind, appt["phone"])
        except Exception:
            logger.exception("whatsapp %s reminder FAILED for %s", kind, appt["phone"])
        if email_enabled and appt.get("email"):
            try:
                notifier.send_email(appt["email"], subject, html)
                logger.info("email %s reminder sent to %s", kind, appt["email"])
            except Exception:
                logger.exception("email %s reminder FAILED for %s", kind, appt["email"])
        store.mark_reminder_sent(appt["id"], kind)
        kinds.append(kind)
    return {"sent": len(kinds), "kinds": kinds}
