from __future__ import annotations
from datetime import datetime
from zoneinfo import ZoneInfo
from google.adk.agents import Agent
from google.adk.models.google_llm import Gemini
from google.genai import types

INSTRUCTION = """You are a warm, professional voice receptionist for a medical clinic.
You are speaking on a live phone call. Converse naturally in {language}.

Your goals, in order:
1. Greet the caller (by name if their name was provided to you) and ask how you can help.
2. Understand what they need (usually booking an appointment).
3. Use `check_availability` to find open times before proposing any slot. Offer at
   most 2-3 options at a time. Never invent availability.
4. Confirm the reason for the visit. Never ask for the caller's phone number or email —
   their contact details are already on file; if their name was not provided, ask only
   for the name.
5. Once you have the chosen time AND the reason, you MUST call the `book_appointment`
   tool. This tool is the ONLY thing that actually books the appointment and sends the
   confirmation — describing a booking does not create one. NEVER tell the caller their
   appointment is booked, confirmed, or that a confirmation is coming unless you have
   already called `book_appointment` in this turn and it returned a success result. If
   you have not called the tool, nothing has been booked. Only after it returns success,
   briefly confirm the day and time.
6. When the caller has nothing else and the conversation is finished (for example they
   say goodbye or "that's all"), give a short, warm farewell and then call `end_call`
   to hang up. Do not call `end_call` before saying goodbye, and never before you have
   booked an appointment the caller asked for.

Style: concise, friendly, one question at a time. Spell dates and times out loud
clearly. Actions happen only through tools — never claim you did something you did not
do with a tool. If a tool reports an error, apologize briefly and offer an alternative.
Do not give medical advice."""


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

    def book_appointment(reason: str, start_iso: str, tool_context,
                         name: str = "", email: str = "") -> dict:
        """Book an appointment. start_iso must be one of the iso_slots from
        check_availability. Caller name/phone/email come from session state (on file);
        name/email params are optional overrides."""
        st = tool_context.state
        name = name or st.get("caller_name", "")
        email = email or st.get("caller_email", "")
        phone = st.get("caller_phone", "")
        start = datetime.fromisoformat(start_iso)
        now = _now_tz(tz_name)
        return booking_service.book(name=name, reason=reason, phone=phone,
                                    email=email, start=start, now=now)

    def end_call(tool_context) -> dict:
        """End the call once the conversation is complete. Only call this right after
        saying a brief goodbye."""
        return {"status": "ended"}

    llm = Gemini(
        model=settings.agent_model,
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(
                    voice_name=settings.agent_voice)),
            language_code="en-US",
        ),
    )
    return Agent(
        name="clinic_receptionist",
        model=llm,
        instruction=INSTRUCTION.format(language="English"),
        tools=[check_availability, book_appointment, end_call],
    )
