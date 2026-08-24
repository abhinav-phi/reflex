"""Validator gates: 100% digit/URL/₹ rejection corpus + schema parsers (Rules §2.2)."""

import pytest
from reflex.prompts.validators import (
    MessageSpanValidator,
    parse_diagnosis,
    parse_reply_intent,
)

# Adversarial LLM spans that MUST be rejected (any digit/http/₹/UPI-)
REJECTION_CORPUS = [
    "Pay ₹299 today",
    "visit http://pay.example.com now",
    "https://rzp.io/i/abc123",
    "amount is 299 rupees",
    "call us at 9876543210",
    "UPI-quick@bank handle",
    "your OTP is 4821",
    "due by 2026-09-01",
    "only 5 minutes left, 50% off",
    "₹",
    "1",
    "card ending 4242 4242 4242 4242",
    "pay via UPI-id x@ybl",
    "deadline 30/09",
]


@pytest.mark.parametrize("span", REJECTION_CORPUS)
def test_digit_bearing_spans_rejected(span):
    reason = MessageSpanValidator.reject_reason(span)
    assert reason is not None


CLEAN_SPANS = [
    "Namaste! Chhoti si reminder — aapki payment pending hai.",
    "Hi! A gentle nudge about your pending payment. Pay securely using the link below.",
    "Service pause hone se pehle payment kar dijiye. Shukriya!",
]


@pytest.mark.parametrize("span", CLEAN_SPANS)
def test_clean_spans_pass(span):
    assert MessageSpanValidator.reject_reason(span) is None


def test_diagnosis_parser():
    ok_json = '{"canonical_code": "INSUFFICIENT_FUNDS", "confidence": 0.9, "rationale": "balance"}'
    d, valid = parse_diagnosis(ok_json)
    assert valid and d.canonical_code == "INSUFFICIENT_FUNDS" and d.confidence == 0.9
    fenced = f"```json\n{ok_json}\n```"
    d2, valid2 = parse_diagnosis(fenced)
    assert valid2

    bad, vbad = parse_diagnosis('{"canonical_code": "NOT_A_CODE", "confidence": 0.9}')
    assert not vbad and bad is None
    conf_bad, vcb = parse_diagnosis(
        '{"canonical_code": "EXPIRED_CARD", "confidence": 1.7, "rationale": "x"}')
    assert not vcb


def test_reply_intent_parser():
    r, ok = parse_reply_intent('{"intent": "PROMISE", "promise_date": null, "rationale": "x"}')
    assert ok and r.intent == "PROMISE"
    _, bad = parse_reply_intent('{"intent": "PROMISE", "promise_date": "tomorrow"}')
    assert not bad
    _, bad2 = parse_reply_intent('{"intent": "SOMETHING"}')
    assert not bad2
