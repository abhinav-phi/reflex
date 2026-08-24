"""Export APIs (TASK-039): watermark mandatory on CSV + JSON, both endpoints."""

from __future__ import annotations

import pytest

WATERMARK = "# REFLEX SIMULATION DATA - NOT REAL TRANSACTIONS"


@pytest.fixture()
def seeded_episode(client, auth_h):  # type: ignore[no-untyped-def]
    """One ingested replay episode so exports have a row."""
    payload = {
        "provider_event_id": "export-test-001",
        "event": "payment.failed",
        "rail": "upi",
        "code_raw": "NSF - insufficient funds in account",
        "amount_paise": 29_900,
        "occurred_at": "2026-08-25T10:00:00+00:00",
        "customer_ref": "idx:1",
    }
    r = client.post(
        "/api/webhooks/ingest?source=replay&arm=reflex",
        json=payload,
        headers=auth_h("admin"),
    )
    assert r.status_code in (200, 202), r.text
    yield


def test_episodes_export_csv_has_watermark(client, auth_h, seeded_episode):  # type: ignore[no-untyped-def]
    r = client.get("/api/episodes/export?format=csv", headers=auth_h("viewer"))
    assert r.status_code == 200, r.text
    assert r.headers["X-Reflex-Data-Watermark"] == WATERMARK
    body = r.text.splitlines()
    assert body[0] == WATERMARK
    assert "amount_paise" in body[1]
    assert len(body) > 2, "expected at least one data row"


def test_episodes_export_json_has_watermark(client, auth_h, seeded_episode):  # type: ignore[no-untyped-def]
    r = client.get("/api/episodes/export?format=json", headers=auth_h("viewer"))
    assert r.status_code == 200
    assert r.headers["X-Reflex-Data-Watermark"] == WATERMARK
    data = r.json()
    assert data["_watermark"] == WATERMARK
    assert data["count"] >= 1
    assert "amount_paise" in data["items"][0]


def test_ledger_export_json_has_watermark(client, auth_h, seeded_episode):  # type: ignore[no-untyped-def]
    r = client.get("/api/ledger/export?format=json", headers=auth_h("viewer"))
    assert r.status_code == 200
    data = r.json()
    assert data["_watermark"] == WATERMARK
    if data["count"]:
        item = data["items"][0]
        assert {"seq", "event", "hash"} <= set(item)


def test_ledger_export_csv_has_watermark(client, auth_h, seeded_episode):  # type: ignore[no-untyped-def]
    r = client.get("/api/ledger/export?format=csv", headers=auth_h("operator"))
    assert r.status_code == 200
    assert r.text.splitlines()[0] == WATERMARK


def test_export_requires_auth(client):  # type: ignore[no-untyped-def]
    assert client.get("/api/episodes/export").status_code in (401, 403)
    assert client.get("/api/ledger/export").status_code in (401, 403)


def test_export_rejects_bad_format(client, auth_h):  # type: ignore[no-untyped-def]
    r = client.get("/api/episodes/export?format=xml", headers=auth_h("viewer"))
    assert r.status_code == 422
