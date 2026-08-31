# Security Policy — Reflex

## Scope

Reflex is a payment-recovery agent that integrates with **Razorpay TEST-MODE APIs only**.
No real money moves, no real customers are contacted, and no live API keys exist anywhere
in the evaluation path. Even so, this codebase implements production-grade fintech
security patterns (RBAC, HMAC webhook verification, hash-chained append-only ledger, JWT
auth) and we treat vulnerabilities in those patterns seriously.

## Supported versions

Only the latest commit on `main` (auto-synced from `master`) is supported.

## Reporting a vulnerability

**Preferred:** use GitHub's **private vulnerability reporting** — open the repository →
**Security** tab → **Report a vulnerability**. This keeps the report confidential until a
fix is released.

Alternatively, open a regular issue **only if the report cannot be used to exploit the
live deployment** (https://reflex-recover.vercel.app). If your report could leak data,
expose a way to gain privileged access, or break the system, do **not** publish details in
a public issue — contact the maintainer directly at
[abhinav-phi@users.noreply.github.com](mailto:abhinav-phi@users.noreply.github.com) and
include the word **SECURITY** in the subject line.

## What to include

- The affected component (API / web / ledger / workers / deployment config)
- Steps to reproduce or a proof of concept
- The impact you believe it enables
- Any relevant environment details

## Response commitment

We will acknowledge reports within **72 hours**, keep you updated throughout the
investigation, and credit you in the fix release (unless you prefer to remain anonymous).

## Out of scope

- The simulated channel simulators and demo seed data (everything is `[SIMULATED]` and
  labeled as such — there is no real customer data to attack)
- Rate limiting of the *public demo deployment itself* (it is intentionally open with
  seeded demo credentials)
- Automated scanner noise without a demonstrated exploit path

## Production data posture (2026-09-01)

Production PostgreSQL runs on **Aiven Free** (Amsterdam) and is reached by the API over
TLS with `sslmode=require` — encrypted in transit, without CA pinning (`verify-full`
requires the server CA certificate, which the current Aiven API surface does not expose
to automation; pinning is the intended upgrade when available). The database holds only
`[SIMULATED]` data, but its integrity controls are real: append-only ledger grants, role
separation, and a hash chain verifiable via `GET /api/ledger/verify`. Connection pools
are capped to the plan's 20-connection budget. The Aiven API token and database password
are secrets handled outside the repository (`.env`/platform variables only; gitleaks
enforces this in CI).
