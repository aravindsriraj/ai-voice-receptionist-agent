from types import SimpleNamespace
import pytest
from app.browser_bridge import run_browser_call


class FakeWS:
    def __init__(self, inbound_frames):
        self._in = list(inbound_frames); self.sent_bytes = []; self.sent_json = []
        self.accepted = False

    async def accept(self): self.accepted = True

    async def receive_bytes(self):
        if self._in:
            return self._in.pop(0)
        from starlette.websockets import WebSocketDisconnect
        raise WebSocketDisconnect(1000)

    async def send_bytes(self, b): self.sent_bytes.append(b)
    async def send_json(self, o): self.sent_json.append(o)


class FakeSession:
    def __init__(self): self.created = []

    async def create_session(self, *, app_name, user_id, session_id, state):
        self.created.append({"state": state, "session_id": session_id})


def _audio_event(pcm):
    part = SimpleNamespace(inline_data=SimpleNamespace(mime_type="audio/pcm;rate=24000", data=pcm))
    return SimpleNamespace(content=SimpleNamespace(parts=[part]), interrupted=False)


def _interrupt_event():
    return SimpleNamespace(content=None, interrupted=True)


class FakeRunner:
    def __init__(self, events): self._e = events

    async def run_live(self, *, user_id, session_id, live_request_queue, run_config):
        for e in self._e:
            yield e


@pytest.mark.asyncio
async def test_browser_call_sets_identity_and_streams_pcm():
    ws = FakeWS([b"\x01\x02" * 160])   # one inbound 16k PCM frame, then disconnect
    sess = FakeSession()
    runner = FakeRunner([_interrupt_event(), _audio_event(b"\x00\x00" * 2400)])
    user = {"name": "Jane", "mobile": "+15551234567", "email": "j@x.com"}

    await run_browser_call(ws, runner, sess, user, session_id="sess1")

    assert sess.created[0]["state"] == {"caller_name": "Jane",
                                        "caller_phone": "+15551234567",
                                        "caller_email": "j@x.com"}
    assert ws.sent_bytes and ws.sent_bytes[0] == b"\x00\x00" * 2400   # 24k PCM passthrough
    assert {"type": "interrupt"} in ws.sent_json                       # barge-in signal
