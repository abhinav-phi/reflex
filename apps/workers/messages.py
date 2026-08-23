"""Message generation: skeleton → LLM phrasing (no digits) → DB slot injection →
validator → template fallback (PRD FR-009, TechSpec §7 AI-3).

The LLM NEVER authors an amount, link, deadline, or UPI handle — slots are
injected from DB data after generation; the validator rejects any digit/URL/₹/
UPI- span in LLM text (Rules §2.2), logging the rejection diff.
"""

from __future__ import annotations

from dataclasses import dataclass

import structlog

from reflex.core.enums import Channel
from reflex.core.money import format_inr
from reflex.prompts import registry as prompts
from reflex.prompts.validators import MessageSpanValidator
from reflex.workers.llm_client import LlmClient

log = structlog.get_logger("reflex.messages")


@dataclass(frozen=True)
class MessageSlots:
    amount_paise: int
    link_or_hint: str  # payment link URL or UPI-app hint (DB-sourced)
    due_date: str  # ISO date string (DB-derived deadline)
    customer_pseudonym: str


@dataclass(frozen=True)
class GeneratedMessage:
    final_text: str
    llm_span: str | None  # None ⇒ template fallback used
    validator_rejected_reason: str | None
    template_used: bool


_TEMPLATES: dict[tuple[str, str], str] = {
    # tone band × language → deterministic skeleton phrasing around slots
    ("GENTLE", "hinglish"): "Namaste {name} ji! Aapki {amount} ki payment pending hai. Neeche diye link se aaram se pay kar dijiye: {link} (by {due}). Dhanyavaad!",
    ("GENTLE", "en"): "Hi {name}, your payment of {amount} is pending. You can pay securely here: {link} by {due}. Thank you!",
    ("FIRM", "hinglish"): "{name} ji, reminder — {amount} ka payment abhi tak pending hai. Kripya {due} tak ye link se pay karein: {link}. Service continue rakhne ke liye zaroori hai.",
    ("FIRM", "en"): "{name}, reminder: your {amount} payment is still pending. Please pay via this link by {due}: {link}. Required to keep your service active.",
    ("URGENT", "hinglish"): "{name} ji, alert — {amount} ka payment {due} tak nahi hua to service pause ho jayegi. Turant pay karein: {link}",
    ("URGENT", "en"): "{name}, urgent: if the {amount} payment is not completed by {due}, your service will pause. Pay now: {link}",
}


def _tone_band(contact_index: int) -> str:
    return ("GENTLE", "FIRM", "URGENT")[min(contact_index, 2)]


def _skeleton(tone_band: str, lang: str) -> tuple[str, str]:
    """Slot skeleton with placeholder spans the LLM may rephrase around."""
    if lang == "hinglish":
        return (
            f"{tone_band} hinglish message: customer ke liye payment reminder likho "
            "jisme payment amount, secure link aur due date ka zikr friendly tarike se ho.",
            "",
        )
    return (
        f"{tone_band} english message: write a payment reminder that mentions the "
        "amount, secure link and due date politely.",
        "",
    )


def _inject_slots(phrasing_body: str, slots: MessageSlots) -> str:
    """DB-side slot injection — the ONLY place money-bearing content enters text."""
    amount = format_inr(slots.amount_paise)
    parts = [phrasing_body.strip()]
    parts.append(f"Amount: {amount}. Pay here: {slots.link_or_hint}. Due by: {slots.due_date}.")
    return " ".join(p for p in parts if p)


def generate_message(
    llm: LlmClient,
    *,
    contact_index: int,
    lang_pref: str,
    slots: MessageSlots,
    session=None,  # type: ignore[no-untyped-def]
    episode_id=None,  # type: ignore[no-untyped-def]
    personalization_enabled: bool = True,
) -> GeneratedMessage:
    tone = _tone_band(contact_index)
    template = _TEMPLATES[(tone, "hinglish" if lang_pref == "hinglish" else "en")].format(
        name=slots.customer_pseudonym,
        amount=format_inr(slots.amount_paise),
        link=slots.link_or_hint,
        due=slots.due_date,
    )

    if not personalization_enabled or not llm.configured or llm.health.is_outage():
        # A3 ablation / degraded / unconfigured ⇒ deterministic template path
        return GeneratedMessage(final_text=template, llm_span=None, validator_rejected_reason=None, template_used=True)

    purpose_log = {
        "purpose": "message",
        "prompt_hash": prompts.prompt_hash("message"),
        "input_redacted": {"tone": tone, "lang": lang_pref, "contact_index": contact_index},
    }
    result = llm.complete(
        system_prompt=prompts.load("message"),
        user_payload=prompts.wrap_data(
            {"task": _skeleton(tone, lang_pref)[0], "lang": lang_pref, "tone": tone}
        ),
        purpose_log=purpose_log,
        max_tokens=120,
        temperature=0.7,
        session=session,
        episode_id=episode_id,
    )
    if result is None or not result.ok:
        log.info("message_template_fallback", reason="llm_unavailable")
        return GeneratedMessage(final_text=template, llm_span=None, validator_rejected_reason=None, template_used=True)

    reason = MessageSpanValidator.reject_reason(result.text)
    if reason is not None:
        # F4: strip/reject + regenerate once would burn another call; spec says
        # reject ⇒ template fallback ⇒ log diff.
        log.warning(
            "validator_rejected_llm_message",
            reason=reason,
            llm_span=result.text[:200],
            episode_id=str(episode_id),
        )
        return GeneratedMessage(
            final_text=template,
            llm_span=result.text,
            validator_rejected_reason=reason,
            template_used=True,
        )

    final = _inject_slots(result.text, slots)
    return GeneratedMessage(final_text=final, llm_span=result.text, validator_rejected_reason=None, template_used=False)


def channel_for(intervention_channel: Channel | None) -> Channel | None:
    return intervention_channel
