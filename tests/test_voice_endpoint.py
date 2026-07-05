from app.main import select_caller


def test_inbound_uses_from():
    # caller dials in: human is the From party
    assert select_caller("inbound", "+15551112222", "+12542745055") == "+15551112222"


def test_outbound_uses_to():
    # Twilio dials the human: human is the To party
    assert select_caller("outbound-api", "+12542745055", "+919941467556") == "+919941467556"
    assert select_caller("outbound-dial", "+12542745055", "+919941467556") == "+919941467556"


def test_missing_direction_defaults_to_from():
    assert select_caller("", "+15551112222", "") == "+15551112222"
