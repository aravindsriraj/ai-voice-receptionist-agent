from __future__ import annotations
from xml.sax.saxutils import quoteattr


def build_connect_stream_twiml(ws_url: str, caller_number: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Response><Connect>"
        f"<Stream url={quoteattr(ws_url)}>"
        f"<Parameter name=\"caller_number\" value={quoteattr(caller_number)}/>"
        "</Stream></Connect></Response>"
    )
