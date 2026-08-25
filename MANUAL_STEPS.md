# Reflex — Manual Setup Guide & Operator Runbook

> **Audience:** Razorpay judges & operators. Everything marked **AUTOMATIC** is handled by code. Everything marked **MANUAL** requires human action.
>
> **Safety Notice:** This project operates strictly in `[TEST MODE]` (Razorpay keys must start with `rzp_test_`) with fully `[SIMULATED]` customer data and channels. Never connect to production credentials — the code refuses live keys by design (`TestModeViolation`).

---

## 1. What I Need to Do (High-Level Summary)

1. **Install prerequisites** (Python 3.11+, Node 18+, Docker Desktop).
2. **Configure `.env`** from the template (`cp .env.example .env`).
3. **`make up`** — boots Postgres + Redis + API + workers + web, applies migrations. *(AUTOMATIC)*
4. **`make seed`** — seeds users, merchant, policy, corpora. *(AUTOMATIC, idempotent)*
5. **`make demo`** — starts the 214-episode demo slice at ×100 speed and streams counters. *(AUTOMATIC once API is reachable; see §7 for the MANUAL alternative.)*

Then open the UI and run the failure-injection playbook (§7).

## 2. Prerequisites & Verification

| Tool | Version | Verify | Notes |
|---|---|---|---|
| Python | ≥ 3.11 | `python --version` | 3.11 is the floor; 3.12 works |
| Node.js | ≥ 18 (22 recommended) | `node --version` | Only needed for local web dev |
| Docker Desktop | any recent | `docker info` | Must be running before `make up` |
| Git | any recent | `git --version` | Tag provenance checks need full history |
| make | — | `make --version` | Windows: use PowerShell + `make` via choco/scoop, or run the Makefile targets manually (each is one command) |

## 3. Environment Variables Configuration

**MANUAL:**
```bash
cp .env.example .env
```

| Variable | Required? | Purpose |
|---|---|---|
| `LLM_API_KEY` | Optional | OpenAI-compatible key. **System runs LLM-absent-safe without it** (rules-only diagnosis, template messages, degraded-safe). Add it to show real LLM phrasing in the demo. |
| `LLM_BASE_URL` / `LLM_MODEL` | Optional | Defaults: `https://api.openai.com/v1` / `gpt-4o-mini`. Any OpenAI-compatible endpoint works. |
| `RAZORPAY_KEY_ID` | For onboarding connectivity check only | Test-mode key (`rzp_test_...`). Demo replay arms never need it. |
| `RAZORPAY_KEY_SECRET` | With above | Test-mode secret. Live keys are rejected in code. |
| `RAZORPAY_WEBHOOK_SECRET` | Optional | HMAC secret for `/webhooks/razorpay`. Defaults to a dev value if unset. |
| `JWT_SECRET` | Yes (dev default provided) | Auth token signing, 8h TTL. |
| `DATABASE_URL` / `DATABASE_URL_ADMIN` / `DATABASE_URL_EVAL` | Compose provides them | Three DB roles: agent (locked out of simulator truth) / admin (migrations) / eval (Proof). |
| `REDIS_URL` | Compose provides it | Streams, dedup TTL, rate limits, kill-switch flag. |
| `POSTGRES_USER/PASSWORD/DB` | Compose provides them | Container bootstrap credentials. |

## 4. Database Setup, Migrations & Verification

**AUTOMATIC:** `make up` boots Postgres (with `-c max_connections=300` for eval parallelism) + Redis; migrations apply via Alembic (`0001_baseline` → `0002_actions_llm_call_id`). `make seed` inserts 4 users, merchant *SipDaily* with guardrail config, policy v1, corpora.

**MANUAL — verify the anti-cheat boundary actually holds** (this is the structural anti-rigging guarantee, ADR-004):

```bash
docker compose exec postgres psql -U postgres -d reflex -c \
  "SELECT has_table_privilege('reflex_agent', 'replay.sim_customers', 'SELECT');"
# Expect: f  (false — agent role cannot read hidden simulator truth)

docker compose exec postgres psql -U postgres -d reflex -c \
  "SELECT has_table_privilege('reflex_agent', 'runtime.action_ledger', 'UPDATE');"
# Expect: f  (false — ledger is append-only for the app role)
```

The test suite proves both dynamically (SQLSTATE `42501` on violation): `pytest tests/security -q`.

## 5. Multi-Terminal Service Startup Guide (If not using make demo)

For local development (hot-reload), run three terminals after `cp .env.example .env`:

**T1 — Postgres + Redis only, then API on :8899**
```bash
docker compose up -d postgres redis
python -m alembic upgrade head
python -m reflex.eval.seed
uvicorn reflex.api.main:app --reload --port 8899     # NOT 8000 — reserved on some hosts
```

**T2 — Workers** (one per role, or all three in separate shells):
```bash
reflex-worker --role diagnosis    # = python -m reflex.workers.runner --role diagnosis
reflex-worker --role decision
reflex-worker --role outcome
```

**T3 — Web dev server**
```bash
cd apps/web && npm install && npm run dev          # http://localhost:5173
```

> `make demo` targets `http://localhost:8899` by default. If you're running the full Docker stack instead (API on :8000, UI on http://localhost:8080), set `REFLEX_API=http://localhost:8000` before `make demo`.

## 6. First Login & Bootstrap Administrator

**MANUAL:**
1. Go to **http://localhost:5173/login** (dev route) or **http://localhost:8080** (Docker route).
2. Log in with seeded credentials — password for all four demo users is **`reflex-demo`** (printed by the seed script):

| Email | Role | Can do |
|---|---|---|
| `admin@reflex.dev` | admin | Everything incl. guardrail settings, user view |
| `operator@reflex.dev` | operator | Mode changes, kill switch, injections, replay start |
| `approver@reflex.dev` | approver | Approve/decline queue items |
| `viewer@reflex.dev` | viewer | Read-only dashboards |

3. Verify you land on the Command Center (`/dashboard`) with empty-state CTAs.
4. RBAC is enforced server-side — logging in as viewer hides controls cosmetically AND the API returns 403 (matrix-tested).

## 7. Interactive Demo & Failure Injection Playbook

**AUTOMATIC (preferred):**
```bash
make demo    # logs in as operator, starts slice via API, streams counters until done
```

**MANUAL (equivalent API call):**
```bash
TOKEN=$(curl -s -X POST http://localhost:8899/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"operator@reflex.dev","password":"reflex-demo"}' | python -c "import sys,json;print(json.load(sys.stdin)['token'])")

curl -X POST http://localhost:8899/api/replay/start \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"n":214, "seed":"demo-7", "arm":"reflex", "speed":100.0, "demo":true}'
```

Watch it live on `/dashboard`: red FAILED counter starts at ₹2,41,000 · diagnosis chips appear · EV drawer shows four-term math on the ₹299 episode · a ₹48,000 corporate order lands in `/approvals` (**approve it as approver — human gate**) · green counter climbs past the naive twin.

### Failure injections (all through the REAL system path)

1. **LLM Outage** → `/ops` → *Inject LLM Outage*. **Verify:** amber DEGRADED banner; stream keeps flowing; new actions stamped `mode=DEGRADED`; zero dropped episodes. Restore via *Inject LLM Restore*.
2. **Webhook Storm** → `/ops` → *Inject Webhook Storm*. **Verify:** 1,000 events → **214 episodes**, duplicates collapsed, dedup counters visible.
3. **Complaint** → pre-seeded trajectory fires mid-episode. **Verify:** instant suppression + approval-queue item *"Human handoff"* + episode STOPPED_CUSTOMER; zero further contact for that customer.

**Kill switch:** control-bar button or:
```bash
curl -X POST http://localhost:8899/api/control/mode \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"mode":"halted","reason":"demo"}'
```
Drain budget ≤1 s — measured at ~25 ms for 500 scheduled actions. Resume with `{"mode":"autonomous"}`.

## 8. Evaluation & Reproducibility Runbook

**MANUAL (one command):**
```bash
./eval/reproduce.sh            # Linux/macOS/WSL/Git-Bash
```

What it does *(AUTOMATIC)*: verifies the `eval-preregistered-v1` git tag exists (refuses otherwise) → boots Postgres+Redis → applies schema + seed → runs the official pre-registered protocol (3 seeds × {B0, B1, Reflex} × ablations A1–A4, bootstrap CIs) → writes `eval/results/<run_id>/results.json` + `tables.md`, all labeled `[SIMULATED]`.

Expected runtime: **< 15 minutes** on a 4-core VM (protocol target <10 min for the runs themselves).

**Status (2026-08-24): the official N=3000×3-seed×8-arm run HAS BEEN EXECUTED.** Protocol `eval-preregistered-v1`, seeds {42, 1337, 2025}, artifacts committed at **`eval/results/20260824T225305Z/`** (`results.json` + `tables.md`), every value labeled `[SIMULATED]`. Headline actuals: Reflex 31.40% CI[28.94, 33.98] · cost ₹0.27/₹100 · complaints 0.244%; B1 21.16% CI[19.10, 23.36]; B0 4.68% CI[3.71, 5.75]; incremental vs B1 +10.24 pp CI[+7.83, +12.62] — pre-registered G1 gate (≥ +15 pp) missed, G2 cost / G3 complaint gates pass. Honest caveat set — including that the run executed without an `LLM_API_KEY` (reflex arm == rules-first path end-to-end) — lives in [docs/limitations.md](docs/limitations.md).

The earlier blocker was environmental and is now history: Windows reserves ports 5276–5875 (`netsh interface ipv4 show excludedportrange protocol=tcp`), covering Postgres' 5432, so the container couldn't bind. Workarounds (still relevant for custom runs):
- Custom Docker runs only: map Postgres to a host port outside the reserved ranges and export `DATABASE_URL*` accordingly, e.g. `-p 15432:5432` — note docker-compose.yml ALREADY defaults to host 15432 → container 5432, so compose runs need no manual flag; or
- Re-reserve dynamic ports as admin: `net stop winnat && net start winnat`.

If `reproduce.sh` fails on your host, inspect `eval/results/`: the citable official run is `20260824T225305Z`. Earlier smoke-scale runs and the superseded pre-amendment attempts (archived with a README under `eval/results/superseded_pre_amendment/`) are preserved for honesty and are **not citable results**.

## 9. Manual vs. Automatic Responsibility Matrix

| Responsibility | Who |
|---|---|
| Webhook HMAC verify, dedup, episode creation | **AUTOMATIC** |
| Rules + LLM diagnosis, confidence gating | **AUTOMATIC** |
| EV scoring & candidate ranking | **AUTOMATIC** |
| Shield guardrail checks (caps/budget/quiet hours/suppression) | **AUTOMATIC — non-overridable** |
| Ledger hash chaining & tamper detection | **AUTOMATIC** |
| Watch windows, attribution, expiry sweeps | **AUTOMATIC** |
| Degraded-mode failover on LLM outage | **AUTOMATIC** |
| Idempotent dispatch (duplicate-key collapse) | **AUTOMATIC** |
| Approving actions > ₹50,000 / pause-cancel class | **MANUAL** — human click in `/approvals`; timeout auto-declines fail-closed |
| Kill switch | **MANUAL** trigger → AUTOMATIC drain |
| Resolving complaint handoffs | **MANUAL** — human queue item; lifting suppression requires admin |
| Setting guardrails / modes / Razorpay keys | **MANUAL** — operator/admin, every change ledgered |

## 10. Troubleshooting Engine

| Symptom / Error | Cause | Fix |
|---|---|---|
| `SQLSTATE 42501` on `replay.sim_customers` | **Working as designed** — agent DB role isolation (ADR-004). | None. If you *wanted* the agent to read it: don't. |
| `SQLSTATE 42501` on `action_ledger` UPDATE | Append-only grants doing their job. | Use INSERT (new event), never modify history. |
| `ports are not available ... 5432` / bind forbidden (Windows) | Excluded-port ranges cover 5432 (Hyper-V reservation). | docker-compose.yml already defaults to host 15432 → container 5432, so compose runs are unaffected. Only custom Docker runs need the manual flag: map an alternate host port (e.g. `-p 15432:5432`) + export `DATABASE_URL*`; or `net stop winnat && net start winnat` (admin). |
| `Docker Desktop crashed during eval` | Connection exhaustion under parallel arms. | Ensure compose Postgres runs `-c max_connections=300` (default here); don't shrink engine pools. |
| `401 Unauthorized` on webhook POSTs | HMAC signature mismatch (`RAZORPAY_WEBHOOK_SECRET`). | Align the secret between sender and `.env`; dev default is used when unset. |
| Duplicate webhook returns `duplicate:true`, no new episode | Dedup working as designed (provider event id unique). | Expected behavior — this is the storm-injection story. |
| Frontend SSE not updating | Backend not on expected port, or Redis pub/sub down. | Dev mode: API must be on `:8899` (or set proxy/target accordingly); check `docker compose ps redis`; refresh to reconnect. |
| Login 401 with seeded email | Seed not applied. | Run `make seed` (idempotent); password is `reflex-demo`. |
| Eval refuses to start: "REFUSING: git tag missing" | Pre-registration gate can't find `eval-preregistered-v1`. | Fetch full history (`git fetch --tags`); NEVER fabricate the tag after results exist. |
| All diagnoses show RULE / template messages | No `LLM_API_KEY` configured — system is intentionally LLM-absent-safe. | Add key to `.env` for the full AI demo, or present degraded-safe mode honestly. |

## 11. TL;DR — Start Everything From Scratch (Copy-Paste)

```bash
git clone https://github.com/abhinav-phi/reflex.git && cd reflex
cp .env.example .env        # optional: add LLM_API_KEY
make up                     # infra + api + workers + web + migrations
make seed                   # users / merchant / policy / corpora
make demo                   # 214 eps / ₹2,41,000 @ ×100  (set REFLEX_API=http://localhost:8000 for full-Docker)
# UI: http://localhost:8080 (Docker)  ·  http://localhost:5173 (dev)   password: reflex-demo
```

One-command evaluation: `./eval/reproduce.sh` · Full backend test suite: `make test`.
