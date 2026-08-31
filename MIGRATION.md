> **STATUS: EXECUTED & COMPLETE.** This migration was performed (frontend → Vercel `reflex-recover.vercel.app`, backend → Railway `reflex-api-production.up.railway.app`). The old Antideploy apps have been deleted. Kept as the deployment reference.

# Deployment migration: Vercel (web) + Railway/Render (API)

Old home (Antideploy) works but its Cloudflare edge rate-limits bursts by IP.
This doc is the self-service path to the split setup.

## Postgres on Aiven Free (2026-09-01) — production DB + ops runbook

The Railway free-plan Postgres hit its hard 500 MB volume ceiling: crash
recovery needed ~16 MB of WAL headroom that did not exist, so it crash-looped
("No space left on device" writing `pg_wal/xlogtemp`), and free-plan volumes
cannot be grown. The database was rescued and migrated to **Aiven for
PostgreSQL Free** (1 GB disk, 1 vCPU/1 GB RAM, Amsterdam `upcloud-nl-ams`,
same city as the API). Migration proven bit-exact: all 23 tables' row counts
and a 9-value ledger fingerprint (row-hash sums, event-text checksums, seq
range) matched the source exactly; the `pg_dump -Fc` sha256 verified on both
ends.

- `DATABASE_URL` (reflex-api on Railway) now points at the Aiven URI
  (`postgres://avnadmin:…@reflex-pg-reflex-prod.j.aivencloud.com:22228/railway?sslmode=require`).
- Connection pools in `apps/api/db.py` + the `main.py` counters seeder are
  capped to fit Aiven Free's **`max_connections = 20`** (agent 6+2, eval 5+3,
  admin 3+0, seeder 1 — steady ~10, worst case 20).
- The old Railway Postgres service is left **frozen (crashed) as a cold
  backup** of the pre-migration volume. Delete it once confidence in Aiven
  settles; that also stops it consuming free-plan usage.

### Operations

1. **Weekly-idle power-off.** Aiven powers free services off after ~1 week of
   no activity (email notice first). Before a demo: console.aiven.io →
   `reflex-pg` → **Power on** (a few minutes), then check `GET /healthz`. The
   API's 10 s connect timeout makes a powered-off DB surface as fast 500s on
   DB routes, never a hang.
2. **Verification queries** (SQL console against the Aiven URI):
   `SELECT COUNT(*) FROM runtime.episodes` → **18041**;
   `SELECT COUNT(*) FROM runtime.action_ledger` → **≥ 204061** (grows with new
   appends); `SELECT last_value FROM runtime.action_ledger_seq_seq` must be
   ≥ max(seq) — else appends would collide.
3. **Historical ledger rows — restamped 2026-09-01, chain now fully valid.**
   The eval/replay bulk loaders had raced on the chain head, leaving ~12.7k
   rows (seq ≥ 32166) whose hashes referenced a stale predecessor — full-table
   `ledger/verify` reported a break and intersecting episode trails returned
   409. The chain was re-derived from stored events (the sanctioned
   `restamp_ledger.py` math, executed in batches) and the trail verifier was
   fixed to check each row against its own global predecessor
   (`verify_episode_slice`) — `ledger/verify` now returns
   `valid:true, checked:204061` and every episode trail verifies. Pre-restamp
   and post-fix dumps are retained (local + Aiven PITR) as the audit trail.
   Note: any ledger-hash values exported **before** 2026-09-01 no longer match
   the database — re-export if a hash-level comparison is needed.
4. **Recent appends are atomic**: since migration `0003`, ledger hashes are
   computed server-side (pgcrypto) inside the single INSERT, so new rows chain
   correctly; `pgcrypto` is present on the Aiven instance.

## Current live deployment (2026-08-28)

| App | URL | Platform |
|---|---|---|
| Command center (React SPA) | **https://reflex-recover.vercel.app** | Vercel — git-connected (push `main` auto-deploys), build env `VITE_REFLEX_API` |
| API (FastAPI + PostgreSQL) | **https://reflex-api-production.up.railway.app** | Railway — git-connected, Dockerfile, `DATABASE_URL` = Postgres plugin (linked), serverless OFF, healthcheck `/healthz` |

Seeded logins (password `reflex-demo`): `admin@reflex.dev` · `approver@` · `operator@` ·
`viewer@`. Both deploy from GitHub `main`; CI (GitHub Actions) must stay green.

## Why this split

- The API is a long-running container: embedded worker threads, the ~16-min
  replay driver, SSE streams, and a PostgreSQL connection pool. That cannot
  run on Vercel serverless functions (they are per-request, no threads, no disk).
- The frontend is a static SPA — Vercel is ideal and free.

## Backend — Railway (recommended) or Render

**PostgreSQL required**: the alembic migrations are PostgreSQL-only
(`gen_random_uuid()`, `JSONB`, `to_regclass`), so the app must get a
`DATABASE_URL`. The SQLite fallback in `apps/api/db.py` only covers the Redis
broker/streams layer (absent `REDIS_URL` ⇒ in-memory fake) — it does not
replace the schema.

Railway:
1. New Project → Deploy from GitHub → `abhinav-phi/reflex` (root, Dockerfile auto).
2. New Project → **Database → PostgreSQL** (plugin). Railway links it automatically
   and injects `DATABASE_URL` into the API service.
3. Redeploy when the DB is ready (env change triggers a restart).
4. Optional: volume at `/app` to persist other runtime files across redeploys.
5. Copy the public URL (e.g. `https://reflex-api-production.up.railway.app`).

Render (alternative):
1. New Web Service → GitHub → `reflex` → Runtime: Docker. (Or import
   `render.yaml` via "Blueprint".)
2. Health check `/healthz` (already wired in the blueprint).
3. Copy the public URL (`https://reflex-api.onrender.com`).

## Frontend — Vercel

1. Import `abhinav-phi/reflex`, Root Directory = `apps/web`.
2. Framework = Vite; Build = `npm run build`; Output = `dist`.
3. Environment Variable (build): `VITE_REFLEX_API = <backend URL from above>`.
   **Required** — the production build now FAILS loudly if it is missing
   (guard in `apps/web/vite.config.ts`), so the old same-origin 405 bug cannot
   silently come back.
4. `vercel.json` (already in `apps/web`) rewrites all routes to `index.html`
   for the SPA router.
5. Custom domain (optional): add after the first deploy.

## CORS

The API already allows any `*.vercel.app` and `*.railway.app` origin
(`apps/api/main.py` middleware) — nothing to add unless you use a custom
domain top-level, in which case extend `allow_origin_regex` (or set
`CORS_ORIGINS` env to an exact list). The frontend calls the API cross-origin,
so the API must ALWAYS be a full https URL in `VITE_REFLEX_API`.

## First-run check

```
curl -s https://<api-url>/healthz      # {"status":"ok",...}
curl -s -X POST https://<api-url>/api/auth/login -H 'content-type: application/json' \
  -d '{"email":"operator@reflex.dev","password":"reflex-demo"}'
```

Then open the Vercel URL, log in, and check Dashboard → SSE pill says
"connected" → Approvals (approver+/admin) → Results → Audit → Ops.
