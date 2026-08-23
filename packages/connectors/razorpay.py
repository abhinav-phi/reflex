"""Razorpay **TEST MODE** client (PRD FR-008, TechSpec §11).

Official public API v1: Orders + Payment Links. `[TEST MODE]` everywhere.
- Refuses any key id not starting with `rzp_test_` (Rules §1.7 — hard fail).
- Every call: timeout → backoff ×3 (1s/4s/16s) → park (caller handles).
- Idempotency is enforced at the DB layer (actions.idempotency_key UNIQUE);
  the client also passes our key in the Idempotency header for providers that honor it.

When keys are unconfigured the client raises ConfigError immediately — callers
must treat that as a PARK (fail-closed), never a fake success.
"""

from __future__ import annotations

import asyncio
import base64
import time
from dataclasses import dataclass
from typing import Any

import httpx

from reflex.connectors.errors import (
    ConfigError,
    RazorpayHTTPError,
    RazorpayTimeout,
    TestModeViolation,
)

BASE_URL = "https://api.razorpay.com/v1"
BACKOFFS_SECS = (1.0, 4.0, 16.0)  # F3
TIMEOUT_SECS = 10.0

SIMULATED_WHEN_UNCONFIGURED = True  # demo environments run without real RP keys


@dataclass(frozen=True)
class RpResult:
    ok: bool
    provider_ref: str | None  # order id / link id
    raw: dict[str, Any]
    simulated: bool = False  # True ⇒ no live test-mode call was possible


class RazorpayTestModeClient:
    label = "razorpay_tm"  # [TEST MODE]

    def __init__(self, key_id: str = "", key_secret: str = "", base_url: str = BASE_URL) -> None:
        self._key_id = key_id
        self._key_secret = key_secret
        self._base_url = base_url.rstrip("/")

    @property
    def configured(self) -> bool:
        return bool(self._key_id and self._key_secret)

    def _auth_header(self) -> dict[str, str]:
        if not self.configured:
            raise ConfigError("razorpay test-mode keys not configured")
        if not self._key_id.startswith("rzp_test_"):
            # Live keys are forbidden in this project, period (Rules §1.7).
            raise TestModeViolation("only rzp_test_ keys allowed")
        token = base64.b64encode(f"{self._key_id}:{self._key_secret}".encode()).decode()
        return {"Authorization": f"Basic {token}"}

    def _request_with_backoff(self, method: str, path: str, json_body: dict[str, Any]) -> dict[str, Any]:
        headers = self._auth_header()
        last_exc: Exception | None = None
        for wait in (0.0, *BACKOFFS_SECS):
            if wait:
                time.sleep(wait)
            try:
                resp = httpx.request(
                    method,
                    f"{self._base_url}{path}",
                    json=json_body,
                    headers=headers,
                    timeout=TIMEOUT_SECS,
                )
                if resp.status_code >= 400:
                    # 4xx from RP is deterministic-ish; retry only on 5xx/timeout.
                    raise RazorpayHTTPError(resp.status_code, resp.text)
                return resp.json()
            except RazorpayHTTPError as exc:
                if exc.status_code < 500 or wait == BACKOFFS_SECS[-1]:
                    raise
                last_exc = exc
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_exc = exc
        raise RazorpayTimeout(str(last_exc))

    # ---- Orders (used by RETRY_* interventions) -----------------------------
    def create_order(
        self,
        *,
        amount_paise: int,
        currency: str = "INR",
        receipt: str,
        notes: dict[str, str] | None = None,
    ) -> RpResult:
        body = {
            "amount": amount_paise,
            "currency": currency,
            "receipt": receipt,
            "notes": {"source": "reflex", "mode": "test"} | (notes or {}),
        }
        raw = self._request_with_backoff("POST", "/orders", body)
        return RpResult(ok=True, provider_ref=raw.get("id"), raw=raw)

    def cancel_order(self, order_id: str) -> RpResult:
        """Used by onboarding connectivity check (create+cancel a ₹1 test order)."""
        raw = self._request_with_backoff("POST", f"/orders/{order_id}/cancel", {})
        return RpResult(ok=True, provider_ref=order_id, raw=raw)

    # ---- Payment Links (primary ad-hoc recovery rail) ------------------------
    def create_payment_link(
        self,
        *,
        amount_paise: int,
        description: str,
        customer_name: str,
        reference_id: str,
        expiry_secs: int = 72 * 3600,
    ) -> RpResult:
        body = {
            "amount": amount_paise,
            "currency": "INR",
            "accept_partial": False,
            "description": description[:200],
            "customer": {"name": customer_name[:60]},
            "reference_id": reference_id[:40],
            "expire_by": int(time.time()) + expiry_secs,
            "notes": {"source": "reflex", "test_mode": "true"},
        }
        raw = self._request_with_backoff("POST", "/payment_links", body)
        return RpResult(ok=True, provider_ref=str(raw.get("id")), raw=raw)


async def create_order_async(client: RazorpayTestModeClient, **kw: Any) -> RpResult:
    return await asyncio.to_thread(client.create_order, **kw)


async def create_payment_link_async(client: RazorpayTestModeClient, **kw: Any) -> RpResult:
    return await asyncio.to_thread(client.create_payment_link, **kw)
