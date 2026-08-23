"""SQLAlchemy ORM models mirroring `5. Schema.md` exactly.

Money is BIGINT paise everywhere. The Alembic baseline owns DDL; these models
are the application-side view (no create_all anywhere).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    NUMERIC,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    SmallInteger,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from reflex.core import enums


class Base(DeclarativeBase):
    pass


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


class User(Base):
    __tablename__ = "users"
    __table_args__ = {"schema": "runtime"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(Text, unique=True)
    role: Mapped[enums.Role] = mapped_column(enums.Role)
    password_hash: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Merchant(Base):
    __tablename__ = "merchants"
    __table_args__ = {"schema": "runtime"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    name: Mapped[str]
    cfg: Mapped[dict[str, Any]] = mapped_column(JSONB)
    mode: Mapped[enums.Mode] = mapped_column(enums.Mode, default=enums.Mode.ADVISORY)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Customer(Base):
    __tablename__ = "customers"
    __table_args__ = {"schema": "runtime"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    merchant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runtime.merchants.id"))
    pseudonym: Mapped[str]
    vpa_masked: Mapped[str | None]
    lang_pref: Mapped[str] = mapped_column(Text, default="hinglish")
    ltv_band: Mapped[enums.LtvBand] = mapped_column(enums.LtvBand, default=enums.LtvBand.MID)
    dnd_flag: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PaymentEvent(Base):
    __tablename__ = "payment_events"
    __table_args__ = (
        CheckConstraint("amount_paise > 0", name="ck_pe_amount_positive"),
        {"schema": "runtime"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    provider_event_id: Mapped[str] = mapped_column(Text, unique=True)
    episode_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("runtime.episodes.id"))
    source: Mapped[enums.EventSource] = mapped_column(enums.EventSource)
    rail: Mapped[enums.Rail] = mapped_column(enums.Rail)
    code_raw: Mapped[str] = mapped_column(Text)
    amount_paise: Mapped[int] = mapped_column(BigInteger)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Episode(Base):
    __tablename__ = "episodes"
    __table_args__ = (
        CheckConstraint("amount_paise > 0", name="ck_ep_amount_positive"),
        CheckConstraint("actions_used BETWEEN 0 AND 4", name="ck_ep_actions_used"),
        {"schema": "runtime"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runtime.customers.id"))
    merchant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runtime.merchants.id"))
    payment_event_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runtime.payment_events.id"))
    amount_paise: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[enums.EpisodeStatus] = mapped_column(
        enums.EpisodeStatus, default=enums.EpisodeStatus.WAITING_DIAGNOSIS
    )
    arm: Mapped[enums.Arm] = mapped_column(enums.Arm, default=enums.Arm.REFLEX)
    actions_used: Mapped[int] = mapped_column(SmallInteger, default=0)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    closes_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Diagnosis(Base):
    __tablename__ = "diagnoses"
    __table_args__ = (
        CheckConstraint("confidence BETWEEN 0 AND 1", name="ck_dx_conf"),
        CheckConstraint("char_length(rationale) <= 240", name="ck_dx_rationale_len"),
        {"schema": "runtime"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    episode_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runtime.episodes.id"))
    canonical_code: Mapped[enums.CanonicalCode] = mapped_column(enums.CanonicalCode)
    confidence: Mapped[float] = mapped_column(NUMERIC(3, 2))
    method: Mapped[enums.DxMethod] = mapped_column(enums.DxMethod)
    rationale: Mapped[str] = mapped_column(Text)
    llm_call_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("runtime.llm_calls.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CandidateIntervention(Base):
    __tablename__ = "candidate_interventions"
    __table_args__ = (
        CheckConstraint("p_recover BETWEEN 0 AND 1", name="ck_ci_p"),
        {"schema": "runtime"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    episode_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runtime.episodes.id"))
    intervention: Mapped[enums.Intervention] = mapped_column(enums.Intervention)
    p_recover: Mapped[float] = mapped_column(NUMERIC(6, 4))
    expected_gain_paise: Mapped[int] = mapped_column(BigInteger)
    cost_paise: Mapped[int] = mapped_column(BigInteger)
    annoyance_paise: Mapped[int] = mapped_column(BigInteger)
    ev_paise: Mapped[int] = mapped_column(BigInteger)
    policy_version: Mapped[str] = mapped_column(Text)
    ranked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Action(Base):
    __tablename__ = "actions"
    __table_args__ = {"schema": "runtime"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    episode_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runtime.episodes.id"))
    intervention: Mapped[enums.Intervention] = mapped_column(enums.Intervention)
    status: Mapped[enums.ActionStatus] = mapped_column(
        enums.ActionStatus, default=enums.ActionStatus.PROPOSED
    )
    idempotency_key: Mapped[str] = mapped_column(Text, unique=True)
    channel: Mapped[enums.Channel | None] = mapped_column(enums.Channel)
    cost_paise: Mapped[int] = mapped_column(BigInteger, default=0)
    mode: Mapped[enums.Mode] = mapped_column(enums.Mode)
    policy_version: Mapped[str] = mapped_column(Text)
    guardrail_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    scheduled_for: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    message_final: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ActionLedgerRow(Base):
    __tablename__ = "action_ledger"
    __table_args__ = {"schema": "runtime"}

    seq: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    episode_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runtime.episodes.id"))
    action_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("runtime.actions.id"))
    event: Mapped[dict[str, Any]] = mapped_column(JSONB)
    prev_hash: Mapped[str] = mapped_column(Text)
    hash: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Outcome(Base):
    __tablename__ = "outcomes"
    __table_args__ = {"schema": "runtime"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    episode_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runtime.episodes.id"))
    action_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("runtime.actions.id"))
    outcome: Mapped[enums.OutcomeKind] = mapped_column(enums.OutcomeKind)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    latency_secs: Mapped[int | None] = mapped_column(Integer)


class PolicyVersion(Base):
    __tablename__ = "policy_versions"
    __table_args__ = {"schema": "runtime"}

    id: Mapped[str] = mapped_column(Text, primary_key=True)  # semver-ish: "v1"
    params: Mapped[dict[str, Any]] = mapped_column(JSONB)
    trained_on_batch: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class LlmCall(Base):
    __tablename__ = "llm_calls"
    __table_args__ = {"schema": "runtime"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    episode_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    purpose: Mapped[enums.LlmPurpose] = mapped_column(enums.LlmPurpose)
    prompt_hash: Mapped[str] = mapped_column(Text)
    input_redacted: Mapped[dict[str, Any]] = mapped_column(JSONB)
    output_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    valid: Mapped[bool] = mapped_column(Boolean, default=False)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    cost_usd: Mapped[float | None] = mapped_column(NUMERIC(10, 6))
    model: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Suppression(Base):
    __tablename__ = "suppressions"
    __table_args__ = (
        UniqueConstraint("customer_id", "reason", name="uq_suppression_customer_reason"),
        {"schema": "runtime"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runtime.customers.id"))
    reason: Mapped[enums.SuppressionReason] = mapped_column(enums.SuppressionReason)
    source: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Approval(Base):
    __tablename__ = "approvals"
    __table_args__ = {"schema": "runtime"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    episode_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runtime.episodes.id"))
    action_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runtime.actions.id"))
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decided_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("runtime.users.id"))
    decision: Mapped[enums.Decision | None] = mapped_column(enums.Decision)
    reason: Mapped[str | None] = mapped_column(Text)


class ModeChange(Base):
    __tablename__ = "mode_changes"
    __table_args__ = {"schema": "runtime"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    merchant_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    from_mode: Mapped[enums.Mode] = mapped_column(enums.Mode)
    to_mode: Mapped[enums.Mode] = mapped_column(enums.Mode)
    actor: Mapped[str] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(Text)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class GuardrailSettingsHistory(Base):
    __tablename__ = "guardrail_settings_history"
    __table_args__ = {"schema": "runtime"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    merchant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    diff: Mapped[dict[str, Any]] = mapped_column(JSONB)
    actor: Mapped[str] = mapped_column(Text)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SecurityEvent(Base):
    __tablename__ = "security_events"
    __table_args__ = {"schema": "runtime"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(Text)
    detail: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ---- replay schema (hidden simulator truth; agent role has NO grants) --------
class ReplayBatch(Base):
    __tablename__ = "replay_batches"
    __table_args__ = {"schema": "replay"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    seed: Mapped[int]
    n_episodes: Mapped[int]
    arm: Mapped[enums.Arm] = mapped_column(enums.Arm)
    simulator_version: Mapped[str]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SimCustomer(Base):
    """HIDDEN ground truth — never read by agent code paths (ADR-004)."""

    __tablename__ = "sim_customers"
    __table_args__ = {"schema": "replay"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    batch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("replay.replay_batches.id"))
    runtime_customer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    p_respond_by_channel: Mapped[dict[str, float]] = mapped_column(JSONB)
    salary_day: Mapped[int]
    annoyance_threshold: Mapped[float] = mapped_column(NUMERIC)
    intent: Mapped[str] = mapped_column(Text)
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class SimEvent(Base):
    __tablename__ = "sim_events"
    __table_args__ = {"schema": "replay"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    batch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("replay.replay_batches.id"))
    episode_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    t_offset_secs: Mapped[int]
    kind: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


# ---- eval schema --------------------------------------------------------------
class EvalRun(Base):
    __tablename__ = "eval_runs"
    __table_args__ = {"schema": "eval"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    batch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("replay.replay_batches.id"))
    arm: Mapped[enums.Arm] = mapped_column(enums.Arm)
    ablation: Mapped[str | None] = mapped_column(Text)
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    preregistered_tag: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class EvalMetric(Base):
    __tablename__ = "eval_metrics"
    __table_args__ = {"schema": "eval"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("eval.eval_runs.id"))
    metric: Mapped[str] = mapped_column(Text)
    value: Mapped[float | None] = mapped_column(NUMERIC)
    ci_low: Mapped[float | None] = mapped_column(NUMERIC)
    ci_high: Mapped[float | None] = mapped_column(NUMERIC)
    seed: Mapped[int | None] = mapped_column(Integer)
