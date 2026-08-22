"""Core domain enums — single source of truth mirroring `5. Schema.md` §5.

DB enums are generated from this file by the Alembic baseline; Pydantic mirrors
these values (`packages/core/schemas.py`); TS types are generated from Pydantic.
"""

from enum import StrEnum


class Rail(StrEnum):
    CARD = "card"
    UPI = "upi"
    NETBANKING = "netbanking"
    WALLET = "wallet"
    NACH_EMANDATE = "nach_emandate"


class CanonicalCode(StrEnum):
    INSUFFICIENT_FUNDS = "INSUFFICIENT_FUNDS"
    ISSUER_DOWNTIME = "ISSUER_DOWNTIME"
    EXPIRED_CARD = "EXPIRED_CARD"
    AUTH_DECLINED_SOFT = "AUTH_DECLINED_SOFT"
    AUTH_DECLINED_HARD = "AUTH_DECLINED_HARD"
    RISK_HELD = "RISK_HELD"
    MANDATE_REVOKED = "MANDATE_REVOKED"
    MANDATE_LIMIT_BREACH = "MANDATE_LIMIT_BREACH"
    INVALID_VPA = "INVALID_VPA"
    CUSTOMER_INITIATED = "CUSTOMER_INITIATED"
    UNKNOWN_AMBIGUOUS = "UNKNOWN_AMBIGUOUS"


class Intervention(StrEnum):
    RETRY_SAME_RAIL = "RETRY_SAME_RAIL"
    RETRY_ALT_RAIL = "RETRY_ALT_RAIL"
    PAYMENT_LINK_PUSH = "PAYMENT_LINK_PUSH"
    UPI_LINK_PUSH = "UPI_LINK_PUSH"
    VOICE_CALL_SIM = "VOICE_CALL_SIM"
    MANDATE_REREG_SIM = "MANDATE_REREG_SIM"
    WAIT = "WAIT"
    STOP_LOW_EV = "STOP_LOW_EV"
    ESCALATE_HUMAN = "ESCALATE_HUMAN"


class Channel(StrEnum):
    WA_SIM = "wa_sim"
    SMS_SIM = "sms_sim"
    EMAIL_SIM = "email_sim"
    VOICE_SIM = "voice_sim"
    RAZORPAY_TM = "razorpay_tm"
    NONE = "none"


class EpisodeStatus(StrEnum):
    WAITING_DIAGNOSIS = "waiting_diagnosis"
    DIAGNOSED = "diagnosed"
    WAITING_APPROVAL = "waiting_approval"
    SCHEDULED = "scheduled"
    ACTED = "acted"
    OBSERVING = "observing"
    RECOVERED = "recovered"
    EXPIRED = "expired"
    STOPPED_CAP = "stopped_cap"
    STOPPED_LOW_EV = "stopped_low_ev"
    STOPPED_CUSTOMER = "stopped_customer"
    STOPPED_APPROVAL_DECLINED = "stopped_approval_declined"
    ESCALATED = "escalated"
    HALTED = "halted"

    @classmethod
    def terminal(cls) -> frozenset["EpisodeStatus"]:
        return frozenset(
            {
                cls.RECOVERED,
                cls.EXPIRED,
                cls.STOPPED_CAP,
                cls.STOPPED_LOW_EV,
                cls.STOPPED_CUSTOMER,
                cls.STOPPED_APPROVAL_DECLINED,
                cls.ESCALATED,
                cls.HALTED,
            }
        )


class ActionStatus(StrEnum):
    PROPOSED = "proposed"
    SHIELD_PASS = "shield_pass"
    SCHEDULED = "scheduled"
    DISPATCHED = "dispatched"
    DELIVERED_SIM = "delivered_sim"
    OBSERVED = "observed"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    BLOCKED = "blocked"
    WAITING_APPROVAL = "waiting_approval"
    CANCELLED_HALT = "cancelled_halt"
    SUPERSEDED = "superseded"
    PARKED = "parked"

    @classmethod
    def terminal(cls) -> frozenset["ActionStatus"]:
        return frozenset(
            {
                cls.SUCCEEDED,
                cls.FAILED,
                cls.BLOCKED,
                cls.CANCELLED_HALT,
                cls.SUPERSEDED,
            }
        )


class OutcomeKind(StrEnum):
    RECOVERED = "recovered"
    FAILED = "failed"
    EXPIRED = "expired"


class Role(StrEnum):
    VIEWER = "viewer"
    OPERATOR = "operator"
    APPROVER = "approver"
    ADMIN = "admin"


ROLE_ORDER: dict[Role, int] = {
    Role.VIEWER: 0,
    Role.OPERATOR: 1,
    Role.APPROVER: 2,
    Role.ADMIN: 3,
}


class Mode(StrEnum):
    ADVISORY = "advisory"
    AUTONOMOUS = "autonomous"
    DEGRADED = "degraded"
    HALTED = "halted"


class Arm(StrEnum):
    REFLEX = "reflex"
    B0 = "b0"
    B1 = "b1"


class DxMethod(StrEnum):
    RULE = "rule"
    LLM = "llm"


class EventSource(StrEnum):
    LIVE_TM = "live_tm"
    REPLAY = "replay"


class SuppressionReason(StrEnum):
    COMPLAINT = "complaint"
    OPTOUT = "optout"
    DND = "dnd"
    ADMIN = "admin"


class LtvBand(StrEnum):
    LOW = "low"
    MID = "mid"
    HIGH = "high"


class Decision(StrEnum):
    APPROVE = "approve"
    DECLINE = "decline"


class LlmPurpose(StrEnum):
    DIAGNOSIS = "diagnosis"
    MESSAGE = "message"
    REPLY_CLASSIFY = "reply_classify"


# Product-level guardrail constants (PRD §15 / Rules §3.4) — hard, non-overridable.
MAX_ACTIONS_PER_EPISODE = 4
MAX_CONTACTS_PER_CUSTOMER_PER_DAY = 2
DAILY_BUDGET_PAISE = 500_000  # ₹5,000
QUIET_HOURS_START = 21  # 21:00 IST inclusive
QUIET_HOURS_END = 9  # 09:00 IST exclusive
APPROVAL_THRESHOLD_PAISE = 5_000_000  # ₹50,000
EPISODE_WINDOW_HOURS = 72
APPROVAL_TIMEOUT_HOURS_SIM = 4

# Confidence gate for LLM outputs (Rules §2.5)
LOW_CONFIDENCE_THRESHOLD = 0.6

# Tone bands per contact index (TechSpec §7 AI-3)
TONE_BANDS = ("GENTLE", "FIRM", "URGENT")

# Watch window default (PRD FR-015)
DEFAULT_WATCH_WINDOW_HOURS_SIM = 6
