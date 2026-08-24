"""AI-4 regression: sarcasm & ambiguity must never read as a payment promise.

Sarcastic replies ("Sure, debit my empty account again!", "Kaat lo paise jab
hai hi nahi") must fall back to the safe AMBIGUOUS (non-response) default —
never PROMISE/PAYING, which downstream schedules another retry. Explicit
COMPLAINT/OPTOUT keyword hits still outrank everything (suppression is
fail-closed), and genuine promises remain classifiable.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass

from reflex.workers.replies import classify_reply


@dataclass
class _FakeResult:
    ok: bool = True
    text: str = ""


@dataclass
class _FakeHealth:
    outage: bool = False

    def is_outage(self) -> bool:
        return self.outage


@dataclass
class _FakeLlm:
    """Duck-typed LlmClient; replies with canned JSON (or fails)."""

    reply_json: str | None = None
    configured: bool = True
    health: _FakeHealth = dataclasses.field(default_factory=_FakeHealth)

    def complete(self, **_kwargs):  # type: ignore[no-untyped-def]
        if self.reply_json is None:
            return None
        return _FakeResult(text=self.reply_json)


def _llm_says(intent: str, confidence: float = 0.95) -> _FakeLlm:
    return _FakeLlm(
        reply_json=(
            f'{{"intent": "{intent}", "promise_date": null, '
            f'"confidence": {confidence}, "rationale": "test"}}'
        )
    )


# --- sarcastic replies must NEVER become PROMISE/PAYING -----------------------

def test_english_sarcasm_not_a_promise_even_when_llm_says_promise():
    llm = _llm_says("PROMISE")
    r = classify_reply(llm, reply_text="Sure, debit my empty account again!")
    assert r.intent == "AMBIGUOUS"
    assert r.method == "RULE"
    assert "sarcasm" in r.rationale


def test_hinglish_sarcasm_not_a_promise_even_when_llm_says_paying():
    llm = _llm_says("PAYING")
    r = classify_reply(llm, reply_text="Kaat lo paise jab hai hi nahi")
    assert r.intent == "AMBIGUOUS"
    assert r.method == "RULE"


def test_stated_inability_with_promise_keyword_falls_back_safe():
    # Contains the promise keyword "salary" AND a negative-polarity phrase —
    # the sarcasm gate must outrank the LLM's confident PROMISE.
    llm = _llm_says("PROMISE", confidence=0.9)
    r = classify_reply(llm, reply_text="Salary aayi tab bata diya, paise hai hi nahin abhi!")
    assert r.intent == "AMBIGUOUS"
    assert r.promise_date is None


# --- suppression keywords still outrank the sarcasm gate ----------------------

def test_sarcastic_complaint_still_suppresses():
    llm = _llm_says("PROMISE")
    r = classify_reply(llm, reply_text="Sure, harass me more, this is fraud!")
    assert r.intent == "COMPLAINT"
    assert r.method == "RULE"


def test_optout_keyword_wins_over_anything():
    llm = _llm_says("PROMISE")
    r = classify_reply(llm, reply_text="Band karo ye messages")
    assert r.intent == "OPTOUT"


# --- TASK-054 confidence fallback + safe defaults (regression) ----------------

def test_low_confidence_non_suppression_intent_downgrades_to_ambiguous():
    llm = _llm_says("PROMISE", confidence=0.4)
    r = classify_reply(llm, reply_text="ok maybe I will arrange something")
    assert r.intent == "AMBIGUOUS"
    assert r.method == "SAFE_DEFAULT"


def test_genuine_high_confidence_promise_still_classified():
    llm = _llm_says("PROMISE")
    r = classify_reply(llm, reply_text="Pakka kal pay kar dunga, salary aa gayi hai")
    assert r.intent == "PROMISE"
    assert r.method in ("LLM", "RULE+LLM")


def test_unconfigured_llm_yields_safe_default():
    llm = _FakeLlm(reply_json=None, configured=False)
    r = classify_reply(llm, reply_text="kuch bhi ho jaye")
    assert r.intent == "AMBIGUOUS"
    assert r.method == "SAFE_DEFAULT"
    assert r.confidence == 0.0


def test_invalid_llm_json_yields_safe_default_after_retry():
    llm = _FakeLlm(reply_json="not json at all {{{")
    r = classify_reply(llm, reply_text="thik hai dekh lunga")
    assert r.intent == "AMBIGUOUS"
    assert r.method == "SAFE_DEFAULT"
