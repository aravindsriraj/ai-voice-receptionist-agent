from __future__ import annotations
from datetime import datetime
from zoneinfo import ZoneInfo
from google.adk.agents import Agent
from google.adk.models.google_llm import Gemini
from google.genai import types

INSTRUCTION = """You are a warm, professional voice receptionist for a medical clinic.
You are speaking on a live phone call. Converse naturally in {language}.

Your goals, in order:
1. Greet the caller and ask how you can help.
2. Understand what they need (usually booking an appointment).
3. Use `check_availability` to find open times before proposing any slot. Offer at
   most 2-3 options at a time. Never invent availability.
4. Collect the caller's full name and the reason for the visit. Their phone number is
   already known from caller ID — confirm it by reading it back, do not ask them to
   recite it.
5. When they choose a time, call `book_appointment`. Then tell them it is booked and
   a confirmation is on the way.

Style: concise, friendly, one question at a time. Spell dates and times out loud
clearly. If a tool reports an error, apologize briefly and offer an alternative.
Do not give medical advice."""

_EMAIL_ON = ("Also ask the caller for an email address and pass it to `book_appointment` "
             "so they get an email confirmation too.")
_EMAIL_OFF = ("Do NOT ask the caller for an email address — confirmations are sent by "
              "WhatsApp only. Call `book_appointment` without an email.")


def _now_tz(tz_name: str) -> datetime:
    return datetime.now(ZoneInfo(tz_name))


def build_agent(settings, booking_service, calendar_client) -> Agent:
    tz_name = settings.clinic_timezone

    def check_availability(date_iso: str, tool_context) -> dict:
        """Return open appointment slots for a given date (YYYY-MM-DD)."""
        date = datetime.fromisoformat(date_iso).date()
        now = _now_tz(tz_name)
        slots = calendar_client.available_slots(date, now)
        return {"date": date_iso,
                "slots": [s.strftime("%-I:%M %p") for s in slots],
                "iso_slots": [s.isoformat() for s in slots]}

    def book_appointment(name: str, reason: str, start_iso: str,
                         tool_context, email: str = "") -> dict:
        """Book an appointment. start_iso must be one of the iso_slots returned by
        check_availability. Phone is taken from caller ID (session state). email is
        optional."""
        phone = tool_context.state.get("caller_phone", "")
        start = datetime.fromisoformat(start_iso)
        now = _now_tz(tz_name)
        return booking_service.book(name=name, reason=reason, phone=phone,
                                    email=email, start=start, now=now)

    llm = Gemini(
        model=settings.agent_model,
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(
                    voice_name=settings.agent_voice)),
            language_code="en-US",
        ),
    )
    email_policy = _EMAIL_ON if getattr(settings, "email_enabled", True) else _EMAIL_OFF
    instruction = INSTRUCTION.format(language="English") + "\n\n" + email_policy
    return Agent(
        name="clinic_receptionist",
        model=llm,
        instruction=instruction,
        tools=[check_availability, book_appointment],
    )
