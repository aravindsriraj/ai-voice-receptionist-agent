from __future__ import annotations
from datetime import datetime
from zoneinfo import ZoneInfo
from app.messaging import confirmation_texts


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
        when = format_when(start, self._tz_name)
        wa_body, subject, html = confirmation_texts(name, when)
        try:
            self.notifier.send_whatsapp(phone, wa_body)
        except Exception:
            pass  # prototype: don't fail the booking if a channel errors
        if email:
            try:
                self.notifier.send_email(email, subject, html)
            except Exception:
                pass
        return {"ok": True, "appointment_id": appt_id,
                "message": f"Booked for {when}. A confirmation is on its way."}
