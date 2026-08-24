"""Reply/complaint classifier (AI-4) + keyword rule gate (defense in depth).

COMPLAINT ⇒ instant global suppression + human handoff (F5).
OPTOUT ⇒ permanent suppression.
AMBIGUOUS ⇒ treated as non-response (safe default, PRD §14 AI-4).

The keyword gate runs REGARDLESS of LLM availability — a complaint must never
be missed because the model was down (trust-killer per PRD §14).
"""

from __future__ import annotations

from dataclasses import dataclass

import structlog

from reflex.core.pii import scrub
from reflex.prompts import registry as prompts
from reflex.prompts.validators import parse_reply_intent
from reflex.workers.llm_client import LlmClient

log = structlog.get_logger("reflex.replies")

# Keyword allowlist — rule-gated COMPLAINT/OPTOUT detection (TechSpec §7 AI-4).
_COMPLAINT_KEYWORDS = (
    "harass", "harassment", "complaint", "complain", "fraud", "cheat",
    "consumer court", "consumer forum", "police", "legal action",
    "stop bothering", "bakwas", "galat", "pareshan", "sharminda",
    "worst service", "report you",
)
_OPTOUT_KEYWORDS = (
    "stop messaging", "unsubscribe", "opt out", "opt-out", "band karo",
    "mat bhejo", "nahin chahiye", "no more messages", "remove me",
)
_PROMISE_KEYWORDS = ("kal", "pakka", "promise", "will pay", "karta hoon", "karunga", "kar dungi", "friday", "monday", "salary")

# Sarcastic / negative-polarity phrases (P1-2): a sardonic "yes, take the money"
# is NOT a payment promise. These fire deterministically BEFORE LLM acceptance
# so a confident false-positive PROMISE/PAYING can never schedule another debit
# against an account the customer is saying is empty. Explicit COMPLAINT/OPTOUT
# keywords still outrank this gate (suppression classes are fail-closed).
_SARCASM_PHRASES = (
    # English sarcasm
    "debit my empty account",
    "empty account again",
    "take my money i don't have",
    "no money to pay you",
    # Hinglish sarcasm / stated inability
    "jab hai hi nahi",        # "...when there isn't any (money)"
    "jab hai hi nahin",
    "paisa hai hi nahi",
    "paisa hai hi nahin",
    "paise hai hi nahi",
    "paise hai hi nahin",
    "paise nahi hain",
    "kat lo paise",
    "kaat lo paise",
)


@dataclass(frozen=True)
class ReplyClassification:
    intent: str  # PROMISE | REFUSE | COMPLAINT | OPTOUT | PAYING | AMBIGUOUS
    promise_date: str | None
    method: str  # RULE | RULE+LLM | LLM | SAFE_DEFAULT
    rationale: str
    confidence: float = 1.0


def _rule_gate(text: str) -> tuple[str, str] | None:
    """(intent, matched keyword) when rules fire decisively."""
    low = text.lower()
    for kw in _OPTOUT_KEYWORDS:
        if kw in low:
            return ("OPTOUT", kw)
    for kw in _COMPLAINT_KEYWORDS:
        if kw in low:
            return ("COMPLAINT", kw)
    return None


def classify_reply(
    llm: LlmClient,
    *,
    reply_text: str,
    session=None,  # type: ignore[no-untyped-def]
    episode_id=None,  # type: ignore[no-untyped-def]
) -> ReplyClassification:
    clean = scrub(reply_text)

    # 1) deterministic keyword gate first (defense in depth; never skipped)
    ruled = _rule_gate(clean)
    if ruled is not None:
        intent, kw = ruled
        log.info("reply_rule_gate", intent=intent, keyword=kw)
        return ReplyClassification(intent, None, "RULE", f"keyword gate: {kw!r}", 1.0)

    # 1b) sarcasm/negative-polarity gate: never let a sardonic reply be read as
    # a promise to pay — safe AMBIGUOUS (non-response) instead of CONFIRM_RETRY.
    low = clean.lower()
    for phrase in _SARCASM_PHRASES:
        if phrase in low:
            log.info("reply_sarcasm_gate", phrase=phrase)
            return ReplyClassification(
                "AMBIGUOUS", None, "RULE", f"sarcasm/negative-polarity gate: {phrase!r}", 1.0
            )

    # 2) LLM classification with <data> wrapping + schema validation + retry-once
    if llm.configured and not llm.health.is_outage():
        purpose_log = {
            "purpose": "reply_classify",
            "prompt_hash": prompts.prompt_hash("reply_classify"),
            "input_redacted": {"reply": clean[:200]},
        }
        result = llm.complete(
            system_prompt=prompts.load("reply_classify"),
            user_payload=prompts.wrap_data({"reply": clean}),
            purpose_log=purpose_log,
            max_tokens=120,
            session=session,
            episode_id=episode_id,
        )
        parsed, valid = (None, False)
        if result is not None and result.ok:
            parsed, valid = parse_reply_intent(result.text)
            if not valid and result is not None:
                result = llm.complete(
                    system_prompt=prompts.load("reply_classify"),
                    user_payload=prompts.wrap_data({"reply": clean}),
                    purpose_log=purpose_log,
                    max_tokens=120,
                    session=session,
                    episode_id=episode_id,
                )
                if result.ok:
                    parsed, valid = parse_reply_intent(result.text)
        if valid and parsed is not None:
            # Confidence-gated fallback mirroring AI-1 (TASK-054): low-confidence
            # NON-suppression classes downgrade to the safe AMBIGUOUS default.
            # COMPLAINT/OPTOUT are exempt — suppression classes are fail-closed
            # (a missed complaint is the trust-killer per PRD §14 AI-4).
            conf = parsed.confidence
            intent = parsed.intent
            if conf < 0.6 and intent not in ("COMPLAINT", "OPTOUT"):
                log.info("reply_low_confidence_default", llm_intent=intent, confidence=conf)
                return ReplyClassification(
                    "AMBIGUOUS", None, "SAFE_DEFAULT",
                    f"low confidence {conf:.2f} on {intent}", conf,
                )
            # LLM may flag complaint/optout the keywords missed — trust it for
            # suppression classes (fail-closed direction), but AMBIGUOUS stays safe.
            date = parsed.promise_date
            return ReplyClassification(intent, date, "LLM", parsed.rationale[:120], conf)

    # 3) safe default: treat as non-response (PRD §14 AI-4 failure behavior)
    return ReplyClassification("AMBIGUOUS", None, "SAFE_DEFAULT", "classifier unavailable/invalid", 0.0)
