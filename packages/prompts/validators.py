"""Output validators for every LLM purpose (Rules §2.1: never trust raw output).

- DiagnosisOutput / ReplyIntentOutput: strict Pydantic schemas; invalid ⇒ one
  retry by caller, second failure ⇒ deterministic fallback (UNKNOWN_AMBIGUOUS /
  non-response default).
- MessageSpanValidator: the digit/URL/₹ guard — rejects ANY digit, URL,
  rupee sign, or UPI prefix inside an LLM-generated span (Rules §2.2), plus any
  spelled-out number/currency word (Hinglish or English): an LLM can bypass the
  digit regex by verbalizing amounts ("teen sau rupaye", "five hundred"), so
  such spans are rejected wholesale and the deterministic slot-template renders
  the amount instead.
"""

from __future__ import annotations

import json
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator
from reflex.core.enums import CanonicalCode

# Validator regex per TechSpec §7 AI-3: any digit, http, ₹, or UPI- in an LLM span.
_FORBIDDEN = re.compile(r"\d|http|₹|UPI-", re.IGNORECASE)

# Spelled-out number/currency words (P1-1 "Hinglish loophole" fix). Matched as
# whole words, case-insensitive. Strictness is deliberate: a false-positive
# rejection costs only the safe deterministic template, while a miss lets an
# unverifiable verbalized amount reach a customer.
_NUMBER_WORDS: frozenset[str] = frozenset({
    # Hindi / Hinglish numerals & currency
    "ek", "do", "teen", "char", "paanch", "chhah", "saat", "aath", "nau",
    "das", "sau", "hazaar", "lakh", "crore", "rupaye", "rupya", "paise",
    # English numerals & currency
    "zero", "one", "two", "three", "four", "five", "six", "seven", "eight",
    "nine", "ten", "hundred", "thousand", "rupees", "bucks",
})

_SPAN_WORDS = re.compile(r"[A-Za-z]+")


class DiagnosisOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    canonical_code: CanonicalCode
    confidence: float
    rationale: str

    @field_validator("confidence")
    @classmethod
    def _conf_range(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            raise ValueError("confidence out of [0,1]")
        return round(v, 2)

    @field_validator("rationale")
    @classmethod
    def _rationale_len(cls, v: str) -> str:
        if len(v) > 200:
            raise ValueError("rationale too long")
        return v


class ReplyIntentOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent: Literal["PROMISE", "REFUSE", "COMPLAINT", "OPTOUT", "PAYING", "AMBIGUOUS"]
    promise_date: str | None = None
    confidence: float = 1.0  # v2 schema (TASK-054); v1 outputs default to 1.0
    rationale: str

    @field_validator("promise_date")
    @classmethod
    def _date_shape(cls, v: str | None) -> str | None:
        if v is None:
            return None
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
            raise ValueError("promise_date must be ISO date or null")
        return v

    @field_validator("confidence")
    @classmethod
    def _conf_range(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            raise ValueError("confidence out of [0,1]")
        return round(v, 2)


def parse_json_object(raw: str) -> dict | None:
    """Tolerate code fences; return dict or None."""
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE)
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        # last resort: first {...} block
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            return None
        try:
            obj = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    return obj if isinstance(obj, dict) else None


def parse_diagnosis(raw: str) -> tuple[DiagnosisOutput | None, bool]:
    obj = parse_json_object(raw)
    if obj is None:
        return None, False
    try:
        return DiagnosisOutput.model_validate(obj), True
    except Exception:
        return None, False


def parse_reply_intent(raw: str) -> tuple[ReplyIntentOutput | None, bool]:
    obj = parse_json_object(raw)
    if obj is None:
        return None, False
    try:
        return ReplyIntentOutput.model_validate(obj), True
    except Exception:
        return None, False


class MessageSpanValidator:
    @staticmethod
    def reject_reason(span: str) -> str | None:
        """Return a rejection reason, or None when span is clean."""
        match = _FORBIDDEN.search(span)
        if match is not None:
            start = max(0, match.start() - 20)
            return f"forbidden token {match.group(0)!r} near ...{span[start : match.end() + 20]!r}"
        for word in _SPAN_WORDS.findall(span):
            if word.lower() in _NUMBER_WORDS:
                start = max(0, span.lower().find(word.lower()) - 20)
                return f"spelled-out number/currency word {word!r} near ...{span[start : start + len(word) + 40]!r}"
        return None

    @staticmethod
    def is_clean(span: str) -> bool:
        return MessageSpanValidator.reject_reason(span) is None
