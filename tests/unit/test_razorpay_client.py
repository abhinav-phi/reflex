"""Razorpay TEST MODE client: duplicate-payment-link guard (TASK-056 / P1-4).

Mocked at the HTTP boundary (`httpx.MockTransport`) — no network, no keys.
Covers:
- pre-flight adoption of an already-existing link for the same reference,
- timeout reconciliation (create MAY have landed ⇒ adopt, never blind-retry),
- park after exhausting backoffs when no link ever appears,
- amount-mismatch links are NOT adopted,
- test-mode key policy still enforced.
"""

from __future__ import annotations

from typing import Callable

import httpx
import pytest

import reflex.connectors.razorpay as rzp
from reflex.connectors.errors import RazorpayTimeout, TestModeViolation
from reflex.connectors.razorpay import RazorpayTestModeClient


class _FakeRpApi:
    """Stateful in-memory stand-in for the RP payment-links endpoints."""

    def __init__(self) -> None:
        self.links: list[dict] = []
        self.post_count = 0
        self.get_count = 0
        self.post_behavior: Callable[[int], None] = lambda n: None  # hook per test

    def transport(self) -> httpx.MockTransport:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "GET" and request.url.path.endswith("/payment_links"):
                self.get_count += 1
                return httpx.Response(200, json={"count": len(self.links), "payment_links": self.links})
            if request.method == "POST" and request.url.path.endswith("/payment_links"):
                self.post_count += 1
                self.post_behavior(self.post_count)
                link = {
                    "id": f"plink_{1_000_000 + self.post_count}",
                    "amount": 29_900,
                    "reference_id": "42",
                    "status": "created",
                    "short_url": "https://rzp.io/i/mock",
                }
                self.links.append(link)
                return httpx.Response(200, json=link)
            return httpx.Response(404, json={"error": "not found"})

        return httpx.MockTransport(handler)

    def seed_link(self, reference_id: str = "42", amount: int = 29_900) -> dict:
        link = {"id": f"plink_{len(self.links) + 900}", "amount": amount, "reference_id": reference_id, "status": "created"}
        self.links.append(link)
        return link


def _client(api: _FakeRpApi) -> RazorpayTestModeClient:
    return RazorpayTestModeClient(
        key_id="rzp_test_1mockkey",
        key_secret="mocksecret",
        transport=api.transport(),
    )


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):  # type: ignore[no-untyped-def]
    monkeypatch.setattr(rzp.time, "sleep", lambda _s: None)


def test_pre_flight_lookup_adopts_existing_link_without_duplicate_post():
    api = _FakeRpApi()
    existing = api.seed_link(reference_id="42", amount=29_900)
    client = _client(api)
    res = client.create_payment_link(
        amount_paise=29_900,
        description="Reflex recovery",
        customer_name="C-1042",
        reference_id="42",
    )
    assert res.ok and res.provider_ref == existing["id"]
    assert res.raw["_reflex_dedupe"] == "pre_flight_lookup"
    assert api.post_count == 0, "a duplicate create was issued despite an existing link"


def test_timeout_mid_retry_reconciles_instead_of_creating_twin():
    api = _FakeRpApi()

    def timeout_but_land(n: int) -> None:
        # Server accepts and creates the link, but the response never arrives.
        link = {"id": f"plink_landed_{n}", "amount": 29_900, "reference_id": "42", "status": "created"}
        api.links.append(link)
        raise httpx.ConnectTimeout("gateway black-holed", request=httpx.Request("POST", "/payment_links"))

    api.post_behavior = timeout_but_land
    client = _client(api)
    res = client.create_payment_link(
        amount_paise=29_900, description="d", customer_name="c", reference_id="42"
    )
    assert res.ok and res.provider_ref == "plink_landed_1"
    assert res.raw["_reflex_dedupe"] == "timeout_reconciliation"
    assert api.post_count == 1, f"blind retry created {api.post_count} links"


def test_timeout_with_empty_lookup_exhausts_backoffs_then_parks():
    api = _FakeRpApi()
    api.post_behavior = lambda n: (_ for _ in ()).throw(
        httpx.ReadTimeout("no response", request=httpx.Request("POST", "/payment_links"))
    )
    client = _client(api)
    with pytest.raises(RazorpayTimeout):
        client.create_payment_link(
            amount_paise=29_900, description="d", customer_name="c", reference_id="77"
        )
    assert api.post_count == len(rzp.BACKOFFS_SECS) + 1, "expected exactly initial+3 attempts"


def test_amount_mismatch_link_is_not_adopted():
    api = _FakeRpApi()
    api.seed_link(reference_id="42", amount=49_900)  # same ref, different amount
    client = _client(api)
    res = client.create_payment_link(
        amount_paise=29_900, description="d", customer_name="c", reference_id="42"
    )
    assert res.raw.get("_reflex_dedupe") is None
    assert api.post_count == 1
    assert res.provider_ref is not None and res.provider_ref != "plink_900"


def test_cancelled_link_is_not_adopted():
    api = _FakeRpApi()
    dead = api.seed_link(reference_id="99", amount=29_900)
    dead["status"] = "cancelled"
    client = _client(api)
    res = client.create_payment_link(
        amount_paise=29_900, description="d", customer_name="c", reference_id="99"
    )
    assert res.raw.get("_reflex_dedupe") is None
    assert api.post_count == 1


def test_live_key_still_violates_test_mode():
    client = RazorpayTestModeClient(key_id="rzp_live_shouldfail", key_secret="x")
    with pytest.raises(TestModeViolation):
        client.create_payment_link(amount_paise=100, description="d", customer_name="c", reference_id="1")
