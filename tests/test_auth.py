import pytest
from app.auth import normalize_e164, hash_password, verify_password, UserStore


# ---- fake Firestore (doc-id keyed) — reused by other tests ----
class _Doc:
    def __init__(self, store, id): self._s, self.id = store, id
    def get(self): return _Snap(self.id, self._s._data.get(self.id))
    def set(self, data): self._s._data[self.id] = dict(data)


class _Snap:
    def __init__(self, id, data): self.id, self._data = id, data
    @property
    def exists(self): return self._data is not None
    def to_dict(self): return dict(self._data) if self._data else None


class _Col:
    def __init__(self, s): self._s = s
    def document(self, id): return _Doc(self._s, id)
    def stream(self): return [_Snap(i, d) for i, d in self._s._data.items()]


class FakeFS:
    def __init__(self): self._data = {}
    def collection(self, name): return _Col(self)


def _store(): return UserStore(FakeFS())


def test_normalize_e164_variants():
    assert normalize_e164("91", "99414 67556") == "+919941467556"
    assert normalize_e164("+1", "(254) 274-5055") == "+12542745055"


def test_normalize_e164_rejects_junk():
    with pytest.raises(ValueError):
        normalize_e164("91", "abc")


def test_hash_and_verify():
    h = hash_password("secret123")
    assert h != "secret123"
    assert verify_password("secret123", h) is True
    assert verify_password("wrong", h) is False


def test_register_get_authenticate():
    s = _store()
    u = s.register("Jane", "Jane@X.com", "secret123", "91", "9941467556")
    assert u["email"] == "jane@x.com" and u["mobile"] == "+919941467556"
    assert s.get("jane@x.com")["name"] == "Jane"
    assert s.authenticate("jane@x.com", "secret123")["name"] == "Jane"
    assert s.authenticate("jane@x.com", "nope") is None


def test_register_duplicate_email_raises():
    s = _store()
    s.register("Jane", "j@x.com", "secret123", "91", "9941467556")
    with pytest.raises(ValueError):
        s.register("Jane2", "j@x.com", "secret123", "91", "9999999999")


def test_find_by_phone():
    s = _store()
    s.register("Jane", "j@x.com", "secret123", "91", "9941467556")
    assert s.find_by_phone("+919941467556")["email"] == "j@x.com"
    assert s.find_by_phone("+10000000000") is None
