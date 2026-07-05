from __future__ import annotations
import re
from datetime import datetime, timezone
import bcrypt


def normalize_e164(country_code: str, number: str) -> str:
    cc = re.sub(r"\D", "", country_code)
    nat = re.sub(r"\D", "", number)
    if not cc or not nat or len(cc + nat) < 8:
        raise ValueError("invalid phone number")
    return f"+{cc}{nat}"


def hash_password(pw: str) -> str:
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()


def verify_password(pw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(pw.encode(), hashed.encode())
    except (ValueError, TypeError):
        return False


class UserStore:
    def __init__(self, client, collection: str = "users") -> None:
        self._col = client.collection(collection)

    def register(self, name, email, password, country_code, mobile) -> dict:
        if not name or not password or len(password) < 6:
            raise ValueError("name and a password of at least 6 chars are required")
        email = email.strip().lower()
        mobile_e164 = normalize_e164(country_code, mobile)
        if self._col.document(email).get().exists:
            raise ValueError("email already registered")
        user = {"name": name.strip(), "email": email, "mobile": mobile_e164,
                "password_hash": hash_password(password),
                "created_at": datetime.now(timezone.utc).isoformat()}
        self._col.document(email).set(user)
        return user

    def get(self, email: str) -> dict | None:
        snap = self._col.document(email.strip().lower()).get()
        return snap.to_dict() if snap.exists else None

    def authenticate(self, email: str, password: str) -> dict | None:
        user = self.get(email)
        if user and verify_password(password, user["password_hash"]):
            return user
        return None

    def find_by_phone(self, phone: str) -> dict | None:
        for snap in self._col.stream():
            d = snap.to_dict()
            if d and d.get("mobile") == phone:
                return d
        return None
