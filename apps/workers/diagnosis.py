"""Diagnosis pipeline: rules-first, LLM tail (ADR-003 / TechSpec §7 AI-1).

Shared by the diagnosis worker and Proof's in-process replay pipeline so
runtime and eval semantics cannot drift.
"""

from __future__ import annotations

from dataclasses import dataclass

import structlog
from sqlalchemy import text
from sqlalchemy.orm import Session

from reflex.core.enums import CanonicalCode, DxMethod
from reflex.core.pii import scrub_payload
from reflex.prompts import registry as prompts
from reflex.prompts.validators import parse_diagnosis
from reflex.workers.llm_client import LlmClient
from reflex.workers.rules_dx import diagnose_rules

log = structlog.get_logger("reflex.diagnosis")

# Redis cache key prefix: hit rate expected >60% on replay (TechSpec §7).
CACHE_TTL_SECS = 6 * 3600


@dataclass(frozen=True)
class DiagnosisResult:
    canonical_code: CanonicalCode
    confidence: float
    method: DxMethod
    rationale: str


def _cache_key(code_raw: str, issuer: str | None) -> str:
    import hashlib

    h = hashlib.sha256(f"{code_raw}|{issuer or ''}".encode()).hexdigest()[:24]
    return f"reflex:dx:{h}"


def _llm_context(
    *,
    code_raw: str,
    rail: str,
    masked_issuer: str | None,
    day_of_month: int,
    hour: int,
    prior_code_counts: dict[str, int],
) -> dict:
    """Redacted, PII-free context per TechSpec §7 AI-1 input pipeline."""
    return {
        "raw_string": code_raw[:300],
        "rail": rail,
        "masked_issuer": masked_issuer or "unknown",
        "day_of_month": day_of_month,
        "hour": hour,
        "prior_code_counts": prior_code_counts,
    }


def masked_issuer_from(raw_payload: dict) -> str | None:
    for key in ("bank", "issuer", "vpa", "method_details"):
        v = raw_payload.get(key)
        if isinstance(v, str) and v:
            return v[:2] + "***"
        if isinstance(v, dict):
            inner = v.get("bank") or v.get("issuer")
            if isinstance(inner, str) and inner:
                return inner[:2] + "***"
    return None


def diagnose_episode(
    session: Session,
    llm: LlmClient,
    redis_client,  # type: ignore[no-untyped-def]
    *,
    episode_id,  # type: ignore[no-untyped-def]
    code_raw: str,
    rail: str,
    amount_paise: int,
    occurred_at,  # type: ignore[no-untyped-def]
    raw_payload: dict | None = None,
    prior_code_counts: dict[str, int] | None = None,
    degraded: bool = False,
    llm_tail_enabled: bool = True,
) -> DiagnosisResult:
    """Rules first; LLM only on the miss; UNKNOWN_AMBIGUOUS as final fallback."""
    # 1) deterministic rules
    hit = diagnose_rules(code_raw)
    if hit is not None:
        log.info(
            "diagnosis_resolved",
            method="RULE",
            code=hit.canonical_code.value,
            episode_id=str(episode_id),
        )
        return DiagnosisResult(hit.canonical_code, hit.confidence, DxMethod.RULE, hit.rationale)

    # 2) degraded mode / ablation A1 ⇒ conservative default without any LLM call
    if degraded or not llm_tail_enabled or not llm.configured:
        return DiagnosisResult(
            CanonicalCode.UNKNOWN_AMBIGUOUS,
            0.30,
            DxMethod.LLM,
            "LLM unavailable/ablated — conservative default applied",
        )

    # 3) cache by (hash(code_raw), issuer)
    issuer = masked_issuer_from(raw_payload or {})
    cache_key = _cache_key(code_raw, issuer)
    try:
        cached = redis_client.get(cache_key)
        if cached:
            import json

            d = json.loads(cached)
            log.info("diagnosis_cache_hit", episode_id=str(episode_id))
            return DiagnosisResult(
                CanonicalCode(d["canonical_code"]),
                float(d["confidence"]),
                DxMethod.LLM,
                d["rationale"] + " (cached)",
            )
    except Exception:
        pass

    # 4) LLM tail with <data>-wrapped redacted context; retry once; then fallback
    ctx = _llm_context(
        code_raw=code_raw,
        rail=rail,
        masked_issuer=issuer,
        day_of_month=occurred_at.day,
        hour=occurred_at.hour,
        prior_code_counts=prior_code_counts or {},
    )
    system_prompt = prompts.load("diagnosis")
    purpose_log = {
        "purpose": "diagnosis",
        "prompt_hash": prompts.prompt_hash("diagnosis"),
        "input_redacted": scrub_payload(ctx),
    }

    result = llm.complete(
        system_prompt=system_prompt,
        user_payload=prompts.wrap_data(ctx),
        purpose_log=purpose_log,
        session=session,
        episode_id=episode_id,
    )
    parsed, valid = (None, False)
    if result is not None and result.ok:
        parsed, valid = parse_diagnosis(result.text)
        if not valid:  # exactly one retry on invalid output (Rules §2.1)
            log.info("diagnosis_invalid_json_retry", episode_id=str(episode_id))
            result = llm.complete(
                system_prompt=system_prompt,
                user_payload=prompts.wrap_data(ctx),
                purpose_log=purpose_log,
                session=session,
                episode_id=episode_id,
            )
            if result is not None and result.ok:
                parsed, valid = parse_diagnosis(result.text)

    if valid and parsed is not None:
        if parsed.confidence < 0.6:
            # Rules §2.5: low confidence ⇒ conservative default
            res = DiagnosisResult(
                CanonicalCode.UNKNOWN_AMBIGUOUS,
                float(parsed.confidence),
                DxMethod.LLM,
                f"low confidence ({parsed.confidence}) — conservative default",
            )
        else:
            res = DiagnosisResult(
                parsed.canonical_code,
                float(parsed.confidence),
                DxMethod.LLM,
                parsed.rationale[:240],
            )
        _cache_put(redis_client, cache_key, res)
        log.info(
            "diagnosis_resolved",
            method="LLM",
            code=res.canonical_code.value,
            confidence=res.confidence,
            episode_id=str(episode_id),
        )
        return res

    # second failure ⇒ deterministic fallback (never a third guess)
    return DiagnosisResult(
        CanonicalCode.UNKNOWN_AMBIGUOUS,
        0.30,
        DxMethod.LLM,
        "invalid/unavailable LLM output after retry — UNKNOWN_AMBIGUOUS fallback",
    )


def _cache_put(redis_client, key: str, res: DiagnosisResult) -> None:  # type: ignore[no-untyped-def]
    import json

    try:
        redis_client.setex(
            key,
            CACHE_TTL_SECS,
            json.dumps(
                {
                    "canonical_code": res.canonical_code.value,
                    "confidence": res.confidence,
                    "rationale": res.rationale,
                }
            ),
        )
    except Exception:
        pass
