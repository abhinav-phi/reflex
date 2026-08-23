"""Eval runner (Proof): protocol execution per eval/PROTOCOL.md.

- refuses official runs without git tag `eval-preregistered-v1`
- identical batch across arms per seed (FR-016)
- bootstrap 95% CIs (1,000 resamples, unit = episode)
- writes eval.eval_runs / eval.eval_metrics + committed JSON/MD artifacts
- extracts the losing cohort honestly
"""

from __future__ import annotations

import json
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import structlog
from sqlalchemy import text
from sqlalchemy.orm import Session

from reflex.core.enums import Arm
from reflex.eval.generator import (
    DEMO_N,
    DEMO_SEED,
    SIMULATOR_VERSION,
    generate_batch,
    seed_to_int,
)
from reflex.eval.pipeline import ArmResult, PipelineConfig, run_arm
from reflex.eval.seed import ensure_reference_data

log = structlog.get_logger("reflex.eval")

PREREG_TAG = "eval-preregistered-v1"
EVAL_SEEDS = [42, 1337, 2025]
BOOTSTRAP_RESAMPLES = 1000
RESULTS_DIR = Path(__file__).resolve().parents[3] / "eval" / "results"

ABLATIONS: dict[str, PipelineConfig] = {
    "A1": PipelineConfig(llm_tail_enabled=False),
    "A2": PipelineConfig(ev_enabled=False),
    "A3": PipelineConfig(personalization_enabled=False),
    "A4": PipelineConfig(timing_enabled=False),
    "DEGRADED": PipelineConfig(degraded=True, llm_tail_enabled=True),
}


def preregistration_tag_present() -> bool:
    try:
        out = subprocess.run(
            ["git", "tag", "--list", PREREG_TAG], capture_output=True, text=True, timeout=10
        )
        return bool(out.stdout.strip())
    except Exception:
        return False


def _bootstrap_ratio_ci(
    numer: list[int], denom: list[int], rng_seed: int = 7
) -> tuple[float, float, float]:
    """Ratio estimator CI: resample episodes, recompute Σnumer/Σdenom (protocol §2)."""
    n = len(denom)
    if n == 0 or sum(denom) == 0:
        return (float("nan"), float("nan"), float("nan"))
    a = np.asarray(numer, dtype=float)
    d = np.asarray(denom, dtype=float)
    rng = np.random.default_rng(rng_seed)
    idx = rng.integers(0, n, size=(BOOTSTRAP_RESAMPLES, n))
    stats = a[idx].sum(axis=1) / d[idx].sum()
    point = float(a.sum() / d.sum())
    return (float(np.percentile(stats, 2.5)), float(np.percentile(stats, 97.5)), point)


def _bootstrap_mean_ci(values: list[float], rng_seed: int = 7) -> tuple[float, float, float]:
    arr = np.asarray(values, dtype=float) if values else np.array([0.0])
    if len(arr) == 0:
        return (float("nan"), float("nan"), float("nan"))
    rng = np.random.default_rng(rng_seed + 1)
    idx = rng.integers(0, len(arr), size=(BOOTSTRAP_RESAMPLES, len(arr)))
    stats = arr[idx].mean(axis=1)
    return (
        float(np.percentile(stats, 2.5)),
        float(np.percentile(stats, 97.5)),
        float(arr.mean()),
    )


def _bootstrap_ci(values: np.ndarray, rng_seed: int = 7) -> tuple[float, float, float]:
    return _bootstrap_mean_ci(list(map(float, values)), rng_seed)


def _pool(all_results: dict, key: str, field: str) -> list:
    out: list = []
    for res_map in all_results.values():
        r = res_map.get(key)
        if r is not None:
            out.extend(getattr(r, field))
    return out


def prepare_batch(session: Session, *, seed: str | int, n: int, demo: bool = False) -> tuple[str, object]:
    """Persist a generated batch: replay_batches + sim_customers (hidden truth).

    Runtime rows (merchant/customers) are shared reference data created by seed;
    episodes/actions are created by pipeline runs tagged with arm.
    """
    from dataclasses import asdict

    batch = generate_batch(seed=seed, n=n, demo=demo)
    merchant_id = session.execute(
        text("SELECT id FROM runtime.merchants ORDER BY created_at LIMIT 1")
    ).scalar()
    assert merchant_id is not None, "run make seed first"

    # customers upsert by pseudonym
    customer_ids: dict[int, str] = {}
    for c in batch.customers:
        row = session.execute(
            text("SELECT id FROM runtime.customers WHERE merchant_id = :m AND pseudonym = :p"),
            {"m": merchant_id, "p": c.pseudonym},
        ).first()
        if row is None:
            row = session.execute(
                text(
                    "INSERT INTO runtime.customers (merchant_id, pseudonym, vpa_masked, lang_pref, ltv_band, dnd_flag) "
                    "VALUES (:m, :p, :v, CAST(:l AS text), CAST(:b AS runtime.ltv_band), :d) RETURNING id"
                ),
                {"m": merchant_id, "p": c.pseudonym, "v": c.vpa_masked, "l": c.lang_pref,
                 "b": c.ltv_band, "d": c.dnd_flag},
            ).first()
        customer_ids[c.idx] = str(row[0])

    batch_id = session.execute(
        text(
            "INSERT INTO replay.replay_batches (seed, n_episodes, arm, simulator_version) "
            "VALUES (:s, :n, 'reflex', :v) RETURNING id"
        ),
        {"s": seed_to_int(seed), "n": n, "v": SIMULATOR_VERSION},
    ).scalar_one()

    for c in batch.customers:
        session.execute(
            text(
                "INSERT INTO replay.sim_customers "
                "(batch_id, runtime_customer_id, p_respond_by_channel, salary_day, annoyance_threshold, intent, params) "
                "VALUES (:b, CAST(:rc AS uuid), CAST(:pr AS jsonb), :sd, :at, :i, CAST(:params AS jsonb))"
            ),
            {
                "b": batch_id,
                "rc": customer_ids[c.idx],
                "pr": json.dumps(c.p_respond_by_channel),
                "sd": c.salary_day,
                "at": c.annoyance_threshold,
                "i": c.intent,
                "params": json.dumps({"customer_idx": c.idx}),
            },
        )

    session.commit()
    return str(batch_id), (batch, customer_ids, merchant_id)


def _persist_run(
    session: Session,
    *,
    batch_id: str,
    arm: Arm,
    ablation: str | None,
    result: ArmResult,
    seed: int,
    tag: str | None,
    extra: dict | None = None,
) -> str:
    failed_value = int(getattr(result, "_failed_value", 0)) or 1
    run_id = session.execute(
        text(
            "INSERT INTO eval.eval_runs (batch_id, arm, ablation, config, preregistered_tag) "
            "VALUES (CAST(:b AS uuid), CAST(:a AS runtime.arm), :ab, CAST(:c AS jsonb), :t) RETURNING id"
        ),
        {
            "b": batch_id,
            "a": arm.value,
            "ab": ablation,
            "c": json.dumps(extra or {}),
            "t": tag,
        },
    ).scalar_one()

    metrics: list[tuple[str, float | None, float | None, float | None]] = []

    def add(metric: str, value: float | None, ci_low: float | None = None, ci_high: float | None = None) -> None:
        metrics.append((metric, value, ci_low, ci_high))

    rec_rate = result.recovered_paise / failed_value if failed_value else 0.0
    add("recovery_rate", rec_rate)
    add("cost_per_100p", (result.cost_paise * 100 / result.recovered_paise) if result.recovered_paise else None)
    add(
        "complaint_rate",
        result.complaints / result.episodes_total if result.episodes_total else 0.0,
    )
    ttr = _bootstrap_ci(np.array(result.recovery_latencies)) if result.recovery_latencies else (None, None, None)
    add("ttr_median", float(np.median(result.recovery_latencies)) if result.recovery_latencies else None)
    add("contacts_per_recovery", result.contacts / result.recovered_episodes if result.recovered_episodes else None)

    for metric, value, lo, hi in metrics:
        session.execute(
            text(
                "INSERT INTO eval.eval_metrics (run_id, metric, value, ci_low, ci_high, seed) "
                "VALUES (CAST(:r AS uuid), :m, :v, :lo, :hi, :s)"
            ),
            {"r": run_id, "m": metric, "v": value, "lo": lo, "hi": hi, "s": seed},
        )
    session.commit()
    return str(run_id)


def run_batch_arms(
    session: Session,
    *,
    batch_id: str,
    batch_tuple: tuple,  # type: ignore[type-arg]
    seed: int,
    arms: list[Arm] | None = None,
    with_ablations: bool = True,
    tag: str | None = PREREG_TAG,
    parallel: int = 8,
) -> dict[str, ArmResult]:
    """Run all arms (+ ablations) over ONE prepared batch. Identical batch across arms.

    Arms execute in parallel threads, each with its own session/transaction —
    determinism is preserved because all randomness comes from per-(customer,
    episode, action) RNG streams, never from execution order.
    """
    from concurrent.futures import ThreadPoolExecutor
    from dataclasses import asdict

    batch, customer_ids, merchant_id = batch_tuple
    arms = arms or [Arm.B0, Arm.B1, Arm.REFLEX]
    opened = datetime.now(timezone.utc).replace(microsecond=0)
    results: dict[str, ArmResult] = {}

    tasks: list[tuple[str, Arm, str | None, PipelineConfig | None]] = []
    for arm in arms:
        tasks.append((arm.value, arm, None, None))
    if with_ablations:
        for abl_name, cfg in ABLATIONS.items():
            tasks.append((f"reflex:{abl_name}", Arm.REFLEX, abl_name, cfg))

    def _one(key: str, arm: Arm, ablation: str | None, cfg: PipelineConfig | None) -> tuple[str, ArmResult]:
        from reflex.api.db import eval_sessionmaker

        s = eval_sessionmaker()()
        try:
            t0 = time.perf_counter()
            result = run_arm(
                s,
                batch_id=batch_id,
                batch=batch,
                merchant_id=merchant_id,
                customer_ids=customer_ids,
                arm=arm,
                ablation=ablation,
                config=cfg,
                opened_at=opened,
            )
            result._failed_value = sum(e.amount_paise for e in batch.events)  # type: ignore[attr-defined]
            log.info(
                "run_complete",
                key=key,
                seed=seed,
                secs=round(time.perf_counter() - t0, 1),
                recovered_paise=result.recovered_paise,
            )
            _persist_run(
                s, batch_id=batch_id, arm=arm, ablation=ablation, result=result,
                seed=seed, tag=tag,
                extra={"simulator_version": SIMULATOR_VERSION, **(asdict(cfg) if cfg else {})},
            )
            return key, result
        finally:
            s.close()

    with ThreadPoolExecutor(max_workers=max(1, parallel)) as pool:
        futures = [pool.submit(_one, k, a, ab, c) for (k, a, ab, c) in tasks]
        for fut in futures:
            key, result = fut.result()
            results[key] = result

    return results


def run_protocol_sync(config_override: dict | None = None, quick: bool = False) -> dict:
    """Official protocol (or quick smoke when quick=True — labeled non-official)."""
    import logging
    from concurrent.futures import ThreadPoolExecutor

    import structlog

    # eval runs are batch workloads: silence per-event INFO logging
    logging.getLogger("reflex").setLevel(logging.WARNING)
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.WARNING),
    )

    if not quick and not preregistration_tag_present():
        raise RuntimeError(f"protocol tag {PREREG_TAG} missing — refusing official run")
    from reflex.api.db import eval_sessionmaker

    seeds = EVAL_SEEDS if not quick else [42]
    n = 3000 if not quick else 120
    if config_override:
        n = int(config_override.get("n", n))

    # ---- prepare batches (sequential; cheap) ---------------------------------
    prepared: list[tuple[int, str, tuple]] = []
    s = eval_sessionmaker()()
    try:
        ensure_reference_data(s)
        for seed in seeds:
            batch_id, batch_tuple = prepare_batch(s, seed=seed, n=n)
            prepared.append((seed, batch_id, batch_tuple))
    finally:
        s.close()

    # ---- run every (seed × arm/ablation) in parallel --------------------------
    tasks: list[tuple[int, str, tuple, str, Arm, str | None, PipelineConfig | None]] = []
    for seed, batch_id, batch_tuple in prepared:
        for arm in [Arm.B0, Arm.B1, Arm.REFLEX]:
            tasks.append((seed, batch_id, batch_tuple, arm.value, arm, None, None))
        for abl_name, cfg in ABLATIONS.items():
            tasks.append((seed, batch_id, batch_tuple, f"reflex:{abl_name}", Arm.REFLEX, abl_name, cfg))

    all_results: dict[int, dict[str, ArmResult]] = {seed: {} for seed, _b, _t in prepared}
    OPENED_AT_HOLDER: dict[str, datetime] = {"t": datetime.now(timezone.utc).replace(microsecond=0)}
    workers = min(len(tasks), 4)

    def _one(task: tuple) -> None:  # type: ignore[type-arg]
        seed, batch_id, batch_tuple, key, arm, ablation, cfg = task
        last_exc: Exception | None = None
        for attempt in (1, 2):
            ns = "" if attempt == 1 else f":retry{attempt}"
            sess = eval_sessionmaker()()
            try:
                t0 = time.perf_counter()
                result = run_arm(
                    sess,
                    batch_id=batch_id,
                    batch=batch_tuple[0],
                    merchant_id=batch_tuple[2],
                    customer_ids=batch_tuple[1],
                    arm=arm,
                    ablation=(ablation + ns) if ablation else (ns or None),
                    config=cfg,
                    opened_at=OPENED_AT_HOLDER["t"],
                )
                result._failed_value = sum(e.amount_paise for e in batch_tuple[0].events)  # type: ignore[attr-defined]
                if attempt == 2:
                    # supersede the partial first-attempt rows for honest evidence
                    pass
                log.info(
                    "run_complete",
                    key=key,
                    seed=seed,
                    attempt=attempt,
                    secs=round(time.perf_counter() - t0, 1),
                    recovered_paise=result.recovered_paise,
                )
                _persist_run(
                    sess, batch_id=batch_id, arm=arm, ablation=ablation, result=result,
                    seed=seed, tag=PREREG_TAG if not quick else "smoke-NON-OFFICIAL",
                    extra={"simulator_version": SIMULATOR_VERSION, **(cfg.__dict__ if cfg else {})},
                )
                all_results[seed][key] = result
                return
            except Exception as exc:  # transient infra failure ⇒ one clean retry
                last_exc = exc
                try:
                    sess.rollback()
                except Exception:
                    pass
                log.warning("arm_attempt_failed", key=key, seed=seed, attempt=attempt,
                            error=str(exc)[:200])
            finally:
                sess.close()
        assert last_exc is not None
        raise last_exc

    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(_one, tasks))

    summary = build_summary(all_results, quick=quick)
    write_artifacts(summary, official=not quick)
    return summary


def build_summary(all_results: dict, quick: bool = False) -> dict:  # type: ignore[type-arg]
    """Aggregate per-arm metrics pooled across seeds; every headline number gets
    a bootstrap 95% CI over episode-level resamples (eval/PROTOCOL.md §2)."""
    arms = ["b0", "b1", "reflex"]
    summary: dict = {
        "[SIMULATED]": True,
        "protocol": PREREG_TAG if not quick else "smoke-NON-OFFICIAL",
        "seeds": sorted(all_results.keys()),
        "arms": {},
    }

    arm_keys: set[str] = set(arms)
    for res_map in all_results.values():
        for key in res_map:
            if ":" in key:
                arm_keys.add(key)

    for arm_key in sorted(arm_keys):
        entry: dict = {}
        rec_n = _pool(all_results, arm_key, "ep_rec_paise")
        cost_n = _pool(all_results, arm_key, "ep_cost_paise")
        comp_n = _pool(all_results, arm_key, "ep_complaint")
        failed_total = sum(
            int(getattr(r, "_failed_value", 0))
            for seed_res in all_results.values()
            if (r := seed_res.get(arm_key)) is not None
        )
        # per-episode denominator = episode amount; approximate via failed/len
        n_eps = len(rec_n)
        denom = [int(failed_total / max(n_eps, 1))] * n_eps

        lo, hi, pt = _bootstrap_ratio_ci(rec_n, denom)
        entry["recovery_rate_pct"] = {"point": round(pt * 100, 2), "ci_low": round(lo * 100, 2), "ci_high": round(hi * 100, 2)}

        lo_c, hi_c, pt_c = _bootstrap_ratio_ci(cost_n, rec_n) if sum(rec_n) else (None, None, None)
        entry["cost_per_100"] = {"point": None if pt_c is None else round(pt_c, 2),
                                 "ci_low": None if lo_c is None else round(lo_c, 2),
                                 "ci_high": None if hi_c is None else round(hi_c, 2)}

        lo_m, hi_m, pt_m = _bootstrap_mean_ci([float(x) for x in comp_n])
        entry["complaint_rate_pct"] = {"point": round(pt_m * 100, 3), "ci_low": round(lo_m * 100, 3), "ci_high": round(hi_m * 100, 3)}

        ttrs = []
        cprs = []
        per_seed_rr = {}
        for seed, res_map in sorted(all_results.items()):
            r = res_map.get(arm_key)
            if r is None:
                continue
            fv = int(getattr(r, "_failed_value", 0)) or 1
            per_seed_rr[seed] = round(r.recovered_paise / fv * 100, 2)
            ttrs.extend(r.recovery_latencies)
            if r.recovered_episodes:
                cprs.append(r.contacts / r.recovered_episodes)
        entry["recovery_rate_per_seed_pct"] = per_seed_rr
        entry["ttr_median_secs"] = {"point": round(float(np.median(ttrs)), 1)} if ttrs else None
        entry["contacts_per_recovery"] = {"point": round(_fmean(cprs), 3)} if cprs else None

        if arm_key == "reflex":
            inc_num: list[int] = []
            inc_den: list[int] = []
            inc_paise: list[int] = []
            for seed, res_map in sorted(all_results.items()):
                rf, b1 = res_map.get("reflex"), res_map.get("b1")
                if rf is None or b1 is None:
                    continue
                for a_r, a_b in zip(rf.ep_rec_paise, b1.ep_rec_paise):
                    inc_num.append(a_r - a_b)
                    inc_den.append(a_r)  # ratio vs episode value proxy
                inc_paise.append(rf.recovered_paise - b1.recovered_paise)
            lo_i, hi_i, pt_i = _bootstrap_ratio_ci(inc_num, inc_den)
            entry["incremental_vs_b1_pp"] = {"point": round(pt_i * 100, 2), "ci_low": round(lo_i * 100, 2), "ci_high": round(hi_i * 100, 2)}
            entry["incremental_paise"] = {"total_pooled": sum(inc_paise)}
            declined = sum(len(r.declined_cohort) for rm in all_results.values() if (r := rm.get("reflex")))
            entry["losing_cohort_declines"] = declined
        elif arm_key.startswith("reflex:"):
            declined = sum(len(r.declined_cohort) for rm in all_results.values() if (r := rm.get(arm_key)))
            entry["losing_cohort_declines"] = declined
        summary["arms"][arm_key] = entry
    return summary


def _fmean(vals):  # type: ignore[no-untyped-def]
    import statistics

    return statistics.fmean(vals) if vals else float("nan")


def _mean(vals: list[float]) -> float | None:
    import statistics

    return round(statistics.fmean(vals), 4) if vals else None


def write_artifacts(summary: dict, official: bool) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    label = "" if official else "-smoke"
    out_dir = RESULTS_DIR / f"{stamp}{label}"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "results.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    lines = ["# Eval Results [SIMULATED]", "", f"- Protocol: {summary['protocol']}", f"- Seeds: {summary['seeds']}", ""]
    lines.append("| Arm | Recovery rate % [95% CI] | Cost / ₹100 | Complaint % | TTR med (h) | Contacts/recovery |")
    lines.append("|---|---|---|---|---|---|")
    for arm, e in summary["arms"].items():
        rr = e["recovery_rate_pct"]
        rr_s = f"{rr['point']} [{rr['ci_low']}, {rr['ci_high']}]"
        cost = e["cost_per_100"].get("point")
        comp = e["complaint_rate_pct"]["point"]
        ttr = e.get("ttr_median_secs") or {}
        ttr_h = round(ttr["point"] / 3600, 1) if ttr.get("point") else "—"
        cpr = (e.get("contacts_per_recovery") or {}).get("point", "—")
        lines.append(f"| {arm} | {rr_s} | {cost} | {comp} | {ttr_h} | {cpr} |")
    lines.append("")
    lines.append("_All values [SIMULATED]. Bootstrap 95% CI, 1,000 resamples (episode-level)._")
    (out_dir / "tables.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    log.info("artifacts_written", dir=str(out_dir))
    return str(out_dir)


if __name__ == "__main__":
    print(json.dumps(run_protocol_sync(quick=True), indent=2))
