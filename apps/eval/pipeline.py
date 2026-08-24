"""In-process virtual-time pipeline — Proof executes one arm over one batch.

Runs the SAME agent code paths as the runtime workers (diagnosis / planner /
dispatcher / outcome ops / simulator bridge) against Postgres with explicit
virtual time, so eval semantics cannot drift from production behavior.

Arms: reflex (full pipeline) · b1 (tuned naive) · b0 (do nothing).
Ablations (on reflex): A1 rules-only dx · A2 EV-off · A3 static templates ·
A4 no timing optimization · DEGRADED (LLM-outage variant).
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import text
from sqlalchemy.orm import Session

from reflex.api.ingest_service import ingest_event
from reflex.core.enums import (
    ActionStatus,
    Arm,
    Channel,
    EventSource,
    Intervention,
    Mode,
)
from reflex.ledger.chain import LedgerWriter
from reflex.shield.guardrails import MerchantGuardrails
from reflex.workers import baselines, dispatcher, outcomes as outcome_ops
from reflex.workers.context import EpisodeContext
from reflex.workers.diagnosis import DiagnosisResult, diagnose_episode
from reflex.workers.planner import PlanOutcome, plan_episode
from reflex.workers.simulator import SimulatorBridge, organic_events_for_customer
from reflex.ledger.chain import fast_ledger

log = structlog.get_logger("reflex.pipeline")

WATCH_WINDOW_H = 6
CONTACT_CHANNELS = {"wa_sim", "sms_sim", "email_sim", "voice_sim"}


@dataclass
class PipelineConfig:
    llm_tail_enabled: bool = True         # ablation A1 disables
    ev_enabled: bool = True               # ablation A2 disables
    personalization_enabled: bool = True  # ablation A3 disables
    timing_enabled: bool = True           # ablation A4 disables
    degraded: bool = False                # LLM-outage variant (F1)
    policy_version: str | None = None


@dataclass(order=True)
class TimedEvent:
    t: datetime
    seq: int
    kind: str
    payload: dict = field(compare=False)


class ArmResult:
    def __init__(self) -> None:
        self.episodes_total = 0
        self.recovered_paise = 0
        self.recovered_episodes = 0
        self.expired_episodes = 0
        self.stopped_cap = 0
        self.stopped_low_ev = 0
        self.stopped_customer = 0
        self.cost_paise = 0
        self.complaints = 0
        self.recovery_latencies: list[float] = []
        self.contacts = 0
        self.declined_cohort: list[dict] = []
        self.shield_blocks = 0
        # per-episode arrays for bootstrap CIs (protocol §2)
        self.ep_rec_paise: list[int] = []      # recovered amount per episode (0 if not)
        self.ep_cost_paise: list[int] = []     # action cost attributed per episode
        self.ep_complaint: list[int] = []      # 1 when COMPLAINT occurred



class _NullRedis:
    """Cache shim for offline eval (no Redis in-process)."""

    def get(self, _k: str) -> None:
        return None

    def setex(self, *_a: object) -> None:
        return None


class _NoopLlm:
    configured = False

    def __init__(self) -> None:
        from reflex.workers.llm_client import LlmHealth

        self.health = LlmHealth(None)


def run_arm(
    session: Session,
    *,
    batch_id: str,
    batch,  # type: ignore[no-untyped-def]
    merchant_id: str,
    customer_ids: dict[int, str],
    arm: Arm,
    ablation: str | None = None,
    config: PipelineConfig | None = None,
    opened_at: datetime | None = None,
) -> ArmResult:
    cfg = config or PipelineConfig()
    # resolve the active policy once per run (planner then skips the store read)
    if cfg.policy_version is None:
        from dataclasses import replace as _dc_replace

        from reflex.brain.policy_store import load_active_policy

        pv, _params = load_active_policy(session)
        cfg = _dc_replace(cfg, policy_version=pv)
    with fast_ledger():
        return _run_arm_inner(
            session,
            batch_id=batch_id,
            batch=batch,
            merchant_id=merchant_id,
            customer_ids=customer_ids,
            arm=arm,
            ablation=ablation,
            cfg=cfg,
            opened_at=opened_at,
        )


def _run_arm_inner(
    session: Session,
    *,
    batch_id: str,
    batch,  # type: ignore[no-untyped-def]
    merchant_id: str,
    customer_ids: dict[int, str],
    arm: Arm,
    ablation: str | None,
    cfg: PipelineConfig,
    opened_at: datetime | None,
) -> ArmResult:
    opened = opened_at or datetime(2026, 8, 28, 9, 0, tzinfo=timezone.utc)
    run_ns = f"{str(batch_id)[:8]}:{arm.value}" + (f":{ablation}" if ablation else "")
    # each episode lives 72h from ITS OWN open; the harness must therefore run
    # until (last opening + 72h) so every episode can reach a terminal state
    max_offset = max(e.t_offset_secs for e in batch.events)
    horizon = opened + timedelta(seconds=max_offset) + timedelta(hours=72)
    now = opened
    seq_counter = iter(range(1, 2**31))

    pq: list[TimedEvent] = []

    def push(t: datetime, kind: str, payload: dict) -> None:
        if t <= horizon:
            heapq.heappush(pq, TimedEvent(t, next(seq_counter), kind, payload))

    sim_bridge = SimulatorBridge(session, seed=batch.seed_int, batch_id=str(batch_id))
    guardrails_cfg = MerchantGuardrails.from_merchant_cfg({})
    noop_llm = _NoopLlm()

    truth_by_idx = {c.idx: c for c in batch.customers}
    result = ArmResult()
    result.episodes_total = len(batch.events)

    ep_state: dict[int, dict] = {}
    contacts: dict[int, int] = {}
    waits: dict[int, int] = {}
    ep_costs: dict[int, int] = {}
    ep_complaint: dict[int, int] = {}

    # ---- schedule openings + organic pay possibilities -----------------------
    for k, ev_spec in enumerate(batch.events):
        open_t = opened + timedelta(seconds=ev_spec.t_offset_secs)
        push(open_t, "open", {"k": k})
        cust = truth_by_idx[ev_spec.customer_idx]
        for t_off_abs, _kind, payload in organic_events_for_customer(
            seed=batch.seed_int,
            customer_idx=cust.idx,
            episode_idx=k,
            code=ev_spec.canonical_code,
            intent=cust.intent,
            episode_open_offset=ev_spec.t_offset_secs,
        ):
            push(
                opened + timedelta(seconds=t_off_abs),
                "pay",
                {"k": k, "action_id": None, "via": "organic"},
            )

    def build_ctx(k: int, episode_id: str) -> EpisodeContext:
        ev = batch.events[k]
        cust = truth_by_idx[ev.customer_idx]
        return EpisodeContext(
            episode_id=episode_id,
            customer_id=customer_ids[cust.idx],
            merchant_id=merchant_id,
            pseudonym=cust.pseudonym,
            lang_pref=cust.lang_pref,
            ltv_band=cust.ltv_band,
            dnd_flag=cust.dnd_flag,
            suppressed=ep_state[k]["suppressed"],
            amount_paise=ev.amount_paise,
            rail=ev.rail,
            code_raw=ev.code_raw,
            actions_used=_actions_used(session, episode_id),
            contacts_today=contacts.get(k, 0),
            prior_recovered=False,
            day_of_month=opened.day,
            hour_ist=opened.astimezone(timezone.utc).hour,
            merchant_cfg={},
            budget_spent_today_paise=0,
            opened_at=opened + timedelta(seconds=ev.t_offset_secs),
            closes_at=opened + timedelta(seconds=ev.t_offset_secs) + timedelta(hours=72),
        )

    while pq:
        evt = heapq.heappop(pq)
        now = evt.t
        k = evt.payload.get("k")
        kind = evt.kind
        st = ep_state.get(k)

        if st is not None and (st["recovered"] or st["suppressed"]) and kind != "pay":
            continue

        if kind == "open":
            ev = batch.events[k]
            normalized = {
                "provider_event_id": f"{ev.provider_event_id}:{run_ns}",
                "event": "payment.failed",
                "rail": ev.rail,
                "code_raw": ev.code_raw,
                "amount_paise": ev.amount_paise,
                "occurred_at": now,
                "raw_payload": {"simulated": True, "batch_id": str(batch_id)},
                "customer_ref": f"idx:{ev.customer_idx}",
            }
            res = ingest_event(
                session,
                source=EventSource.REPLAY,
                normalized=normalized,
                arm=arm,
                batch_customer_resolver=lambda _n: customer_ids[ev.customer_idx],
                now_sim=now,
            )
            if not res.accepted or res.episode_id is None:
                continue
            ep_state[k] = {"episode_id": res.episode_id, "recovered": False, "suppressed": False}
            contacts.setdefault(k, 0)

            if ev.force_complaint_reply_at is not None:
                fc_t = opened + timedelta(seconds=min(ev.force_complaint_reply_at, 71 * 3600))
                push(
                    fc_t,
                    "reply",
                    {
                        "k": k,
                        "text": "aap baar baar message bhejte ho, harassment hai, complaint karunga",
                        "label": "COMPLAINT",
                    },
                )

            if arm is Arm.B0:
                continue
            if arm is Arm.B1:
                baselines.plan_b1(
                    session, episode_id=res.episode_id, amount_paise=ev.amount_paise, now_sim=now
                )
                _set_episode_status(session, res.episode_id, "diagnosed")
                _set_episode_status(session, res.episode_id, "scheduled")
                for row in _episode_actions(session, res.episode_id):
                    push(row["scheduled_for"], "act", {"k": k, "action_id": str(row["id"])})
                continue
            _plan_reflex(session, build_ctx(k, res.episode_id), cfg, now, push, k, result, waits)

        elif kind == "replan":
            if st is None:
                continue
            _plan_reflex(session, build_ctx(k, st["episode_id"]), cfg, now, push, k, result, waits)

        elif kind == "act":
            if st is None:
                continue
            action_id = evt.payload["action_id"]
            row = _action_row(session, action_id)
            if row is None or ActionStatus(row["status"]) is not ActionStatus.SCHEDULED:
                continue
            ctx = build_ctx(k, st["episode_id"])
            dr = dispatcher.dispatch_action(
                agent_session=session,
                sim_bridge=sim_bridge,
                llm=noop_llm,
                redis_client=None,
                rp_client=None,
                action_id=action_id,
                now_sim=now,
                mode=Mode.AUTONOMOUS,
                personalization_enabled=cfg.personalization_enabled,
                ctx_override=ctx,
            )
            if dr.status == "dispatched":
                if row["channel"] in CONTACT_CHANNELS:
                    contacts[k] = contacts.get(k, 0) + 1
                    result.contacts += 1
                result.cost_paise += int(row["cost_paise"])
                ep_costs[k] = ep_costs.get(k, 0) + int(row["cost_paise"])
                # schedule the simulator's stochastic response on the timeline
                for t_off, kind_ev, payload in dr.sim_events:
                    if kind_ev == "pay":
                        push(
                            now + timedelta(seconds=t_off),
                            "pay",
                            {"k": k, "action_id": payload.get("action_id"), "via": payload.get("via", "")},
                        )
                    elif kind_ev == "reply":
                        push(
                            now + timedelta(seconds=t_off),
                            "reply",
                            {"k": k, "text": payload.get("text", ""), "label": payload.get("label", "AMBIGUOUS")},
                        )
                push(now + timedelta(hours=WATCH_WINDOW_H), "watch", {"k": k, "action_id": action_id})
            elif dr.status == "blocked":
                result.shield_blocks += 1

        elif kind == "pay":
            if st is None or st["recovered"]:
                continue
            ev = batch.events[k]
            latency = max(int((now - (opened + timedelta(seconds=ev.t_offset_secs))).total_seconds()), 1)
            ok = outcome_ops.apply_recovery(
                session,
                episode_id=st["episode_id"],
                observed_at=now,
                action_id=evt.payload.get("action_id"),
                latency_secs=latency,
                source_note=str(evt.payload.get("via", "")),
            )
            if ok:
                st["recovered"] = True
                result.recovered_paise += ev.amount_paise
                result.recovered_episodes += 1
                # TTR is protocol-defined over ALL recovered episodes (PROTOCOL.md
                # §2.6), including organic B0 recoveries — not just action-driven ones.
                result.recovery_latencies.append(float(latency))

        elif kind == "reply":
            if st is None:
                continue
            label = evt.payload.get("label", "AMBIGUOUS")
            if label == "COMPLAINT":
                ep_complaint[k] = 1
            if label in ("COMPLAINT", "OPTOUT"):
                ev = batch.events[k]
                cust = truth_by_idx[ev.customer_idx]
                outcome_ops.stop_customer(
                    session,
                    episode_id=st["episode_id"],
                    customer_id=customer_ids[cust.idx],
                    reason_reason=label.lower(),
                    suppression_source="[SIMULATED] reply classifier",
                    at=now,
                )
                st["suppressed"] = True
                if label == "COMPLAINT":
                    result.complaints += 1

        elif kind == "watch":
            if st is None:
                continue
            res_kind = outcome_ops.apply_watch_window_expiry(
                session, episode_id=st["episode_id"], action_id=evt.payload["action_id"], observed_at=now
            )
            if res_kind == "STOPPED_CAP":
                result.stopped_cap += 1
            elif res_kind == "REPLAN" and arm is Arm.REFLEX:
                push(now + timedelta(seconds=1), "replan", {"k": k})

    # 72h expiry sweep for everything still open
    outcome_ops.expire_due(session, horizon)

    # per-episode CI arrays (episode order stable)
    for kk in range(result.episodes_total):
        st_k = ep_state.get(kk)
        rec_amt = batch.events[kk].amount_paise if (st_k and st_k.get("recovered")) else 0
        result.ep_rec_paise.append(rec_amt)
        result.ep_cost_paise.append(ep_costs.get(kk, 0))
        result.ep_complaint.append(ep_complaint.get(kk, 0))

    # ---- final tallies (statuses of this run's episodes) -----------------------
    if ep_state:
        ep_ids = [st["episode_id"] for st in ep_state.values()]
        rows = session.execute(
            text(
                """
                SELECT status::text AS s, count(*) FROM runtime.episodes
                WHERE id = ANY(CAST(:ids AS uuid[]))
                GROUP BY 1
                """
            ),
            {"ids": ep_ids},
        ).all()
        for s_name, cnt in rows:
            cnt = int(cnt)
            if s_name == "stopped_low_ev":
                result.stopped_low_ev = max(result.stopped_low_ev, cnt)
            elif s_name == "expired":
                result.expired_episodes = cnt
            elif s_name == "stopped_cap":
                result.stopped_cap = max(result.stopped_cap, cnt)
            elif s_name == "stopped_customer":
                result.stopped_customer = cnt

    return result


def _plan_reflex(
    session: Session,
    ctx: EpisodeContext,
    cfg: PipelineConfig,
    now: datetime,
    push,  # type: ignore[no-untyped-def]
    k: int,
    result: ArmResult,
    waits: dict[int, int],
) -> None:
    # consecutive WAIT bookkeeping: after two deferrals, waiting is excluded
    waits[k] = waits.get(k, 0)
    dx = diagnose_episode(
        session,
        noop_llm := _NoopLlm(),
        _NullRedis(),
        episode_id=ctx.episode_id,
        code_raw=ctx.code_raw,
        rail=ctx.rail,
        amount_paise=ctx.amount_paise,
        occurred_at=ctx.opened_at,
        degraded=cfg.degraded,
        llm_tail_enabled=cfg.llm_tail_enabled,
    )
    session.execute(
        text(
            "INSERT INTO runtime.diagnoses (episode_id, canonical_code, confidence, method, rationale) "
            "VALUES (:e, CAST(:c AS runtime.canonical_code), :cf, CAST(:m AS runtime.dx_method), :r)"
        ),
        {
            "e": ctx.episode_id,
            "c": dx.canonical_code.value,
            "cf": dx.confidence,
            "m": dx.method.value,
            "r": dx.rationale[:240],
        },
    )
    LedgerWriter(session).append(
        episode_id=ctx.episode_id,
        event={
            "type": "DIAGNOSIS_STORED",
            "canonical_code": dx.canonical_code.value,
            "confidence": dx.confidence,
            "method": dx.method.value,
            "rationale": dx.rationale[:240],
        },
        at=now,
    )

    plan = plan_episode(
        session,
        ctx,
        diagnosis_code=dx.canonical_code,
        now_sim=now,
        mode=Mode.AUTONOMOUS,
        policy_version=cfg.policy_version,
        ev_enabled=cfg.ev_enabled,
        timing_enabled=cfg.timing_enabled,
        allow_wait=waits.get(k, 0) < 2,
    )
    # mirror the runtime decision worker: keep the episode state machine true.
    # Only a fresh episode needs waiting_diagnosis → diagnosed; replans on
    # already-active episodes keep their current status.
    session.execute(
        text(
            "UPDATE runtime.episodes SET status = 'diagnosed' "
            "WHERE id = CAST(:e AS uuid) AND status = 'waiting_diagnosis'"
        ),
        {"e": ctx.episode_id},
    )
    status_map = {
        "SCHEDULED": "scheduled",
        "APPROVAL": "waiting_approval",
        "STOPPED_LOW_EV": "stopped_low_ev",
    }
    if plan.kind in status_map:
        session.execute(
            text(
                "UPDATE runtime.episodes SET status = CAST(:s AS runtime.episode_status) "
                "WHERE id = CAST(:e AS uuid) AND status IN ('waiting_diagnosis','diagnosed')"
            ),
            {"s": status_map[plan.kind], "e": ctx.episode_id},
        )
    if plan.kind == "STOPPED_LOW_EV":
        result.stopped_low_ev += 1
        if ctx.amount_paise <= 15_000:
            result.declined_cohort.append({"episode_id": ctx.episode_id, "amount_paise": ctx.amount_paise})
        return
    if plan.action_id is None:
        return
    row = _action_row(session, plan.action_id)
    if row is not None and row["intervention"] == Intervention.WAIT.value:
        waits[k] = waits.get(k, 0) + 1
        # WAIT ⇒ re-plan at the deferred time (horizon-1 observe loop)
        push(plan.scheduled_for or now + timedelta(hours=4), "replan", {"k": k})
        return
    waits[k] = 0
    if plan.scheduled_for is not None:
        push(plan.scheduled_for, "act", {"k": k, "action_id": plan.action_id})


# ---- small DB helpers ------------------------------------------------------------


def _set_episode_status(session: Session, episode_id: str, status: str) -> None:
    session.execute(
        text(
            "UPDATE runtime.episodes SET status = CAST(:s AS runtime.episode_status) "
            "WHERE id = CAST(:e AS uuid)"
        ),
        {"s": status, "e": episode_id},
    )


def _actions_used(session: Session, episode_id: str) -> int:
    return int(
        session.execute(
            text("SELECT actions_used FROM runtime.episodes WHERE id = CAST(:e AS uuid)"),
            {"e": episode_id},
        ).scalar()
        or 0
    )


def _action_row(session: Session, action_id: str) -> dict | None:  # type: ignore[type-arg]
    row = session.execute(
        text(
            "SELECT a.id::text AS id, a.intervention::text AS intervention, a.status::text AS status, "
            "a.channel::text AS channel, a.cost_paise, e.amount_paise AS amount_paise "
            "FROM runtime.actions a JOIN runtime.episodes e ON e.id = a.episode_id "
            "WHERE a.id = CAST(:a AS uuid)"
        ),
        {"a": action_id},
    ).mappings().first()
    return dict(row) if row else None


def _episode_actions(session: Session, episode_id: str) -> list[dict]:  # type: ignore[type-arg]
    rows = session.execute(
        text(
            "SELECT id::text AS id, scheduled_for FROM runtime.actions "
            "WHERE episode_id = CAST(:e AS uuid) AND status = 'scheduled' ORDER BY created_at"
        ),
        {"e": episode_id},
    ).mappings().all()
    return [dict(r) for r in rows]


def _set_action_status(session: Session, action_id: str, status: ActionStatus) -> None:
    session.execute(
        text("UPDATE runtime.actions SET status = CAST(:s AS runtime.action_status) WHERE id = CAST(:a AS uuid)"),
        {"s": status.value, "a": action_id},
    )
