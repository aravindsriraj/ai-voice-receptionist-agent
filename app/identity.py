from __future__ import annotations


def identity_state(name: str = "", phone: str = "", email: str = "") -> dict:
    return {"caller_name": name, "caller_phone": phone, "caller_email": email}


def greeting_kickoff(name: str = "", phone: str = "", email: str = "") -> str:
    if name:
        parts = [f"phone {phone}"] if phone else []
        if email:
            parts.append(f"email {email}")
        on_file = f" ({', '.join(parts)} on file)" if parts else ""
        return (f"A caller just connected. You are speaking with {name}{on_file}. "
                f"Greet them by name as the clinic receptionist, and when booking use "
                f"these contact details — do not ask for their phone or email.")
    known = phone or "unknown"
    return (f"A new caller is on the line (phone {known}). Greet them warmly as the "
            f"clinic receptionist, ask how you can help, and ask for their name. "
            f"Do not ask for a phone number or email.")
