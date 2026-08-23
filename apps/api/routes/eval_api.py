"""Eval run API (operator) — refuses to run without the pre-registration tag."""

from __future__ import annotations

import subprocess
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import text

from reflex.api.security import require_role
from reflex.core.enums import Role
from reflex.core.schemas import EvalRunRequest

router = APIRouter()

PREREG_TAG = "eval-preregistered-v1"


def _tag_exists() -> bool:
    try:
        out = subprocess.run(
            ["git", "tag", "--list", PREREG_TAG], capture_output=True, text=True, timeout=10
        )
        return bool(out.stdout.strip())
    except Exception:
        return False


@router.post("/eval/run")
def run_eval(
    body: EvalRunRequest,
    request: Request,
    user: dict[str, Any] = Depends(require_role(Role.OPERATOR)),
) -> dict:
    request.app.state.rate.check("eval_run", user["user_id"])
    if not _tag_exists():
        raise HTTPException(
            status_code=409,
            detail=f"refusing to run official eval: protocol tag {PREREG_TAG} missing from git history",
        )
    redis = request.app.state.redis
    if redis.get("reflex:eval:running"):
        raise HTTPException(status_code=409, detail="an eval run is already in progress")

    from reflex.eval.runner import run_protocol_async

    config = body.config or None
    import threading

    thread = threading.Thread(target=_run_bg, args=(config,), daemon=True)
    redis.set("reflex:eval:running", "1")
    thread.start()
    return {"ok": True, "note": "protocol run started; results appear in /api/metrics/eval [SIMULATED]"}


def _run_bg(config: dict | None) -> None:
    try:
        from reflex.eval.runner import run_protocol_sync

        run_protocol_sync(config_override=config, quick=False)
    finally:
        try:
            from reflex.api.db import get_redis

            get_redis().delete("reflex:eval:running")
        except Exception:
            pass


@router.get("/eval/status")
def status(request: Request, user: dict[str, Any] = Depends(require_role(Role.VIEWER))) -> dict:
    running = bool(request.app.state.redis.get("reflex:eval:running"))
    return {"running": running, "preregistered_tag": PREREG_TAG, "tag_present": _tag_exists()}
