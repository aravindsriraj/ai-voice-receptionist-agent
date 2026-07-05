from app.config import load_settings

BASE_ENV = {
    "AGENT_MODEL": "m", "AGENT_VOICE": "Aoede",
    "CLINIC_CALENDAR_ID": "c", "CLINIC_TIMEZONE": "America/New_York",
    "OPEN_HOUR": "9", "CLOSE_HOUR": "17", "SLOT_MINUTES": "30",
    "TWILIO_ACCOUNT_SID": "AC1", "TWILIO_AUTH_TOKEN": "t",
    "TWILIO_WHATSAPP_FROM": "whatsapp:+1", "RESEND_API_KEY": "re_1",
    "EMAIL_FROM": "Clinic <a@b.com>", "PUBLIC_BASE_URL": "https://x",
}


def test_load_settings_parses_types():
    s = load_settings(BASE_ENV)
    assert s.open_hour == 9 and s.close_hour == 17 and s.slot_minutes == 30
    assert s.clinic_timezone == "America/New_York"


def test_load_settings_missing_key_raises():
    import pytest
    env = dict(BASE_ENV); del env["TWILIO_AUTH_TOKEN"]
    with pytest.raises(KeyError):
        load_settings(env)
