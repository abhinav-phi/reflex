"""PROOF-EMBEDDED SIMULATOR BRIDGE — hidden-truth side of the house.

This module is Proof (TechSpec §1: replay engine + outcome simulator with
hidden params). It is NOT agent code: it reads `replay.sim_*` with the
reflex_eval role and never exposes hidden parameters to agent decisions.

Agent packages (core/shield/brain/api decision paths) must not import this
module — enforced by tests/security/test_shield_isolation.py and the import
lint rule. The DB role boundary (ADR-004) is the hard guarantee.

Stochastic model: data/calibration_sources.md §3–4, deterministic RNG streams
keyed by (seed, customer, episode, contact seq) so results are
order-independent and reproducible.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import numpy as np
from sqlalchemy import text
from sqlalchemy.orm import Session

SIM_VERSION = "sim-v1"

# Cause-gated resolution probabilities for link-based interventions
# (calibration_sources.md §4; retry table handled by _retry_resolve).
_LINK_CAUSE_GATE: dict[str, float] = {
    "INSUFFICIENT_FUNDS": 0.85,
    "ISSUER_DOWNTIME": 0.75,
    "EXPIRED_CARD": 0.70,  # pay via link with another instrument
    "AUTH_DECLINED_SOFT": 0.70,
    "AUTH_DECLINED_HARD": 0.15,
    "RISK_HELD": 0.30,
    "MANDATE_REVOKED": 0.55,
    "MANDATE_LIMIT_BREACH": 0.65,
    "INVALID_VPA": 0.55,
    "CUSTOMER_INITIATED": 0.0,  # never contact; never pay via outreach
    "UNKNOWN_AMBIGUOUS": 0.35,
}

_RETRY_RESOLVE: dict[str, float] = {
    "INSUFFICIENT_FUNDS": 0.10,
    "ISSUER_DOWNTIME": 0.80,
    "EXPIRED_CARD": 0.0,
    "AUTH_DECLINED_SOFT": 0.50,
    "AUTH_DECLINED_HARD": 0.05,
    "RISK_HELD": 0.10,
    "MANDATE_REVOKED": 0.0,
    "MANDATE_LIMIT_BREACH": 0.0,
    "INVALID_VPA": 0.0,
    "CUSTOMER_INITIATED": 0.0,
    "UNKNOWN_AMBIGUOUS": 0.12,
}

_ORGANIC_P: dict[str, float] = {
    "INSUFFICIENT_FUNDS": 0.080,
    "ISSUER_DOWNTIME": 0.045,
    "EXPIRED_CARD": 0.008,
    "AUTH_DECLINED_SOFT": 0.045,
    "AUTH_DECLINED_HARD": 0.004,
    "RISK_HELD": 0.020,
    "MANDATE_REVOKED": 0.012,
    "MANDATE_LIMIT_BREACH": 0.025,
    "INVALID_VPA": 0.008,
    "CUSTOMER_INITIATED": 0.0,
    "UNKNOWN_AMBIGUOUS": 0.020,
}

_INTENT_ORGANIC_MULT = {"would_pay_if": 1.6, "wait_pay": 0.5, "never_pay": 0.0}

_CHANNEL_BASE: dict[str, float] = {"wa_sim": 0.45, "sms_sim": 0.35, "email_sim": 0.15, "voice_sim": 0.55}


def _rng(seed: int, *parts: Any) -> np.random.Generator:
    key = ":".join(str(p) for p in parts)
    digest = int(hashlib.sha256(f"{seed}:{key}".encode()).hexdigest()[:16], 16)
    return np.random.default_rng(digest)


@dataclass
class SimTruth:
    intent: str
    salary_day: int
    annoyance_threshold: float
    p_respond_by_channel: dict[str, float]
    customer_idx: int
    episode_idx: int


class SimulatorBridge:
    """Reads hidden truth (eval role), writes scheduled sim_events (replay schema),
    and surfaces due events to the outcome layer. Runtime-demo mode."""

    def __init__(self, eval_session: Session, *, seed: int, batch_id: str) -> None:
        self.s = eval_session
        self.seed = seed
        self.batch_id = batch_id

    def _truth(self, episode_id: str) -> SimTruth | None:
        row = self.s.execute(
            text(
                "SELECT sc.intent, sc.salary_day, sc.annoyance_threshold, "
                "sc.p_respond_by_channel, sc.params "
                "FROM replay.sim_customers sc "
                "JOIN runtime.episodes e ON e.customer_id = sc.runtime_customer_id "
                "WHERE e.id = CAST(:e AS uuid) AND sc.batch_id = CAST(:b AS uuid)"
            ),
            {"e": episode_id, "b": self.batch_id},
        ).first()
        if row is None:
            return None
        params = dict(row[4] or {})
        return SimTruth(
            intent=row[0],
            salary_day=int(row[1]),
            annoyance_threshold=float(row[2]),
            p_respond_by_channel=dict(row[3]),
            customer_idx=int(params.get("customer_idx", 0)),
            episode_idx=int(params.get("episode_idx", 0)),
        )

    def _diagnosis_of(self, episode_id: str) -> str:
        row = self.s.execute(
            text(
                "SELECT canonical_code::text FROM runtime.diagnoses "
                "WHERE episode_id = :e ORDER BY created_at DESC LIMIT 1"
            ),
            {"e": episode_id},
        ).first()
        return str(row[0]) if row else "UNKNOWN_AMBIGUOUS"

    def respond_to_action(
        self,
        *,
        agent_session: Session,  # type: ignore[no-untyped-def]
        action: dict[str, Any],
        contacts_today: int,
    ) -> list[tuple[int, str, dict]]:
        """Compute the stochastic customer response; persist + RETURN sim events.

        Returned tuples are (t_offset_secs_from_dispatch, kind, payload) so the
        in-process eval pipeline can schedule them on its virtual timeline;
        the runtime outcome worker instead polls the persisted rows.
        """
        episode_id = action["episode_id"]
        truth = self._truth(episode_id)
        dispatched = action["dispatched_at"]
        if not isinstance(dispatched, datetime):
            dispatched = datetime.fromisoformat(str(dispatched))
        contact_seq = contacts_today

        if truth is None:
            # live_tm episode without replay truth: outcomes arrive via real webhooks.
            return []

        rng = _rng(self.seed, truth.customer_idx, truth.episode_idx, "resp", contact_seq)
        events: list[tuple[int, str, dict]] = []

        intervention = action["intervention"]
        channel = action["channel"]
        code = self._diagnosis_of(episode_id)

        if intervention in ("RETRY_SAME_RAIL", "RETRY_ALT_RAIL"):
            p = _RETRY_RESOLVE.get(code, 0.10)
            if rng.random() < p:
                delay = int(rng.uniform(60, 6 * 3600))
                events.append((delay, "pay", {"via": "retry", "action_id": action["id"]}))
        else:
            base = truth.p_respond_by_channel.get(channel or "sms_sim", 0.3)
            gate = _LINK_CAUSE_GATE.get(code, 0.35)
            intent_mult = {"would_pay_if": 1.0, "wait_pay": 0.55, "never_pay": 0.05}[truth.intent]
            p_pay = min(0.95, base * gate * intent_mult)
            u = rng.random()
            if u < p_pay:
                # pay after lognormal latency
                latency_h = float(np.exp(rng.normal(math.log(2.2), 0.9)))
                delay = int(latency_h * 3600)
                events.append((delay, "pay", {"via": channel or "link", "action_id": action["id"]}))
            elif u < p_pay + 0.12 and truth.intent == "wait_pay":
                delay = int(rng.uniform(2 * 3600, 30 * 3600))
                events.append(
                    (delay, "reply", {"action_id": action["id"], "text": "kal ya parso pakka kar dunga", "label": "PROMISE"})
                )
            else:
                # annoyance-driven negative replies
                p_complaint = 0.010 * (1.6 ** contact_seq)
                p_optout = 0.012 * (1.5 ** contact_seq)
                u2 = rng.random()
                if u2 < p_complaint:
                    delay = int(rng.uniform(600, 4 * 3600))
                    events.append(
                        (
                            delay,
                            "reply",
                            {
                                "action_id": action["id"],
                                "text": "aap baar baar message bhejte ho, ye harassment hai. main complaint karunga",
                                "label": "COMPLAINT",
                            },
                        )
                    )
                elif u2 < p_complaint + p_optout:
                    delay = int(rng.uniform(600, 4 * 3600))
                    events.append(
                        (delay, "reply", {"action_id": action["id"], "text": "stop messaging me", "label": "OPTOUT"})
                    )

        for t_offset, kind, payload in events:
            self.s.execute(
                text(
                    "INSERT INTO replay.sim_events (batch_id, episode_id, t_offset_secs, kind, payload) "
                    "VALUES (CAST(:b AS uuid), CAST(:e AS uuid), :t, :k, CAST(:p AS jsonb))"
                ),
                {
                    "b": self.batch_id,
                    "e": episode_id,
                    "t": t_offset,
                    "k": kind,
                    "p": _dumps(payload),
                },
            )
        return events

    def due_events(self, now_sim: datetime, batch_opened_at: datetime) -> list[dict[str, Any]]:
        """Sim events whose scheduled sim-time has arrived (kind pay/reply)."""
        elapsed = (now_sim - batch_opened_at).total_seconds()
        rows = self.s.execute(
            text(
                "SELECT se.id, se.episode_id, se.kind, se.payload, se.t_offset_secs "
                "FROM replay.sim_events se WHERE se.batch_id = :b AND se.t_offset_secs <= :el "
                "AND se.kind IN ('pay','reply') ORDER BY se.t_offset_secs"
            ),
            {"b": self.batch_id, "el": int(elapsed)},
        ).mappings().all()
        return [dict(r) for r in rows]

    def consume_event(self, event_id: str) -> None:
        self.s.execute(text("DELETE FROM replay.sim_events WHERE id = :i"), {"i": event_id})


def _dumps(obj: dict) -> str:
    import json

    return json.dumps(obj, ensure_ascii=False)


def organic_events_for_customer(
    *,
    seed: int,
    customer_idx: int,
    episode_idx: int,
    code: str,
    intent: str,
    episode_open_offset: int,
) -> list[tuple[int, str, dict]]:
    """Organic self-correction (B0's only path). Deterministic per RNG stream."""
    rng = _rng(seed, customer_idx, episode_idx, "organic")
    p = _ORGANIC_P.get(code, 0.05) * _INTENT_ORGANIC_MULT.get(intent, 0.0)
    if intent == "never_pay" or rng.random() >= p:
        return []
    delay = int(rng.uniform(2 * 3600, 66 * 3600))
    return [(episode_open_offset + delay, "pay", {"via": "organic", "action_id": None})]
