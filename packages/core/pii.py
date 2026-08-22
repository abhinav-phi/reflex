"""PII scrubber + prompt hygiene (Rules §1.8, Schema §12).

No real PII exists in Reflex (synthetic customers), but the scrubber is still
enforced at every untrusted-text boundary: webhook payloads, bank strings,
simulated replies, LLM inputs/outputs, logs. `tests/security` runs the scanner.
"""

from __future__ import annotations

import re

# Emails (incl. masked VPAs like name@ybl)
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
# Phone numbers: 10-digit Indian mobiles w/ optional +91 / 0 prefix
_PHONE = re.compile(r"(?:\+91[\s-]?|0)?\b[6-9]\d{9}\b")
# Card numbers (13–19 digits with spaces/dashes)
_CARD = re.compile(r"\b(?:\d[ -]?){13,19}\b")
# UPI VPA style handles not caught by email regex (no dot TLD): user@bankname
_VPA = re.compile(r"\b[\w.-]+@(?:ybl|okaxis|oksbi|okhdfcbank|paytm|upi|apl|ibl)\b")
# OTP-ish digit clusters
_OTP = re.compile(r"\b\d{4,8}\b")

_REDACTED = "[REDACTED]"


def scrub(text: str) -> str:
    """Replace PII-shaped spans with [REDACTED]. Deterministic, order-stable."""
    out = _CARD.sub(_REDACTED, text)
    out = _EMAIL.sub(_REDACTED, out)
    out = _VPA.sub(_REDACTED, out)
    out = _PHONE.sub(_REDACTED, out)
    out = _OTP.sub(_REDACTED, out)
    return out


def scrub_payload(obj: object) -> object:
    """Recursively scrub all strings inside JSON-ish structures."""
    if isinstance(obj, str):
        return scrub(obj)
    if isinstance(obj, dict):
        return {k: scrub_payload(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [scrub_payload(v) for v in obj]
    return obj


def assert_no_pii(text: str) -> None:
    """Raise if any PII pattern survives — used before LLM calls and on logs."""
    for rx, label in ((_EMAIL, "email"), (_VPA, "vpa"), (_PHONE, "phone"), (_CARD, "card")):
        if rx.search(text):
            raise ValueError(f"PII leak detected in text boundary: {label}")
