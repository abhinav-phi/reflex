"""G5 reproduction check + A2 divergence analysis (PROTOCOL.md §5 G5, §6 honesty).

Reruns seed 42 with the FULL official arm set under identical serial conditions
and compares per-arm recovery rates against the committed official artifacts
(±0.005 absolute tolerance). Because batches and customer-response RNG streams
are seed-deterministic, Reflex and A2(EV-off) episodes can also be compared
PAIRWISE to localize exactly where EV ranking changes outcomes.

Artifacts: eval/results/g5_repro_check/{results.json, divergence.md}
This is a reproducibility/investigation run — NOT new headline evidence.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

OUT_DIR = Path(__file__).resolve().parents[1] / "eval" / "results" / "g5_repro_check"
COMMITTED = Path(__file__).resolve().parents[1] / "eval" / "results" / "20260825T221826Z" / "results.json"
SEED = 42
N = 3000
TOL = 0.005  # PROTOCOL G5: ±0.005 absolute on recovery_rate

ARMS = [
    ("b0", "b0", None, None),
    ("b1", "b1", None, None),
    ("reflex", "reflex", None, None),
    ("reflex:A1", "reflex", "A1", dict(llm_tail_enabled=False)),
    ("reflex:A2", "reflex", "A2", dict(ev_enabled=False)),
    ("reflex:A3", "reflex", "A3", dict(personalization_enabled=False)),
    ("reflex:A4", "reflex", "A4", dict(timing_enabled=False)),
    ("reflex:DEGRADED", "reflex", "DEGRADED", dict(degraded=True)),
]


def main() -> int:
    import logging

    logging.getLogger("reflex").setLevel(logging.WARNING)
    import structlog

    structlog.configure(
        processors=[structlog.processors.add_log_level, structlog.processors.TimeStamper(fmt="iso"), structlog.processors.JSONRenderer()],
        wrapper_class=structlog.make_filtering_bound_logger(logging.WARNING),
    )

    from reflex.api.db import eval_sessionmaker
    from reflex.core.enums import Arm
    from reflex.eval.generator import SIMULATOR_VERSION
    from reflex.eval.pipeline import run_arm
    from reflex.eval.runner import ABLATIONS, prepare_batch
    from reflex.eval.seed import ensure_reference_data

    s = eval_sessionmaker()()
    try:
        ensure_reference_data(s)
        batch_id, batch_tuple = prepare_batch(s, seed=SEED, n=N)
    finally:
        s.close()

    from reflex.eval.runner import EVAL_OPENED_AT

    opened = EVAL_OPENED_AT
    results: dict[str, object] = {}
    for key, arm_name, ablation, cfg_over in ARMS:
        cfg = None
        if cfg_over:
            cfg = next(c for n_, c in ABLATIONS.items() if n_ == ablation)
        sess = eval_sessionmaker()()
        t0 = time.perf_counter()
        try:
            res = run_arm(
                sess,
                batch_id=batch_id,
                batch=batch_tuple[0],
                merchant_id=batch_tuple[2],
                customer_ids=batch_tuple[1],
                arm=Arm(arm_name),
                ablation=(f"{ablation}:repro" if ablation else "repro"),
                config=cfg,
                opened_at=opened,
            )
            res._failed_value = sum(e.amount_paise for e in batch_tuple[0].events)  # type: ignore[attr-defined]
            results[key] = res
            print(f"{key}: rr={res.recovered_paise / res._failed_value:.4f} "
                  f"({time.perf_counter() - t0:.0f}s)", flush=True)
        finally:
            sess.close()

    # ---- G5 tolerance vs committed ------------------------------------------
    committed = json.loads(COMMITTED.read_text(encoding="utf-8"))
    g5: dict[str, dict] = {}
    all_pass = True
    for key, _a, _b, _c in ARMS:
        entry = committed["arms"].get(key)
        if entry is None:
            continue
        committed_rr = entry.get("recovery_rate_per_seed_pct", {}).get(str(SEED))
        if committed_rr is None:
            continue
        res = results[key]
        rerun_rr = res.recovered_paise / res._failed_value * 100  # type: ignore[attr-defined]
        diff_pp = round(rerun_rr - committed_rr, 4)
        ok = abs(diff_pp) / 100 <= TOL
        all_pass &= ok
        g5[key] = {"committed_pct": committed_rr, "rerun_pct": round(rerun_rr, 2),
                   "diff_pp": diff_pp, "within_tol": ok}

    # ---- pairwise reflex vs A2 divergence -----------------------------------
    rf, a2 = results["reflex"], results["reflex:A2"]
    rf_rec = rf.ep_rec_paise  # type: ignore[attr-defined]
    a2_rec = a2.ep_rec_paise  # type: ignore[attr-defined]
    events = batch_tuple[0].events
    only_reflex = [(i, rf_rec[i]) for i in range(len(rf_rec)) if rf_rec[i] > 0 and a2_rec[i] == 0]
    only_a2 = [(i, a2_rec[i]) for i in range(len(a2_rec)) if a2_rec[i] > 0 and rf_rec[i] == 0]
    both = [(i, rf_rec[i]) for i in range(len(rf_rec)) if rf_rec[i] > 0 and a2_rec[i] > 0]

    def _amount(idx_list):  # type: ignore[no-untyped-def]
        return sum(events[i].amount_paise for i, _v in idx_list)

    div = {
        "episodes_total": len(rf_rec),
        "both_recovered": {"count": len(both), "value_paise": _amount(both)},
        "only_full_ev_recovered": {"count": len(only_reflex), "value_paise": _amount(only_reflex)},
        "only_ev_off_recovered": {"count": len(only_a2), "value_paise": _amount(only_a2)},
        "full_contacts": rf.contacts,  # type: ignore[attr-defined]
        "evoff_contacts": a2.contacts,  # type: ignore[attr-defined]
        "full_complaints": rf.complaints,  # type: ignore[attr-defined]
        "evoff_complaints": a2.complaints,  # type: ignore[attr-defined]
        "full_declined_cohort": len(rf.declined_cohort),  # type: ignore[attr-defined]
        "evoff_declined_cohort": len(a2.declined_cohort),  # type: ignore[attr-defined]
        "full_cost_paise": rf.cost_paise,  # type: ignore[attr-defined]
        "evoff_cost_paise": a2.cost_paise,  # type: ignore[attr-defined]
        "only_a2_sample_codes": sorted(
            {events[i].canonical_code for i, _ in only_a2[:200]}
        ),
        "only_reflex_sample_codes": sorted(
            {events[i].canonical_code for i, _ in only_reflex[:200]}
        ),
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    summary = {
        "[SIMULATED]": True,
        "purpose": "G5 reproduction + A2 divergence investigation (NOT headline evidence)",
        "protocol": "eval-preregistered-v1",
        "seed": SEED,
        "n": N,
        "g5_tolerance_abs": TOL,
        "g5_all_arms_within_tolerance": all_pass,
        "g5_per_arm": g5,
        "a2_divergence": div,
        "simulator_version": SIMULATOR_VERSION,
        "wall_clock_opened_utc": opened.isoformat(),
    }
    (OUT_DIR / "results.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")

    lines = [
        "# G5 Reproduction & A2 Divergence — seed 42 [SIMULATED]",
        "",
        f"G5 all arms within ±{TOL}: **{'PASS' if all_pass else 'FAIL'}**",
        "",
        "| Arm | Committed % | Rerun % | Diff pp | In tol |",
        "|---|---|---|---|---|",
    ]
    for k, v in g5.items():
        lines.append(f"| {k} | {v['committed_pct']} | {v['rerun_pct']} | {v['diff_pp']} | {'✅' if v['within_tol'] else '❌'} |")
    lines += ["", "## Reflex(full-EV) vs A2(EV-off) paired episode outcomes", ""]
    for k, v in div.items():
        lines.append(f"- {k}: `{v}`")
    lines += [
        "",
        "_Wall-clock start differs between runs by construction; any drift beyond",
        f"tolerance indicates hidden wall-clock dependence (opened_at={opened.isoformat()})._",
        "",
    ]
    (OUT_DIR / "divergence.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(g5, indent=2))
    print("divergence:", json.dumps(div, indent=2, default=str))
    return 0 if all_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
