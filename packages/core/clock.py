"""Sim-time clock.

The runtime system runs on a Redis-backed accelerated clock (demo ×1/×25/×100);
Proof's in-process eval uses a deterministic VirtualClock. Both implement
`now_sim()` returning timezone-aware UTC instants representing simulated time.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from reflex.core.enums import Mode

IST = ZoneInfo("Asia/Kolkata")
EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)

CLOCK_KEY = "reflex:clock"


class ClockProtocol:
    def now_sim(self) -> datetime: ...

    def speed(self) -> float: ...


def to_ist(dt: datetime) -> datetime:
    return dt.astimezone(IST)


def ist_hour(dt: datetime) -> int:
    return dt.astimezone(IST).hour


def ist_date_key(dt: datetime) -> str:
    """Local (IST) calendar day key — contacts/day and budget windows."""
    return dt.astimezone(IST).strftime("%Y-%m-%d")


def in_quiet_hours(dt: datetime) -> bool:
    """Quiet hours 21:00–09:00 IST. Exactly 21:00:00 is quiet; 09:00:00 is not."""
    h = ist_hour(dt)
    return h >= 21 or h < 9


class RealClock:
    """Wall-clock at ×1 (used when no replay is active)."""

    def now_sim(self) -> datetime:
        return datetime.now(timezone.utc)

    def speed(self) -> float:
        return 1.0


class SimClock:
    """Redis-backed accelerated clock shared by API + workers.

    Stores: {"speed": float, "anchor_real": epoch secs, "anchor_sim": epoch secs}
    sim_now = anchor_sim + (real_now - anchor_real) * speed
    """

    def __init__(self, redis_client) -> None:  # type: ignore[no-untyped-def]
        self._r = redis_client

    def configure(self, *, sim_start: datetime, speed: float) -> None:
        import json

        self._r.set(
            CLOCK_KEY,
            json.dumps(
                {
                    "speed": speed,
                    "anchor_real": time.time(),
                    "anchor_sim": sim_start.timestamp(),
                }
            ),
        )

    def reset(self) -> None:
        self._r.delete(CLOCK_KEY)

    def state(self) -> dict[str, float] | None:
        import json

        raw = self._r.get(CLOCK_KEY)
        return json.loads(raw) if raw else None

    def now_sim(self) -> datetime:
        st = self.state()
        if st is None:
            return datetime.now(timezone.utc)
        delta = timedelta(seconds=(time.time() - st["anchor_real"]) * st["speed"])
        return EPOCH + timedelta(seconds=st["anchor_sim"]) + delta

    def speed(self) -> float:
        st = self.state()
        return float(st["speed"]) if st else 1.0

    def real_deadline_for(self, sim_dt: datetime) -> tuple[float, float]:
        """(real_epoch_seconds_when_sim_deadline_hits, speed) — for scheduler sleeps."""
        st = self.state()
        if st is None:
            return sim_dt.timestamp(), 1.0
        sim_delta = (sim_dt - EPOCH - timedelta(seconds=st["anchor_sim"])).total_seconds()
        real = st["anchor_real"] + sim_delta / max(st["speed"], 1e-9)
        return real, float(st["speed"])


class VirtualClock:
    """Deterministic in-process clock for Proof/eval. Advanced explicitly."""

    def __init__(self, start: datetime) -> None:
        self._t = start
        self._speed = 100.0  # informational only in eval context

    def now_sim(self) -> datetime:
        return self._t

    def advance_to(self, dt: datetime) -> None:
        if dt > self._t:
            self._t = dt

    def advance_by(self, seconds: float) -> None:
        self._t = self._t + timedelta(seconds=seconds)

    def speed(self) -> float:
        return self._speed


# ---- global mode flags (control plane; kill switch lives here too) ----------
MODE_KEY = "reflex:mode"
HALT_FLAG = "reflex:halted"
LLM_OUTAGE_KEY = "reflex:inject:llm_outage"
DEGRADED_KEY = "reflex:mode_effective"


def effective_mode(redis_client, db_mode: str) -> Mode:
    """Halt flag wins over everything; LLM outage degrades autonomous mode."""
    import json

    if redis_client.get(HALT_FLAG):
        return Mode.HALTED
    if redis_client.get(LLM_OUTAGE_KEY):
        return Mode.DEGRADED
    try:
        return Mode(json.loads(db_mode))
    except Exception:
        return Mode(db_mode)  # type: ignore[arg-value]
