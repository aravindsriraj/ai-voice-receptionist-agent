from app.messaging import Notifier, confirmation_texts, reminder_texts


class FakeMessages:
    def __init__(self): self.created = []
    def create(self, **kwargs): self.created.append(kwargs)


class FakeTwilio:
    def __init__(self): self.messages = FakeMessages()


class FakeResend:
    class Emails:
        sent = []


def _resend():
    FakeResend.Emails.sent = []
    FakeResend.Emails.send = staticmethod(lambda p: FakeResend.Emails.sent.append(p))
    return FakeResend


def test_send_whatsapp_prefixes_channel():
    tw = FakeTwilio()
    n = Notifier(tw, "whatsapp:+14155238886", _resend(), "Clinic <a@b.com>")
    n.send_whatsapp("+15551234567", "Hi")
    msg = tw.messages.created[0]
    assert msg["from_"] == "whatsapp:+14155238886"
    assert msg["to"] == "whatsapp:+15551234567"
    assert msg["body"] == "Hi"


def test_send_email_calls_resend():
    mod = _resend()
    n = Notifier(FakeTwilio(), "whatsapp:+1", mod, "Clinic <a@b.com>")
    n.send_email("j@x.com", "Confirmed", "<p>ok</p>")
    sent = mod.Emails.sent[0]
    assert sent["to"] == "j@x.com" and sent["from"] == "Clinic <a@b.com>"
    assert sent["subject"] == "Confirmed"


def test_text_builders_include_details():
    wa, subj, html = confirmation_texts("Jane", "Wed Jul 8 at 10:00 AM")
    assert "Jane" in wa and "Jul 8" in wa
    assert "confirm" in subj.lower()
    assert "Jane" in html and "10:00" in html
    rwa, rsubj, rhtml = reminder_texts("Jane", "Wed Jul 8 at 10:00 AM", "1h")
    assert "remind" in rsubj.lower() and "Jane" in rwa
