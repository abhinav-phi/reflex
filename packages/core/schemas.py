"""Boundary schemas (Pydantic) — mirrors `5. Schema.md` §10.

Web app TS types are generated from this module (scripts/gen_ts_types.py).
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Paise = Annotated[int, Field(strict=True, ge=1)]
NonNegInt = Annotated[int, Field(strict=True, ge=0)]


class ApiError(BaseModel):
    """Rules §6.2: errors are structured, never leak stack traces."""

    error: dict[str, str]  # {code, message, action?}


# ---- webhook ingestion (FR-001) ---------------------------------------------
RazorpayEventName = Literal[
    "payment.failed",
    "payment.captured",
    "subscription.charged",
    "subscription.halted",
    "subscription.cancelled",
]


class RazorpayWebhookPayload(BaseModel):
    """Subset of the public webhook schema we rely on; unknown fields preserved."""

    model_config = ConfigDict(extra="allow")

    event: str
    payload: dict[str, object]

    @field_validator("event")
    @classmethod
    def _known_event(cls, v: str) -> str:
        return v


class NormalizedFailureEvent(BaseModel):
    provider_event_id: str
    source: Literal["live_tm", "replay"]
    rail: str
    code_raw: str
    amount_paise: Paise
    occurred_at: datetime


class WebhookAck(BaseModel):
    accepted: bool
    duplicate: bool = False
    episode_id: str | None = None


# ---- API request bodies ------------------------------------------------------
class ReplayStartRequest(BaseModel):
    n: NonNegInt = Field(default=214)
    seed: str | int = "demo-7"
    arm: Literal["reflex", "b0", "b1"] = "reflex"
    speed: float = Field(default=100.0, gt=0)
    demo: bool = False


class ModeChangeRequest(BaseModel):
    mode: Literal["advisory", "autonomous", "degraded", "halted"]
    reason: str | None = None


class ApprovalDecisionRequest(BaseModel):
    decision: Literal["approve", "decline"]
    reason: str | None = None


class EvalRunRequest(BaseModel):
    config: dict[str, object] | None = None  # None ⇒ preregistered default


class LoginRequest(BaseModel):
    email: str
    password: str


class GuardrailSettingsUpdate(BaseModel):
    caps_per_episode: int | None = Field(default=None, ge=0, le=4)
    contacts_per_day: int | None = Field(default=None, ge=0, le=10)
    quiet_hours: str | None = None
    budget_paise_daily: int | None = Field(default=None, ge=0)
    approval_threshold_paise: int | None = Field(default=None, ge=0)


# ---- API response DTOs --------------------------------------------------------
class DiagnosisDto(BaseModel):
    canonical_code: str
    confidence: float
    method: str
    rationale: str
    created_at: datetime


class CandidateDto(BaseModel):
    intervention: str
    p_recover: float
    expected_gain_paise: int
    cost_paise: int
    annoyance_paise: int
    ev_paise: int
    policy_version: str


class ActionDto(BaseModel):
    id: str
    episode_id: str
    intervention: str
    status: str
    channel: str | None
    cost_paise: int
    mode: str
    policy_version: str
    guardrail_snapshot: dict[str, object]
    scheduled_for: datetime | None
    dispatched_at: datetime | None
    message_final: str | None
    created_at: datetime


class OutcomeDto(BaseModel):
    outcome: str
    action_id: str | None
    observed_at: datetime
    latency_secs: int | None


class EpisodeDto(BaseModel):
    id: str
    customer_pseudonym: str
    amount_paise: int
    status: str
    arm: str
    rail: str
    actions_used: int
    opened_at: datetime
    closes_at: datetime
    diagnosis: DiagnosisDto | None = None
    candidates: list[CandidateDto] = []
    actions: list[ActionDto] = []
    outcomes: list[OutcomeDto] = []


class LedgerEventDto(BaseModel):
    seq: int
    episode_id: str
    action_id: str | None
    event: dict[str, object]
    prev_hash: str
    hash: str
    created_at: datetime


class LedgerVerifyResponse(BaseModel):
    valid: bool
    first_bad_seq: int | None = None
    checked: int


class LiveMetrics(BaseModel):
    failed_today_paise: int
    recovered_reflex_paise: int
    recovered_b1_paise: int
    complaint_rate: float
    cost_per_100p: float | None
    episodes_open: int
    episodes_terminal: int
    speed: float
    mode: str


class CountersSnapshot(BaseModel):
    events_ingested: int
    duplicates_collapsed: int
    episodes_created: int
    dx_rule: int
    dx_llm: int
    shield_pass: int
    shield_block: int
    shield_approval: int
    dispatched: int
    recovered: int
