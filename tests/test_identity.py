from app.identity import identity_state, greeting_kickoff


def test_identity_state_has_all_keys():
    s = identity_state(name="Jane", phone="+15551234567", email="j@x.com")
    assert s == {"caller_name": "Jane", "caller_phone": "+15551234567",
                 "caller_email": "j@x.com"}


def test_greeting_kickoff_known_name_mentions_name_and_number():
    k = greeting_kickoff(name="Jane", phone="+15551234567", email="j@x.com")
    assert "Jane" in k and "+15551234567" in k
    assert "greet" in k.lower()


def test_greeting_kickoff_unknown_asks_for_name():
    k = greeting_kickoff(phone="+15551234567")
    assert "+15551234567" in k
    assert "name" in k.lower()
