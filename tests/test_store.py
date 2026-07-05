from datetime import datetime, timezone
from app.store import AppointmentStore


class _Doc:
    def __init__(self, store, id): self._store, self.id = store, id
    def set(self, data): self._store._data[self.id] = dict(data)
    def update(self, patch): self._store._data[self.id].update(patch)


class _Snap:
    def __init__(self, id, data): self.id, self._data = id, data
    def to_dict(self): return dict(self._data)


class _Collection:
    def __init__(self, store): self._store = store
    def document(self, id=None):
        if id is None:
            id = f"doc{len(self._store._data)}"
        return _Doc(self._store, id)
    def stream(self):
        return [_Snap(i, d) for i, d in self._store._data.items()]


class FakeFirestore:
    def __init__(self): self._data = {}
    def collection(self, name): return _Collection(self)


def _make():
    return AppointmentStore(FakeFirestore())


def test_create_and_list():
    store = _make()
    appt_id = store.create_appointment({
        "name": "Jane", "reason": "checkup", "phone": "+1", "email": "j@x.com",
        "start": datetime(2026, 7, 8, 10, tzinfo=timezone.utc), "timezone": "UTC",
        "calendar_event_id": "ev1", "status": "booked",
        "reminder_24h_sent": False, "reminder_1h_sent": False,
    })
    rows = store.list_booked()
    assert len(rows) == 1
    assert rows[0]["id"] == appt_id and rows[0]["name"] == "Jane"


def test_mark_reminder_sent():
    store = _make()
    appt_id = store.create_appointment({
        "name": "Jane", "reason": "x", "phone": "+1", "email": "j@x.com",
        "start": datetime(2026, 7, 8, 10, tzinfo=timezone.utc), "timezone": "UTC",
        "calendar_event_id": "ev1", "status": "booked",
        "reminder_24h_sent": False, "reminder_1h_sent": False,
    })
    store.mark_reminder_sent(appt_id, "24h")
    assert store.list_booked()[0]["reminder_24h_sent"] is True
