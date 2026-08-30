"""Copy official eval results from the local reproduction DB to production.

Reads eval.eval_runs / eval.eval_metrics (plus the replay.replay_batches rows
they reference) from the local reproduce.sh database and upserts them into the
production database with the SAME ids, so the deployed Results page shows the
pre-registered protocol runs. Idempotent (ON CONFLICT DO NOTHING).

    SRC="postgresql://postgres:reflex_dev_pg@localhost:15432/reflex" \
    DST="postgresql://postgres:...@shinkansen.proxy.rlwy.net:48122/railway?sslmode=require" \
    python scripts/copy_eval_to_railway.py
"""

from __future__ import annotations

import json
import os
import sys

from sqlalchemy import create_engine, text


def _engine(url: str):
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg2://", 1)
    return create_engine(url, pool_pre_ping=True)


def main() -> None:
    src = _engine(os.environ["SRC"])
    dst = _engine(os.environ["DST"])

    with src.connect() as s:
        runs = [dict(r) for r in s.execute(text("SELECT * FROM eval.eval_runs ORDER BY created_at")).mappings()]
        metrics = [dict(r) for r in s.execute(text("SELECT * FROM eval.eval_metrics")).mappings()]
        batch_ids = sorted({r["batch_id"] for r in runs})
        batches = []
        for bid in batch_ids:
            row = s.execute(text("SELECT * FROM replay.replay_batches WHERE id = CAST(:b AS uuid)"), {"b": str(bid)}).mappings().first()
            if row:
                batches.append(dict(row))
    print(f"local: {len(runs)} runs, {len(metrics)} metrics, {len(batches)} batches")

    with dst.begin() as d:
        for b in batches:
            d.execute(
                text("INSERT INTO replay.replay_batches (id, seed, n_episodes, arm, simulator_version) "
                     "VALUES (:id, :seed, :n_episodes, :arm, :simulator_version) ON CONFLICT (id) DO NOTHING"),
                {"id": str(b["id"]), "seed": int(b["seed"]), "n_episodes": int(b["n_episodes"]),
                 "arm": str(b["arm"]), "simulator_version": str(b["simulator_version"])},
            )
        for r in runs:
            d.execute(
                text("INSERT INTO eval.eval_runs (id, batch_id, arm, ablation, config, preregistered_tag, created_at) "
                     "VALUES (CAST(:id AS uuid), CAST(:batch_id AS uuid), :arm, :ablation, "
                     "CAST(:config AS jsonb), :preregistered_tag, :created_at) ON CONFLICT (id) DO NOTHING"),
                {"id": str(r["id"]), "batch_id": str(r["batch_id"]), "arm": str(r["arm"]),
                 "ablation": r["ablation"], "config": json.dumps(r["config"], ensure_ascii=False),
                 "preregistered_tag": r["preregistered_tag"], "created_at": r["created_at"]},
            )
        for m in metrics:
            d.execute(
                text("INSERT INTO eval.eval_metrics (id, run_id, metric, value, ci_low, ci_high, seed) "
                     "VALUES (CAST(:id AS uuid), CAST(:run_id AS uuid), :metric, :value, :ci_low, :ci_high, :seed) "
                     "ON CONFLICT (id) DO NOTHING"),
                {"id": str(m["id"]), "run_id": str(m["run_id"]), "metric": str(m["metric"]),
                 "value": m["value"], "ci_low": m["ci_low"], "ci_high": m["ci_high"], "seed": m["seed"]},
            )
    print("copy complete")


if __name__ == "__main__":
    main()
