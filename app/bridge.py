from __future__ import annotations
import asyncio, base64, json, logging
from google.adk.agents.run_config import RunConfig, StreamingMode
from google.adk.agents.live_request_queue import LiveRequestQueue
from google.genai import types
from app.audio import Resampler, ulaw8k_to_pcm16k, pcm24k_to_ulaw8k

logger = logging.getLogger(__name__)

APP_NAME = "voice-agent"


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
async def run_call(websocket, runner, session_service) -> None:
    """Bridge one Twilio Media Stream call to one ADK run_live() session.

    session_service is passed explicitly because Runner exposes no public
    session_service attribute in google-adk 2.3.0. The runner MUST be built with
    app_name=APP_NAME so run_live() can find the session created here.
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
        async for event in runner.run_live(
                user_id=caller_number or "anon", session_id=stream_sid,
                live_request_queue=live_queue, run_config=run_config):
            _log_event(event)
            if getattr(event, "error_code", None):
                logger.error("live error: %s - %s", event.error_code, event.error_message)
            if is_interrupt(event) and stream_sid:
                await websocket.send_text(twilio_clear_frame(stream_sid))
                continue
            for pcm24k in extract_audio_bytes(event):
                ulaw = pcm24k_to_ulaw8k(pcm24k, outbound_rs)
                await websocket.send_text(twilio_media_frame(
                    stream_sid, base64.b64encode(ulaw).decode()))

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
                await session_service.create_session(
                    app_name=APP_NAME, user_id=caller_number or "anon",
                    session_id=stream_sid, state={"caller_phone": caller_number})
                # kick the agent to greet first
                live_queue.send_content(types.Content(
                    role="user",
                    parts=[types.Part(text="A caller just connected. Greet them.")]))
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
