<!-- markdownlint-disable MD024 -->
# Changelog 📜

All notable changes to the **Reflex** repository are documented in this file. The format
is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/) and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [1.0.0] — 2026-08-31

### Added
- Production deployment: frontend on Vercel, backend on Railway (PostgreSQL 18 + Redis on
  the private network), CI via GitHub Actions, `master → main` auto-sync workflow.
- **Ledger integrity, root-cause fix:** the event hash is now computed server-side inside
  a single atomic INSERT over the jsonb-normalized event text (`sha256(seq | prev_hash |
  event::text)` via pgcrypto, migration `0003`) — append and verify agree by construction;
  concurrent writers cannot fork the chain; the false-TAMPER cycle is dead (chain stayed
  valid through multiple live demos).
- **Security hardening:** random production `JWT_SECRET`, `/debug/*` admin-gated
  (tracebacks no longer leaked), `/metrics` and `/docs`/`/openapi.json` access-gated, CORS
  scoped to the deployed origins, CSP + security headers on the static app.
- **Real Redis:** live SSE events now genuinely stream through pubsub (the in-memory fake
  only emitted keepalives); embedded workers start unconditionally.
- **Reliability:** Ops counters recomputed from Postgres at startup; replay drive-end
  force-resolves all non-terminal episodes (fail-closed timeouts, ledgered) and resets the
  sim clock to wall time; eval pre-registration gate falls back to `git ls-remote` /
  GitHub API with a 60-second negative-cache TTL.
- **SSE hardening:** dedicated 32-thread pubsub pool; `POST /api/stream/token` mints a
  60-second stream credential so the session JWT never rides the SSE URL.
- **Frontend:** EV/Ledger drawer width fixes, B0/B1 self-explaining filter copy, results
  header showing the seeds actually present, audit-page error handling, `og:url` fix.
- Documentation synced end-to-end: `README`, `llm.txt`, `MANUAL_STEPS`, `MIGRATION`,
  `CONTRIBUTING`, `docs/summary`, `docs/judge_qa`, `docs/limitations`, `docs/1–8`.

### Fixed
- Embedded workers were gated on `REDIS_URL` being absent — with a real Redis on Railway
  they never started and the pipeline silently halted at diagnosis.
- Production signed tokens with the default dev JWT secret (forgeable admin tokens).
- A frontend build without `VITE_REFLEX_API` produced a same-origin bundle that silently
  broke every API call — the build now fails loudly (CI skips the guard).

## [0.9.0] — 2026-08-28

### Added
- Production deployment (Vercel + Railway split: static SPA + containerized FastAPI) with
  PostgreSQL and embedded workers; legacy platform decommissioned.
- Real-time dashboard: SSE-connected command center, live demo replay at ×100–×800 sim
  speed, failure-injection suite (LLM outage, webhook storm, complaint), kill switch,
  guardrail editor, watermarked exports.
- Human approval gate (fail-closed, 4-hour timeout, reasons recorded in the ledger) and
  role-based access control (viewer → operator → approver → admin).

## [0.5.0] — 2026-08-26

### Added
- Official pre-registered evaluation executed and committed: protocol
  `eval-preregistered-v1`, artifacts at `eval/results/20260830T105923Z/` — **Reflex 33.83%
  [29.36, 38.75]** vs B1 25.06% vs B0 4.11% recovery, incremental **+8.77 pp [4.49,
  13.28]** (CI excludes zero), bootstrap 95% CIs, ablations A1–A4 + DEGRADED, published
  losing cohort (1,189 declined episodes).
- Anti-cheat architecture: DB role separation (the agent cannot read simulator ground
  truth), git-tagged pre-registration, honestly tuned baseline.
- AI-safety expansions: Hinglish number-word blocklist, sarcasm gate, 500-case diagnosis
  holdout with injection defense, Razorpay duplicate-payment-link guard.

## [0.1.0] — 2026-08-22

### Added
- Initial build: FastAPI ingestion/diagnosis/EV/guardrail/dispatch pipeline, React command
  center, hash-chained ledger, React command center design system, full design
  documentation (`docs/1–8`), test suite (unit/api/integration/security/load).
