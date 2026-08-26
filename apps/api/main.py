"""FastAPI application — Pulse ingestion + REST + SSE + control plane (TechSpec §10)."""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import structlog
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from reflex.api.db import agent_session, get_redis
from reflex.api.ingest_service import (
    ingest_event,
    normalize_event,
    verify_webhook_signature,
)
from reflex.api.routes import (
    approvals,
    control,
    episodes,
    eval_api,
    export,
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
from reflex.core.enums import Arm, EventSource, Role
from reflex.core.schemas import (
    LoginRequest,
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
    app.state.started_at = datetime.now(UTC)
    # Auto-seed for cloud deploys (Antideploy) - if users table empty, seed it so login works without manual console
    try:
        from sqlalchemy import text as _sa_text
        from reflex.api.db import agent_sessionmaker as _agent_mk

        _s = _agent_mk()()
        try:
            _cnt = _s.execute(_sa_text("SELECT COUNT(*) FROM runtime.users")).scalar()  # type: ignore[attr-defined]
            if _cnt == 0:
                log.info("cloud_autoseed_trigger", reason="users_empty")
                from reflex.eval.seed import main as _seed_main

                _seed_main()
                log.info("cloud_autoseed_done")
        except Exception as _e:
            log.warning("cloud_autoseed_skip", error=str(_e))
        finally:
            try:
                _s.close()
            except Exception:
                pass
    except Exception as _e:
        log.warning("cloud_autoseed_outer_skip", error=str(_e))
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


# ---- structured error envelope (Rules §6.2: {error: {code, message, action?}}) ------

_ERROR_CODES: dict[int, str] = {
    400: "BAD_REQUEST", 401: "UNAUTHORIZED", 403: "FORBIDDEN", 404: "NOT_FOUND",
    409: "CONFLICT", 410: "GONE", 422: "VALIDATION_ERROR", 429: "RATE_LIMITED",
}


def _envelope(status: int, message: str, action: str | None = None) -> JSONResponse:
    err: dict = {"code": _ERROR_CODES.get(status, f"HTTP_{status}"), "message": message}
    if action:
        err["action"] = action
    return JSONResponse(status_code=status, content={"error": err})


@app.exception_handler(HTTPException)
async def http_exception_envelope(request: Request, exc: HTTPException):  # type: ignore[no-untyped-def]
    return _envelope(exc.status_code, str(exc.detail))


@app.exception_handler(RequestValidationError)
async def validation_exception_envelope(request: Request, exc: RequestValidationError):  # type: ignore[no-untyped-def]
    return _envelope(422, "request validation failed", action="fix request body and retry")


@app.exception_handler(Exception)
async def unhandled_exception_envelope(request: Request, exc: Exception):  # type: ignore[no-untyped-def]
    log.error("unhandled_api_exception", path=request.url.path, error=type(exc).__name__)
    return _envelope(500, "internal error", action="retry; if persistent, check /ops")


# ---- Idempotency-Key response store (Rules §1.4) ------------------------------------
# POSTs to /api/* carrying an Idempotency-Key replay the FIRST response for the
# key's TTL instead of re-executing (judge double-click safety). Absent header ⇒
# pass-through (webhook dedup is provider-event-id based and lives outside /api).

IDEMPOTENCY_TTL_SECS = 6 * 3600


class IdempotencyMiddleware:
    def __init__(self, app: object) -> None:
        self.app = app  # type: ignore[attr-defined]

    async def __call__(self, scope, receive, send):  # type: ignore[no-untyped-def]
        if scope["type"] != "http" or scope.get("method") != "POST":
            await self.app(scope, receive, send)  # type: ignore[attr-defined]
            return
        headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
        idem_key = headers.get("idempotency-key")
        path = scope.get("path", "")
        if not idem_key or not path.startswith("/api/"):
            await self.app(scope, receive, send)  # type: ignore[attr-defined]
            return

        redis = getattr(app.state, "redis", None)
        if redis is None:
            await self.app(scope, receive, send)  # type: ignore[attr-defined]
            return

        auth = headers.get("authorization", "")
        principal = auth[-24:] if auth else "anon"
        store_key = f"reflex:idem:{principal}:{path}:{idem_key}"
        try:
            cached = redis.get(store_key)
        except Exception:
            cached = None
        if cached:
            # replay stored response via raw ASGI messages (never a bare return)
            saved = json.loads(cached)
            body = json.dumps(saved["body"]).encode()
            await send({
                "type": "http.response.start",
                "status": saved["status"],
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"idempotent-replay", b"true"),
                ],
            })
            await send({"type": "http.response.body", "body": body})
            return

        status_holder = {"status": 200}
        body_chunks: list[bytes] = []

        async def send_wrapper(message):  # type: ignore[no-untyped-def]
            if message["type"] == "http.response.start":
                status_holder["status"] = message["status"]
            elif message["type"] == "http.response.body":
                body_chunks.append(message.get("body", b""))
            await send(message)

        await self.app(scope, receive, send_wrapper)  # type: ignore[attr-defined]

        if status_holder["status"] < 500 and body_chunks:
            try:
                body_bytes = b"".join(body_chunks)
                saved_body = json.loads(body_bytes) if body_bytes else {}
                redis.setex(store_key, IDEMPOTENCY_TTL_SECS, json.dumps({"status": status_holder["status"], "body": saved_body}))
            except Exception:
                pass  # non-JSON or storage failure ⇒ never break the live request


app.add_middleware(IdempotencyMiddleware)


# ---- health ------------------------------------------------------------------------


@app.get("/")
def root() -> dict:
    return {"status": "ok", "service": "reflex-api", "docs": "/docs", "health": "/healthz"}

@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok", "service": "reflex-api"}


@app.get("/metrics")
def metrics_snapshot() -> dict:
    r: object = getattr(app.state, "redis", None)
    keys = [
        "events_ingested", "duplicates_collapsed", "episodes_created",
        "dx_rule", "dx_llm", "shield_pass", "shield_block", "shield_approval",
        "dispatched", "recovered",
    ]
    out = {}
    for k in keys:
        try:
            v = r.get(f"reflex:ctr:{k}") if r is not None and hasattr(r, "get") else None
        except Exception:
            v = None  # Redis not reachable on Antideploy single-DB deploys - return zeros instead of 500
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
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="malformed payload") from exc

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
        s.commit()
        s.close()


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
# export first: its static paths (/episodes/export) must outrank the
# parameterized /episodes/{episode_id} route registered later.
for router in (
    export.router,
    episodes.router,
    approvals.router,
    control.router,
    metrics.router,
    eval_api.router,
    ledger_api.router,
    onboarding.router,
):
    app.include_router(router, prefix="/api")
