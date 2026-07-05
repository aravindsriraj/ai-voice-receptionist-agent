from __future__ import annotations
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")  # BEFORE reading env

from fastapi import FastAPI, Request, Response  # noqa: E402
from app.config import load_settings            # noqa: E402
from app.twiml import build_connect_stream_twiml  # noqa: E402

settings = load_settings(os.environ)
app = FastAPI()


@app.get("/healthz")
async def healthz():
    return {"ok": True}


@app.post("/voice")
async def voice(request: Request):
    form = await request.form()
    caller = form.get("From", "")
    ws_host = settings.public_base_url.replace("https://", "").replace("http://", "")
    ws_url = f"wss://{ws_host}/media"
    xml = build_connect_stream_twiml(ws_url, caller)
    return Response(content=xml, media_type="application/xml")
