from datetime import datetime
from zoneinfo import ZoneInfo
from types import SimpleNamespace
from app.agent import build_agent, INSTRUCTION

TZ = "America/New_York"


class FakeCalendar:
    def available_slots(self, date, now):
        return [datetime(2026, 7, 8, 10, tzinfo=ZoneInfo(TZ)),
                datetime(2026, 7, 8, 10, 30, tzinfo=ZoneInfo(TZ))]


class FakeBooking:
    def __init__(self): self.calls = []
    def book(self, name, reason, phone, email, start, now):
        self.calls.append((name, reason, phone, email, start))
        return {"ok": True, "appointment_id": "a1", "message": "Booked."}


def _settings():
    return SimpleNamespace(agent_model="m", agent_voice="Aoede",
                           clinic_timezone=TZ, slot_minutes=30)


def test_instruction_is_english_and_has_persona():
    text = INSTRUCTION.format(language="English")
    assert "English" in text
    assert "receptionist" in text.lower()


def test_agent_registers_two_tools():
    agent = build_agent(_settings(), FakeBooking(), FakeCalendar())
    tool_names = {getattr(t, "__name__", getattr(t, "name", "")) for t in agent.tools}
    assert "check_availability" in tool_names
    assert "book_appointment" in tool_names


def test_book_tool_reads_caller_phone_from_state():
    booking = FakeBooking()
    agent = build_agent(_settings(), booking, FakeCalendar())
    book_tool = next(t for t in agent.tools
                     if getattr(t, "__name__", "") == "book_appointment")
    ctx = SimpleNamespace(state={"caller_phone": "+15551234567"})
    result = book_tool(name="Jane", reason="checkup",
                       start_iso="2026-07-08T10:00:00-04:00",
                       email="j@x.com", tool_context=ctx)
    assert result["ok"] is True
    assert booking.calls[0][2] == "+15551234567"   # phone came from state
