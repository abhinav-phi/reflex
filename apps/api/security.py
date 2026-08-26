"""Auth + RBAC middleware (TASK-011) and rate limiting (TechSpec §10).

Server-side enforcement only — UI hiding is cosmetic (Rules §1.2).
JWT 8h; seeded demo users; no self-signup (TechSpec §12.1).
"""

from __future__ import annotations

import hashlib
import hmac
import time
from typing import Any

import jwt
import structlog
from fastapi import Depends, HTTPException, Request
from reflex.core.enums import ROLE_ORDER, Role
from reflex.core.settings import get_settings
from sqlalchemy import text
from sqlalchemy.orm import Session

log = structlog.get_logger("reflex.auth")

# ---- passwords (pbkdf2, stdlib) ------------------------------------------------


def hash_password(password: str, salt: str = "reflex-static-demo-salt") -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 200_000).hex()


def verify_password(password: str, stored: str) -> bool:
    return hmac.compare_digest(hash_password(password), stored)


# ---- JWT ------------------------------------------------------------------------


def create_token(user_id: str, role: str) -> str:
    s = get_settings()
    now = int(time.time())
    return jwt.encode(
        {"sub": user_id, "role": role, "iat": now, "exp": now + s.jwt_ttl_hours * 3600},
        s.jwt_secret,
        algorithm="HS256",
    )


def decode_token(token: str) -> dict[str, Any]:
    try:
        return jwt.decode(token, get_settings().jwt_secret, algorithms=["HS256"])
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(status_code=401, detail="token expired") from exc
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status_code=401, detail="invalid token") from exc


def bearer_payload(request: Request) -> dict[str, Any]:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    return decode_token(auth[7:])


def current_user(request: Request) -> dict[str, Any]:
    payload = bearer_payload(request)
    if payload.get("exp", 0) < time.time():
        raise HTTPException(status_code=401, detail="token expired")
    return {"user_id": payload["sub"], "role": Role(payload["role"])}


def require_role(minimum: Role):
    def dep(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
        if ROLE_ORDER[user["role"]] < ROLE_ORDER[minimum]:
            log.info("rbac_denied", role=user["role"], required=minimum.value)
            raise HTTPException(status_code=403, detail="insufficient role")
        return user

    return dep


# ---- login against seeded users ---------------------------------------------------


def authenticate(session: Session, email: str, password: str) -> dict[str, Any] | None:
    # Try Postgres query first, fallback to SQLite-compatible for Antideploy Node builds where we use sqlite + "runtime.users"
    try:
        row = session.execute(
            text("SELECT id, role::text, password_hash FROM runtime.users WHERE email = :e"),
            {"e": email},
        ).first()
    except Exception as _e:
        # SQLite fallback: no :: cast, and table may be "runtime.users" quoted
        if "no such table" in str(_e).lower() or "syntax" in str(_e).lower() or "near" in str(_e).lower():
            try:
                row = session.execute(
                    text('SELECT id, role, password_hash FROM "runtime.users" WHERE email = :e'),
                    {"e": email},
                ).first()
            except Exception:
                row = session.execute(
                    text("SELECT id, role, password_hash FROM users WHERE email = :e"),
                    {"e": email},
                ).first()
        else:
            raise
    if row is None or not verify_password(password, str(row[2])):
        log.info("login_failed", email=email)
        return None
    return {"user_id": str(row[0]), "role": str(row[1])}


# ---- rate limiting (Redis fixed window per route+principal) -----------------------

RATE_LIMITS: dict[str, tuple[int, int]] = {
    # route prefix → (max requests, window secs) per TechSpec §10
    "webhook": (500, 60),
    "replay_start": (10, 60),
    "episodes_list": (60, 60),
    "episode_get": (120, 60),
    "approvals": (30, 60),
    "control_mode": (12, 60),
    "control_inject": (12, 60),
    "metrics_live": (60, 60),
    "metrics_eval": (60, 60),
    "eval_run": (2, 60),
    "stream": (5, 60),
    "ledger_verify": (6, 60),
    "auth_login": (20, 60),
}


class RateLimiter:
    def __init__(self, redis_client) -> None:  # type: ignore[no-untyped-def]
        self.r = redis_client

    def check(self, bucket: str, principal: str) -> None:
        limit, window = RATE_LIMITS.get(bucket, (60, 60))
        key = f"rl:{bucket}:{principal}:{int(time.time() // window)}"
        try:
            count = self.r.incr(key)
            if count == 1:
                self.r.expire(key, window)
        except Exception:
            return  # limiter outage must not take the API down; log path covers abuse
        if count > limit:
            raise HTTPException(status_code=429, detail="rate limit exceeded")


def principal_of(request: Request) -> str:
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        try:
            return str(decode_token(auth[7:]).get("sub"))
        except HTTPException:
            return "anon"
    ip = request.client.host if request.client else "unknown"
    return f"ip:{ip}"
