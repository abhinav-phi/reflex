"""Shared fixtures: DB cleanup, app client, seeded users, eval-role sessions."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("DATABASE_URL_ADMIN", "postgresql+psycopg://postgres:reflex_dev_pg@localhost:5432/reflex")
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://reflex_agent:agent_dev_pw@localhost:5432/reflex")
os.environ.setdefault("DATABASE_URL_EVAL", "postgresql+psycopg://reflex_eval:eval_dev_pw@localhost:5432/reflex")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("JWT_SECRET", "test-secret-not-a-real-secret")

TRUNCATE = """
TRUNCATE runtime.episodes, runtime.payment_events, runtime.actions,
         runtime.outcomes, runtime.candidate_interventions, runtime.diagnoses,
         runtime.action_ledger RESTART IDENTITY CASCADE;
"""


@pytest.fixture()
def db_admin():  # type: ignore[no-untyped-def]
    from sqlalchemy import create_engine, text

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

    db_admin.execute(text(TRUNCATE))
    db_admin.commit()
    yield db_admin


@pytest.fixture()
def client(clean_db):  # type: ignore[no-untyped-def]
    from fastapi.testclient import TestClient

    from reflex.api.main import app

    with TestClient(app) as c:
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
