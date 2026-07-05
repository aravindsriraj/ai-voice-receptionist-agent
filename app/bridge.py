from __future__ import annotations
import asyncio, base64, json, logging
from google.adk.agents.run_config import RunConfig, StreamingMode
from google.adk.agents.live_request_queue import LiveRequestQueue
from google.genai import types
from app.audio import Resampler, ulaw8k_to_pcm16k, pcm24k_to_ulaw8k
from app.identity import identity_state, greeting_kickoff

logger = logging.getLogger(__name__)

APP_NAME = "voice-agent"
# Seconds to let the farewell audio flush before hanging up after the agent's end_call.
HANGUP_DELAY_S = 1.5


# ---- pure helpers (unit-tested) ------------------------------------------------
def parse_twilio_message(raw: str) -> dict:
    return json.loads(raw)


def twilio_media_frame(stream_sid: str, ulaw_b64: str) -> str:
    return json.dumps({"event": "media", "streamSid": stream_sid,
                       "media": {"payload": ulaw_b64}})


def twilio_clear_frame(stream_sid: str) -> str:
    return json.dumps({"event": "clear", "streamSid": stream_sid})


def extract_audio_bytes(event) -> list[bytes]:
    out = []
    content = getattr(event, "content", None)
    if content and getattr(content, "parts", None):
        for part in content.parts:
            inline = getattr(part, "inline_data", None)
            if inline and getattr(inline, "mime_type", "") and \
               inline.mime_type.startswith("audio/pcm") and inline.data:
                out.append(inline.data)
    return out


def is_interrupt(event) -> bool:
    return bool(getattr(event, "interrupted", False))


def is_end_call(event) -> bool:
    """True when the agent invoked the end_call tool (signal to hang up)."""
    gfc = getattr(event, "get_function_calls", None)
    if callable(gfc):
        return any(getattr(fc, "name", "") == "end_call" for fc in (gfc() or []))
    return False


def _log_event(event) -> None:
    """Best-effort visibility into the live conversation (tool calls + final transcripts).
    Guarded with getattr so it is safe for both real ADK events and test doubles."""
    gfc = getattr(event, "get_function_calls", None)
    if callable(gfc):
        for fc in (gfc() or []):
            logger.info("tool call: %s(%s)", fc.name, dict(fc.args or {}))
    it = getattr(event, "input_transcription", None)
    if it and getattr(it, "text", None) and getattr(it, "finished", False):
        logger.info("caller said: %s", it.text)
    ot = getattr(event, "output_transcription", None)
    if ot and getattr(ot, "text", None) and getattr(ot, "finished", False):
        logger.info("agent said: %s", ot.text)


# ---- orchestration (integration; driven by manual test call) -------------------
async def run_call(websocket, runner, session_service, store=None) -> None:
    """Bridge one Twilio Media Stream call to one ADK run_live() session.

    session_service is passed explicitly because Runner exposes no public
    session_service attribute in google-adk 2.3.0. The runner MUST be built with
    app_name=APP_NAME so run_live() can find the session created here. When a `store`
    is given, the caller is looked up by phone to enrich session state with name/email.
    """
    await websocket.accept()
    stream_sid: str | None = None
    caller_number = ""
    downstream: asyncio.Task | None = None
    live_queue = LiveRequestQueue()
    inbound_rs = Resampler(8000, 16000)   # Twilio -> Gemini
    outbound_rs = Resampler(24000, 8000)  # Gemini -> Twilio
    run_config = RunConfig(response_modalities=["AUDIO"],
                           streaming_mode=StreamingMode.BIDI)

    async def pump_gemini_to_twilio():
        ending = False
        async for event in runner.run_live(
                user_id=caller_number or "anon", session_id=stream_sid,
                live_request_queue=live_queue, run_config=run_config):
            _log_event(event)
            if getattr(event, "error_code", None):
                logger.error("live error: %s - %s", event.error_code, event.error_message)
            if is_end_call(event):
                ending = True
            if is_interrupt(event) and stream_sid:
                await websocket.send_text(twilio_clear_frame(stream_sid))
                continue
            for pcm24k in extract_audio_bytes(event):
                ulaw = pcm24k_to_ulaw8k(pcm24k, outbound_rs)
                await websocket.send_text(twilio_media_frame(
                    stream_sid, base64.b64encode(ulaw).decode()))
            if ending and getattr(event, "turn_complete", False):
                await asyncio.sleep(HANGUP_DELAY_S)  # let the goodbye audio play out
                logger.info("agent ended the call; hanging up")
                try:
                    await websocket.close()
                except Exception:
                    pass
                break

    async def pump_twilio_to_gemini():
        nonlocal stream_sid, caller_number, downstream
        while True:
            raw = await websocket.receive_text()
            msg = parse_twilio_message(raw)
            ev = msg.get("event")
            if ev == "start":
                stream_sid = msg["start"]["streamSid"]
                caller_number = msg["start"].get("customParameters", {}).get(
                    "caller_number", "")
                user = store.find_by_phone(caller_number) if store and caller_number else None
                name = user["name"] if user else ""
                email = user["email"] if user else ""
                await session_service.create_session(
                    app_name=APP_NAME, user_id=caller_number or "anon",
                    session_id=stream_sid,
                    state=identity_state(name=name, phone=caller_number, email=email))
                # Give the model the caller's identity so it greets/reads back accurately
                # (session state is visible to tools, not to the model itself).
                live_queue.send_content(types.Content(
                    role="user",
                    parts=[types.Part(text=greeting_kickoff(
                        name=name, phone=caller_number, email=email))]))
                downstream = asyncio.create_task(pump_gemini_to_twilio())
            elif ev == "media":
                pcm16k = ulaw8k_to_pcm16k(
                    base64.b64decode(msg["media"]["payload"]), inbound_rs)
                live_queue.send_realtime(types.Blob(
                    mime_type="audio/pcm;rate=16000", data=pcm16k))
            elif ev == "stop":
                break

    try:
        await pump_twilio_to_gemini()
    except Exception as e:  # WebSocketDisconnect and friends
        logger.info("call ended: %s", e)
    finally:
        live_queue.close()  # signals run_live() to end the downstream task
        if downstream is not None:
            try:
                await downstream
            except Exception as e:
                logger.info("downstream task ended: %s", e)
