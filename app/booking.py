from __future__ import annotations
import logging
from datetime import datetime
from zoneinfo import ZoneInfo
from app.messaging import confirmation_texts

logger = logging.getLogger(__name__)


def format_when(start: datetime, tz_name: str) -> str:
    local = start.astimezone(ZoneInfo(tz_name))
    return local.strftime("%A, %b %-d at %-I:%M %p")


class BookingService:
    def __init__(self, calendar, store, notifier, tz_name: str, slot_minutes: int):
        self.calendar = calendar
        self.store = store
        self.notifier = notifier
        self._tz_name = tz_name
        self._slot_minutes = slot_minutes

    def book(self, name, reason, phone, email, start: datetime, now: datetime) -> dict:
        if start <= now:
            return {"ok": False, "appointment_id": None,
                    "message": "That time is in the past. Please choose a future time."}
        summary = f"Checkup - {name}" if not reason else f"{reason} - {name}"
        event_id = self.calendar.create_event(
            summary=summary,
            description=f"Booked by voice agent. Reason: {reason}. Phone: {phone}.",
            start=start, duration_minutes=self._slot_minutes)
        appt_id = self.store.create_appointment({
            "name": name, "reason": reason, "phone": phone, "email": email,
            "start": start, "timezone": self._tz_name, "calendar_event_id": event_id,
            "status": "booked", "reminder_24h_sent": False, "reminder_1h_sent": False,
        })
        logger.info("booked appointment %s: %s (%s) at %s, event=%s",
                    appt_id, name, phone, start.isoformat(), event_id)
        when = format_when(start, self._tz_name)
        wa_body, subject, html = confirmation_texts(name, when)
        try:
            self.notifier.send_whatsapp(phone, wa_body)
            logger.info("whatsapp confirmation sent to %s", phone)
        except Exception:
            # don't fail the booking if a channel errors, but make it visible
            logger.exception("whatsapp confirmation FAILED for %s", phone)
        if email:
            try:
                self.notifier.send_email(email, subject, html)
                logger.info("email confirmation sent to %s", email)
            except Exception:
                logger.exception("email confirmation FAILED for %s", email)
        else:
            logger.info("no email captured; skipping email confirmation")
        return {"ok": True, "appointment_id": appt_id,
                "message": f"Booked for {when}. A confirmation is on its way."}
