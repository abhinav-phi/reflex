"""B1 honest-tuning search on DEV seeds {7, 99} (eval/PROTOCOL.md §3, TASK-032).

Grid over retry/SMS offsets; maximizes value-weighted recovery on dev seeds
only. The chosen configuration is committed to eval/results/b1_tuning.json with
the full search table — never tuned against eval seeds (Rules §4.8).
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import text

from reflex.api.db import eval_sessionmaker
from reflex.core.enums import Arm
from reflex.eval.generator import generate_batch
from reflex.eval.pipeline import run_arm
from reflex.eval.seed import ensure_reference_data

DEV_SEEDS = [7, 99]
DEV_N = 250

GRID = {
    "retry_offsets_hours": [(0.0, 6.0, 24.0), (0.0, 1.0, 12.0), (0.0, 12.0, 48.0)],
    "sms_offsets_hours": [(2.0, 30.0), (1.0, 24.0), (6.0, 48.0)],
}

RESULTS = Path(__file__).resolve().parents[2] / "eval" / "results"


def main() -> int:
    import logging

    logging.disable(logging.INFO)
    s = eval_sessionmaker()()
    table: list[dict] = []
    try:
        ensure_reference_data(s)
        from concurrent.futures import ThreadPoolExecutor

        from reflex.eval.runner import prepare_batch
        from reflex.workers import baselines as bl

        opened = datetime.now(timezone.utc).replace(microsecond=0)

        def _run_config(r_off, m_off):
            sess = eval_sessionmaker()()
            try:
                ensure_reference_data(sess)
                bl.B1_DEFAULTS["retry_offsets_hours"] = tuple(r_off)
                bl.B1_DEFAULTS["sms_offsets_hours"] = tuple(m_off)
                rates = []
                t0 = time.perf_counter()
                for seed in DEV_SEEDS:
                    # fresh batch per config ⇒ distinct provider-event namespace
                    batch_id, bt = prepare_batch(sess, seed=seed, n=DEV_N)
                    batch, cust_ids, mid = bt
                    res = run_arm(
                        sess, batch_id=batch_id, batch=batch, merchant_id=mid,
                        customer_ids=cust_ids, arm=Arm.B1, opened_at=opened,
                    )
                    failed = sum(e.amount_paise for e in batch.events)
                    rates.append(res.recovered_paise / failed * 100)
                return {
                    "retry_offsets_hours": list(r_off),
                    "sms_offsets_hours": list(m_off),
                    "dev_recovery_rate_pct_per_seed": [round(r, 2) for r in rates],
                    "mean": round(sum(rates) / len(rates), 2),
                    "secs": round(time.perf_counter() - t0, 1),
                }
            finally:
                sess.close()

        with ThreadPoolExecutor(max_workers=9) as pool:
            futs = [pool.submit(_run_config, ro, mo)
                    for ro in GRID["retry_offsets_hours"] for mo in GRID["sms_offsets_hours"]]
            for f in futs:
                entry = f.result()
                table.append(entry)
                print(json.dumps(entry))
    finally:
        s.close()

    best = max(table, key=lambda e: e["mean"])
    out = {
        "[SIMULATED]": True,
        "note": "B1 tuning search on DEV seeds only; eval seeds untouched "
        "(eval/PROTOCOL.md §3). Pre-registered default remains the shipped "
        "configuration unless the search shows a materially better one.",
        "pre_registered_default": {"retry_offsets_hours": [0.0, 6.0, 24.0], "sms_offsets_hours": [2.0, 30.0]},
        "grid": GRID,
        "search_table": table,
        "best": best,
        "chosen": best,
    }
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "b1_tuning.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"\nBEST: {json.dumps(best)}\nwritten: {RESULTS/'b1_tuning.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
