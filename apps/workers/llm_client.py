"""OpenAI-compatible LLM client wrapper (AI-1/3/4).

- Absent/unreachable provider ⇒ system runs degraded/cached end-to-end
  (Rules §15.2). Two consecutive failures flip the global degraded flag (F1).
- Every call is schema-gated by callers; this layer logs purpose, prompt hash,
  redacted input, output, validity, latency, cost, model to runtime.llm_calls
  (Rules §2.6) — no PII, never the raw prompt.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any

import httpx
import structlog
from reflex.core.settings import Settings, get_settings

log = structlog.get_logger("reflex.llm")

# F1: two consecutive failures ⇒ outage detected.
OUTAGE_THRESHOLD = 2


@dataclass
class LlmResult:
    ok: bool
    text: str
    latency_ms: int
    cost_usd: float | None
    model: str | None
    call_id: str | None = None  # runtime.llm_calls id (TASK-055 provenance)


class LlmHealth:
    """Tracks consecutive failures; flips Redis DEGRADED flag at threshold."""

    def __init__(self, redis_client=None) -> None:  # type: ignore[no-untyped-def]
        self._r = redis_client
        self._consecutive_failures = 0
        self.in_memory_outage = False

    def record_success(self) -> None:
        self._consecutive_failures = 0
        was_down = self.in_memory_outage
        self.in_memory_outage = False
        if self._r is not None:
            self._r.delete("reflex:llm:consecutive_failures")
            if was_down:
                self._r.delete("reflex:inject:llm_outage")  # restore clears banner

    def record_failure(self) -> bool:
        """Returns True when outage threshold crossed (mode should degrade)."""
        self._consecutive_failures += 1
        if self._r is not None:
            self._r.set("reflex:llm:consecutive_failures", self._consecutive_failures)
        if self._consecutive_failures >= OUTAGE_THRESHOLD:
            self.in_memory_outage = True
            return True
        return False

    def is_outage(self) -> bool:
        return self.in_memory_outage


class LlmClient:
    def __init__(
        self,
        settings: Settings | None = None,
        redis_client=None,  # type: ignore[no-untyped-def]
        health: LlmHealth | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.health = health or LlmHealth(redis_client)

    @property
    def configured(self) -> bool:
        return bool(self.settings.llm_api_key)

    def complete(
        self,
        *,
        system_prompt: str,
        user_payload: str,
        purpose_log: dict[str, Any],
        max_tokens: int = 300,
        temperature: float = 0.2,
        session=None,  # SQLAlchemy session for llm_calls logging; None ⇒ skip
        episode_id=None,  # type: ignore[no-untyped-def]
    ) -> LlmResult | None:
        """One chat completion. Returns None when unconfigured/outage/failure."""
        if not self.configured or self.health.is_outage():
            return None

        redacted_input = _redact(purpose_log.get("input_redacted", {}))
        started = time.perf_counter()
        try:
            resp = httpx.post(
                f"{self.settings.llm_base_url.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {self.settings.llm_api_key}"},
                json={
                    "model": self.settings.llm_model,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_payload},
                    ],
                },
                timeout=30.0,
            )
            resp.raise_for_status()
            body = resp.json()
            text = body["choices"][0]["message"]["content"]
            usage = body.get("usage") or {}
            cost = _estimate_cost(usage, self.settings.llm_model)
            latency_ms = int((time.perf_counter() - started) * 1000)
            self.health.record_success()
            call_id = self._log_call(session, episode_id, purpose_log, redacted_input, {"raw": text}, True, latency_ms, cost)
            return LlmResult(ok=True, text=text, latency_ms=latency_ms, cost_usd=cost, model=self.settings.llm_model, call_id=call_id)
        except Exception as exc:
            latency_ms = int((time.perf_counter() - started) * 1000)
            crossed = self.health.record_failure()
            log.warning(
                "llm_call_failed",
                error=type(exc).__name__,
                consecutive_failures=self._failures_from_redis(),
                outage_detected=crossed,
                purpose=purpose_log.get("purpose"),
            )
            self._log_call(session, episode_id, purpose_log, redacted_input, None, False, latency_ms, None)
            if crossed and session is not None:
                _stamp_degraded_transition(session)
            return None

    def _failures_from_redis(self) -> int:
        try:
            if self._redis() is not None:
                v = self._redis().get("reflex:llm:consecutive_failures")
                return int(v) if v else 0
        except Exception:
            pass
        return self.health._consecutive_failures

    def _redis(self):  # type: ignore[no-untyped-def]
        return getattr(self.health, "_r", None)

    def _log_call(
        self,
        session,  # type: ignore[no-untyped-def]
        episode_id,  # type: ignore[no-untyped-def]
        purpose_log: dict[str, Any],
        redacted_input: Any,
        output: Any,
        valid: bool,
        latency_ms: int,
        cost_usd: float | None,
    ) -> str | None:
        """Insert one llm_calls row; returns its id (None when unlogged)."""
        if session is None:
            return None
        from sqlalchemy import text as sql_text

        try:
            row = session.execute(
                sql_text(
                    "INSERT INTO runtime.llm_calls "
                    "(episode_id, purpose, prompt_hash, input_redacted, output_json, valid, latency_ms, cost_usd, model) "
                    "VALUES (:ep, CAST(:purpose AS runtime.llm_purpose), :ph, CAST(:in_red AS jsonb), "
                    "CAST(:out AS jsonb), :valid, :latency, :cost, :model) RETURNING id"
                ),
                {
                    "ep": episode_id,
                    "purpose": purpose_log.get("purpose", "diagnosis"),
                    "ph": purpose_log.get("prompt_hash", ""),
                    "in_red": json.dumps(_redact(redacted_input), ensure_ascii=False),
                    "out": json.dumps(output, ensure_ascii=False) if output is not None else None,
                    "valid": valid,
                    "latency": latency_ms,
                    "cost": cost_usd,
                    "model": self.settings.llm_model,
                },
            ).scalar()
            return str(row) if row is not None else None
        except Exception as exc:  # logging must never break the pipeline
            log.error("llm_calls_log_failed", error=str(exc)[:200])
            return None


def _redact(obj: Any) -> Any:
    from reflex.core.pii import scrub_payload

    return scrub_payload(obj)


def _estimate_cost(usage: dict[str, Any], model: str) -> float | None:
    """Rough mini-class pricing; exact accounting is not a product requirement."""
    ptok = float(usage.get("prompt_tokens") or 0)
    ctok = float(usage.get("completion_tokens") or 0)
    if not (ptok or ctok):
        return None
    return round((ptok * 0.15 + ctok * 0.60) / 1_000_000, 6)


def _stamp_degraded_transition(session) -> None:  # type: ignore[no-untyped-def]
    """Outage crossing is an auditable event (F1)."""
    from sqlalchemy import text as sql_text

    try:
        session.execute(
            sql_text(
                "INSERT INTO runtime.mode_changes (merchant_id, from_mode, to_mode, actor, reason) "
                "VALUES (NULL, 'autonomous', 'degraded', 'system', 'LLM outage detected (2 consecutive failures)')"
            )
        )
    except Exception:
        pass
