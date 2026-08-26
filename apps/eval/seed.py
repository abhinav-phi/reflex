"""Idempotent reference seed (make seed): users, merchant SipDaily, policy v1."""

from __future__ import annotations

import json
import sys

from reflex.api.security import hash_password
from sqlalchemy import text
from sqlalchemy.orm import Session


def ensure_reference_data(session: Session, verbose: bool = False) -> None:
    def log(msg: str) -> None:
        if verbose:
            print(msg, file=sys.stderr)

    # ---- users (AppFlow §3: admin@/approver@/operator@/viewer@reflex.dev) -----
    users = [
        ("admin@reflex.dev", "admin", "admin"),
        ("approver@reflex.dev", "approver", "approver"),
        ("operator@reflex.dev", "operator", "operator"),
        ("viewer@reflex.dev", "viewer", "viewer"),
    ]
    for email, _label, role in users:
        row = session.execute(
            text("SELECT id FROM runtime.users WHERE email = :e"), {"e": email}
        ).first()
        if row is None:
            session.execute(
                text(
                    "INSERT INTO runtime.users (email, role, password_hash) "
                    "VALUES (:e, CAST(:r AS runtime.role), :p)"
                ),
                {"e": email, "r": role, "p": hash_password("reflex-demo")},
            )
            log(f"user seeded: {email} ({role}) password: reflex-demo")

    # ---- merchant SipDaily with guardrail defaults (PRD §9 step 1) -----------
    cfg = {
        "caps_per_episode": 4,
        "contacts_per_day": 2,
        "quiet_hours": "21:00-09:00",
        "budget_paise_daily": 500_000,
        "approval_threshold_paise": 5_000_000,
    }
    row = session.execute(text("SELECT id FROM runtime.merchants LIMIT 1")).first()
    if row is None:
        session.execute(
            text(
                "INSERT INTO runtime.merchants (name, cfg, mode) "
                "VALUES ('SipDaily', CAST(:c AS jsonb), 'advisory')"
            ),
            {"c": json.dumps(cfg)},
        )
        log("merchant seeded: SipDaily [SIMULATED]")

    # ---- policy v1 ------------------------------------------------------------
    row = session.execute(
        text("SELECT id FROM runtime.policy_versions WHERE id = 'v1'")
    ).first()
    if row is None:
        from reflex.brain.policy_store import FROZEN_V1

        params = dict(FROZEN_V1)
        params["model"] = "logistic-regression-priors"
        params["features"] = [
            "canonical_code", "amount_band", "rail", "contact_count", "hour",
            "day_of_month(salary proximity)", "ltv_band", "prior_recovered", "channel",
        ]
        session.execute(
            text(
                "INSERT INTO runtime.policy_versions (id, params, notes) "
                "VALUES ('v1', CAST(:p AS jsonb), :n)"
            ),
            {
                "p": json.dumps(params),
                "n": "Literature-calibrated priors; coefficients in reflex.brain.ev "
                "(data/calibration_sources.md). v2 trained on replay outcomes via trainer.",
            },
        )
        log("policy seeded: v1 (prior-frozen)")

    session.commit()


def main() -> int:  # console entrypoint: reflex-seed
    from reflex.api.db import admin_engine, agent_sessionmaker
    from sqlalchemy import text as _t

    # Try agent first (normal), fallback to admin for CI where agent role may not yet be usable
    # or where agent_engine fell back to sqlite. Also handle the case where runtime.users
    # doesn't exist (migrate not yet run) by trying admin.
    last_exc: Exception | None = None
    for mk in (agent_sessionmaker, lambda: __import__("sqlalchemy.orm", fromlist=["sessionmaker"]).sessionmaker(bind=admin_engine(), expire_on_commit=False)):
        try:
            s = mk()()  # type: ignore[operator]
            try:
                # quick probe: does runtime.users exist?
                s.execute(_t("SELECT 1 FROM runtime.users LIMIT 1"))
                s.rollback()
                ensure_reference_data(s, verbose=True)
                print("seed complete (idempotent)")
                return 0
            finally:
                s.close()
        except Exception as e:
            last_exc = e
            # try next maker (agent -> admin)
            continue
    # if both failed, raise the last error for CI visibility
    if last_exc:
        raise last_exc
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
