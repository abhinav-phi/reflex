"""Security suite: Shield isolation, agent-role DB lockout, PII scanner (ADR-001/004)."""

import ast
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

# Shield may import ONLY stdlib + reflex.core (TechSpec §6 isolation contract)
SHIELD_ALLOWED_PREFIXES = ("reflex.core", "reflex", "reflex.shield")

# Agent decision code must never touch hidden replay truth by name
AGENT_DECISION_MODULES = [
    "packages/core",
    "packages/shield",
    "packages/brain",
    "apps/api/ingest_service.py",
    "apps/api/routes",
    "apps/workers/planner.py",
    "apps/workers/context.py",
    "apps/workers/diagnosis.py",
    "apps/workers/dispatcher.py",
]


def _imports_of(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    mods: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                mods.add(a.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            mods.add(node.module.split(".")[0])
    return mods


def test_shield_import_isolation():
    """Shield has no network / LLM / Brain dependencies — import-lint (ADR-001)."""
    forbidden = {"httpx", "requests", "redis", "sqlalchemy", "openai", "sklearn"}
    shield_dir = REPO / "packages" / "shield"
    for py in shield_dir.rglob("*.py"):
        mods = _imports_of(py)
        assert not (mods & forbidden), f"{py.name} imports {mods & forbidden}"
        for m in mods:
            if m in ("brain", "connectors", "api", "workers", "eval"):
                raise AssertionError(f"{py.name} imports protected module {m}")


def test_agent_code_never_references_replay_tables():
    """Rules §17.7: agent decision modules must not read replay.sim_* (name-level
    lint; the hard guarantee is the DB role)."""
    banned = ["sim_customers", "sim_events"]
    targets = [REPO / "apps" / "workers" / "planner.py",
               REPO / "apps" / "workers" / "context.py",
               REPO / "apps" / "workers" / "diagnosis.py"]
    brain_dir = REPO / "packages" / "brain"
    targets.extend(brain_dir.rglob("*.py"))
    for t in targets:
        if not t.exists():
            continue
        src = t.read_text(encoding="utf-8")
        for b in banned:
            assert b not in src or b == "", f"{t.name} references {b}"
    # simulator.py is the ONLY allowed consumer (Proof side) — it must live in eval/sim module
    sim = (REPO / "apps" / "workers" / "simulator.py").read_text(encoding="utf-8")
    assert "replay.sim_customers" in sim  # exists, but ONLY there


def _agent_conn():  # type: ignore[no-untyped-def]
    import os

    import psycopg

    # honor env (conftest defaults) — hardcoded 5432 hangs on hosts where the
    # port is firewalled/reserved (e.g., Windows excluded-port ranges)
    url = os.environ.get(
        "DATABASE_URL",
        "postgresql://reflex_agent:agent_dev_pw@localhost:15432/reflex",
    )
    return psycopg.connect(url.replace("+psycopg", ""), autocommit=True)


@pytest.mark.integration
def test_agent_role_cannot_read_replay(clean_db):  # type: ignore[no-untyped-def]
    conn = _agent_conn()
    try:
        with pytest.raises(Exception):
            conn.execute("SELECT count(*) FROM replay.sim_customers").fetchone()
    finally:
        conn.close()


@pytest.mark.integration
def test_agent_role_cannot_update_ledger(clean_db):  # type: ignore[no-untyped-def]
    import os

    from sqlalchemy import create_engine, text

    admin_url = os.environ.get(
        "DATABASE_URL_ADMIN",
        "postgresql+psycopg://postgres:reflex_dev_pg@localhost:15432/reflex",
    )
    eng = create_engine(admin_url)
    with eng.begin() as c:
        c.execute(text(OPEN_EPISODE))
        ep = c.execute(text("SELECT id FROM runtime.episodes LIMIT 1")).scalar()
        if ep is None:
            return  # no data yet
    conn = _agent_conn()
    try:
        with pytest.raises(Exception):
            conn.execute(
                "UPDATE runtime.action_ledger SET hash='x' WHERE episode_id=%s", (ep,)
            )
    finally:
        conn.close()


OPEN_EPISODE = """
INSERT INTO runtime.customers (merchant_id, pseudonym)
SELECT m.id, 'C-TEST-SEC' FROM runtime.merchants m LIMIT 1
"""


@pytest.mark.integration
def test_no_pii_in_llm_call_logs_after_run(clean_db):  # type: ignore[no-untyped-def]
    """Schema §12: llm_calls inputs are redacted at write (scanner gate)."""
    from sqlalchemy import text as sql_text

    from reflex.api.db import eval_sessionmaker
    from reflex.eval.seed import ensure_reference_data
    from reflex.eval.runner import prepare_batch
    from reflex.eval.pipeline import run_arm
    from reflex.core.enums import Arm
    from reflex.core.pii import assert_no_pii

    s = eval_sessionmaker()()
    try:
        ensure_reference_data(s)
        batch_id, bt = prepare_batch(s, seed=99, n=6)
        run_arm(s, batch_id=batch_id, batch=bt[0], merchant_id=bt[2],
                customer_ids=bt[1], arm=Arm.REFLEX)
        rows = s.execute(sql_text(
            "SELECT input_redacted::text FROM runtime.llm_calls")).scalars().all()
        for blob in rows:
            assert_no_pii(blob)  # raises on email/vpa/phone/card patterns
    finally:
        s.close()
