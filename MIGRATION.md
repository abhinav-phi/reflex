# Deployment migration: Vercel (web) + Railway/Render (API)

Old home (Antideploy) works but its Cloudflare edge rate-limits bursts by IP.
This doc is the self-service path to the split setup.

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
