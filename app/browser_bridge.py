from __future__ import annotations
import asyncio, logging
from google.adk.agents.run_config import RunConfig, StreamingMode
from google.adk.agents.live_request_queue import LiveRequestQueue
from google.genai import types
from app.bridge import APP_NAME, extract_audio_bytes, is_interrupt, _log_event
from app.identity import identity_state, greeting_kickoff

logger = logging.getLogger(__name__)


async def run_browser_call(websocket, runner, session_service, user, session_id) -> None:
    """Bridge one browser mic/speaker session to one ADK run_live() session.

    Browser sends 16kHz PCM binary frames and plays 24kHz PCM binary frames — no
    transcoding. Auth is handled by the caller (session cookie).
    """
    await websocket.accept()
    name, phone, email = user["name"], user["mobile"], user["email"]
    live_queue = LiveRequestQueue()
    run_config = RunConfig(response_modalities=["AUDIO"], streaming_mode=StreamingMode.BIDI)

    await session_service.create_session(
        app_name=APP_NAME, user_id=email, session_id=session_id,
        state=identity_state(name=name, phone=phone, email=email))
    live_queue.send_content(types.Content(
        role="user",
        parts=[types.Part(text=greeting_kickoff(name=name, phone=phone, email=email))]))

    async def downstream():
        async for event in runner.run_live(
                user_id=email, session_id=session_id,
                live_request_queue=live_queue, run_config=run_config):
            _log_event(event)
            if is_interrupt(event):
                await websocket.send_json({"type": "interrupt"})
                continue
            ot = getattr(event, "output_transcription", None)
            if ot and getattr(ot, "text", None) and getattr(ot, "finished", False):
                await websocket.send_json({"type": "transcript", "role": "agent", "text": ot.text})
            it = getattr(event, "input_transcription", None)
            if it and getattr(it, "text", None) and getattr(it, "finished", False):
                await websocket.send_json({"type": "transcript", "role": "user", "text": it.text})
            for pcm in extract_audio_bytes(event):
                await websocket.send_bytes(pcm)

    down_task = asyncio.create_task(downstream())
    try:
        while True:
            data = await websocket.receive_bytes()
            live_queue.send_realtime(types.Blob(mime_type="audio/pcm;rate=16000", data=data))
    except Exception as e:  # WebSocketDisconnect etc.
        logger.info("browser call ended: %s", e)
    finally:
        live_queue.close()
        try:
            await down_task
        except Exception as e:
            logger.info("browser downstream ended: %s", e)
