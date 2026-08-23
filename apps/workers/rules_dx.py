"""Deterministic rules-first diagnosis (ADR-003, PRD FR-004).

Regex/lookup mapping of structured + messy decline strings to canonical codes,
confidence 1.0, method RULE. Anything unmatched falls through to the LLM tail
(caller's job). Target: ≥70% of synthetic events classified by rules alone;
p95 < 100 ms.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from reflex.core.enums import CanonicalCode


@dataclass(frozen=True)
class RuleHit:
    canonical_code: CanonicalCode
    confidence: float
    rationale: str


# Ordered patterns; first match wins. Patterns are case-insensitive.
_PATTERNS: tuple[tuple[re.Pattern[str], CanonicalCode, str], ...] = (
    (
        re.compile(r"revok|withdraw|auto.?pay.{0,12}cancell?|mandate.{0,16}(cancel|remov)", re.I),
        CanonicalCode.MANDATE_REVOKED,
        "mandate revoked/withdrawn by customer",
    ),
    (
        re.compile(r"customer.{0,20}cancell?|unsubscribe|self.?service|user.initiated", re.I),
        CanonicalCode.CUSTOMER_INITIATED,
        "customer-initiated cancellation",
    ),
    (
        re.compile(r"expired|validity over|expiry date passed|card_exp", re.I),
        CanonicalCode.EXPIRED_CARD,
        "instrument expired",
    ),
    (
        re.compile(
            r"stolen|permanen\w* block|card blocked|account closed|hard.?decline|do not charge",
            re.I,
        ),
        CanonicalCode.AUTH_DECLINED_HARD,
        "permanent issuer decline",
    ),
    (
        re.compile(r"risk (team|hold|review)|fraud suspicion|high.velocity flag|risk held", re.I),
        CanonicalCode.RISK_HELD,
        "issuer risk hold",
    ),
    (
        re.compile(
            r"downtime|bank.?down|issuer unavailable|issuer timeout|maintenance|link failure",
            re.I,
        ),
        CanonicalCode.ISSUER_DOWNTIME,
        "issuer downtime window",
    ),
    (
        re.compile(r"(insufficient|insuf|low)\s*(balance|bal|funds)|nsf\b|balance nahin|no enough balance", re.I),
        CanonicalCode.INSUFFICIENT_FUNDS,
        "insufficient funds at debit time",
    ),
    (
        re.compile(r"cap exceeded|mandate limit|limit breach|autopay cap|ceiling", re.I),
        CanonicalCode.MANDATE_LIMIT_BREACH,
        "mandate amount cap breached",
    ),
    (
        re.compile(r"invalid vpa|vpa does not exist|handle not found|invalid upi|handle resolution failed", re.I),
        CanonicalCode.INVALID_VPA,
        "invalid UPI handle",
    ),
    (
        re.compile(r"do not honor|soft.?decline|generic decline|code 05\b|transient|auth declined", re.I),
        CanonicalCode.AUTH_DECLINED_SOFT,
        "temporary auth decline",
    ),
)


def diagnose_rules(code_raw: str) -> RuleHit | None:
    """Return a confident RULE hit or None (⇒ LLM tail). Deterministic."""
    for pattern, code, why in _PATTERNS:
        if pattern.search(code_raw):
            return RuleHit(canonical_code=code, confidence=1.0, rationale=f"RULE match: {why}")
    return None
