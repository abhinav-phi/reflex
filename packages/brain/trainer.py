"""Policy v2 trainer (TASK-029, P1): logistic regression on replay outcomes.

Fits sklearn LogisticRegression on features extracted from a completed eval
batch's episodes (diagnosis code, amount band, rail, contact count, hour,
salary proximity, LTV band, channel) → recovered label. Stores coefficients in
policy_versions (explainable EV drawer, ADR-005) + learning-curve datapoint
(v1 vs v2 log-loss on the same data).
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from sqlalchemy import text
from sqlalchemy.orm import Session

CODES = [
    "INSUFFICIENT_FUNDS", "ISSUER_DOWNTIME", "EXPIRED_CARD", "AUTH_DECLINED_SOFT",
    "AUTH_DECLINED_HARD", "RISK_HELD", "MANDATE_REVOKED", "MANDATE_LIMIT_BREACH",
    "INVALID_VPA", "CUSTOMER_INITIATED", "UNKNOWN_AMBIGUOUS",
]
CHANNELS = ["wa_sim", "sms_sim", "email_sim", "voice_sim", "razorpay_tm"]
RAILS = ["card", "upi", "netbanking", "wallet", "nach_emandate"]


def _onehot(value: str, vocab: list[str]) -> list[float]:
    return [1.0 if value == v else 0.0 for v in vocab]


def featurize_row(row: dict) -> list[float]:  # type: ignore[type-arg]
    feats: list[float] = []
    feats += _onehot(row["code"], CODES)
    feats += _onehot(row["channel"] or "", CHANNELS)
    feats += _onehot(row["rail"], RAILS)
    band = 0.0 if row["amount_paise"] < 25_000 else 1.0 if row["amount_paise"] < 50_000 else 2.0 if row["amount_paise"] < 100_000 else 3.0
    feats += [band / 3.0, row["actions_used"] / 4.0, row["hour_ist"] / 23.0, 1.0 - min(abs(row["day_of_month"] - 4) / 15.0, 1.0)]
    return feats


def train_v2(session: Session, batch_prefix: str | None = None) -> dict:
    rows = session.execute(
        text(
            """
            SELECT d.canonical_code::text AS code, e.amount_paise, pe.rail::text AS rail,
                   e.actions_used, EXTRACT(hour FROM e.opened_at) AS hour_ist,
                   EXTRACT(day FROM e.opened_at) AS day_of_month,
                   (SELECT a.channel::text FROM runtime.actions a WHERE a.episode_id=e.id
                     AND a.dispatched_at IS NOT NULL ORDER BY a.created_at DESC LIMIT 1) AS channel,
                   EXISTS (SELECT 1 FROM runtime.outcomes o WHERE o.episode_id=e.id
                            AND o.outcome='recovered') AS y
            FROM runtime.episodes e
            JOIN runtime.payment_events pe ON pe.id = e.payment_event_id
            LEFT JOIN LATERAL (SELECT canonical_code::text FROM runtime.diagnoses dx
                                WHERE dx.episode_id=e.id ORDER BY created_at DESC LIMIT 1) d ON true
            WHERE e.arm = 'reflex' AND pe.source='replay'
              AND (:bp IS NULL OR pe.provider_event_id LIKE :bp)
              AND d.canonical_code IS NOT NULL
            LIMIT 20000
            """
        ),
        {"bp": f"%{batch_prefix}%" if batch_prefix else None},
    ).mappings().all()

    if len(rows) < 200:
        return {"ok": False, "note": f"insufficient rows ({len(rows)}) for training"}

    X = np.array([featurize_row(dict(r)) for r in rows])
    y = np.array([int(r["y"]) for r in rows])

    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import log_loss
    from sklearn.model_selection import train_test_split

    Xtr, Xte, ytr, yte = train_test_split(X, y, test_size=0.25, random_state=42, stratify=y)
    clf = LogisticRegression(max_iter=500, C=1.0)
    clf.fit(Xtr, ytr)
    loss_v2 = float(log_loss(yte, clf.predict_proba(Xte), labels=[0, 1]))

    # v1 baseline on the same split: constant prior = train mean
    prior = float(np.clip(ytr.mean(), 1e-6, 1 - 1e-6))
    loss_v1 = float(log_loss(yte, np.full((len(yte), 2), [1 - prior, prior]), labels=[0, 1]))

    coefs = {
        "feature_order": ["code:" + c for c in CODES]
        + ["channel:" + c for c in CHANNELS]
        + ["rail:" + r for r in RAILS]
        + ["amount_band", "contact_count", "hour", "salary_proximity"],
        "coefficients": [round(float(x), 5) for x in clf.coef_[0]],
        "intercept": round(float(clf.intercept_[0]), 5),
    }

    version_id = "v2"
    session.execute(
        text(
            "INSERT INTO runtime.policy_versions (id, params, notes) "
            "VALUES (:id, CAST(:p AS jsonb), :n) "
            "ON CONFLICT (id) DO UPDATE SET params = CAST(:p AS jsonb), notes = :n"
        ),
        {
            "id": version_id,
            "p": json.dumps(coefs),
            "n": f"trained on {len(rows)} replay episodes; val log-loss v2={loss_v2:.4f} vs v1-prior={loss_v1:.4f}",
        },
    )
    session.commit()

    curve_path = Path(__file__).resolve().parents[3] / "eval" / "results" / "learning_curve.json"
    curve_path.parent.mkdir(parents=True, exist_ok=True)
    curve = {"[SIMULATED]": True, "points": [{"version": "v1-prior", "val_log_loss": round(loss_v1, 4)}, {"version": "v2-trained", "val_log_loss": round(loss_v2, 4)}]}
    curve_path.write_text(json.dumps(curve, indent=2), encoding="utf-8")

    return {
        "ok": True,
        "rows": len(rows),
        "v2_val_log_loss": round(loss_v2, 4),
        "v1_prior_val_log_loss": round(loss_v1, 4),
        "beats_v1": loss_v2 < loss_v1,
        "curve_file": str(curve_path),
    }
