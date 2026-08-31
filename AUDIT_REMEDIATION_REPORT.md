# Final Technical Audit Remediation Report — Project Reflex

**Date:** 2026-08-25 · **Scope:** end-to-end codebase & documentation synchronization and audit remediation (P0→P3) · **Repo:** `abhinav-phi/reflex` (`master` = `main`)

---

## 1. Executive Summary

All five mission phases were executed. The headline outcome: **the official pre-registered multi-seed evaluation has been executed and committed** — the single largest open item on the project's honesty ledger. Along the way the remediation found and fixed **four evaluation-harness correctness bugs** (invalidating all previously "committed" confidence intervals), **two production-grade runtime bugs** (a silently-dead Redis consumer and an ADR-004 role violation that killed dispatch), **one latent API crash** (`NameError` in the kill-switch path), plus the mandated AI-safety expansions (Hinglish number-word blocklist, sarcasm gate, 500-case holdout with injection defense) and the Razorpay duplicate-payment-link guard.

Final state: `ruff` clean across `packages apps tests scripts`; backend suite **164 passed / 0 failed**; web typecheck clean; live stack verified streaming end-to-end over SSE.

### Official run actuals (all `[SIMULATED]`, artifacts: `eval/results/20260824T225305Z/`)

| Arm | Recovery rate [95% CI] | Cost/₹100 | Complaint % |
|---|---|---|---|
| B0 organic | 4.11% [2.72, 5.82] | — | 0 | *(superseded 2026-08-30 artifact — see Addendum below)*
| B1 tuned naive | 21.16% [19.10, 23.36] | ₹0.15 | 0.567 |
| **Reflex** | **31.40% [28.94, 33.98]** | **₹0.27** | **0.244** |

Incremental vs B1: **+10.24pp [+7.83, +12.62]** · per-seed Reflex {42: 34.33, 1337: 29.62, 2025: 30.15} · losing-cohort correct declines: 3,642.

**Gate scorecard:** G2 cost ✅ (₹0.27 ≤ ₹3.5) · G3 complaint ✅ (0.244% < 0.5%) · **G1 ❌ honest miss** (+10.24pp < +15 target; CI excludes zero, so the effect is real, just smaller than aspirational) · G6 technically met but vacuous (run had no LLM key ⇒ full mode IS degraded mode) · G5 not yet demonstrated (no second identical run). Full analysis in `docs/limitations.md`.

## 2. Remediation Matrix

| ID | Item | Status | Key artifacts |
|---|---|---|---|
| P0-1 | Windows port collision → host 15432 | ✅ (residual stale defaults fixed: `alembic/env.py`, `core/settings.py`) | docker-compose.yml, .env.example, tests/conftest.py |
| P0-2 | RISK_HELD protocol amendment + tag | ✅ | `eval/PROTOCOL.md §0`, tags `eval-preregistered-v1.1-risk-held-amendment` + alias `eval-protocol-amendment-risk-held` (pushed) |
| P0-3 | Live stack + SSE stream | ✅ after 4 fixes (see §3) | `/api/stream` verified: `episode.created` ×8, `action.dispatched` ×2, 0 worker errors |
| P0-4 | Official N=3000×3-seed×8-arm eval | ✅ executed on attempt 3 | `eval/results/20260824T225305Z/{results.json,tables.md}` committed |
| P1-1 | AI-3 spelled-out-number blocklist | ✅ | `packages/prompts/validators.py` `_NUMBER_WORDS`; `tests/ai/test_message_generator.py` (9 tests) |
| P1-2 | AI-4 sarcasm/negative-polarity gate | ✅ | `apps/workers/replies.py` `_SARCASM_PHRASES`; `tests/ai/test_reply_classifier.py` (9 tests) |
| P1-3 | AI-1 500-case holdout | ✅ | `tests/ai/test_diagnosis_accuracy.py`; `eval/results/dx_holdout/report.{json,md}` — 100% degraded accuracy, 89.6% rules coverage, injections fail-closed |
| P1-4 | Razorpay duplicate-link guard (TASK-056) | ✅ code-complete; live rzp_test_ observation owed | pre-flight + timeout reconciliation via `reference_id`; `tests/unit/test_razorpay_client.py` (6 tests) |
| P1-5 | LICENSE / limitations.md | ✅ | Apache-2.0 (pre-existing); `docs/limitations.md` created |
| P2 | reproduce.sh, secrets, exports, codegen, design tokens | ✅ | reproduce.sh Windows venv fix; secret scan clean; `/api/episodes/export` + `/api/ledger/export` watermarked & live-tested; `npm run codegen` wired; navy/tabular-nums/INR verified |
| P3 | 10-documentation synchronization | ✅ | mixture/WAIT/ablation-priority/target-vs-actual syncs applied in two audits; docs un-ignored and tracked |

Task ledger: **31 ✅ / 19 🟡 / 6 ❌ (~72%)** per Tracker; TASK-033/036/039/056/057/058 statuses updated with evidence.

## 3. Bugs Found & Fixed (beyond the checklist)

1. **Bootstrap CI axis bug** — scalar `.sum()` divided every resampled denominator by `BOOTSTRAP_RESAMPLES`: all ratio CIs were compressed exactly 1000×. Every prior CI was invalid; stranded runs archived under `eval/results/superseded_pre_amendment/` (incl. a pre-amendment official-labeled run, marked superseded per PROTOCOL §0).
2. **cost_per_100 missing ×100** in summary builder (G2 metric read ~0).
3. **B0 organic recoveries excluded from TTR** (protocol defines TTR over ALL recovered episodes).
4. **RESULTS_DIR outside the repo** — artifacts were landing on the Desktop.
5. **Advisory-lock starvation → deadlocks**: `stop_customer` used a global transaction-scoped lock (held per whole arm transaction) then swallowed deadlock errors, poisoning transactions. Fixed: session-scoped millisecond hold, no swallowing, serial-arm default at N≥3000 (+ `--parallel` override).
6. **Silently-dead diagnosis consumer**: `xread` called with the `>` ID (only valid for XREADGROUP); every read errored into `except: continue`. Consumer groups showed 0 consumers forever. Fixed to `xreadgroup`.
7. **ADR-004 violation in workers**: sim-clock/batch reads queried `replay.*` under the agent role (no grants) → dispatch loop crashed each tick. Reads moved to the eval role.
8. **Illegal state transition spam**: planner mapped Shield-BLOCKED plans to `stopped_cap` (legal only from `observing`) → trigger exception per tick. Now maps to legal `halted`.
9. **Kill-switch `NameError`**: `LedgerWriter` never imported in `control.py` (found by lint F821).
10. **Replay ingest published no SSE events** — console blind to demo episodes; publish added.
11. **reproduce.sh** used POSIX venv paths on Windows; stale `localhost:5432` defaults missed by P0-1.

## 4. AI Guardrail & Security Updates

- **Hinglish loophole closed**: any of 32 Hinglish/English number/currency words in an LLM span ⇒ rejection ⇒ deterministic slot-template fallback (the only path money enters text). Strictness deliberate: false positives cost only the safe template.
- **Sarcasm gate**: deterministic negative-polarity phrases outrank confident LLM PROMISE/PAYING (safe AMBIGUOUS); explicit COMPLAINT/OPTOUT keywords still outrank everything (fail-closed suppression).
- **Injection defense**: deterministic marker pre-filter in `diagnose_rules`; all 4 corpus injection attempts classify fail-closed to `UNKNOWN_AMBIGUOUS` in degraded mode.
- **Anti-cheat intact**: agent-role isolation tests green (`InsufficientPrivilege` assertions tightened from blind `Exception`).

## 5. Documentation Sync Summary

Two audit passes: (1) twelve mechanical consistency clusters (amended mixture everywhere — zero `34%` remains; WAIT atomic-enum semantics; A1+A2 core-gate ablations; export/TASK-056/AI-holdout status flips; ₹6.9 provenance; MANUAL_STEPS 15432-default framing); (2) official-results flip across README/MANUAL_STEPS/PRD/TechSpec/ImplPlan/Tracker/Rules/judge_qa/summary with exact CIs, plus new `docs/limitations.md`. Verification greps: `"NOT YET RUN|has not been executed"` → 0 matches; docs now tracked in git (was ignored).

## 6. Remaining Items / Pitch-Video Checklist

1. **Push pending commits when connectivity returns** — local `master` is ahead: `6d9fd9e` (results+P0-3+lint), `b485b8d` (export tests). Then fast-forward `main`.
2. Record the 5-minute pitch (demo flow: `make up && make seed`, `scripts/start_demo.py`, console at :8080/:8899; quote official actuals + G1 miss honestly).
3. Optional hardening: keyed rerun to measure LLM-tail value (opens G6 meaningfully); second identical run for G5 tolerance; A2 EV-off anomaly investigation before pilot; live Razorpay test-mode note (TASK-056 tail).


---

## Post-script (2026-08-25 — supersedes §5/§6 items above where they differ)

This report was written before the G5 reproduction run completed. Latest measured findings live in
`docs/limitations.md` and supersede this document as source-of-truth:

- **G5 same-seed reproduction MEASURED FAIL** — full 8-arm seed-42 rerun (`scripts/g5_repro.py`,
  artifacts `eval/results/g5_repro_check/`): b0 organic reproduces exactly (4.11% ⇒ batch/response
  determinism holds); every contact-scheduling arm drifts −0.8 to −2.8 pp, outside the ±0.005
  tolerance. Cause isolated to wall-clock `opened_at` scheduling; fix tracked TASK-061.
- **A2 EV-off anomaly QUANTIFIED at episode level** — of the 1,221 episodes full-EV declines, 407
  would have paid (₹77,240 [SIMULATED]) for ~₹1,300 of extra contact cost, spread across all nine
  actionable codes; EV arithmetic verified unit-correct ⇒ cause is over-pessimistic v1 priors.
  Remedy: protocol-disciplined v2 recalibration run — never a post-hoc tune of frozen v1 numbers.
- **CI stabilization landed** (`tests/conftest.py`: rate-limit bucket flush per client test + stray
  idle-in-transaction backend termination before TRUNCATE + deadlock retry) — GitHub Actions backend
  job green (runs #10, #12).


---

# Addendum — 2026-08-30 Session (Deployment + Hardening Round)

**Scope:** production deployment (Vercel + Railway), security hardening, ledger integrity root-cause fix, reliability work, and documentation sync.

## Executed

1. **Production deployment.** Frontend on Vercel (`reflex-recover.vercel.app`), backend on Railway (`reflex-api-production.up.railway.app`) with PostgreSQL 18 and Redis (private network). The legacy Antideploy apps were decommissioned and deleted by the owner.
2. **Security hardening.** Random `JWT_SECRET` in production (the default `"dev-only-change-me"` was forgeable-admin territory); `/debug/env|login_check|migrate` now require the ADMIN role and no longer leak tracebacks; `POST /debug/migrate` runs real alembic (alembic moved into runtime deps; the production `alembic_version` was stamped to the true baseline); `/metrics` requires VIEWER; CORS narrowed to the deployed origins; CSP + `X-Content-Type-Options` + `Referrer-Policy` headers on the Vercel app.
3. **Ledger integrity — root-cause fix (no more re-stamps).** The false-TAMPER cycle (seq 3562/20970/21320) had two causes: hashes computed over the in-memory event dict while verification read the jsonb-normalized stored text, and a head-read race between concurrent writers. Fix: the hash is now computed **server-side inside a single atomic INSERT** — `sha256(seq ‖ prev_hash ‖ event::text)` via pgcrypto (migration `0003`) — and verification hashes the same stored text. A batched re-stamp re-derived all 31,000+ events; the chain has since stayed valid through multiple live demos.
4. **Pipeline availability fix.** The embedded workers were gated on `REDIS_URL` being absent (Antideploy single-container mode); with a real Redis on Railway they never started, halting diagnosis. Workers are now unconditional. A real Redis also makes SSE deliver genuine pubsub events (the in-memory fake never did).
5. **Reliability.** Ops counters recompute from Postgres at startup (no more zeros after redeploys); drive-end force-resolves all non-terminal episodes (fail-closed timeouts, ledgered) and resets the sim clock — zero frozen "observing" episodes; the eval pre-registration gate now falls back to `git ls-remote`/GitHub API (cached, fails closed) so "Run eval" works from the deployed container.
6. **Client resilience.** 15–60 s polling with SSE-driven invalidation, exponential SSE reconnect backoff, no retries on 4xx, readable error banners, and a short-lived 60-second stream credential so the session JWT never rides the SSE URL.

## Verification highlights

`/healthz` 200 · forged old-secret token 401 · `/debug/*` 401 unauth / 200 admin · `/metrics` 401 unauth · ledger `{"valid":true,"checked":31,369}` · eval `tag_present: true` from the container · 26 official eval runs loaded · CI green on `main` · sync workflow green on `master`.
