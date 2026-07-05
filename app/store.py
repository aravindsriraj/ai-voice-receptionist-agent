from __future__ import annotations


class AppointmentStore:
    def __init__(self, client, collection: str = "appointments") -> None:
        self._col = client.collection(collection)

    def create_appointment(self, data: dict) -> str:
        doc = self._col.document()
        doc.set(data)
        return doc.id

    def list_booked(self) -> list[dict]:
        rows = []
        for snap in self._col.stream():
            d = snap.to_dict()
            d["id"] = snap.id
            if d.get("status") == "booked":
                rows.append(d)
        return rows

    def mark_reminder_sent(self, appt_id: str, kind: str) -> None:
        field = {"24h": "reminder_24h_sent", "1h": "reminder_1h_sent"}[kind]
        self._col.document(appt_id).update({field: True})
