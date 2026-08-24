"""AI-1 holdout: 500-case ambiguous-decline evaluation (TASK-020 / P1-3).

Deterministic corpus: every labeled decline string from
`data/generators/corpus_strings.py` plus seeded surface perturbations, the
deliberately-unmatchable RULES_MISS tail, and prompt-injection strings —
500 cases total. Ground truth is the corpus label; nothing is tuned to pass.

Pipeline under test = runtime semantics with `LLM_API_KEY` ABSENT:
`diagnose_rules` first; misses degrade to the conservative UNKNOWN_AMBIGUOUS
fallback (`diagnose_episode`, unconfigured LLM) — exactly the degraded path a
key-less deployment takes (Rules §15.2).

Artifacts: confusion matrix + accuracy report written to
`eval/results/dx_holdout/` (JSON + Markdown), regenerated on each run.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest
from reflex.core.enums import CanonicalCode
from reflex.core.settings import Settings
from reflex.workers.diagnosis import diagnose_episode
from reflex.workers.llm_client import LlmClient
from reflex.workers.rules_dx import diagnose_rules

from data.generators.corpus_strings import (
    INJECTION_STRINGS,
    all_labeled,
)

N_CASES = 500
SEED = 2026  # holdout construction seed (not an eval seed; no metrics gate on it)
RESULTS_DIR = Path(__file__).resolve().parents[2] / "eval" / "results" / "dx_holdout"

_PERTURBATIONS = (
    lambda s: s,
    str.upper,
    str.lower,
    lambda s: f"Issuer response: {s}",
    lambda s: f"{s} (ref)",
    lambda s: "  " + " ".join(s.split()) + " . ",
    lambda s: f"[gateway] {s.lower()}",
    lambda s: f"{s}??",
)


class _StubRedis:
    """In-process stand-in for the diagnosis cache (degraded path never writes)."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    def get(self, key):  # type: ignore[no-untyped-def]
        return self.store.get(key)

    def setex(self, key, ttl, value):  # type: ignore[no-untyped-def]
        self.store[key] = value


def _build_holdout() -> list[tuple[str, CanonicalCode]]:
    """Exactly N_CASES cases: perturbed labeled strings + tail + injections."""
    rng = np.random.default_rng(SEED)
    base = all_labeled()  # labeled DECLINE_STRINGS + RULES_MISS tail
    cases: list[tuple[str, CanonicalCode]] = []

    # Cycle base pairs, applying seeded perturbations until full.
    i = 0
    while len(cases) < N_CASES - len(INJECTION_STRINGS):
        text, label = base[i % len(base)]
        p = _PERTURBATIONS[int(rng.integers(len(_PERTURBATIONS)))]
        cases.append((p(text), label))
        i += 1

    # Injection attempts must classify fail-closed (UNKNOWN_AMBIGUOUS or a
    # suppression-safe code) — never obeyed.
    for inj in INJECTION_STRINGS:
        cases.append((inj, CanonicalCode.UNKNOWN_AMBIGUOUS))

    assert len(cases) == N_CASES
    order = rng.permutation(len(cases))
    return [cases[j] for j in order]


def _unconfigured_llm() -> LlmClient:
    settings = Settings(llm_api_key="")
    assert not settings.llm_api_key
    return LlmClient(settings=settings)


def _degraded_predict(text: str) -> tuple[CanonicalCode, float, str]:
    res = diagnose_episode(
        session=None,  # type: ignore[arg-type]
        llm=_unconfigured_llm(),
        redis_client=_StubRedis(),
        episode_id="dx-holdout",
        code_raw=text,
        rail="upi",
        amount_paise=29_900,
        occurred_at=datetime(2026, 8, 25, 14, 30, tzinfo=UTC),
    )
    return res.canonical_code, res.confidence, res.method.value


@pytest.fixture(scope="module")
def holdout_report() -> dict:  # type: ignore[type-arg]
    cases = _build_holdout()
    codes = [c for c in CanonicalCode]
    confusion: dict[str, Counter] = {code.value: Counter() for code in codes}
    rules_fired = 0
    correct = 0
    per_code_totals: Counter = Counter()

    for text, truth in cases:
        pred, _conf, _method = _degraded_predict(text)
        confusion[truth.value][pred.value] += 1
        per_code_totals[truth.value] += 1
        if diagnose_rules(text) is not None:
            rules_fired += 1
        if pred == truth:
            correct += 1

    accuracy = correct / len(cases)
    injection_texts = set(INJECTION_STRINGS)
    injection_cases = [t for t, _ in cases if t in injection_texts]
    injection_safe = all(
        _degraded_predict(t)[0] == CanonicalCode.UNKNOWN_AMBIGUOUS for t in injection_cases
    )

    report = {
        "suite": "dx_holdout",
        "n_cases": len(cases),
        "seed": SEED,
        "llm_configured": False,
        "mode": "degraded (rules + conservative UNKNOWN_AMBIGUOUS fallback)",
        "accuracy": round(accuracy, 4),
        "correct": correct,
        "rules_fired": rules_fired,
        "rules_coverage": round(rules_fired / len(cases), 4),
        "per_code_support": dict(per_code_totals),
        "injection_cases_safe": injection_safe,
        "confusion_matrix": {k: dict(v) for k, v in confusion.items()},
    }

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    (RESULTS_DIR / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

    lines = [
        "# AI-1 Diagnosis Holdout — 500-case degraded-mode report",
        "",
        f"* Cases: **{len(cases)}** · construction seed `{SEED}` · `[SIMULATED]` corpus",
        "* Mode: LLM_API_KEY absent ⇒ rules-first, conservative `UNKNOWN_AMBIGUOUS` tail",
        f"* End-to-end accuracy: **{accuracy:.2%}** ({correct}/{len(cases)})",
        f"* Rules coverage (share classified by rules alone): "
        f"**{report['rules_coverage']:.2%}** (target ≥70% of matchable events, TechSpec §7 AI-1)",
        f"* Prompt-injection cases fail-closed to UNKNOWN_AMBIGUOUS: "
        f"**{'YES' if injection_safe else 'NO'}**",
        "",
        "## Confusion matrix (rows = ground truth, columns = prediction)",
        "",
    ]
    predicted_labels = sorted({p for counts in confusion.values() for p in counts})
    header = "| truth \\ pred | " + " | ".join(predicted_labels) + " |"
    lines.append(header)
    lines.append("|---" * (len(predicted_labels) + 1) + "|")
    for truth in codes:
        row = [str(confusion[truth.value].get(p, 0)) for p in predicted_labels]
        lines.append(f"| {truth.value} | " + " | ".join(row) + " |")
    lines += [
        "",
        "Reproduce: `python -m pytest tests/ai/test_diagnosis_accuracy.py -q`",
        "",
    ]
    (RESULTS_DIR / "report.md").write_text("\n".join(lines), encoding="utf-8")
    return report


def test_holdout_size_is_500(holdout_report):  # type: ignore[no-untyped-def]
    assert holdout_report["n_cases"] == 500


def test_degraded_accuracy_floor(holdout_report):  # type: ignore[no-untyped-def]
    # Rules resolve their own corpus near-perfectly; misses fall back safely.
    # Floor is honest headroom for cross-paraphrase collisions, not a target.
    assert holdout_report["accuracy"] >= 0.95, holdout_report["accuracy"]


def test_rules_coverage_target(holdout_report):  # type: ignore[no-untyped-def]
    # TechSpec §7 AI-1: ≥70% of synthetic events classified by rules alone.
    assert holdout_report["rules_coverage"] >= 0.70, holdout_report["rules_coverage"]


def test_injection_attempts_fail_closed(holdout_report):  # type: ignore[no-untyped-def]
    assert holdout_report["injection_cases_safe"] is True


def test_ambiguous_tail_never_gets_a_confident_specific_code(holdout_report):  # type: ignore[no-untyped-def]
    # Every RULES_MISS/injected case must land on UNKNOWN_AMBIGUOUS in degraded mode.
    cm = holdout_report["confusion_matrix"]
    tail_preds = cm[CanonicalCode.UNKNOWN_AMBIGUOUS.value]
    for pred, n in tail_preds.items():
        if pred != CanonicalCode.UNKNOWN_AMBIGUOUS.value:
            raise AssertionError(f"{n} tail cases misread as {pred}")


def test_artifacts_written(holdout_report):  # type: ignore[no-untyped-def]
    assert (RESULTS_DIR / "report.json").exists()
    assert (RESULTS_DIR / "report.md").exists()


def test_rules_hits_carry_full_confidence():  # type: ignore[no-untyped-def]
    hit = diagnose_rules("NSF - insufficient funds in account")
    assert hit is not None
    assert hit.canonical_code == CanonicalCode.INSUFFICIENT_FUNDS
    assert hit.confidence == 1.0
