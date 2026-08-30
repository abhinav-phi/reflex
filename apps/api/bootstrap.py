"""Schema bootstrap — creates the full Reflex schema without requiring alembic.

Runs the same DDL as `alembic upgrade head` by importing the migration
modules and driving their `upgrade()` with a tiny alembic-compatible `op`
shim. This lets Antideploy/cloud deploys self-migrate on startup even when
the platform's migration job is skipped or unavailable.

Safe to call repeatedly: every DDL statement is idempotent-guarded the same
way the migrations guard themselves (to_regclass checks, IF NOT EXISTS,
duplicate-type/column swallows).
"""

from __future__ import annotations

import importlib.util
import logging
import sys
from pathlib import Path

from sqlalchemy import text

log = logging.getLogger("reflex.bootstrap")

_REPO_ROOT = Path(__file__).resolve().parents[2]
_MIGRATIONS = ("0001_baseline", "0002_actions_llm_call_id", "0003_pgcrypto")


class _FakeOp:
    """Minimal stand-in for alembic's `op` — execute() + get_bind() only."""

    def __init__(self, conn) -> None:  # type: ignore[no-untyped-def]
        self._conn = conn

    def execute(self, sql: str) -> None:  # type: ignore[no-untyped-def]
        self._conn.execute(text(sql))

    def get_bind(self):  # type: ignore[no-untyped-def]
        return self._conn


def _load_migration(name: str):  # type: ignore[no-untyped-def]
    """Import an alembic migration module, injecting a fake `alembic` package."""
    import types

    # Build a fake alembic.op module with execute() and get_bind()
    op_holder: dict[str, _FakeOp | None] = {"op": None}

    class _FakeOpModule(types.ModuleType):
        """This module does double duty as alembic.op and as the `op` object."""

        def execute(self, sql: str) -> None:  # type: ignore[no-untyped-def]
            if op_holder["op"] is None:
                raise RuntimeError("op not bound yet")
            op_holder["op"].execute(sql)

        def get_bind(self):  # type: ignore[no-untyped-def]
            if op_holder["op"] is None:
                raise RuntimeError("op not bound yet")
            return op_holder["op"].get_bind()

    op_mod = _FakeOpModule("alembic.op")

    # Thread the fake alembic package into sys.modules so that
    # `from alembic import op` resolves to op_mod, and
    # `from alembic import op as op` (which is the same) works.
    alembic_pkg = types.ModuleType("alembic")
    alembic_pkg.__path__ = []  # type: ignore[attr-defined]  # mark as a package
    alembic_pkg.op = op_mod  # from alembic import op ✓
    sys.modules["alembic"] = alembic_pkg
    sys.modules["alembic.op"] = op_mod

    path = _REPO_ROOT / "alembic" / "versions" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"alembic.versions.{name}", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[f"alembic.versions.{name}"] = mod
    spec.loader.exec_module(mod)
    return mod, op_holder


def ensure_schema(conn) -> bool:  # type: ignore[no-untyped-def]
    """Create the schema if missing. Returns True when it (re)created it."""
    try:
        exists = conn.execute(text("SELECT to_regclass('runtime.users')")).scalar()
        if exists is not None:
            return False
    except Exception:
        pass  # catalog query failed — try creating anyway

    log.info("bootstrap_schema_start")
    try:
        for name in _MIGRATIONS:
            mod, op_holder = _load_migration(name)
            op_holder["op"] = _FakeOp(conn)
            try:
                mod.upgrade()  # type: ignore[attr-defined]
            finally:
                op_holder["op"] = None
        log.info("bootstrap_schema_done")
        return True
    except Exception as exc:  # pragma: no cover - defensive
        log.error("bootstrap_schema_failed", error=str(exc)[:300])
        return False


def maybe_seed(conn) -> None:  # type: ignore[no-untyped-def]
    """Seed demo users/merchant if runtime.users is empty (idempotent)."""
    try:
        from reflex.eval.seed import main as seed_main

        cnt = conn.execute(text("SELECT count(*) FROM runtime.users")).scalar()
        if int(cnt or 0) == 0:
            log.info("bootstrap_seed_start")
            seed_main()
            log.info("bootstrap_seed_done")
    except Exception as exc:  # pragma: no cover - defensive
        log.error("bootstrap_seed_failed", error=str(exc)[:300])


def bootstrap(engine) -> None:  # type: ignore[no-untyped-def]
    """Create schema + seed if the app is starting against an empty database."""
    conn = None
    try:
        conn = engine.connect()
        created = ensure_schema(conn)
        if created:
            conn.commit()
            maybe_seed(conn)
            conn.commit()
    except Exception as exc:  # pragma: no cover - defensive
        log.error("bootstrap_failed", error=str(exc)[:300])
    finally:
        if conn is not None:
            conn.close()
