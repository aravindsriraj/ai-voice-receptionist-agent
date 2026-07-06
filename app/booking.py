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
    def __init__(self, calendar, store, notifier, tz_name: str, slot_minutes: int,
                 email_enabled: bool = True, whatsapp_enabled: bool = True,
                 background=None):
        self.calendar = calendar
        self.store = store
        self.notifier = notifier
        self._tz_name = tz_name
        self._slot_minutes = slot_minutes
        self._email_enabled = email_enabled
        self._whatsapp_enabled = whatsapp_enabled
        # `background(fn)` runs fn off the booking's critical path so the agent can
        # confirm immediately. Default runs inline (used by tests); production passes a
        # thread-pool submit so WhatsApp/email don't block the agent's response.
        self._background = background or (lambda fn: fn())

    def book(self, name, reason, phone, email, start: datetime, now: datetime) -> dict:
        if start <= now:
            return {"ok": False, "appointment_id": None,
                    "message": "That time is in the past. Please choose a future time."}
        # Critical path: create the real booking (fast) so the confirmation is truthful.
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
        # Slow, fire-and-forget confirmations run in the background.
        self._background(lambda: self._send_confirmations(name, phone, email, when))
        return {"ok": True, "appointment_id": appt_id,
                "message": f"Booked for {when}. A confirmation is on its way."}

    def _send_confirmations(self, name, phone, email, when) -> None:
        wa_body, subject, html = confirmation_texts(name, when)
        # Email is the primary channel (reaches any registered user). WhatsApp is
        # optional and only works with a joined sandbox number or a real WABA sender.
        if self._whatsapp_enabled and phone:
            try:
                self.notifier.send_whatsapp(phone, wa_body)
                logger.info("whatsapp confirmation sent to %s", phone)
            except Exception:
                logger.exception("whatsapp confirmation FAILED for %s", phone)
        if self._email_enabled and email:
            try:
                self.notifier.send_email(email, subject, html)
                logger.info("email confirmation sent to %s", email)
            except Exception:
                logger.exception("email confirmation FAILED for %s", email)
        elif not self._email_enabled:
            logger.info("email disabled; skipping email confirmation")
        else:
            logger.info("no email captured; skipping email confirmation")
