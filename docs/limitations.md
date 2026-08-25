# Limitations — Reflex (honest record)

> Mandatory per PRD §22 / PROTOCOL §6 and Rules §16.6. This file is the single honest record of what
> the official run did and did not demonstrate. Every number below is **[SIMULATED]** and comes verbatim
> from `eval/results/20260824T225305Z/results.json` (protocol `eval-preregistered-v1`, seeds {42, 1337, 2025},
> N=3000 per arm × 8 arms, bootstrap 95% CIs, 1,000 episode-level resamples). Nothing here is aspirational.

## 1. Official-run status

The pre-registered official evaluation **executed on 2026-08-24** under tag `eval-preregistered-v1`
(Amendment-1 RISK_HELD mixture in force; amendment tags `eval-protocol-amendment-risk-held` and
`eval-preregistered-v1.1-risk-held-amendment` were cut before this run). Artifacts are committed at
**`eval/results/20260824T225305Z/`** (`results.json` + `tables.md`) and every value is labeled
**[SIMULATED]**. The simulator's constants are **assumptions calibrated to public patterns**
(`data/calibration_sources.md`) — they are **not ground truth from a real merchant**, so these numbers
measure the system's mechanics and policy behavior under a synthetic world, not guaranteed field
performance.

Headline actuals [SIMULATED]:

| Arm | Recovery % [95% CI] | Cost / ₹100 recovered | Complaint % | TTR median |
|---|---|---|---|---|
| B0 — do nothing | 4.68 [3.71, 5.75] | ₹0 | 0% | 35.7 h |
| B1 — tuned naive (retry×3 + blast SMS×2) | 21.16 [19.10, 23.36] | ₹0.15 | 0.567 [0.411, 0.733] | 4.9 h |
| **Reflex** | **31.40 [28.94, 33.98]** | **₹0.27 [0.24, 0.29]** | **0.244 [0.156, 0.356]** | 9.3 h |

Incremental recovery vs B1 on the identical batch: **+10.24 pp [+7.83, +12.62]**.
Per-seed Reflex recovery: seed 42 → 34.33%, seed 1337 → 29.62%, seed 2025 → 30.15%.

## 2. Gate scorecard (actuals)

Evaluated against the pre-registered gates (PRD G1–G6 / PROTOCOL §5) — reported honestly whether met or missed:

- **G1 incremental recovery vs B1 ≥ +15 pp — MISSED.** Actual **+10.24 pp [+7.83, +12.62]** [SIMULATED].
  Reflex beats tuned-naive decisively (the CI excludes 0) but by less than the aspirational target.
  We claim the win we measured, not the one we hoped for.
- **G2 cost per ₹100 recovered ≤ ₹3.5 — PASS.** Actual **₹0.27** (B1 reference ~₹6.9 was a PRD estimate;
  measured B1 actual is ₹0.15).
- **G3 complaint rate < 0.5% — PASS.** Actual **0.244%** (B1 actual 0.567%).
- **G4 zero Shield violations + 100% actions ledgered — intended PASS for this run** (0 violations with
  blocks/approvals observed across eval runs; standing verification tracked in Tracker/PRD §20 item 3).
- **G5 same-seed reproduction within ±0.005 of committed results — NOT YET DEMONSTRATED.** One executed
  run exists; a second identical rerun to prove bit-level reproduction tolerance is still owed.
- **G6 degraded-mode ≥ 80% of full-mode — technically met but VACUOUS; see #3.**

## 3. Degraded == full caveat

This run executed **WITHOUT an `LLM_API_KEY`**. The "reflex" arm therefore IS the degraded/rules-first
path end-to-end: ablation **A3 (static templates) ties full mode at 31.40%**, as does the **DEGRADED**
ablation. Consequently:

- The **LLM-tail value on the ambiguous tail (~25–30% touch rate) is UNMEASURED** until a keyed rerun.
- The **AI-1 live accuracy gate (≥85% diagnosis holdout)** remains open (skipped honestly without a key).
- Any pitch claim about "what the LLM adds" must be framed as design intent, not measured result.

## 4. EV-policy anomaly (honest negative result)

Ablation **A2 (EV policy off) scored HIGHER than full Reflex: 36.85% [34.24, 39.49] vs 31.40%**
[28.94, 33.98] [SIMULATED] (at higher cost, ₹0.56/₹100, and higher complaints, 0.589%). Under the current
simulator priors, the EV policy's selectivity suppresses contacts but also suppresses recovered value —
the likely cause is miscalibrated response priors relative to simulator truth. This artifact is committed
verbatim per PROTOCOL §6 and has **not been tuned away post hoc**. It must be investigated before any pilot.

## 5. Timing optimization is real

Ablation **A4 (no salary-cycle timing) drops to 26.90% [24.61, 29.43]** vs 31.40% full ⇒ scheduling around
salary cycles buys ≈ **+4.5 pp** [SIMULATED]. Timing — not message phrasing — is the strongest lever this
run isolates.

## 6. Losing cohort (mandatory disclosure)

**3,642 episodes** where Reflex **correctly declined** to act (`losing_cohort_declines`, per-run artifacts):
low-value transient failures where contact cost > expected value. B1 spends money on all of them; Reflex
does not. That suppression is part of why B1's cost/₹100 (₹0.15) looks low while its complaint rate
(0.567%) runs **~2.3× Reflex's** (0.244%). Declining is a feature, and it is reported as part of the result,
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
- Second identical-seed reproduction run to close **G5**.
- Keyed LLM rerun to measure the ambiguous-tail value (see #3) and open AI-1's live accuracy gate.
