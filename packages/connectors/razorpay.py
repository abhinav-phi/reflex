"""Razorpay **TEST MODE** client (PRD FR-008, TechSpec §11).

Official public API v1: Orders + Payment Links. `[TEST MODE]` everywhere.
- Refuses any key id not starting with `rzp_test_` (Rules §1.7 — hard fail).
- Every call: timeout → backoff ×3 (1s/4s/16s) → park (caller handles).

Duplicate-link guard (TASK-056): Razorpay's public API does NOT honor client
idempotency headers, so idempotency is enforced two ways:
  1. DB layer — `actions.idempotency_key` UNIQUE gates double dispatch.
  2. This client — Payment Links carry `reference_id` (the action row id);
     before creating (pre-flight) and after any timeout/transport error
     mid-backoff, we look the reference up and ADOPT the existing link instead
     of issuing a duplicate creation request. A timeout after the provider
     accepted the create is exactly the case a blind retry would duplicate.

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

    def __init__(
        self,
        key_id: str = "",
        key_secret: str = "",
        base_url: str = BASE_URL,
        transport: httpx.BaseTransport | None = None,  # injectable for tests
    ) -> None:
        self._key_id = key_id
        self._key_secret = key_secret
        self._base_url = base_url.rstrip("/")
        self._client = httpx.Client(base_url=self._base_url, transport=transport)

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
                resp = self._client.request(
                    method,
                    path,
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

    # ---- Duplicate-link guard (TASK-056) ------------------------------------
    def _find_link_by_reference(self, reference_id: str, amount_paise: int) -> dict[str, Any] | None:
        """Most recent live payment link with this reference AND amount, or None."""
        raw = self._request_with_backoff("GET", "/payment_links", {})
        links = raw.get("payment_links") if isinstance(raw, dict) else None
        if not isinstance(links, list):
            return None
        for link in links:
            if (
                str(link.get("reference_id")) == reference_id
                and link.get("amount") == amount_paise
                and link.get("status") not in ("cancelled",)
            ):
                return link
        return None

    def _adopt(self, link: dict[str, Any], dedupe_via: str) -> RpResult:
        raw = dict(link)
        raw["_reflex_dedupe"] = dedupe_via  # provenance of an adopted (not created) link
        return RpResult(ok=True, provider_ref=str(link.get("id")), raw=raw)

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
        # Pre-flight: a link for this action may already exist (double dispatch,
        # prior crashed worker) — adopt it instead of creating a twin.
        existing = self._find_link_by_reference(reference_id, amount_paise)
        if existing is not None:
            return self._adopt(existing, "pre_flight_lookup")

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
        last_timeout: Exception | None = None
        for wait in (0.0, *BACKOFFS_SECS):
            if wait:
                time.sleep(wait)
            try:
                raw = self._request_once("POST", "/payment_links", body)
                return RpResult(ok=True, provider_ref=str(raw.get("id")), raw=raw)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                # The create MAY have landed server-side. Never blind-retry:
                # reconcile by reference first; only retry when lookup is empty.
                last_timeout = exc
                adopted = self._safe_lookup(reference_id, amount_paise)
                if adopted is not None:
                    return self._adopt(adopted, "timeout_reconciliation")
        raise RazorpayTimeout(str(last_timeout))

    def _request_once(self, method: str, path: str, json_body: dict[str, Any]) -> dict[str, Any]:
        headers = self._auth_header()
        resp = self._client.request(method, path, json=json_body, headers=headers, timeout=TIMEOUT_SECS)
        if resp.status_code >= 400:
            raise RazorpayHTTPError(resp.status_code, resp.text)
        return resp.json()

    def _safe_lookup(self, reference_id: str, amount_paise: int) -> dict[str, Any] | None:
        try:
            return self._find_link_by_reference(reference_id, amount_paise)
        except Exception:
            return None  # lookup failure must not mask the original timeout


async def create_order_async(client: RazorpayTestModeClient, **kw: Any) -> RpResult:
    return await asyncio.to_thread(client.create_order, **kw)


async def create_payment_link_async(client: RazorpayTestModeClient, **kw: Any) -> RpResult:
    return await asyncio.to_thread(client.create_payment_link, **kw)
