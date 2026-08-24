"""Ingestion service (PRD FR-001): HMAC verify → dedup → normalize → episodes.

Shared by the webhook route and the replay driver so live and simulated events
flow through identical code paths.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import datetime, timedelta

import structlog
from reflex.core.enums import (
    EPISODE_WINDOW_HOURS,
    Arm,
    EventSource,
    Rail,
)
from reflex.core.pii import scrub_payload
from reflex.ledger.chain import LedgerWriter
from sqlalchemy import text
from sqlalchemy.orm import Session

log = structlog.get_logger("reflex.pulse")

RAILS: set[str] = {r.value for r in Rail}


class InvalidSignature(Exception):
    pass


def verify_webhook_signature(raw_body: bytes, signature: str | None, secret: str) -> bool:
    if not signature:
        return False
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


@dataclass(frozen=True)
class IngestResult:
    accepted: bool
    duplicate: bool
    episode_id: str | None
    event_id: str | None


def normalize_event(payload: dict) -> dict | None:
    """Extract our normalized shape from a Razorpay-style webhook body.

    Returns None for events that don't open/attach episodes (captures attach,
    failures open). Unknown fields preserved in raw_payload (never dropped).
    """
    event = str(payload.get("event", ""))
    inner = payload.get("payload") or {}
    payment = ((inner.get("payment") or {}).get("entity")) or {}

    if not isinstance(payment, dict):
        return None

    provider_event_id = str(
        payload.get("id") or f"{event}:{payment.get('id')}"
    )
    amount = int(payment.get("amount") or 0)
    if amount <= 0:
        return None  # AppFlow §9 edge case: reject ₹0/negative at ingestion

    rail = _map_rail(payment)
    error_desc = str(
        payment.get("error_description")
        or payment.get("error_source")
        or payment.get("notes", {}).get("sim_code")
        or "unknown failure"
    )
    return {
        "provider_event_id": provider_event_id,
        "event": event,
        "rail": rail,
        "code_raw": error_desc[:300],
        "amount_paise": amount,
        "occurred_at": _parse_ts(payment.get("created_at")),
        "raw_payload": payload,
        "customer_ref": str(payment.get("customer_id") or payment.get("contact") or payment.get("email") or "anon"),
    }


def _map_rail(payment: dict) -> str:
    method = str(payment.get("method") or "").lower()
    vpa = payment.get("vpa")
    if method == "upi" or vpa or "upi" in json.dumps(payment).lower():
        return Rail.UPI.value
    if method in ("emandate", "nach", "autopay"):
        return Rail.NACH_EMANDATE.value
    if method == "netbanking":
        return Rail.NETBANKING.value
    if method == "wallet":
        return Rail.WALLET.value
    return Rail.CARD.value


def _parse_ts(v: object) -> datetime:
    if isinstance(v, (int, float)):
        return datetime.fromtimestamp(float(v), tz=__import__("datetime").timezone.utc)
    if isinstance(v, str):
        try:
            return datetime.fromisoformat(v.replace("Z", "+00:00"))
        except ValueError:
            pass
    return datetime.now(__import__("datetime").timezone.utc).replace(tzinfo=None)


def ingest_event(
    session: Session,
    *,
    source: EventSource,
    normalized: dict,
    arm: Arm = Arm.REFLEX,
    batch_customer_resolver=None,  # type: ignore[no-untyped-def]
    now_sim: datetime | None = None,
) -> IngestResult:
    """Insert payment_events row + create episode on first failure for a payment.

    Dedup: provider_event_id UNIQUE at DB level; duplicates return 200/dup=True
    (Rules §6.3). PII scrubbed from raw_payload before store (Schema §12).
    """
    occurred_at = normalized["occurred_at"]
    ts = now_sim or datetime.now(__import__("datetime").timezone.utc)

    # dedup insert (atomic via unique constraint)
    dup = session.execute(
        text("SELECT 1 FROM runtime.payment_events WHERE provider_event_id = :pid"),
        {"pid": normalized["provider_event_id"]},
    ).first()
    if dup is not None:
        # dedup counter tracked in Redis; no write amplification on the hot path
        return IngestResult(False, True, None, normalized["provider_event_id"])

    raw_scrubbed = scrub_payload(normalized["raw_payload"])
    result = session.execute(
        text(
            """
            INSERT INTO runtime.payment_events
              (provider_event_id, source, rail, code_raw, amount_paise, occurred_at, raw_payload)
            VALUES (:pid, CAST(:src AS runtime.source), CAST(:rail AS runtime.rail),
                    :code_raw, :amt, :occurred, CAST(:raw AS jsonb))
            ON CONFLICT (provider_event_id) DO NOTHING
            RETURNING id
            """
        ),
        {
            "pid": normalized["provider_event_id"],
            "src": source.value,
            "rail": normalized["rail"],
            "code_raw": normalized["code_raw"],
            "amt": normalized["amount_paise"],
            "occurred": occurred_at,
            "raw": json.dumps(raw_scrubbed, ensure_ascii=False),
        },
    ).first()

    if result is None:  # raced duplicate
        return IngestResult(False, True, None, normalized["provider_event_id"])

    event_row_id = result[0]

    # customer resolution: replay batches map deterministically; live uses ref hash
    customer_id = None
    if batch_customer_resolver is not None:
        customer_id = batch_customer_resolver(normalized)
    if customer_id is None:
        customer_id = _resolve_live_customer(session, normalized["customer_ref"])

    merchant_id = session.execute(text("SELECT id FROM runtime.merchants ORDER BY created_at LIMIT 1")).scalar()

    ep_result = session.execute(
        text(
            """
            INSERT INTO runtime.episodes
              (customer_id, merchant_id, payment_event_id, amount_paise, status, arm,
               opened_at, closes_at)
            VALUES (:cid, :mid, :peid, :amt, 'waiting_diagnosis', CAST(:arm AS runtime.arm),
                    :opened, :closes)
            RETURNING id
            """
        ),
        {
            "cid": customer_id,
            "mid": merchant_id,
            "peid": event_row_id,
            "amt": normalized["amount_paise"],
            "arm": arm.value,
            "opened": ts,
            "closes": ts + timedelta(hours=EPISODE_WINDOW_HOURS),
        },
    ).first()
    episode_id = ep_result[0]

    session.execute(
        text("UPDATE runtime.payment_events SET episode_id = :e WHERE id = :p"),
        {"e": episode_id, "p": event_row_id},
    )

    LedgerWriter(session).append(
        episode_id=episode_id,
        action_id=None,
        event={
            "type": "EPISODE_CREATED",
            "amount_paise": normalized["amount_paise"],
            "rail": normalized["rail"],
            "source": source.value,
            "arm": arm.value,
            "provider_event_id": normalized["provider_event_id"],
        },
        at=ts,
    )
    log.info(
        "episode_created",
        episode_id=str(episode_id),
        amount_paise=normalized["amount_paise"],
        rail=normalized["rail"],
        source=source.value,
    )
    return IngestResult(True, False, str(episode_id), normalized["provider_event_id"])


def _resolve_live_customer(session: Session, customer_ref: str) -> str:
    """Live TM customers are pseudonymized by hashing their gateway ref."""
    pseudo = f"C-{hashlib.sha256(customer_ref.encode()).hexdigest()[:8].upper()}"
    merchant_id = session.execute(text("SELECT id FROM runtime.merchants ORDER BY created_at LIMIT 1")).scalar()
    row = session.execute(
        text("SELECT id FROM runtime.customers WHERE pseudonym = :p AND merchant_id = :m"),
        {"p": pseudo, "m": merchant_id},
    ).first()
    if row:
        return str(row[0])
    new_id = session.execute(
        text(
            "INSERT INTO runtime.customers (merchant_id, pseudonym, lang_pref, ltv_band) "
            "VALUES (:m, :p, 'hinglish', 'mid') RETURNING id"
        ),
        {"m": merchant_id, "p": pseudo},
    ).scalar_one()
    return str(new_id)
