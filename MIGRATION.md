# Deployment migration: Vercel (web) + Railway/Render (API)

Old home (Antideploy) works but its Cloudflare edge rate-limits bursts by IP.
This doc is the self-service path to the split setup.

## Why this split

- The API is a long-running container: embedded worker threads, the ~16-min
  replay driver, SSE streams, and a SQLite file. That cannot run on Vercel
  serverless functions (they are per-request, no threads, no disk).
- The frontend is a static SPA — Vercel is ideal and free.

## Backend — Railway (recommended) or Render

Zero secrets needed: absent DATABASE_URL/REDIS_URL the app uses SQLite
(`/app/reflex-cloud.db`) and an in-memory fake Redis, bootstraps its schema on
startup, auto-seeds the 4 demo users (`admin@reflex.dev`, `approver@`,
`operator@`, `viewer@reflex.dev`, password `reflex-demo`).

Railway:
1. New Project → Deploy from GitHub → `abhinav-phi/reflex` (root, Dockerfile auto).
2. Start command: none needed (Dockerfile CMD) — but ensure PORT env is honored
   (the Dockerfile already is `${PORT:-8000}`).
3. Optional: volume at `/app` to persist SQLite across redeploys.
4. Copy the public URL (e.g. `https://reflex-api-production.up.railway.app`).

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
