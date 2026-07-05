from __future__ import annotations
from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class Settings:
    agent_model: str
    agent_voice: str
    clinic_calendar_id: str
    clinic_timezone: str
    open_hour: int
    close_hour: int
    slot_minutes: int
    twilio_account_sid: str
    twilio_auth_token: str
    twilio_whatsapp_from: str
    resend_api_key: str
    email_from: str
    public_base_url: str


def load_settings(env: Mapping[str, str]) -> Settings:
    return Settings(
        agent_model=env["AGENT_MODEL"],
        agent_voice=env["AGENT_VOICE"],
        clinic_calendar_id=env["CLINIC_CALENDAR_ID"],
        clinic_timezone=env["CLINIC_TIMEZONE"],
        open_hour=int(env["OPEN_HOUR"]),
        close_hour=int(env["CLOSE_HOUR"]),
        slot_minutes=int(env["SLOT_MINUTES"]),
        twilio_account_sid=env["TWILIO_ACCOUNT_SID"],
        twilio_auth_token=env["TWILIO_AUTH_TOKEN"],
        twilio_whatsapp_from=env["TWILIO_WHATSAPP_FROM"],
        resend_api_key=env["RESEND_API_KEY"],
        email_from=env["EMAIL_FROM"],
        public_base_url=env["PUBLIC_BASE_URL"],
    )
