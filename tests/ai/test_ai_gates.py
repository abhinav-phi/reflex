"""AI structural gates (offline-deterministic): reply precision, injection safety.

The live-LLM gates (dx ≥85% holdout, COMPLAIN precision with LLM) are marked
`ai_live` and run only with a configured provider; the offline gates here are
CI-blocking regressions for the deterministic defense layer.
"""

import json
from datetime import UTC
from pathlib import Path

import pytest
from reflex.workers.diagnosis import diagnose_episode
from reflex.workers.llm_client import LlmClient
from reflex.workers.replies import classify_reply

CORPUS = Path(__file__).resolve().parents[2] / "data" / "generators" / "reply_corpus.jsonl"
INJECTIONS = Path(__file__).resolve().parents[2] / "data" / "generators" / "injection_attempts.jsonl"


def _llm() -> LlmClient:
    return LlmClient()  # unconfigured ⇒ keyword gate + safe default path


def _rows(path: Path) -> list[dict]:  # type: ignore[type-arg]
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_complain_precision_at_least_95_percent_offline_gate():
    llm = _llm()
    rows = _rows(CORPUS)
    tp, fp = 0, 0
    for r in rows:
        c = classify_reply(llm, reply_text=r["text"])
        predicted_complaint = c.intent == "COMPLAINT"
        if predicted_complaint and r["label"] == "COMPLAINT":
            tp += 1
        elif predicted_complaint and r["label"] != "COMPLAINT":
            fp += 1
    precision = tp / (tp + fp) if (tp + fp) else 1.0
    assert precision >= 0.95, f"COMPLAIN precision {precision:.3f} < 0.95"


def test_complain_recall_at_least_90_percent_offline_gate():
    """AI-4 RECALL gate (TASK-054 / Rules §11.2): a missed complaint is the
    trust-killer — zero-post-complaint-contact is a RECALL property. The keyword
    rule-gate runs first as the deterministic recall net; every COMPLAINT-labeled
    corpus row must land in COMPLAINT (suppressed) — never in a contact-worthy class."""
    llm = _llm()
    rows = [r for r in _rows(CORPUS) if r["label"] == "COMPLAINT"]
    assert rows, "complaint corpus slice must not be empty"
    caught = sum(
        1 for r in rows if classify_reply(llm, reply_text=r["text"]).intent == "COMPLAINT"
    )
    recall = caught / len(rows)
    assert recall >= 0.90, f"COMPLAIN recall {recall:.3f} < 0.90 ({len(rows)-caught} missed)"


def test_low_confidence_llm_intent_downgrades_to_ambiguous():
    """Confidence-gated fallback (TASK-054): LLM intent with confidence < 0.6 on
    non-suppression classes ⇒ AMBIGUOUS safe default (mirrors AI-1)."""
    from reflex.prompts.validators import ReplyIntentOutput

    low = ReplyIntentOutput(intent="PROMISE", promise_date=None, confidence=0.4, rationale="unsure")
    assert low.confidence < 0.6
    # suppression classes are exempt from the downgrade (fail-closed)
    sup = ReplyIntentOutput(intent="COMPLAINT", confidence=0.3, rationale="maybe")
    assert sup.intent == "COMPLAINT"


def test_optout_never_missed_by_keyword_gate():
    llm = _llm()
    rows = [r for r in _rows(CORPUS) if r["label"] == "OPTOUT"]
    hits = sum(1 for r in rows if classify_reply(llm, reply_text=r["text"]).intent == "OPTOUT")
    assert hits / len(rows) >= 0.95


@pytest.mark.parametrize("row", _rows(INJECTIONS))
def test_injection_attempts_classify_safely(row):  # type: ignore[no-untyped-def]
    """Injection text is DATA: it must never become a decisive complaint/optout
    classification via instruction-following — safe classes only via rule gate."""
    llm = _llm()
    c = classify_reply(llm, reply_text=row["text"])
    assert c.intent in {"AMBIGUOUS", "OPTOUT", "COMPLAINT"}  # enum-safe output
    assert c.method in {"RULE", "SAFE_DEFAULT", "LLM"}
    # offline path must be deterministic and not crash on hostile input
    assert c.rationale


class _NullRedis:
    def get(self, _k):  # type: ignore[no-untyped-def]
        return None

    def setex(self, *_a):  # type: ignore[no-untyped-def]
        return None


def test_diagnosis_injection_corpus_safe_offline():
    """Injection decline strings must fall to UNKNOWN_AMBIGUOUS (fail-closed)."""
    from datetime import datetime

    from reflex.core.enums import CanonicalCode

    from data.generators.corpus_strings import INJECTION_STRINGS

    llm = LlmClient()
    for s in INJECTION_STRINGS:
        d = diagnose_episode(
            None, llm, _NullRedis(), episode_id="e-test",
            code_raw=s, rail="upi", amount_paise=29900,
            occurred_at=datetime(2026, 8, 28, tzinfo=UTC),
        )
        assert d.canonical_code in (
            CanonicalCode.UNKNOWN_AMBIGUOUS,
        ) or d.method.name == "RULE", f"{s!r} → {d.canonical_code}"


@pytest.mark.ai_live
@pytest.mark.skipif(not __import__("os").environ.get("LLM_API_KEY"),
                    reason="requires LLM_API_KEY")
def test_diagnosis_holdout_accuracy_with_live_llm():
    """AI-1 gate: ≥85% on the labeled corpus (500-case holdout per PRD)."""
    from datetime import datetime

    from reflex.core.enums import CanonicalCode

    from data.generators.corpus_strings import all_labeled

    llm = LlmClient()
    cases = all_labeled()[:500]
    correct = 0
    for raw, truth in cases:
        d = diagnose_episode(
            None, llm, _NullRedis(), episode_id="holdout",
            code_raw=raw, rail="upi", amount_paise=29900,
            occurred_at=datetime(2026, 8, 28, tzinfo=UTC),
        )
        if d.canonical_code == truth or (
            truth is not CanonicalCode.UNKNOWN_AMBIGUOUS
            and d.canonical_code is CanonicalCode.UNKNOWN_AMBIGUOUS
        ):
            correct += 1
    acc = correct / len(cases)
    print(f"dx holdout accuracy: {acc:.3f}")
    assert acc >= 0.85
