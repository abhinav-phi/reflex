"""Batch generator (Proof): customers, failure events, hidden sim params.

Deterministic: same seed ⇒ byte-identical batch (FR-002). Hidden behavioral
truth never leaves this module except into `replay.sim_*` tables.

Demo slice (seed `demo-7`): EXACTLY 214 episodes / ₹2,41,000 failed value,
including one ₹48,000 B2B-style invoice (approval moment) and one pre-seeded
complaint trajectory (injection 3) — Schema §13.
"""

from __future__ import annotations

import hashlib
import zlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import numpy as np

from data.generators.corpus_strings import DECLINE_STRINGS, RULES_MISS_STRINGS
from reflex.core.enums import CanonicalCode, LtvBand, Rail

SIMULATOR_VERSION = "sim-v1"

# Failure mixture per Schema §13 (percent). v1.2 TASK-053 amendment: RISK_HELD
# added (2%) so synthetic data covers all 11 canonical codes — INSUFFICIENT_FUNDS
# rebalanced 34→32 to keep the total at 100%. Protocol amendment tag must be cut
# BEFORE the official eval run (pre-registration discipline).
CODE_MIXTURE: tuple[tuple[str, float], ...] = (
    ("INSUFFICIENT_FUNDS", 32.0),
    ("AUTH_DECLINED_SOFT", 14.0),
    ("ISSUER_DOWNTIME", 12.0),
    ("MANDATE_REVOKED", 9.0),
    ("EXPIRED_CARD", 7.0),
    ("AUTH_DECLINED_HARD", 6.0),
    ("MANDATE_LIMIT_BREACH", 5.0),
    ("CUSTOMER_INITIATED", 4.0),
    ("INVALID_VPA", 3.0),
    ("RISK_HELD", 2.0),
    ("AMBIGUOUS_TAIL", 6.0),
)

AMOUNT_TIERS: tuple[tuple[tuple[int, ...], float], ...] = (
    ((19_900, 29_900, 39_900), 60.0),
    ((49_900, 59_900, 69_900, 99_900), 25.0),
    ((149_900, 249_900), 10.0),
    ((9_900, 15_000, 5_500, 449_900, 499_900), 5.0),
)

INTENT_PRIOR: tuple[tuple[str, float], ...] = (
    ("would_pay_if", 55.0),
    ("wait_pay", 30.0),
    ("never_pay", 15.0),
)

CHANNEL_BASE = {"wa_sim": 0.45, "sms_sim": 0.35, "email_sim": 0.15, "voice_sim": 0.55}

DEMO_SEED = "demo-7"
DEMO_N = 214
DEMO_TOTAL_PAISE = 24_100_000  # ₹2,41,000
DEMO_HIGH_VALUE_PAISE = 4_800_000  # ₹48,000


def seed_to_int(seed: str | int) -> int:
    if isinstance(seed, int):
        return seed
    return zlib.crc32(seed.encode()) & 0x7FFFFFFF


@dataclass
class CustomerSpec:
    idx: int
    pseudonym: str
    vpa_masked: str
    lang_pref: str
    ltv_band: str
    dnd_flag: bool
    salary_day: int
    intent: str
    annoyance_threshold: float
    p_respond_by_channel: dict[str, float]


@dataclass
class EventSpec:
    t_offset_secs: int
    customer_idx: int
    rail: str
    code_raw: str
    canonical_code: str  # hidden ground truth label
    amount_paise: int
    provider_event_id: str
    force_complaint_reply_at: int | None = None  # pre-seeded complaint trajectory


@dataclass
class GeneratedBatch:
    seed_int: int
    n_episodes: int
    customers: list[CustomerSpec] = field(default_factory=list)
    events: list[EventSpec] = field(default_factory=list)

    def fingerprint(self) -> str:
        """Byte-identity check for FR-002 (same seed ⇒ identical batch)."""
        h = hashlib.sha256()
        for c in self.customers:
            h.update(
                f"{c.idx}|{c.pseudonym}|{c.vpa_masked}|{c.lang_pref}|{c.ltv_band}|{int(c.dnd_flag)}|"
                f"{c.salary_day}|{c.intent}|{c.annoyance_threshold:.6f}|"
                f"{sorted(c.p_respond_by_channel.items())}".encode()
            )
        for e in self.events:
            h.update(
                f"{e.t_offset_secs}|{e.customer_idx}|{e.rail}|{e.code_raw}|{e.canonical_code}|"
                f"{e.amount_paise}|{e.provider_event_id}|{e.force_complaint_reply_at}".encode()
            )
        return h.hexdigest()


def generate_batch(*, seed: str | int, n: int, demo: bool = False) -> GeneratedBatch:
    seed_int = seed_to_int(seed)
    rng = np.random.default_rng(seed_int)
    batch = GeneratedBatch(seed_int=seed_int, n_episodes=n)

    # ---- customers ---------------------------------------------------------
    n_customers = max(n, 300)  # reuse pool; some customers may fail more than once
    codes, weights = zip(*CODE_MIXTURE)
    weights_arr = np.array(weights) / sum(weights)

    intents, intent_w = zip(*INTENT_PRIOR)
    intent_arr = np.array(intent_w) / sum(intent_w)

    for i in range(n_customers):
        band_r = rng.random()
        band = "low" if band_r < 0.30 else ("mid" if band_r < 0.80 else "high")
        salary_day = int(rng.integers(1, 8)) if rng.random() < 0.70 else int(rng.integers(8, 29))
        lang = "hinglish" if rng.random() < 0.70 else "en"
        dnd = bool(rng.random() < 0.03)
        intent = str(rng.choice(list(intents), p=intent_arr))
        annoyance = float(rng.gamma(3.0, 1.2))
        # per-customer channel response multipliers around the public base rates
        p_by_channel = {
            ch: round(min(0.95, base * float(rng.uniform(0.75, 1.3))), 4)
            for ch, base in CHANNEL_BASE.items()
        }
        handle = _handle(rng)
        batch.customers.append(
            CustomerSpec(
                idx=i,
                pseudonym=f"C-{1000 + i}",
                vpa_masked=f"{handle[0]}***@{handle.split('@')[1]}",
                lang_pref=lang,
                ltv_band=band,
                dnd_flag=dnd,
                salary_day=salary_day,
                intent=intent,
                annoyance_threshold=annoyance,
                p_respond_by_channel=p_by_channel,
            )
        )

    # ---- failure events ------------------------------------------------------
    chosen = rng.choice(n_customers, size=n, replace=n > n_customers)
    all_amounts = sorted(a for amounts, _pct in AMOUNT_TIERS for a in amounts)
    amount_probs = np.array(
        [pct / len(amounts) for amounts, pct in AMOUNT_TIERS for _ in amounts], dtype=float
    )

    rails = list(Rail)
    rail_probs = np.array([0.52, 0.24, 0.12, 0.06, 0.06])  # upi-heavy India mix [ASSUMPTION]

    demo_high_value_assigned = False
    complaint_trajectory_assigned = False

    amounts: list[int] = []
    remaining_budget = DEMO_TOTAL_PAISE - DEMO_HIGH_VALUE_PAISE if demo else None
    for k in range(n):
        if demo and k == n // 2:
            amounts.append(DEMO_HIGH_VALUE_PAISE)  # reserved invoice, outside budget
            demo_high_value_assigned = True
            continue
        if demo:
            eps_left_after = sum(
                1 for j in range(k + 1, n) if not (demo and j == n // 2)
            )
            floor_needed = 10_000 * eps_left_after  # every later episode ≥ ₹100
            cap = remaining_budget - floor_needed
            pool_mask = np.array([a <= cap for a in all_amounts])
            if not pool_mask.any():
                amounts.append(10_000)  # ₹100 fallback
                remaining_budget -= 10_000
                continue
            sub_probs = amount_probs * pool_mask
            sub_probs /= sub_probs.sum()
            amt = int(rng.choice(all_amounts, p=sub_probs))
            amounts.append(amt)
            remaining_budget -= amt
        else:
            probs = amount_probs / amount_probs.sum()
            amounts.append(int(rng.choice(all_amounts, p=probs)))

    running_total = 0
    for k in range(n):
        cust = batch.customers[int(chosen[k])]
        code_label = str(rng.choice(list(codes), p=weights_arr))
        amount = amounts[k]

        if demo and amount == DEMO_HIGH_VALUE_PAISE and k == n // 2:
            code_label = "MANDATE_LIMIT_BREACH"  # above-limit B2B-style invoice
        running_total += amount

        rail = str(rng.choice(rails, p=rail_probs))
        if code_label == "AMBIGUOUS_TAIL":
            code_raw = str(RULES_MISS_STRINGS[int(rng.integers(len(RULES_MISS_STRINGS)))])
            canonical = CanonicalCode.UNKNOWN_AMBIGUOUS.value
        else:
            variants = DECLINE_STRINGS[code_label]
            code_raw = str(variants[int(rng.integers(len(variants)))])
            canonical = code_label

        # spread over a simulated day; demo compresses into ~36h window
        t_offset = int(rng.uniform(0, 36 * 3600)) if demo else int(rng.uniform(0, 72 * 3600))
        provider_event_id = f"evt_{seed_int}_{k:05d}"

        force_complaint = None
        if demo and not complaint_trajectory_assigned and canonical == "INSUFFICIENT_FUNDS":
            force_complaint = t_offset + int(3.5 * 3600)  # angry reply mid-episode
            complaint_trajectory_assigned = True

        batch.events.append(
            EventSpec(
                t_offset_secs=t_offset,
                customer_idx=cust.idx,
                rail=rail,
                code_raw=code_raw,
                canonical_code=canonical,
                amount_paise=amount,
                provider_event_id=provider_event_id,
                force_complaint_reply_at=force_complaint,
            )
        )

    # ---- demo total fitting: adjust deterministically to hit ₹2,41,000 -------
    if demo:
        assert demo_high_value_assigned and complaint_trajectory_assigned, (
            "demo slice must contain the high-value case and complaint trajectory"
        )
        diff = DEMO_TOTAL_PAISE - running_total
        if diff < 0:
            # overspent: shrink deterministically (never below ₹100, never the invoice)
            adjustable = sorted(
                (e for e in batch.events if e.amount_paise != DEMO_HIGH_VALUE_PAISE),
                key=lambda e: -e.amount_paise,
            )
            i = 0
            while diff < 0:
                progressed = False
                for e in adjustable:
                    if diff >= 0:
                        break
                    if e.amount_paise - 100 >= 10_000:
                        e.amount_paise -= 100
                        diff += 100
                        progressed = True
                if not progressed:
                    for e in adjustable:
                        if diff >= 0:
                            break
                        if e.amount_paise - 100 > 0:
                            e.amount_paise -= 100
                            diff += 100
                            progressed = True
                if not progressed:
                    break
        else:
            # spread leftover evenly, then ₹1-sweep the remainder (deterministic)
            adjustable = [e for e in batch.events if e.amount_paise != DEMO_HIGH_VALUE_PAISE]
            base = diff // len(adjustable)
            if base > 0:
                for e in adjustable:
                    e.amount_paise += base
                diff -= base * len(adjustable)
            i = 0
            while diff > 0:
                adjustable[i % len(adjustable)].amount_paise += 100
                diff -= 100
                i += 1
            if diff < 0:  # remainder from the ₹1 sweep — fold into first adjustable
                adjustable[0].amount_paise += diff
                diff = 0
        total = sum(e.amount_paise for e in batch.events)
        assert total == DEMO_TOTAL_PAISE, f"demo total mismatch: {total}"

    return batch


def _handle(rng: np.random.Generator) -> str:
    banks = ["ybl", "okaxis", "oksbi", "okhdfcbank", "paytm", "apl"]
    names = ["arjun", "priya", "kavya", "rohit", "neha", "vikram", "sneha", "amit"]
    return f"{names[int(rng.integers(len(names)))]}{int(rng.integers(10, 99))}@{banks[int(rng.integers(len(banks)))]}"


def batch_open_time(now: datetime | None = None) -> datetime:
    return (now or datetime.now(timezone.utc)).replace(microsecond=0)


def horizon_end(opened: datetime, hours: int = 72) -> datetime:
    return opened + timedelta(hours=hours)
