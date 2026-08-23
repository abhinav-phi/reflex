"""FastAPI application — Pulse ingestion + REST + SSE + control plane (TechSpec §10)."""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import structlog
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from reflex.api.db import agent_session, get_redis
from reflex.api.ingest_service import (
    InvalidSignature,
    ingest_event,
    normalize_event,
    verify_webhook_signature,
)
from reflex.api.routes import (
    approvals,
    control,
    episodes,
    eval_api,
    ledger_api,
    metrics,
    onboarding,
)
from reflex.api.security import (
    RateLimiter,
    authenticate,
    create_token,
    principal_of,
    require_role,
)
from reflex.core.clock import SimClock, effective_mode
from reflex.core.enums import Arm, EventSource, Role
from reflex.core.schemas import (
    ApprovalDecisionRequest,
    LoginRequest,
    ModeChangeRequest,
    ReplayStartRequest,
    WebhookAck,
)

structlog.configure(
    processors=[
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ]
)
log = structlog.get_logger("reflex.api")


@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[no-untyped-def]
    app.state.redis = get_redis()
    app.state.rate = RateLimiter(app.state.redis)
    app.state.started_at = datetime.now(timezone.utc)
    yield


app = FastAPI(title="Reflex", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[],  # no wildcard; explicit origins only (Rules §1.6)
    allow_origin_regex=r"^http://(localhost|127\.0\.0\.1):(5173|8080)$",
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-Razorpay-Signature"],
)


# ---- health ------------------------------------------------------------------------


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok", "service": "reflex-api"}


@app.get("/metrics")
def metrics_snapshot() -> dict:
    r: object = app.state.redis
    keys = [
        "events_ingested", "duplicates_collapsed", "episodes_created",
        "dx_rule", "dx_llm", "shield_pass", "shield_block", "shield_approval",
        "dispatched", "recovered",
    ]
    out = {}
    for k in keys:
        v = r.get(f"reflex:ctr:{k}") if hasattr(r, "get") else None
        out[k] = int(v) if v else 0
    return out


# ---- auth --------------------------------------------------------------------------


@app.post("/api/auth/login")
def login(body: LoginRequest, request: Request) -> dict:
    app.state.rate.check("auth_login", principal_of(request))
    from reflex.api.db import agent_sessionmaker

    s = agent_sessionmaker()()
    try:
        user = authenticate(s, body.email, body.password)
    finally:
        s.close()
    if user is None:
        raise HTTPException(status_code=401, detail="invalid credentials")
    return {"token": create_token(user["user_id"], user["role"]), "role": user["role"]}


# ---- webhook ingestion (HMAC-authenticated, not JWT) --------------------------------


@app.post("/webhooks/razorpay")
async def webhook_razorpay(request: Request) -> WebhookAck:
    import os

    raw = await request.body()
    request.scope["raw_body"] = raw
    signature = request.headers.get("X-Razorpay-Signature")
    secret = os.environ.get("RAZORPAY_WEBHOOK_SECRET", "dev-webhook-secret")

    if not verify_webhook_signature(raw, signature, secret):
        _security_event(request, "webhook_invalid_signature")
        raise HTTPException(status_code=401, detail="invalid signature")

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="malformed payload")

    normalized = normalize_event(payload)
    if normalized is None:
        return WebhookAck(accepted=False, duplicate=False)

    session = next(agent_session())
    redis = app.state.redis
    try:
        result = ingest_event(session, source=EventSource.LIVE_TM, normalized=normalized)
        session.commit()
        if result.accepted and result.episode_id:
            _bump(redis, "events_ingested")
            _bump(redis, "episodes_created")
            publish_event(redis, {"type": "episode.created", "episode_id": result.episode_id})
            enqueue_diagnosis(redis, result.episode_id)
        elif result.duplicate:
            _bump(redis, "duplicates_collapsed")
        return WebhookAck(accepted=result.accepted, duplicate=result.duplicate, episode_id=result.episode_id)
    finally:
        session.close()


def _security_event(request: Request, kind: str) -> None:
    from sqlalchemy import text as sql_text

    s = next(agent_session())
    try:
        s.execute(
            sql_text(
                "INSERT INTO runtime.security_events (kind, detail) "
                "VALUES (:k, CAST(:d AS jsonb))"
            ),
            {"k": kind, "d": json.dumps({"path": request.url.path, "ip": request.client.host if request.client else None})},
        )
    finally:
        s.commit(); s.close()


def _bump(redis: object, key: str) -> None:
    try:
        redis.incr(f"reflex:ctr:{key}")  # type: ignore[attr-defined]
        publish_counters(redis)  # type: ignore[arg-type]
    except Exception:
        pass


# ---- SSE stream (ADR-006) -----------------------------------------------------------


def publish_event(redis: object, event: dict) -> None:
    try:
        redis.publish("reflex:events", json.dumps(event))  # type: ignore[attr-defined]
    except Exception:
        pass


def publish_counters(redis: object) -> None:
    keys = [
        "events_ingested", "duplicates_collapsed", "episodes_created",
        "dx_rule", "dx_llm", "shield_pass", "shield_block", "shield_approval",
        "dispatched", "recovered",
    ]
    snap = {}
    for k in keys:
        v = redis.get(f"reflex:ctr:{k}")  # type: ignore[attr-defined]
        snap[k] = int(v) if v else 0
    publish_event(redis, {"type": "counters.updated", "counters": snap})


def enqueue_diagnosis(redis: object, episode_id: str) -> None:
    """Shard by episode hash → per-episode ordering across consumer group."""
    shard = int(hash(episode_id) % 16)
    try:
        redis.xadd(f"reflex:dx:{shard}", {"episode_id": str(episode_id)})  # type: ignore[attr-defined]
    except Exception:
        log.error("stream_enqueue_failed", episode_id=episode_id)


@app.get("/api/stream")
async def stream(request: Request, user: dict = Depends(require_role(Role.VIEWER))) -> StreamingResponse:
    app.state.rate.check("stream", user["user_id"])
    redis = app.state.redis
    pubsub = redis.pubsub()
    pubsub.subscribe("reflex:events")

    async def gen():  # type: ignore[no-untyped-def]
        loop = asyncio.get_event_loop()
        yield f"event: hello\ndata: {json.dumps({'ok': True})}\n\n"
        try:
            while True:
                if await request.is_disconnected():
                    break
                msg = await loop.run_in_executor(None, pubsub.get_message, True, 1.0)
                if msg and msg.get("type") == "message":
                    data = msg["data"]
                    yield f"data: {data}\n\n"
                else:
                    yield ": keepalive\n\n"
        finally:
            pubsub.close()

    return StreamingResponse(gen(), media_type="text/event-stream")


# ---- replay start (operator) ---------------------------------------------------------


@app.post("/api/replay/start")
def replay_start(body: ReplayStartRequest, request: Request, user: dict = Depends(require_role(Role.OPERATOR))) -> dict:
    app.state.rate.check("replay_start", user["user_id"])
    from reflex.eval.replay_driver import start_replay_batch

    running = app.state.redis.get("reflex:replay:running")
    if running:
        raise HTTPException(status_code=409, detail="a replay batch is already running")
    batch_ids = start_replay_batch(
        n=body.n,
        seed=body.seed,
        arm=Arm(body.arm),
        speed=body.speed,
        demo=body.demo,
        redis_client=app.state.redis,
    )
    return {"batch_ids": batch_ids}


# include routers
for router in (
    episodes.router,
    approvals.router,
    control.router,
    metrics.router,
    eval_api.router,
    ledger_api.router,
    onboarding.router,
):
    app.include_router(router, prefix="/api")
