"""Export APIs (TASK-039): watermark mandatory on CSV + JSON, both endpoints.

Ingestion has no plain HTTP entry point by design (HMAC-signed Razorpay webhook
or the internal replay driver), so these tests assert watermark/shape contracts
against empty-but-valid exports — headers and inline watermarks are row-count
independent.
"""

from __future__ import annotations

WATERMARK = "# REFLEX SIMULATION DATA - NOT REAL TRANSACTIONS"


def test_episodes_export_csv_has_watermark(client, auth_h):  # type: ignore[no-untyped-def]
    r = client.get("/api/episodes/export?format=csv", headers=auth_h("viewer"))
    assert r.status_code == 200, r.text
    assert r.headers["X-Reflex-Data-Watermark"] == WATERMARK
    body = r.text.splitlines()
    assert body[0] == WATERMARK
    assert "amount_paise" in body[1]


def test_episodes_export_json_has_watermark(client, auth_h):  # type: ignore[no-untyped-def]
    r = client.get("/api/episodes/export?format=json", headers=auth_h("viewer"))
    assert r.status_code == 200
    assert r.headers["X-Reflex-Data-Watermark"] == WATERMARK
    data = r.json()
    assert data["_watermark"] == WATERMARK
    assert isinstance(data["items"], list)
    if data["count"]:
        assert "amount_paise" in data["items"][0]


def test_ledger_export_json_has_watermark(client, auth_h):  # type: ignore[no-untyped-def]
    r = client.get("/api/ledger/export?format=json", headers=auth_h("viewer"))
    assert r.status_code == 200
    data = r.json()
    assert data["_watermark"] == WATERMARK
    for item in data["items"][:1]:
        assert {"seq", "event", "hash"} <= set(item)


def test_ledger_export_csv_has_watermark(client, auth_h):  # type: ignore[no-untyped-def]
    r = client.get("/api/ledger/export?format=csv", headers=auth_h("operator"))
    assert r.status_code == 200
    assert r.text.splitlines()[0] == WATERMARK


def test_export_requires_auth(client):  # type: ignore[no-untyped-def]
    assert client.get("/api/episodes/export").status_code in (401, 403)
    assert client.get("/api/ledger/export").status_code in (401, 403)


def test_export_rejects_bad_format(client, auth_h):  # type: ignore[no-untyped-def]
    r = client.get("/api/episodes/export?format=xml", headers=auth_h("viewer"))
    assert r.status_code == 422
