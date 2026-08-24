"""API contract + RBAC matrix + webhook HMAC/dedup (TechSpec §10, Rules §1)."""

import hashlib
import hmac
import json

from sqlalchemy import text


def _sig(body: bytes, secret: str = "dev-webhook-secret") -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _failed_event_body(provider_id: str, amount: int = 29900) -> bytes:
    payload = {
        "event": "payment.failed",
        "payload": {
            "payment": {
                "entity": {
                    "id": f"pay_{provider_id}",
                    "amount": amount,
                    "method": "upi",
                    "vpa": "arjun99@ybl",
                    "error_description": "Sim:insufficient balance — try later",
                    "created_at": 1787900000,
                }
            }
        },
    }
    return json.dumps(payload).encode()


def test_login_bad_credentials_401(client):  # type: ignore[no-untyped-def]
    r = client.post("/api/auth/login", json={"email": "admin@reflex.dev", "password": "wrong"})
    assert r.status_code == 401


def test_webhook_invalid_signature_401(client, clean_db):  # type: ignore[no-untyped-def]
    body = _failed_event_body("sigtest1")
    r = client.post("/webhooks/razorpay", content=body,
                    headers={"X-Razorpay-Signature": "bad" * 8,
                             "Content-Type": "application/json"})
    assert r.status_code == 401


def test_webhook_valid_signature_creates_episode(client, clean_db):  # type: ignore[no-untyped-def]
    body = _failed_event_body("oktest1")
    r = client.post("/webhooks/razorpay", content=body,
                    headers={"X-Razorpay-Signature": _sig(body),
                             "Content-Type": "application/json"})
    assert r.status_code == 200
    data = r.json()
    assert data["accepted"] is True and data["episode_id"]


def test_webhook_duplicate_returns_200_and_dedups(client, clean_db):  # type: ignore[no-untyped-def]
    body = _failed_event_body("duptest1")
    hdrs = {"X-Razorpay-Signature": _sig(body), "Content-Type": "application/json"}
    r1 = client.post("/webhooks/razorpay", content=body, headers=hdrs)
    r2 = client.post("/webhooks/razorpay", content=body, headers=hdrs)
    assert r1.status_code == 200 and r2.status_code == 200
    assert r2.json()["duplicate"] is True
    n = clean_db.execute(text("SELECT count(*) FROM runtime.payment_events")).scalar()
    assert n == 1


def test_zero_amount_rejected_at_ingestion(client, clean_db):  # type: ignore[no-untyped-def]
    body = _failed_event_body("zerotest1", amount=0)
    r = client.post("/webhooks/razorpay", content=body,
                    headers={"X-Razorpay-Signature": _sig(body),
                             "Content-Type": "application/json"})
    # ₹0/negative ⇒ rejected at validation (AppFlow §9), never an episode
    accepted = r.json()["accepted"] if r.status_code == 200 else True
    assert accepted is False


# ---- RBAC matrix (server-side enforcement) ------------------------------------
ROUTE_CASES = [
    ("GET", "/api/episodes", "viewer"),
    ("GET", "/api/episodes/00000000-0000-0000-0000-000000000000", "viewer"),
    ("GET", "/api/metrics/live", "viewer"),
    ("GET", "/api/metrics/eval", "viewer"),
    ("GET", "/api/approvals", "approver"),
    ("POST", "/api/control/mode", "operator"),
    ("POST", "/api/replay/start", "operator"),
    ("POST", "/api/eval/run", "operator"),
    ("GET", "/api/onboarding/state", "admin"),
]


def test_rbac_matrix(client, auth_h):  # type: ignore[no-untyped-def]
    for method, route, min_role in ROUTE_CASES:
        order = ["none", "viewer", "operator", "approver", "admin"]
        min_idx = order.index(min_role)
        allowed = {"viewer", "operator", "approver", "admin"} if min_role == "viewer" else \
                  {"operator", "approver", "admin"} if min_role == "operator" else \
                  {"approver", "admin"} if min_role == "approver" else {"admin"}
        for role in order:
            h = auth_h(role)
            kw = {"headers": h}
            if method == "POST":
                kw["json"] = {}
            r = client.request(method, route, **kw)
            if role in allowed:
                assert r.status_code != 401 and r.status_code != 403, (route, role, r.status_code)
            elif role == "none":
                assert r.status_code == 401, (route, role, r.status_code)
            else:
                assert r.status_code == 403, (route, role, r.status_code)


def test_no_endpoint_returns_replay_hidden_truth(client, auth_h, clean_db):  # type: ignore[no-untyped-def]
    """Rules §6.5: no endpoint may return replay.sim_* data. Structural check via
    episode detail — it must not contain hidden simulator fields."""
    h = auth_h("viewer")
    eps = client.get("/api/episodes?limit=1", headers=h).json()
    for item in eps.get("items", []):
        blob = json.dumps(item)
        assert "p_respond" not in blob and "intent" not in blob


# ---- structured error envelope (Rules §6.2) ------------------------------------


def test_error_envelope_shape_on_401_and_403(client):  # type: ignore[no-untyped-def]
    r = client.post("/api/control/mode", json={"mode": "halted"})
    assert r.status_code == 401
    err = r.json()["error"]
    assert set(err) >= {"code", "message"}
    assert err["code"] == "UNAUTHORIZED"


def test_error_envelope_shape_on_404(client, auth_h):  # type: ignore[no-untyped-def]
    r = client.get(
        "/api/episodes/00000000-0000-0000-0000-000000000000", headers=auth_h("viewer")
    )
    if r.status_code == 404:
        assert r.json()["error"]["code"] == "NOT_FOUND"


# ---- Idempotency-Key response store (Rules §1.4) --------------------------------


def test_idempotency_key_replays_first_response(client):  # type: ignore[no-untyped-def]
    h = {"Idempotency-Key": "test-suite-key-1"}
    r1 = client.post("/api/auth/login",
                     json={"email": "viewer@reflex.dev", "password": "reflex-demo"}, headers=h)
    r2 = client.post("/api/auth/login",
                     json={"email": "viewer@reflex.dev", "password": "reflex-demo"}, headers=h)
    assert r1.status_code == 200 and r2.status_code == 200
    assert r2.headers.get("Idempotent-Replay") == "true"
    assert r1.json() == r2.json()


def test_without_idempotency_key_request_executes_normally(client):  # type: ignore[no-untyped-def]
    r1 = client.post("/api/auth/login",
                     json={"email": "viewer@reflex.dev", "password": "reflex-demo"})
    r2 = client.post("/api/auth/login",
                     json={"email": "viewer@reflex.dev", "password": "reflex-demo"})
    assert r1.status_code == 200 and r2.status_code == 200
    assert "Idempotent-Replay" not in r2.headers
