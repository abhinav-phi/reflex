"""Time-shift scheduling (A4 ablation disables this).

Deterministic salary-cycle/hour heuristics — never LLM (PRD §14 "scheduling math
is deterministic"). INSUFFICIENT_FUNDS near month-end defers to the evening
funds window; issuer downtime waits out the transient outage window.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from reflex.core.clock import IST, in_quiet_hours
from reflex.core.enums import CanonicalCode, Intervention

# Optimal contact hours (IST) by cause — quiet-hours compliant.
_OPTIMAL_HOUR: dict[CanonicalCode, int] = {
    CanonicalCode.INSUFFICIENT_FUNDS: 16,  # evening funds window on salary weeks
    CanonicalCode.ISSUER_DOWNTIME: 11,
    CanonicalCode.UNKNOWN_AMBIGUOUS: 10,
}


def next_allowed_contact(dt: datetime) -> datetime:
    """If dt is in quiet hours (21:00–09:00 IST), roll to 09:00 IST same/next day."""
    if not in_quiet_hours(dt):
        return dt
    ist = dt.astimezone(IST)
    if ist.hour >= 21:
        target = (ist + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
    else:
        target = ist.replace(hour=9, minute=0, second=0, microsecond=0)
    return target.astimezone(dt.tzinfo)


def schedule_for(
    code: CanonicalCode,
    intervention: Intervention,
    now_sim: datetime,
    day_of_month: int,
    timing_enabled: bool = True,
) -> datetime:
    """Return the sim-time an action should fire. WAIT defers; others may time-shift."""
    if not timing_enabled or intervention is Intervention.STOP_LOW_EV:
        return now_sim

    if intervention is Intervention.WAIT:
        delay = _wait_delay(code, day_of_month)
        return next_allowed_contact(now_sim + timedelta(seconds=delay))

    # Non-WAIT actions: nudge to optimal hour if it's within 8h ahead and clear of quiet hours.
    hour = _OPTIMAL_HOUR.get(code)
    if hour is None:
        return now_sim
    candidate = now_sim.replace(hour=hour, minute=0, second=0, microsecond=0)
    if candidate < now_sim:
        candidate += timedelta(days=1)
    if (candidate - now_sim) <= timedelta(hours=8):
        return next_allowed_contact(candidate)
    return next_allowed_contact(now_sim)


def _wait_delay(code: CanonicalCode, day_of_month: int) -> int:
    """Seconds to wait before re-planning (sim-time)."""
    if code is CanonicalCode.ISSUER_DOWNTIME:
        return 4 * 3600  # transient outage window ~1–6h; re-check at +4h
    if code is CanonicalCode.RISK_HELD:
        return 6 * 3600
    if code is CanonicalCode.INSUFFICIENT_FUNDS:
        # Near salary credit (last week of month): wait for funds to land.
        if day_of_month >= 26:
            return 6 * 3600
        return 4 * 3600
    return 4 * 3600  # conservative default per AppFlow §5 (UNKNOWN ⇒ WAIT 4h)
