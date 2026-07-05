from __future__ import annotations


def confirmation_texts(name: str, when_str: str):
    wa = (f"Hi {name}, your appointment is confirmed for {when_str}. "
          f"Reply here if you need to reschedule.")
    subject = "Your appointment is confirmed"
    html = (f"<p>Hi {name},</p><p>Your appointment is <b>confirmed</b> for "
            f"<b>{when_str}</b>.</p><p>See you then!</p>")
    return wa, subject, html


def reminder_texts(name: str, when_str: str, kind: str):
    lead = "tomorrow" if kind == "24h" else "in about an hour"
    wa = f"Hi {name}, a reminder: your appointment is {lead} — {when_str}."
    subject = "Appointment reminder"
    html = (f"<p>Hi {name},</p><p>This is a reminder that your appointment is "
            f"{lead}: <b>{when_str}</b>.</p>")
    return wa, subject, html


class Notifier:
    def __init__(self, twilio_client, whatsapp_from: str, resend_module, email_from: str):
        self._tw = twilio_client
        self._wa_from = whatsapp_from
        self._resend = resend_module
        self._email_from = email_from

    def send_whatsapp(self, to_phone: str, body: str) -> None:
        self._tw.messages.create(
            from_=self._wa_from,
            to=f"whatsapp:{to_phone}",
            body=body,
        )

    def send_email(self, to_email: str, subject: str, html: str) -> None:
        self._resend.Emails.send({
            "from": self._email_from,
            "to": to_email,
            "subject": subject,
            "html": html,
        })
