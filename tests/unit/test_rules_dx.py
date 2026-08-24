"""Rules-first diagnosis coverage ≥70% (FR-004) + ambiguous tail + injection safety."""

from reflex.core.enums import CanonicalCode
from reflex.workers.rules_dx import diagnose_rules

from data.generators.corpus_strings import (
    DECLINE_STRINGS,
    INJECTION_STRINGS,
    RULES_MISS_STRINGS,
)


def test_rules_cover_at_least_70_percent_of_classifiable():
    hits = 0
    total = 0
    for code, strings in DECLINE_STRINGS.items():
        for s in strings:
            total += 1
            hit = diagnose_rules(s)
            if hit is not None and hit.canonical_code == CanonicalCode(code):
                hits += 1
    coverage = hits / total
    assert coverage >= 0.70, f"rules coverage {coverage:.2%} < 70% ({hits}/{total})"


def test_ambiguous_tail_falls_through():
    for s in RULES_MISS_STRINGS:
        assert diagnose_rules(s) is None, s


def test_injection_strings_do_not_map_to_codes():
    """Injection attempts must never be confidently classified by string rules."""
    for s in INJECTION_STRINGS:
        hit = diagnose_rules(s)
        # either no hit (→ LLM tail with <data> defense) or explicitly UNKNOWN
        assert hit is None or hit.canonical_code is CanonicalCode.UNKNOWN_AMBIGUOUS
