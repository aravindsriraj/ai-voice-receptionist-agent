from types import SimpleNamespace
from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware
from fastapi.testclient import TestClient
from app.web import make_router
from app.auth import UserStore
from tests.test_auth import FakeFS   # reuse the fake Firestore


class FakeCalls:
    def __init__(self): self.created = []
    def create(self, **kw):
        self.created.append(kw)
        return SimpleNamespace(sid="CA1", status="queued")


class FakeTwilio:
    def __init__(self): self.calls = FakeCalls()


def _client(tmp_path):
    store = UserStore(FakeFS())
    twilio = FakeTwilio()
    settings = SimpleNamespace(twilio_caller_number="+12542745055",
                               public_base_url="https://x")
    (tmp_path / "login.html").write_text("<h1>login</h1>")
    (tmp_path / "register.html").write_text("<h1>register</h1>")
    (tmp_path / "app.html").write_text("<h1>app</h1>")
    app = FastAPI()
    app.add_middleware(SessionMiddleware, secret_key="test")
    app.include_router(make_router(lambda: store, lambda: twilio, settings, str(tmp_path)))
    return TestClient(app), store, twilio


def test_register_login_logout_and_guard(tmp_path):
    c, store, twilio = _client(tmp_path)
    # guard: /app blocked when logged out
    assert c.get("/app", follow_redirects=False).status_code in (302, 303, 307, 401)
    # register logs you in
    r = c.post("/register", data={"name": "Jane", "email": "j@x.com",
               "password": "secret123", "country_code": "91", "mobile": "9941467556"},
               follow_redirects=False)
    assert r.status_code in (302, 303, 307)
    assert c.get("/app").status_code == 200
    # call-me dials the account mobile
    r = c.post("/api/call-me")
    assert r.status_code == 200 and r.json()["status"] == "queued"
    assert twilio.calls.created[0]["to"] == "+919941467556"
    assert twilio.calls.created[0]["from_"] == "+12542745055"
    assert twilio.calls.created[0]["url"].endswith("/voice")
    # logout blocks again
    c.post("/logout")
    assert c.get("/app", follow_redirects=False).status_code in (302, 303, 307, 401)


def test_login_bad_password_blocks(tmp_path):
    c, store, _ = _client(tmp_path)
    c.post("/register", data={"name": "Jane", "email": "j@x.com", "password": "secret123",
                              "country_code": "91", "mobile": "9941467556"})
    c.post("/logout")
    r = c.post("/login", data={"email": "j@x.com", "password": "wrong"},
               follow_redirects=False)
    assert r.status_code == 401
    assert c.get("/app", follow_redirects=False).status_code in (302, 303, 307, 401)


def test_call_me_requires_login(tmp_path):
    c, store, _ = _client(tmp_path)
    assert c.post("/api/call-me").status_code == 401


def test_api_me_returns_account_after_login(tmp_path):
    c, store, _ = _client(tmp_path)
    assert c.get("/api/me").status_code == 401
    c.post("/register", data={"name": "Jane Doe", "email": "j@x.com", "password": "secret123",
                              "country_code": "91", "mobile": "9941467556"})
    me = c.get("/api/me")
    assert me.status_code == 200
    assert me.json() == {"name": "Jane Doe", "email": "j@x.com", "mobile": "+919941467556"}
