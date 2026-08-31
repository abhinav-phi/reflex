"""Malformed path/query identifiers must 422, not 500 (UUID casts in SQL)."""

from __future__ import annotations

BAD = "not-a-uuid"


def test_episode_ledger_invalid_uuid_422(client, auth_h):  # type: ignore[no-untyped-def]
    r = client.get(f"/api/episodes/{BAD}/ledger", headers=auth_h("viewer"))
    assert r.status_code == 422, r.text


def test_episode_detail_invalid_uuid_422(client, auth_h):  # type: ignore[no-untyped-def]
    r = client.get(f"/api/episodes/{BAD}", headers=auth_h("viewer"))
    assert r.status_code == 422, r.text


def test_episode_escalate_invalid_uuid_422(client, auth_h):  # type: ignore[no-untyped-def]
    r = client.post(f"/api/episodes/{BAD}/escalate", headers=auth_h("operator"))
    assert r.status_code == 422, r.text


def test_metrics_eval_invalid_run_uuid_422(client, auth_h):  # type: ignore[no-untyped-def]
    r = client.get(f"/api/metrics/eval?run_id={BAD}", headers=auth_h("viewer"))
    assert r.status_code == 422, r.text


def test_approval_decide_invalid_uuid_422(client, auth_h):  # type: ignore[no-untyped-def]
    r = client.post(
        f"/api/approvals/{BAD}/decide",
        headers=auth_h("approver"),
        json={"decision": "approve", "reason": "ok"},
    )
    assert r.status_code == 422, r.text


def test_valid_uuid_still_not_500(client, auth_h):  # type: ignore[no-untyped-def]
    # Well-formed UUID must pass validation and reach the handler (404/200, never 500).
    import uuid

    rid = str(uuid.uuid4())
    r = client.get(f"/api/episodes/{rid}", headers=auth_h("viewer"))
    assert r.status_code in (200, 404), r.text
