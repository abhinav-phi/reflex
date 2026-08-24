# Evaluation Protocol — Reflex

**Status:** PRE-REGISTERED · Git tag `eval-preregistered-v1` points at this file.
**Commitment:** this protocol was committed, tagged, and pushed **before** the first evaluation
result was produced. Any change to this file after results exist invalidates provenance and must
be recorded as a protocol amendment (new tag, old results marked superseded).

Simulation integrity rules (`8. Rules.md` §16, ADR-007): no target metric may be hard-coded into
agent/UI code; the simulator is calibrated to cited public patterns (`data/calibration_sources.md`)
and actuals are reported whatever they are; one honestly-reported cohort where Reflex loses or
correctly declines is mandatory in `docs/limitations.md`.

---

## 0. Protocol amendments

### Amendment 1 — RISK_HELD mixture rebalance (pre-official-run)

**Status:** PRE-REGISTERED · Git tag `eval-preregistered-v1.1-risk-held-amendment` (alias
`eval-protocol-amendment-risk-held`) points at commit `ff679ac`, recorded **before** any official
multi-seed evaluation run produced results. No prior official-run artifacts exist to supersede.

**Change:** synthetic failure mixture in `apps/eval/generator.py` (`CODE_MIXTURE`,
`sim-v1`) gains `RISK_HELD` at **2%**, rebalancing `INSUFFICIENT_FUNDS` from **34% → 32%**
(total stays 100%). All other shares, amounts, behavioral constants, and metric definitions are
unchanged; `SIMULATOR_VERSION` remains `sim-v1`.

**Rationale:** the frozen `sim-v1` mixture generated only 10 of the 11 canonical decline codes;
`RISK_HELD` (issuer risk review) had no synthetic coverage, so agent behavior on that code was
untestable and the losing-cohort analysis could not observe it. Issuer risk-holds are a real,
non-trivial Indian decline category (`data/calibration_sources.md` §4: 0.10 same-rail retry
resolution `[ASSUMPTION]`). Rebalancing INSUFFICIENT_FUNDS (the dominant share) by −2 pts keeps
the ordering intact and the total exact.

**Effect on gates:** none by construction — G1–G6 are computed from actuals under the identical
definitions in §2/§5. The batch-identity rule (§1) now applies to the amended mixture: every arm
on a given seed sees the same amended batch.

---

## 1. Fixed design

| Item | Value |
|---|---|
| Episodes per batch | N = 3,000 |
| Eval seeds | `{42, 1337, 2025}` |
| Arms | `b0` (do nothing), `b1` (tuned naive), `reflex` |
| Ablations | A1 rules-only diagnosis · A2 EV-off fixed-priority policy · A3 static templates · A4 no timing optimization (all on `reflex` arm) |
| Batch identity | Identical batch (customers, failure events, hidden truth) across arms & ablations for a given seed |
| Episode horizon | 72 h simulated time from episode open |
| Dev/tuning seeds | `{7, 99}` — used ONLY for B1 tuning; never reported as results |
| Bootstrap | 1,000 resamples, percentile 95% CI, resampling unit = episode |
| Simulator version | `sim-v1` (constants frozen in `data/calibration_sources.md`; bump ⇒ new protocol tag) |
| RNG scheme | numpy `PCG64` via `SeedSequence(seed)`; customer-response streams spawned per `(customer_index, episode_index, action_seq)` so results are order-independent |

## 2. Metric definitions (exact)

All money in paise. Per arm `a` on batch `B`:

1. `recovery_rate` = Σ `amount_paise` over episodes with outcome `recovered` ÷ Σ `amount_paise` over all episodes in `B`.
   *Value-weighted* (primary KPI basis). Also reported unweighted as `episode_recovery_rate`.
2. `incremental_paise` = recovered_paise(`reflex`) − recovered_paise(`b1`) on the same batch.
3. `incremental_recovery_rate` = recovery_rate(`reflex`) − recovery_rate(`b1`) (percentage points).
4. `cost_per_100p` = 100 × Σ `actions.cost_paise` (dispatched actions) ÷ recovered_paise. Undefined (∞) if recovered_paise = 0; reported as `null` then.
5. `complaint_rate` = episodes with ≥1 COMPLAINT-classified reply ÷ all episodes.
6. `ttr_median` = median over recovered episodes of (`outcome.observed_at` − opening event `occurred_at`), seconds sim-time.
7. `contacts_per_recovery` = dispatched contact actions ÷ recoveries.
8. `p95_latency_ms` = p95 wall-clock of the decision step (diagnose→plan→guard) measured in-harness.
9. `regret` = oracle_recovered_paise − arm recovered_paise, where oracle = per-episode best achievable outcome given hidden truth (upper bound, computed by Proof only).
10. `degraded_delta` (informational) = recovery_rate(full) − recovery_rate(A-degraded variant) when run.
11. `losing_cohort_rate` = share of cohort episodes (amount < 15,000 paise, transient causes) where Reflex correctly declines to act; reported with b1 spend on the same cohort.

Every headline number is published as `value [ci_low, ci_high]` with arm, seed, and `[SIMULATED]` label.

## 3. Arm definitions (frozen)

- **B0 do-nothing:** no agent actions ever. Organic recovery only (simulator models customers who self-correct, e.g., pay manually after salary credit).
- **B1 tuned naive:** immediate same-rail retry ×3 (t+0h, t+6h, t+24h) + generic English SMS blast ×2 (t+2h, t+30h). Ignores root cause, channel preference, quiet hours are respected ONLY because the simulator refuses off-window responses (compliance floor, not B1 intelligence). Tuning: grid search over retry offsets {0,1,6,12}×{6,12,24}×{24,48} h and SMS offsets {1,2,6}×{24,30,48} h maximizing value recovery on dev seeds {7,99}; chosen parameters and search table committed in `eval/results/b1_tuning.json`. Never a strawman (`8. Rules.md` §4.8).
- **Reflex:** full Pulse→Brain→Shield→Hands pipeline, policy v1 priors (v2 learning optional, reported separately), guardrails per PRD §15.

## 4. Procedure

1. `./eval/reproduce.sh` from a clean clone (target < 15 min): builds env, migrates DB, seeds reference data, runs steps 2–5, writes `eval/results/<run_id>/`.
2. For each seed s ∈ {42,1337,2025}: generate batch(s) once → byte-identical regeneration check (hash of normalized batch JSON must equal across two generations).
3. Run arms [b0, b1, reflex] and ablations [A1..A4 on reflex] over the virtual timeline to terminal states.
4. Compute metrics §2 per arm; bootstrap CIs across episodes.
5. Write machine results `results.json`, human tables `tables.md`, DB rows into `eval.eval_runs` / `eval.eval_metrics` with `preregistered_tag=eval-preregistered-v1`.
6. Runner REFUSES official runs if the git tag is absent from history (app-level check, TechSpec §10).

## 5. Acceptance gates (from PRD G1–G6, evaluated on actuals)

Reported honestly whether met or missed; gates are goals, not manipulable knobs:

- G1 incremental value-weighted recovery vs B1 ≥ +15 pts (CI reported)
- G2 cost per ₹100 recovered ≤ ₹3.5 (B1 reference ~₹6.9 was a PRD estimate; report measured B1 actual alongside)
- G3 complaint rate < 0.5% (B1 reference ~1.9%)
- G4 zero Shield violations in any run; 100% actions ledgered
- G5 one-command reproduction within tolerance: recovery_rate per arm within ±0.005 absolute of committed results on same seed
- G6 degraded-mode recovery ≥ 80% of full-mode recovery (measured by degraded ablation run)

## 6. Honesty requirements

- All outputs labeled `[SIMULATED]` (files, tables, UI, README).
- Hidden simulator truth lives only in `replay.sim_*` (DB role `reflex_eval`); agent code paths read runtime schema only — enforced by role grants + import-lint.
- If Reflex loses to B1 on any seed/metric, that result is committed verbatim and discussed in `docs/limitations.md`.
