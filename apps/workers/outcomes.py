"""Outcome observation & attribution (PRD FR-015) + episode terminals.

- One recovery per episode (partial unique index enforces).
- Attribution: the currently open action gets credit; organic = NULL action.
- Watch-window expiry ⇒ failed ⇒ re-plan (caps permitting) or STOPPED_CAP.
- 72h expiry sweep; pending approvals auto-expire fail-closed.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import structlog
from sqlalchemy import text
from sqlalchemy.orm import Session

from reflex.core.enums import ActionStatus, EpisodeStatus, OutcomeKind
from reflex.ledger.chain import LedgerWriter
from reflex.workers.dispatcher import transition_action

log = structlog.get_logger("reflex.outcomes")


def _episode(session: Session, episode_id: str) -> dict | None:
    return session.execute(
        text(
            "SELECT id, status::text AS status, actions_used, opened_at, closes_at, "
            "arm::text AS arm FROM runtime.episodes WHERE id = :e FOR UPDATE"
        ),
        {"e": episode_id},
    ).mappings().first()


def apply_recovery(
    session: Session,
    *,
    episode_id: str,
    observed_at: datetime,
    action_id: str | None = None,
    latency_secs: int | None = None,
    source_note: str = "",
) -> bool:
    """Match a capture to the episode; idempotent; supersede other open actions."""
    ep = _episode(session, episode_id)
    if ep is None:
        return False
    if ep["status"] in ("recovered", "expired", "stopped_cap", "stopped_low_ev",
                        "stopped_customer", "stopped_approval_declined", "escalated", "halted"):
        # terminal already — duplicate capture is ignored + logged (AppFlow §9)
        log.info("duplicate_capture_ignored", episode_id=episode_id, current=ep["status"])
        return False

    try:
        with session.begin_nested():  # duplicate-capture conflicts stay isolated
            session.execute(
                text(
                    "INSERT INTO runtime.outcomes (episode_id, action_id, outcome, observed_at, latency_secs) "
                    "VALUES (:e, CAST(:a AS uuid), 'recovered', :obs, :lat)"
                ),
                {"e": episode_id, "a": action_id, "obs": observed_at, "lat": latency_secs},
            )
    except Exception as exc:
        log.info("recovery_insert_conflict", episode_id=episode_id, error=str(exc)[:120])
        return False

    ledger = LedgerWriter(session)
    ledger.append(
        episode_id=episode_id,
        action_id=action_id,
        event={
            "type": "OUTCOME_RECOVERED",
            "attribution": str(action_id) if action_id else "organic",
            "latency_secs": latency_secs,
            "source_note": source_note,
        },
        at=observed_at,
    )

    # supersede any other scheduled/waiting actions (AppFlow §9 edge case)
    rows = session.execute(
        text(
            "SELECT id FROM runtime.actions WHERE episode_id = :e "
            "AND status IN ('scheduled','waiting_approval') AND id <> CAST(:a AS uuid)"
        ),
        {"e": episode_id, "a": action_id},
    ).scalars().all()
    for other in rows:
        transition_action(session, str(other), ActionStatus.SUPERSEDED)
        ledger.append(
            episode_id=episode_id,
            action_id=other,
            event={"type": "ACTION_SUPERSEDED", "reason": "earlier action recovered"},
            at=observed_at,
        )
    # expire undecided approvals tied to this episode
    session.execute(
        text(
            "UPDATE runtime.approvals SET decided_at = now(), decision = 'decline', reason = 'superseded by recovery' "
            "WHERE episode_id = :e AND decided_at IS NULL"
        ),
        {"e": episode_id},
    )

    session.execute(
        text("UPDATE runtime.episodes SET status = 'recovered' WHERE id = :e"),
        {"e": episode_id},
    )
    log.info("episode_recovered", episode_id=episode_id, attribution=str(action_id))
    return True


def apply_watch_window_expiry(
    session: Session,
    *,
    episode_id: str,
    action_id: str,
    observed_at: datetime,
) -> str:
    """Watch window elapsed without success → failed → re-plan or stop.

    Returns one of: REPLAN | STOPPED_CAP | IGNORED
    """
    ep = _episode(session, episode_id)
    if ep is None or ep["status"] != "observing":
        return "IGNORED"

    ledger = LedgerWriter(session)
    session.execute(
        text(
            "INSERT INTO runtime.outcomes (episode_id, action_id, outcome, observed_at) "
            "VALUES (:e, CAST(:a AS uuid), 'failed', :obs)"
        ),
        {"e": episode_id, "a": action_id, "obs": observed_at},
    )
    ledger.append(
        episode_id=episode_id,
        action_id=action_id,
        event={"type": "WATCH_WINDOW_EXPIRED", "result": "no recovery in window"},
        at=observed_at,
    )

    if ep["actions_used"] >= 4:
        session.execute(
            text("UPDATE runtime.episodes SET status = 'stopped_cap' WHERE id = :e"),
            {"e": episode_id},
        )
        ledger.append(
            episode_id=episode_id,
            action_id=None,
            event={"type": "EPISODE_STOPPED_CAP", "actions_used": ep["actions_used"]},
            at=observed_at,
        )
        return "STOPPED_CAP"

    session.execute(
        text("UPDATE runtime.episodes SET status = 'diagnosed' WHERE id = :e"),
        {"e": episode_id},
    )
    return "REPLAN"


def stop_customer(
    session: Session,
    *,
    episode_id: str,
    customer_id: str,
    reason_reason: str,
    suppression_source: str,
    at: datetime,
) -> None:
    """COMPLAINT/OPTOUT path: instant global suppression + human handoff (F5).

    A single global advisory lock (session-scoped, ms hold) serializes the
    suppression upsert across concurrent arms/workers — deadlock-proof under
    parallel eval (see lock-history note below).
    """
    from reflex.core.enums import SuppressionReason

    reason = (
        SuppressionReason.COMPLAINT
        if "complaint" in reason_reason.lower()
        else SuppressionReason.OPTOUT
    )
    # Single global lock, SESSION-scoped and held only across the upsert.
    # History: per-customer keys interleaved across parallel arms into wait
    # cycles; the first fix used pg_advisory_XACT_lock(723302), which couples
    # the critical section to the CALLER'S ENTIRE TRANSACTION — at eval scale
    # (N=3000 x 4 parallel arms) that starved every arm behind one idle-in-
    # transaction holder. A session-level lock released in `finally` keeps the
    # single-key no-cycle property with millisecond hold times.
    #
    # NO exception swallowing here: a Postgres deadlock victim must propagate
    # so the caller rolls back and retries — swallowing leaves the transaction
    # aborted and poisons every later statement in the arm.
    locked = False
    try:
        session.execute(text("SELECT pg_advisory_lock(723302)"))
        locked = True
        with session.begin_nested():
            session.execute(
                text(
                    "INSERT INTO runtime.suppressions (customer_id, reason, source) "
                    "VALUES (CAST(:c AS uuid), CAST(:r AS runtime.suppression_reason), :s) "
                    "ON CONFLICT (customer_id, reason) DO NOTHING"
                ),
                {"c": customer_id, "r": reason.value, "s": suppression_source},
            )
    finally:
        if locked:
            try:
                session.execute(text("SELECT pg_advisory_unlock(723302)"))
            except Exception:
                # Aborted/deadlocked transaction: end it so the pooled
                # connection resets and releases session-level locks.
                session.rollback()
                raise
    ledger = LedgerWriter(session)
    ledger.append(
        episode_id=episode_id,
        action_id=None,
        event={
            "type": "CUSTOMER_SUPPRESSED",
            "reason": reason.value,
            "handoff": "human handoff filed to approval queue",
        },
        at=at,
    )
    try:
        with session.begin_nested():
            session.execute(
                text("UPDATE runtime.episodes SET status = 'stopped_customer' WHERE id = :e AND status NOT IN ('recovered','expired','halted')"),
                {"e": episode_id},
            )
    except Exception:
        pass  # terminal already (e.g., escalated) — suppression itself persisted


def escalate_human(session: Session, *, episode_id: str, note: str, at: datetime) -> None:
    session.execute(
        text("UPDATE runtime.episodes SET status = 'escalated' WHERE id = :e AND status IN ('diagnosed','observing','waiting_diagnosis')"),
        {"e": episode_id},
    )
    LedgerWriter(session).append(
        episode_id=episode_id,
        action_id=None,
        event={"type": "ESCALATED_HUMAN", "note": note},
        at=at,
    )


def expire_due(session: Session, now_sim: datetime) -> int:
    """72h expiry sweep + fail-closed approval timeout auto-decline."""
    count = 0
    rows = session.execute(
        text(
            "SELECT id FROM runtime.episodes "
            "WHERE closes_at <= :now AND status NOT IN "
            "('recovered','expired','stopped_cap','stopped_low_ev','stopped_customer',"
            "'stopped_approval_declined','escalated','halted') LIMIT 500"
        ),
        {"now": now_sim},
    ).scalars().all()
    ledger = LedgerWriter(session)
    for episode_id in rows:
        session.execute(
            text("UPDATE runtime.episodes SET status = 'expired' WHERE id = :e"),
            {"e": episode_id},
        )
        session.execute(
            text(
                "INSERT INTO runtime.outcomes (episode_id, action_id, outcome, observed_at) "
                "VALUES (:e, NULL, 'expired', :now)"
            ),
            {"e": episode_id, "now": now_sim},
        )
        ledger.append(
            episode_id=episode_id,
            action_id=None,
            event={"type": "EPISODE_EXPIRED", "window_hours": 72},
            at=now_sim,
        )
        count += 1

    # approval timeout auto-decline (fail-closed, AppFlow §10 step 5)
    cutoff = now_sim - timedelta(hours=4)
    approvals = session.execute(
        text(
            """
            SELECT ap.id, ap.action_id, ap.episode_id, e.closes_at
            FROM runtime.approvals ap
            JOIN runtime.episodes e ON e.id = ap.episode_id
            WHERE ap.decided_at IS NULL
              AND ap.requested_at <= :cutoff
            """
        ),
        {"cutoff": cutoff},
    ).mappings().all()
    approvals += session.execute(
        text(
            """
            SELECT ap.id, ap.action_id, ap.episode_id, e.closes_at
            FROM runtime.approvals ap
            JOIN runtime.episodes e ON e.id = ap.episode_id
            WHERE ap.decided_at IS NULL
              AND e.id = ANY(CAST(:expired AS uuid[]))
            """
        ),
        {"expired": list(rows)},
    ).mappings().all() if rows else []

    for ap in approvals:
        decided = session.execute(
            text(
                "UPDATE runtime.approvals SET decided_at = :now, decision = 'decline', "
                "reason = 'timeout auto-decline (fail-closed)' WHERE id = :id AND decided_at IS NULL RETURNING id"
            ),
            {"now": now_sim, "id": ap["id"]},
        ).first()
        if decided is None:
            continue
        transition_action(session, str(ap["action_id"]), ActionStatus.BLOCKED)
        ledger.append(
            episode_id=ap["episode_id"],
            action_id=ap["action_id"],
            event={"type": "APPROVAL_TIMEOUT_DECLINED", "reason": "fail-closed"},
            at=now_sim,
        )
        session.execute(
            text(
                "UPDATE runtime.episodes SET status = 'stopped_approval_declined' WHERE id = :e "
                "AND status = 'waiting_approval'"
            ),
            {"e": ap["episode_id"]},
        )
    return count
