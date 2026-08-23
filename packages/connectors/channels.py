"""[SIMULATED] channel gateways: WhatsApp / SMS / Email / Voice (PRD FR-008).

These are simulators, clearly labeled `[SIMULATED]` in metadata everywhere.
Delivery latency + stochastic customer responses come from the Proof response
engine — the gateway itself only models transport latency and returns a
delivery receipt. No real message ever leaves the system.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

# Transport-latency model (seconds): channel-typical delivery ack delays.
TRANSPORT_LATENCY_SECS: dict[str, tuple[float, float]] = {
    "wa_sim": (2, 30),
    "sms_sim": (3, 45),
    "email_sim": (5, 120),
    "voice_sim": (10, 60),
}


@dataclass(frozen=True)
class DeliveryReceipt:
    channel: str
    simulated: bool  # always True here — [SIMULATED]
    delivered_at: datetime
    provider_ref: str
    note: str = "[SIMULATED]"


class ChannelGateway:
    """Base for simulated channels. Deterministic under seed via rng_provider."""

    channel = "sim"
    label = "[SIMULATED]"

    def __init__(self, rng_provider=None) -> None:  # type: ignore[no-untyped-def]
        # rng_provider(action_key) -> random.Random-like with .uniform(a,b)
        self._rng_provider = rng_provider or _hash_rng

    def deliver(
        self,
        *,
        action_id: str,
        recipient_pseudonym: str,
        message: str,
        at_sim: datetime,
    ) -> DeliveryReceipt:
        lo, hi = TRANSPORT_LATENCY_SECS.get(self.channel, (2, 60))
        rng = self._rng_provider(f"{self.channel}:{action_id}")
        delay = rng.uniform(lo, hi)
        ref_src = f"{self.channel}:{recipient_pseudonym}:{action_id}"
        return DeliveryReceipt(
            channel=self.channel,
            simulated=True,
            delivered_at=at_sim + timedelta(seconds=delay),
            provider_ref=hashlib.sha256(ref_src.encode()).hexdigest()[:16],
        )


class WhatsAppSim(ChannelGateway):
    channel = "wa_sim"


class SmsSim(ChannelGateway):
    channel = "sms_sim"


class EmailSim(ChannelGateway):
    channel = "email_sim"


class VoiceSim(ChannelGateway):
    """Scripted Hinglish recovery call (demo channel; PRD §11 non-goal beyond this)."""

    channel = "voice_sim"

    SCRIPT_TEMPLATE = (
        "Namaste {name}! SipDaily se bol rahe hain. Aapki payment "
        "{due_phrase} ke liye ek chhota reminder — link aapko WhatsApp par "
        "mil jayega. Shukriya!"
    )


def _hash_rng(key: str):  # type: ignore[no-untyped-def]
    import random

    seed = int(hashlib.sha256(key.encode()).hexdigest()[:12], 16)
    return random.Random(seed)


GATEWAYS: dict[str, ChannelGateway] = {
    "wa_sim": WhatsAppSim(),
    "sms_sim": SmsSim(),
    "email_sim": EmailSim(),
    "voice_sim": VoiceSim(),
}
