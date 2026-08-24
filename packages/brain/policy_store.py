"""Policy version store. v1 = frozen priors; v2+ trained on replay outcomes."""

from __future__ import annotations

from typing import Any

from reflex.brain.ev import POLICY_V1
from sqlalchemy import text
from sqlalchemy.orm import Session

FROZEN_V1: dict[str, Any] = {
    "id": "v1",
    "source": "literature-calibrated priors (data/calibration_sources.md)",
}


def load_active_policy(session: Session) -> tuple[str, dict[str, Any]]:
    """Returns (version_id, params). Falls back to frozen v1 if DB unavailable/empty."""
    try:
        row = session.execute(
            text(
                "SELECT id, params FROM runtime.policy_versions "
                "ORDER BY created_at DESC LIMIT 1"
            )
        ).first()
        if row is not None:
            return str(row[0]), dict(row[1])
    except Exception:
        pass
    return POLICY_V1, FROZEN_V1
