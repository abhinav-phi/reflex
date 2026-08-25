"""Shared fixtures: DB cleanup, app client, seeded users, eval-role sessions."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("DATABASE_URL_ADMIN", "postgresql+psycopg://postgres:reflex_dev_pg@localhost:15432/reflex")
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://reflex_agent:agent_dev_pw@localhost:15432/reflex")
os.environ.setdefault("DATABASE_URL_EVAL", "postgresql+psycopg://reflex_eval:eval_dev_pw@localhost:15432/reflex")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("JWT_SECRET", "test-secret-not-a-real-secret")

TRUNCATE = """
TRUNCATE runtime.episodes, runtime.payment_events, runtime.actions,
         runtime.outcomes, runtime.candidate_interventions, runtime.diagnoses,
         runtime.action_ledger RESTART IDENTITY CASCADE;
"""


def _terminate_stray_backends(conn) -> None:  # type: ignore[no-untyped-def]
    """Kill leftover 'idle in transaction' sessions from earlier tests (TestClient
    lifespan engine pools, load-test helper connections). One such holder made
    every later TRUNCATE deadlock in CI: it keeps row locks while TRUNCATE needs
    AccessExclusiveLock, and the holder's next statement cycles into a lock wait.
    Safe here: dedicated test database, we connect as its owner."""
    from sqlalchemy import text

    conn.execute(
        text(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = current_database() AND pid <> pg_backend_pid() "
            "AND state = 'idle in transaction'"
        )
    )
    conn.commit()


def _flush_rate_limits(app) -> None:  # type: ignore[no-untyped-def]
    """Reset fixed-window limiter buckets. Every login in the suite shares the
    'auth_login' bucket (limit 20/min) via TestClient's constant host, so a
    full-suite CI run crosses the window and fails setup with 429s."""
    redis = getattr(app.state, "redis", None)
    if redis is None:
        return
    try:
        for key in list(redis.scan_iter("rl:*")):
            redis.delete(key)
    except Exception:
        pass  # limiter hygiene must never fail the test itself


@pytest.fixture()
def db_admin():  # type: ignore[no-untyped-def]
    from sqlalchemy import create_engine

    eng = create_engine(os.environ["DATABASE_URL_ADMIN"], future=True)
    conn = eng.connect()
    try:
        yield conn
    finally:
        conn.close()
        eng.dispose()


@pytest.fixture()
def clean_db(db_admin):  # type: ignore[no-untyped-def]
    from sqlalchemy import text

    import time

    last_exc: Exception | None = None
    for attempt in range(3):
        try:
            _terminate_stray_backends(db_admin)
            db_admin.execute(text(TRUNCATE))
            db_admin.commit()
            break
        except Exception as exc:  # belt-and-braces: self-heal a rare race
            db_admin.rollback()
            if "deadlock" not in str(exc).lower():
                raise
            last_exc = exc
            time.sleep(0.5 * (attempt + 1))
    else:
        raise AssertionError(f"TRUNCATE deadlocked after retries: {last_exc}")
    yield db_admin


@pytest.fixture()
def client(clean_db):  # type: ignore[no-untyped-def]
    from fastapi.testclient import TestClient
    from reflex.api.main import app

    with TestClient(app) as c:
        _flush_rate_limits(c.app)
        yield c


@pytest.fixture()
def tokens(client):  # type: ignore[no-untyped-def]
    def _tok(email: str) -> str:
        r = client.post("/api/auth/login", json={"email": email, "password": "reflex-demo"})
        assert r.status_code == 200, r.text
        return r.json()["token"]

    return {
        "admin": _tok("admin@reflex.dev"),
        "approver": _tok("approver@reflex.dev"),
        "operator": _tok("operator@reflex.dev"),
        "viewer": _tok("viewer@reflex.dev"),
        "none": "",
    }


@pytest.fixture()
def auth_h(tokens):  # type: ignore[no-untyped-def]
    def _h(role: str) -> dict:  # type: ignore[type-arg]
        t = tokens[role]
        return {"Authorization": f"Bearer {t}"} if t else {}

    return _h
