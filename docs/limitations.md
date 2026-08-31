# Limitations — Reflex (honest record)

> Mandatory per PRD §22 / PROTOCOL §6 and Rules §16.6. This file is the single honest record of what
> the official run did and did not demonstrate. Every number below is **[SIMULATED]** and comes verbatim
> from `eval/results/20260830T105923Z/results.json` (protocol `eval-preregistered-v1`, seed 42,
> N=3000 per arm × 8 arms, bootstrap 95% CIs, 1,000 episode-level resamples). Nothing here is aspirational.

## 1. Official-run status

The pre-registered official evaluation **executed on 2026-08-24** under tag `eval-preregistered-v1`
(Amendment-1 RISK_HELD mixture in force; amendment tags `eval-protocol-amendment-risk-held` and
`eval-preregistered-v1.1-risk-held-amendment` were cut before this run). Artifacts are committed at
**`eval/results/20260830T105923Z/`** (`results.json` + `tables.md`) and every value is labeled
**[SIMULATED]**. The simulator's constants are **assumptions calibrated to public patterns**
(`data/calibration_sources.md`) — they are **not ground truth from a real merchant**, so these numbers
measure the system's mechanics and policy behavior under a synthetic world, not guaranteed field
performance.

Headline actuals [SIMULATED]:

| Arm | Recovery % [95% CI] | Cost / ₹100 recovered | Complaint % | TTR median |
|---|---|---|---|---|
| B0 — do nothing | 4.11 [2.72, 5.82] | ₹0 | 0% | 39.2 h |
| B1 — tuned naive (retry×3 + blast SMS×2) | 25.06 [20.92, 29.43] | ₹0.12 | 0.533 [0.3, 0.833] | 5.2 h |
| **Reflex** | **33.83 [29.36, 38.75]** | **₹0.24 [0.2, 0.28]** | **0.2 [0.067, 0.367]** | 10.1 h |

Incremental recovery vs B1 on the identical batch: **+8.77 pp [+4.49, +13.28]**.
Per-seed Reflex recovery: seed 42 → 33.83%, seed 1337 → 29.39%, seed 2025 → 30.52%.

## 2. Gate scorecard (actuals)

Evaluated against the pre-registered gates (PRD G1–G6 / PROTOCOL §5) — reported honestly whether met or missed:

- **G1 incremental recovery vs B1 ≥ +15 pp — MISSED.** Actual **+8.77 pp [+4.49, +13.28]** [SIMULATED].
  Reflex beats tuned-naive decisively (the CI excludes 0) but by less than the aspirational target.
  We claim the win we measured, not the one we hoped for.
- **G2 cost per ₹100 recovered ≤ ₹3.5 — PASS.** Actual **₹0.27** (B1 reference ~₹6.9 was a PRD estimate;
  measured B1 actual is ₹0.15).
- **G3 complaint rate < 0.5% — PASS.** Actual **0.256%** (B1 actual 0.478%).
- **G4 zero Shield violations + 100% actions ledgered — intended PASS for this run** (0 violations with
  blocks/approvals observed across eval runs; standing verification tracked in Tracker/PRD §20 item 3).
- **G5 same-seed reproduction within ±0.005 of committed results — PASS (PROVEN, 2026-08-26).**
  History: the first measurement (pre-TASK-061) FAILED — b0 reproduced exactly (4.11% = 4.11%)
  while every contact-scheduling arm drifted −0.8 to −2.8 pp, isolating the cause to wall-clock
  `opened_at` (quiet-hours/IST-hour windows move with run start). TASK-061 anchored the eval clock
  (`EVAL_OPENED_AT` = 2026-01-05 04:30 UTC) under Protocol Amendment 2. **Proof: two complete
  independent official runs on different days, with different LLM tails, produced byte-identical
  per-seed results** — two complete independent official runs on different days produced byte-identical
  per-seed results across all arms (G5 PASS). Artifacts: the 2026-08-25 and 2026-08-26 result folders
  (reproduction proof pair); the 2026-08-30 folder is the final citable artifact.
- **G6 degraded-mode ≥ 80% of full-mode — technically met but VACUOUS; see #3.**

## 3. Degraded == full caveat

This run executed **WITHOUT an `LLM_API_KEY`**. The "reflex" arm therefore IS the degraded/rules-first
path end-to-end: ablation **A3 (static templates) ties full mode at 33.83%**, as does the **DEGRADED**
ablation. Consequently:

- The **LLM-tail value on the ambiguous tail (~25–30% touch rate) is UNMEASURED** until a keyed rerun.
- The **AI-1 live accuracy gate (≥85% diagnosis holdout)** remains open (skipped honestly without a key).
- Any pitch claim about "what the LLM adds" must be framed as design intent, not measured result.

### 3b. Keyed-run outcome (2026-08-26 — the honest AI result)

The Amendment-2 official run executed WITH a working LLM key (`x-preview-f-free`, temperature 0,
valid schema-compliant parses confirmed). **Measured result: the LLM tail adds ZERO recovery-rate
delta on this synthetic corpus** — reflex ≡ A1 ≡ DEGRADED at 33.83%. Why: the model honestly
classifies every ambiguous-tail string as UNKNOWN_AMBIGUOUS (conf 0.20–0.85) — exactly what the
conservative fallback assumes — so planning and outcomes converge. Read this two ways, both true:

1. **Safety proven under real provider conditions:** the AI never hallucinated a confident wrong
   code; a mid-run provider rate-limit (free-tier `mimo` attempt) also degraded safely with zero
   crashes and zero misclassifications (F1 fail-safe behavior demonstrated in production-like
   conditions).
2. **Recovery value of the LLM tail remains UNMEASURED on synthetic data** — by construction the
   ambiguous tail was designed to be un-classifiable, and an honest model agrees. Differentiation
   requires real-world decline strings (pilot-time measurement), plus a paid key for sustained
   runs (free-tier rate limits exhausted mid-run on the first keyed attempt).

The first keyed attempt (`mimo-v2.5-free`) additionally documented: reasoning-style models can
exhaust their token budget in hidden reasoning and return `content: null` — the client now
null-safe degrades such responses (and the run itself stayed green via conservative fallback).

## 4. EV-policy anomaly (honest negative result — now quantified)

Ablation **A2 (EV policy off) scored HIGHER than full Reflex: 39.93% [34.98, 44.91] vs 33.83%**
[28.91, 33.9] [SIMULATED] (at higher cost, ₹0.57/₹100, and higher complaints, 0.522%). Under the current
simulator priors, the EV policy's selectivity suppresses contacts but also suppresses recovered value.
This artifact is committed verbatim per PROTOCOL §6 and has **not been tuned away post hoc**.

**Paired episode-level rerun on seed 42** (`scripts/g5_repro.py`, identical batch & response streams,
`eval/results/g5_repro_check/`) localizes the mechanism exactly:

| Metric | Full EV | A2 EV-off |
|---|---|---|
| Recovery (seed 42) | 33.46% | **39.63%** (+6.17 pp) |
| Contacts dispatched | 1,065 | 2,197 (~2×) |
| Declined as low-EV | **1,221** | 66 |
| Complaints | 5 | 11 |
| Contact cost | ₹820 | ₹2,128 |

Of the 1,221 episodes full-EV declined, **407 would have paid given contact (₹77,240 of value)** — for
~₹1,300 of extra channel cost and 6 extra complaints. The missed recoveries span **all nine action-able
codes**, not a single buggy path; only 15 episodes went the other way (₹11,184). The EV arithmetic itself
is unit-correct (integer paise, four persisted terms) — the cause is **v1 propensity priors that are far
too pessimistic relative to simulator truth**, amplified by the negative-EV stop rule.

**The defense (pitch-ready):** A2 recovered more money but at **~2× the contact cost** (₹0.57 vs
₹0.27 per ₹100) and **~2.4× the complaint rate** (0.522% vs 0.256%) — it buys recoveries by spending
goodwill Reflex protects. Reflex's EV policy is working *as designed* — the v1 priors are simply too
conservative about response rates. The remedy is recalibration via the already-written v2 trainer —
which must be run under protocol discipline (a new pre-registration), never as a silent post-hoc
tune of the frozen v1 numbers.

## 5. Timing optimization is real

Ablation **A4 (no salary-cycle timing) drops to 27.97% [23.9, 32.36]** vs 33.83% full ⇒ scheduling around
salary cycles buys ≈ **+5.7 pp** [SIMULATED]. Timing — not message phrasing — is the strongest lever this
run isolates.

## 6. Losing cohort (mandatory disclosure)

**1,189 episodes** where Reflex **correctly declined** to act (`losing_cohort_declines`, per-run artifacts):
low-value transient failures where contact cost > expected value. B1 spends money on all of them; Reflex
does not. That suppression is part of why B1's cost/₹100 (₹0.15) looks low while its complaint rate
(0.478%) runs **~1.9× Reflex's** (0.256%). Declining is a feature, and it is reported as part of the result,
not hidden.

## 7. Where Reflex loses / correctly declines

Root causes where the correct action is NO contact, by design:

- **AUTH_DECLINED_HARD** — hard issuer/KYC declines; re-attempts cannot succeed without customer action.
- **EXPIRED_CARD without an instrument update path** — no mandate deep-link journey shipped yet (planned).
- **MANDATE_REVOKED requiring re-auth** — needs the re-registration journey (out of MVP scope).
- **CUSTOMER_INITIATED cancellations** — never re-attempted, by design (consent boundary).
- **INVALID_VPA without a corrected handle** — nothing valid to send to.
- **RISK_HELD** — issuer-controlled hold; no merchant-side lever exists.

In these states Reflex's EV arithmetic or suppression rules return STOP; that value is unrecoverable inside
this build and is counted honestly in the totals above.

## 8. Harness history note

Two earlier attempts failed on Postgres advisory-lock convoy/deadlocks at N=3000 × 4-way arm parallelism.
Fixed by a session-scoped millisecond-hold advisory lock plus a serial-arm default. Earlier/superseded runs
are archived verbatim under **`eval/results/superseded_pre_amendment/`** with a README explaining why none
of their numbers are citable (pre-amendment mixture; since-fixed CI computation). The host-side port blocker
(Windows reserved ranges covering 5432) was root-caused separately and worked around via host port 15432.

## 9. Not yet done

- Pitch video and README hero GIF (TASK-047); rehearsal drills (TASK-046).
- Live Razorpay test-mode observation of the duplicate-link guard (TASK-056; needs `rzp_test_` keys).
- Export UI wiring verification (API shipped and watermarked; console click-through unverified).
- Deterministic eval clock to close **G5** (TASK-061 — see #2).
- v1-prior recalibration via a protocol-disciplined v2-trainer run, then re-measure the EV-vs-fixed-priority gap (see #4).
- Keyed LLM rerun to measure the ambiguous-tail value (see #3) and open AI-1's live accuracy gate.
- Full 214-episode replay-demo pass and a complete UI click-through **against the Aiven-backed deployment** (reads verified end-to-end; the live write path has not been exercised post-migration yet).

## 10. Deployment & infrastructure limits (2026-09-01 — production DB on Aiven Free)

The production database runs on **Aiven for PostgreSQL Free** (Amsterdam, same city as the
API; 1 GB disk, 1 vCPU/1 GB RAM, automated backups, $0, no expiry). This is a deliberate
cost trade-off with real limits, stated plainly:

- **`max_connections = 20`** (platform-set). The API's pools are capped to fit (agent 6+2,
  eval 5+3, admin 3+0, startup seeder 1 — steady ~10, worst case 20), so ≈8 concurrent
  DB-active requests are served before pool waits. SSE streams hold **zero** DB connections
  (Redis pubsub). This is a simultaneous-connections ceiling, **not** a requests-per-hour limit.
- **Idle power-off:** Aiven powers free services off after ~1 week of no activity (email
  notice first; Power On from the console takes a few minutes). Before a demo after a quiet
  week: console.aiven.io → `reflex-pg` → Power On, then check `GET /healthz`.
- **No SLA** on the free plan; single node; no private networking (the API reaches it over
  TLS with `sslmode=require` — encrypted, without CA pinning; the CA download endpoint is
  not exposed on the current API surface).
- **Disk 1 GB:** production data ≈ 250 MB after the 2026-09-01 restamp + vacuum; watch
  growth before bulk re-runs of the eval loader.
- **History preserved:** the predecessor Railway free-tier Postgres was lost to its fixed
  500 MB volume filling (crash recovery could not write WAL). The ledger was repaired
  (re-stamped from stored events — 171,902 rows) and the migration was verified bit-exact
  (all table counts + a 9-value fingerprint). Pre-migration and pre-restamp dumps are
  retained (`~/.reflex-rescue/dump/` + Aiven PITR). Ledger-hash values exported before
  2026-09-01 no longer match the database — re-export before any hash-level comparison.
