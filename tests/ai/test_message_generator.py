"""AI-3 regression: spelled-out number/currency words MUST be rejected (P1-1).

An LLM phrasing span can bypass the digit/₹ regex by verbalizing amounts
("teen sau rupaye", "do hazaar", "five hundred"). Every such span must be
rejected by MessageSpanValidator so generate_message falls back to the
deterministic slot-template (the ONLY place money-bearing content enters text).
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass

from reflex.core.enums import Channel
from reflex.prompts.validators import MessageSpanValidator
from reflex.workers.messages import MessageSlots, generate_message

# Every blacklisted word must trigger rejection on its own (Hinglish + English).
HINGLISH_NUMBER_WORDS = [
    "ek", "do", "teen", "char", "paanch", "chhah", "saat", "aath", "nau",
    "das", "sau", "hazaar", "lakh", "crore", "rupaye", "rupya", "paise",
]
ENGLISH_NUMBER_WORDS = [
    "zero", "one", "two", "three", "four", "five", "six", "seven", "eight",
    "nine", "ten", "hundred", "thousand", "rupees", "bucks",
]


@dataclass
class _FakeResult:
    ok: bool = True
    text: str = ""
    call_id: str | None = None


@dataclass
class _FakeHealth:
    def is_outage(self) -> bool:
        return False


@dataclass
class _FakeLlm:
    """Duck-typed LlmClient returning a canned span."""

    text: str | None
    configured: bool = True
    health: _FakeHealth = dataclasses.field(default_factory=_FakeHealth)

    def complete(self, **_kwargs):  # type: ignore[no-untyped-def]
        if self.text is None:
            return None
        return _FakeResult(text=self.text)


def _slots() -> MessageSlots:
    return MessageSlots(
        amount_paise=29_900,
        link_or_hint="https://rzp.io/i/demo-link",
        due_date="2026-09-01",
        customer_pseudonym="C-1042",
    )


def test_every_hinglish_number_word_rejected():
    for word in HINGLISH_NUMBER_WORDS:
        reason = MessageSpanValidator.reject_reason(f"Namaste ji, kripya {word} ka payment karein.")
        assert reason is not None, f"Hinglish word {word!r} was NOT rejected"


def test_every_english_number_word_rejected():
    for word in ENGLISH_NUMBER_WORDS:
        reason = MessageSpanValidator.reject_reason(f"Please pay the {word} pending amount.")
        assert reason is not None, f"English word {word!r} was NOT rejected"


def test_case_insensitive_and_mixed_script_bypass_rejected():
    for span in [
        "Teen Sau Rupaye pending hai",
        "DO HAZAAR only",
        "Five Hundred Rupees due",
        "just TEN bucks",
    ]:
        assert MessageSpanValidator.reject_reason(span) is not None, span


def test_verbalized_amount_spans_rejected_wholesale():
    for span in [
        "aapko teen sau rupaye chukana hain",
        "please pay five hundred at your convenience",
        "sirf do minute ka kaam hai",
    ]:
        assert MessageSpanValidator.reject_reason(span) is not None, span


def test_clean_non_numeric_span_still_passes():
    span = "Namaste! Chhoti si reminder — aapki payment pending hai, neeche link se pay kar dijiye."
    assert MessageSpanValidator.reject_reason(span) is None


def test_generate_message_falls_back_to_template_on_hinglish_loophole():
    llm = _FakeLlm(text="Aapki payment pending hai — teen sau rupaye jama kar dijiye.")
    result = generate_message(
        llm,
        contact_index=0,
        lang_pref="hinglish",
        slots=_slots(),
    )
    assert result.template_used is True
    assert result.validator_rejected_reason is not None
    assert "teen" in result.validator_rejected_reason or "rupaye" in result.validator_rejected_reason
    # The verbalized span never reaches the customer…
    assert "teen sau rupaye" not in result.final_text
    # …and the deterministic slot-template carries the real formatted amount.
    assert "₹299" in result.final_text
    assert result.final_text.index("₹299") >= 0  # slot-injected, not LLM-authored


def test_generate_message_accepts_clean_llm_span_with_slot_injection():
    llm = _FakeLlm(text="Namaste! Chhoti si reminder — aapki subscription payment pending hai.")
    result = generate_message(
        llm,
        contact_index=0,
        lang_pref="hinglish",
        slots=_slots(),
    )
    assert result.template_used is False
    assert result.validator_rejected_reason is None
    # DB-side slot injection appended AFTER the clean LLM span
    assert result.final_text.startswith("Namaste!")
    assert "Amount: ₹299" in result.final_text
    assert _slots().link_or_hint in result.final_text


def test_channel_helper_passthrough():
    from reflex.workers.messages import channel_for

    assert channel_for(Channel.WA_SIM) == Channel.WA_SIM
    assert channel_for(None) is None
