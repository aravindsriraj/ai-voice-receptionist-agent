import xml.etree.ElementTree as ET
from app.twiml import build_connect_stream_twiml


def test_twiml_has_connect_stream_with_wss_and_param():
    xml = build_connect_stream_twiml("wss://host/media", "+15551234567")
    root = ET.fromstring(xml)
    stream = root.find("./Connect/Stream")
    assert stream is not None
    assert stream.get("url") == "wss://host/media"
    param = stream.find("./Parameter")
    assert param.get("name") == "caller_number"
    assert param.get("value") == "+15551234567"
