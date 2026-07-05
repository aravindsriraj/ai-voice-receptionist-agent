import audioop, base64, json
from types import SimpleNamespace
import pytest
from app.bridge import (run_call, parse_twilio_message, twilio_media_frame,
                        twilio_clear_frame, extract_audio_bytes, is_interrupt)


def test_parse_twilio_message():
    raw = json.dumps({"event": "media", "media": {"payload": "AAA="}})
    assert parse_twilio_message(raw)["event"] == "media"


def test_media_frame_shape():
    frame = json.loads(twilio_media_frame("SID1", "QUJD"))
    assert frame["event"] == "media"
    assert frame["streamSid"] == "SID1"
    assert frame["media"]["payload"] == "QUJD"


def test_clear_frame_shape():
    frame = json.loads(twilio_clear_frame("SID1"))
    assert frame == {"event": "clear", "streamSid": "SID1"}


def test_extract_audio_bytes_from_pcm_parts():
    part = SimpleNamespace(inline_data=SimpleNamespace(mime_type="audio/pcm;rate=24000",
                                                       data=b"\x01\x02"))
    non_audio = SimpleNamespace(inline_data=None, text="hi")
    event = SimpleNamespace(content=SimpleNamespace(parts=[part, non_audio]),
                            interrupted=False)
    assert extract_audio_bytes(event) == [b"\x01\x02"]


def test_is_interrupt():
    assert is_interrupt(SimpleNamespace(interrupted=True)) is True
    assert is_interrupt(SimpleNamespace(interrupted=False)) is False
    assert is_interrupt(SimpleNamespace()) is False


# ---- integration: run_call orchestration with fakes ---------------------------

class FakeWebSocket:
    def __init__(self, incoming):
        self._incoming = list(incoming)
        self.sent = []
        self.accepted = False

    async def accept(self):
        self.accepted = True

    async def receive_text(self):
        if not self._incoming:
            raise AssertionError("run_call read past the provided messages")
        return self._incoming.pop(0)

    async def send_text(self, text):
        self.sent.append(text)


class FakeSessionService:
    def __init__(self):
        self.created = []

    async def create_session(self, *, app_name, user_id, session_id, state):
        self.created.append({"app_name": app_name, "user_id": user_id,
                             "session_id": session_id, "state": state})


class FakeStore:
    def __init__(self, user=None): self._user = user
    def find_by_phone(self, phone): return self._user


def _audio_event(pcm24k_bytes):
    part = SimpleNamespace(inline_data=SimpleNamespace(
        mime_type="audio/pcm;rate=24000", data=pcm24k_bytes))
    return SimpleNamespace(content=SimpleNamespace(parts=[part]), interrupted=False)


def _interrupt_event():
    return SimpleNamespace(content=None, interrupted=True)


class FakeRunner:
    """run_live yields one interrupt then one audio event, then completes."""
    def __init__(self, events):
        self._events = events
        self.run_live_kwargs = None

    async def run_live(self, *, user_id, session_id, live_request_queue, run_config):
        self.run_live_kwargs = {"user_id": user_id, "session_id": session_id,
                                "run_config": run_config}
        for ev in self._events:
            yield ev


@pytest.mark.asyncio
async def test_run_call_creates_session_and_bridges_audio_and_barge_in():
    pcm24k = b"\x00\x00" * 2400  # 100ms of silence @ 24k
    start = json.dumps({"event": "start", "start": {
        "streamSid": "MZ123",
        "customParameters": {"caller_number": "+15551234567"}}})
    ulaw_in = base64.b64encode(audioop.lin2ulaw(b"\x00\x00" * 160, 2)).decode()
    media = json.dumps({"event": "media", "media": {"payload": ulaw_in}})
    stop = json.dumps({"event": "stop"})

    ws = FakeWebSocket([start, media, stop])
    session_service = FakeSessionService()
    runner = FakeRunner([_interrupt_event(), _audio_event(pcm24k)])
    user = {"name": "Aravindan", "mobile": "+15551234567", "email": "a@b.com"}

    await run_call(ws, runner, session_service, store=FakeStore(user))

    # session created with the account identity, enriched by phone lookup
    assert session_service.created[0]["state"] == {
        "caller_name": "Aravindan", "caller_phone": "+15551234567",
        "caller_email": "a@b.com"}
    assert session_service.created[0]["session_id"] == "MZ123"
    assert runner.run_live_kwargs["session_id"] == "MZ123"

    # outbound: a clear frame (barge-in) and a media frame (audio) were sent to Twilio
    events = [json.loads(s)["event"] for s in ws.sent]
    assert "clear" in events
    assert "media" in events
    media_frame = next(json.loads(s) for s in ws.sent if json.loads(s)["event"] == "media")
    assert media_frame["streamSid"] == "MZ123"
    assert len(base64.b64decode(media_frame["media"]["payload"])) > 0
