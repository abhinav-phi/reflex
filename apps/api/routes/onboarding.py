"""Onboarding flow (AppFlow §2): keys check, webhook setup, guardrails, mode."""

from __future__ import annotations

import secrets
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from reflex.api.security import require_role
from reflex.core.enums import Mode, Role
from reflex.core.schemas import GuardrailSettingsUpdate
from sqlalchemy import text

router = APIRouter()


class OnboardingState(BaseModel):
    configured: bool


@router.get("/onboarding/state")
def state(user: dict[str, Any] = Depends(require_role(Role.ADMIN))) -> dict:
    from reflex.api.db import agent_sessionmaker

    s = agent_sessionmaker()()
    try:
        row = s.execute(
            text("SELECT name, cfg, mode::text AS mode FROM runtime.merchants ORDER BY created_at LIMIT 1")
        ).first()
        return {
            "configured": row is not None,
            "merchant": {"name": row[0], "cfg": dict(row[1] or {}), "mode": row[2]} if row else None,
        }
    finally:
        s.close()


@router.post("/onboarding/verify_keys")
def verify_keys(body: dict[str, str], user: dict[str, Any] = Depends(require_role(Role.ADMIN))) -> dict:
    """Connectivity check per AppFlow §2: create + cancel a ₹1 test order."""
    from reflex.connectors.errors import ConnectorError, TestModeViolation
    from reflex.connectors.razorpay import RazorpayTestModeClient

    key_id = body.get("key_id", "")
    if not key_id.startswith("rzp_test_"):
        raise HTTPException(status_code=400, detail="only rzp_test_ keys are permitted [TEST MODE]")
    client = RazorpayTestModeClient(key_id=key_id, key_secret=body.get("key_secret", ""))
    try:
        order = client.create_order(amount_paise=100, receipt="reflex-onboarding-check")
        client.cancel_order(str(order.provider_ref))
    except TestModeViolation as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ConnectorError as exc:
        raise HTTPException(status_code=502, detail=f"razorpay check failed: {exc}") from exc
    return {"ok": True, "note": "[TEST MODE] ₹1 test order created and cancelled"}


@router.post("/onboarding/webhook_secret")
def webhook_secret(user: dict[str, Any] = Depends(require_role(Role.ADMIN))) -> dict:
    generated = "whsec_" + secrets.token_hex(16)
    return {
        "webhook_url": "/webhooks/razorpay",
        "secret_generated": True,
        "note": "store via env RAZORPAY_WEBHOOK_SECRET; HMAC ping uses X-Razorpay-Signature",
        "secret_preview": generated[:10] + "...",
    }


@router.post("/onboarding/guardrails")
def guardrails(
    body: GuardrailSettingsUpdate,
    request: Request,
    user: dict[str, Any] = Depends(require_role(Role.ADMIN)),
) -> dict:
    """Guardrail defaults — merchant cfg may only tighten hard bounds; changes ledgered."""
    from reflex.api.db import agent_sessionmaker
    from reflex.shield.guardrails import MerchantGuardrails

    effective = MerchantGuardrails.from_merchant_cfg(
        {
            "caps_per_episode": body.caps_per_episode or 4,
            "contacts_per_day": body.contacts_per_day or 2,
            "budget_paise_daily": body.budget_paise_daily or 500_000,
            "approval_threshold_paise": body.approval_threshold_paise or 5_000_000,
        }
    )
    s = agent_sessionmaker()()
    try:
        row = s.execute(text("SELECT id FROM runtime.merchants ORDER BY created_at LIMIT 1")).first()
        if row is None:
            raise HTTPException(status_code=404, detail="no merchant configured")
        before = s.execute(
            text("SELECT cfg FROM runtime.merchants WHERE id = :m"), {"m": row[0]}
        ).scalar_one()
        new_cfg = dict(before or {})
        new_cfg.update(
            {
                "caps_per_episode": effective.caps_per_episode,
                "contacts_per_day": effective.contacts_per_day,
                "budget_paise_daily": effective.budget_paise_daily,
                "approval_threshold_paise": effective.approval_threshold_paise,
                "quiet_hours": body.quiet_hours or "21:00-09:00",
            }
        )
        s.execute(text("UPDATE runtime.merchants SET cfg = CAST(:c AS jsonb) WHERE id = :m"), {"c": _dumps(new_cfg), "m": row[0]})
        s.execute(
            text(
                "INSERT INTO runtime.guardrail_settings_history (merchant_id, diff, actor) "
                "VALUES (:m, CAST(:d AS jsonb), :a)"
            ),
            {"m": row[0], "d": _dumps({"before": before, "after": new_cfg}), "a": user["user_id"]},
        )
        s.commit()
        return {"ok": True, "effective": new_cfg}
    finally:
        s.close()


@router.post("/onboarding/mode")
def choose_mode(body: dict[str, str], user: dict[str, Any] = Depends(require_role(Role.ADMIN))) -> dict:
    mode = Mode(body.get("mode", "advisory"))
    from reflex.api.db import agent_sessionmaker

    s = agent_sessionmaker()()
    try:
        s.execute(text("UPDATE runtime.merchants SET mode = CAST(:m AS runtime.mode)"), {"m": mode.value})
        s.execute(
            text(
                "INSERT INTO runtime.mode_changes (merchant_id, from_mode, to_mode, actor, reason) "
                "SELECT id, mode, CAST(:m AS runtime.mode), :a, 'onboarding' FROM runtime.merchants"
            ),
            {"m": mode.value, "a": user["user_id"]},
        )
        s.commit()
        return {"ok": True, "mode": mode.value}
    finally:
        s.close()


def _dumps(obj: dict) -> str:
    import json

    return json.dumps(obj)
