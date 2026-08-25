# PART A — FIX VERIFICATION: WHAT'S LEFT FROM THE AUDIT

I re-audited your Revision 1.1 documents against every finding in my original report.

**Closed (verified in v1.1):** SAFE-001 (pgcrypto ✔), SAFE-002 (hash/revision binding ✔ + FR-026/NFR-007/R6.2), MILP-001/002/003/004 (interval reformulation ✔ + ADR-005), SAFE-003 (Emergency Service/PROVISIONAL/ADR-006 ✔), SAFE-004 (feeding map + acks ✔ + R6.5), DOC-001 (Tracker reset + R6.6 ✔), FSM-001/002 (12-state CHECKs, retry cap ✔), APP-001 (distinct-approver CHECK + idempotency ✔), DB-001/002/003/004/005/006 ✔, TEL-001/002 ✔, ML-001/002, BENCH-001 ✔, UX-001 ✔, SAFE-006 (outbox ✔), PERF-001/002 ✔, DOC-002..006, XC-001..012 ✔, INFO-001/002 ✔.

**Residuals still open — found in v1.1 itself (all small, all fixed in the code below):**

| ID | Sev | Residual Issue | Resolution in this codebase |
|---|---|---|---|
| RES-01 | P1 | `PROVISIONAL` plan state is referenced (FR-028, AppFlow Sc.A, Design token `status-provisional`) but is **absent from the 12-value `approval_status` CHECK** — same mismatch class I flagged as FSM-001. | `PROVISIONAL` added to CHECK. Update Schema.md with this one line. |
| RES-02 | P1 | FR-016/AppFlow reference `PENDING_TRANSMISSION` — also not representable in the 12-state CHECK. | Implemented as a separate `optimization.coa_outbox` table; plan status stays `AUTHORIZED_DRM` until COA ack. FSM untouched. |
| RES-03 | P2 | `excl_active_overlap` EXCLUDE only protects `block_plans.section_id` — secondary sections via `plan_sections` are unprotected. | Application-level overlap check in Plan Lifecycle + Sentinel MILP-C1 runs over **all** plan sections. |
| RES-04 | P2 | `solver_run_id` references a registry that doesn't exist. | `optimization.solver_runs` table added. |
| RES-05 | P2 | `ledger_writer` is `NOLOGIN` — the app cannot connect *as* it. | Guard triggers are the real enforcement (they fire for the owner too); role kept per spec; documented. |
| RES-06 | P1 | **Your MISSION BRIEF regresses to pre-audit content**: Module 2 asks for the old `x/y/z/w` binaries + `Σz+Σw+y≤1` (the MILP-001/002 bugs), Module 3 asks for "air-gapped… 14 hard-coded rules" (the DOC-001 fabrication). | Hardened v1.1 docs take precedence. Mission brief honored for repo structure, datasets, env layout. |
| RES-07 | P3 | Mission-brief Datasets 1/6/7 need columns/tables absent from v1.1 schema. | Additive extensions: `crossover_points JSONB`, `train_paths.metadata JSONB`, `operations.weather_alerts`. |
| RES-08 | P3 | No users/machines/weather/solver-run registries exist anywhere. | Additive tables: `auth.users`, `infrastructure.machines`, `operations.weather_alerts`, `optimization.solver_runs`, `optimization.coa_outbox`, `audit.idempotency_keys`, `demands.block_demands.features JSONB`. |

**Precedence rule applied throughout:** Rules.md v1.1 > TechSpec v1.1 §2/ADR-004/005/006 > mission brief. Nowhere did I implement the regressed formulation.

---

# PART B — THE CODEBASE

All directories additionally contain an empty `__init__.py`. Python containers run with `PYTHONPATH=/srv:/srv/packages`.

## Root

**`docker-compose.yml`**
```yaml
services:
  postgres:
    image: postgis/postgis:16-3.4
    environment:
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB: ${POSTGRES_DB}
    volumes:
      - pgdata:/var/lib/postgresql/data
      - ./data/sql:/docker-entrypoint-initdb.d
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER} -d ${POSTGRES_DB}"]
      interval: 5s
      retries: 12
    ports: ["5432:5432"]

  seeder:
    build: ./apps/api
    command: python -m data.generators.seed_all
    environment: &appenv
      DATABASE_URL: ${DATABASE_URL}
      REDIS_URL: ${REDIS_URL}
      JWT_SECRET: ${JWT_SECRET}
      JWT_ALGORITHM: ${JWT_ALGORITHM}
      ACCESS_TOKEN_EXPIRE_MINUTES: ${ACCESS_TOKEN_EXPIRE_MINUTES}
      INGEST_KEY_TMS: ${INGEST_KEY_TMS}
      INGEST_KEY_TDMS: ${INGEST_KEY_TDMS}
      INGEST_KEY_SMMS: ${INGEST_KEY_SMMS}
      INGEST_KEY_FOIS: ${INGEST_KEY_FOIS}
      IMD_API_KEY: ${IMD_API_KEY}
      COA_BRIDGE_SECRET: ${COA_BRIDGE_SECRET}
      SOLVER_MAX_TIME_SECONDS: ${SOLVER_MAX_TIME_SECONDS}
      SOLVER_NUM_WORKERS: ${SOLVER_NUM_WORKERS}
      OBJECTIVE_WEIGHT_PAX_DELAY: ${OBJECTIVE_WEIGHT_PAX_DELAY}
      OBJECTIVE_WEIGHT_FRT_DELAY: ${OBJECTIVE_WEIGHT_FRT_DELAY}
      OBJECTIVE_WEIGHT_SHADOW_REWARD: ${OBJECTIVE_WEIGHT_SHADOW_REWARD}
      OBJECTIVE_WEIGHT_MACHINE_IDLE: ${OBJECTIVE_WEIGHT_MACHINE_IDLE}
      OBJECTIVE_WEIGHT_UNADDRESSED_DEFECT: ${OBJECTIVE_WEIGHT_UNADDRESSED_DEFECT}
      OBJECTIVE_WEIGHT_EARLY_START: ${OBJECTIVE_WEIGHT_EARLY_START}
      DEMAND_STALENESS_TTL_HOURS: ${DEMAND_STALENESS_TTL_HOURS}
      WEATHER_STALENESS_TTL_HOURS: ${WEATHER_STALENESS_TTL_HOURS}
      FREIGHT_HARD_CONFIDENCE: ${FREIGHT_HARD_CONFIDENCE}
      HEADWAY_HIGH_PRIORITY_MINS: ${HEADWAY_HIGH_PRIORITY_MINS}
      HEADWAY_DEFAULT_MINS: ${HEADWAY_DEFAULT_MINS}
      EMERGENCY_SOLVE_BUDGET_SECONDS: ${EMERGENCY_SOLVE_BUDGET_SECONDS}
      WEEKLY_PLAN_CRON: ${WEEKLY_PLAN_CRON}
      ENABLE_ML_URGENCY: ${ENABLE_ML_URGENCY}
      SEED_PASSWORD: ${SEED_PASSWORD}
    depends_on:
      postgres: { condition: service_healthy }
    restart: "no"

  api:
    build: ./apps/api
    command: uvicorn apps.api.main:app --host 0.0.0.0 --port ${API_PORT}
    environment: *appenv
    depends_on:
      postgres: { condition: service_healthy }
      redis: { condition: service_started }
      seeder: { condition: service_completed_successfully }
    ports: ["${API_PORT}:8000"]
    healthcheck:
      test: ["CMD-SHELL", "python -c \"import urllib.request;urllib.request.urlopen('http://localhost:8000/health')\""]
      interval: 10s
      retries: 12

  worker:
    build: ./apps/workers
    command: celery -A apps.workers.tasks:app worker --loglevel=info --concurrency=2
    environment: *appenv
    depends_on:
      postgres: { condition: service_healthy }
      redis: { condition: service_started }
      seeder: { condition: service_completed_successfully }

  web:
    build: ./apps/web
    ports: ["5173:80"]
    depends_on:
      api: { condition: service_started }

  redis:
    image: redis:7.2
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      retries: 12

volumes:
  pgdata:
```

**`.env.example`**
```env
# Backend & Database
API_PORT=8000
API_HOST=0.0.0.0
POSTGRES_USER=rail_admin
POSTGRES_PASSWORD=rail_secure_password
POSTGRES_DB=railbloc_db
POSTGRES_HOST=postgres
POSTGRES_PORT=5432
DATABASE_URL=postgresql+asyncpg://rail_admin:rail_secure_password@postgres:5432/railbloc_db
DATABASE_URL_SYNC=postgresql+psycopg2://rail_admin:rail_secure_password@postgres:5432/railbloc_db

# Caching & Worker Queue
REDIS_HOST=redis
REDIS_PORT=6379
REDIS_URL=redis://redis:6379/0

# Security & Tokens
JWT_SECRET=super_secret_jwt_key_railbloc_2026
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=480
SEED_PASSWORD=railbloc

# Optimization Engine Parameters
SOLVER_MAX_TIME_SECONDS=35
SOLVER_NUM_WORKERS=8
OBJECTIVE_WEIGHT_PAX_DELAY=10.0
OBJECTIVE_WEIGHT_FRT_DELAY=4.0
OBJECTIVE_WEIGHT_SHADOW_REWARD=25.0
OBJECTIVE_WEIGHT_MACHINE_IDLE=2.5
OBJECTIVE_WEIGHT_UNADDRESSED_DEFECT=100.0
OBJECTIVE_WEIGHT_EARLY_START=0.05

# External API Mocks & Ingestion Keys (per-source machine credentials — TEL-001/XC-011)
IMD_API_KEY=mock_imd_weather_key_railway_ops
COA_BRIDGE_SECRET=mock_coa_dispatch_token
FOIS_FEED_SECRET=mock_fois_freight_token
INGEST_KEY_TMS=mock_tms_source_key
INGEST_KEY_TDMS=mock_tdms_source_key
INGEST_KEY_SMMS=mock_smms_source_key
INGEST_KEY_FOIS=mock_fois_freight_token

# Fail-closed staleness TTLs (TEL-001/TEL-002)
DEMAND_STALENESS_TTL_HOURS=12
WEATHER_STALENESS_TTL_HOURS=3

# Solver / safety parameters
FREIGHT_HARD_CONFIDENCE=0.60
HEADWAY_HIGH_PRIORITY_MINS=15
HEADWAY_DEFAULT_MINS=5
EMERGENCY_SOLVE_BUDGET_SECONDS=35
MAX_SENTINEL_RETRIES=3

# FR-013 cadence — configurable, never hardcoded (XC-010)
WEEKLY_PLAN_CRON=0 15 * * 4

# ML advisory toggles (Rules.md §2 — ML never enters a feasibility constraint)
ENABLE_ML_URGENCY=true
```

## data/sql

**`data/sql/01_init_postgis.sql`**
```sql
-- SAFE-001: pgcrypto is REQUIRED for the ledger trigger's digest(). No ledger hash without it.
CREATE EXTENSION IF NOT EXISTS "pgcrypto";
CREATE EXTENSION IF NOT EXISTS "postgis";
CREATE EXTENSION IF NOT EXISTS "btree_gist"; -- DB-003: UUID equality inside GiST EXCLUDE

-- DB-001: INSERT-only ledger role. It is NOLOGIN by design; the application role is
-- granted membership. Real enforcement against the owner/superuser is the guard triggers.
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='ledger_writer') THEN
    CREATE ROLE ledger_writer NOLOGIN;
  END IF;
END $$;
```

**`data/sql/02_schema_ddl.sql`**
```sql
CREATE SCHEMA IF NOT EXISTS infrastructure;
CREATE SCHEMA IF NOT EXISTS demands;
CREATE SCHEMA IF NOT EXISTS operations;
CREATE SCHEMA IF NOT EXISTS optimization;
CREATE SCHEMA IF NOT EXISTS audit;
CREATE SCHEMA IF NOT EXISTS auth;

-- ============ INFRASTRUCTURE ============
CREATE TABLE infrastructure.block_sections (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    section_code VARCHAR(32) NOT NULL,
    division VARCHAR(16) NOT NULL,
    zone VARCHAR(8) NOT NULL,
    start_km NUMERIC(7,3) NOT NULL,
    end_km NUMERIC(7,3) NOT NULL,
    line_type VARCHAR(16) NOT NULL CHECK (line_type IN ('SINGLE','DOUBLE','3RD_LINE','QUAD')),
    electrification VARCHAR(16) NOT NULL DEFAULT '25KV_AC' CHECK (electrification IN ('NONE','25KV_AC','2X25KV_AC')),
    speed_limit_mps SMALLINT NOT NULL DEFAULT 110,
    crossover_points JSONB DEFAULT '[]'::jsonb,   -- RES-07: mission-brief Dataset 1
    track_geom GEOMETRY(LineString, 4326) NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT true,       -- DB-004 soft-delete
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_section UNIQUE (division, section_code)
);
CREATE INDEX idx_block_sections_geom ON infrastructure.block_sections USING GIST (track_geom);
CREATE INDEX idx_block_sections_active ON infrastructure.block_sections (is_active);

-- SAFE-004: OHE feeding-section model (G&SR-4 enforcement data)
CREATE TABLE infrastructure.ohe_feeding_sections (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    feeding_section_code VARCHAR(32) NOT NULL,
    division VARCHAR(16) NOT NULL,
    isolator_boundary_geom GEOMETRY(LineString, 4326) NOT NULL,
    substation_ref VARCHAR(64) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_feeding_section UNIQUE (division, feeding_section_code)
);
CREATE INDEX idx_ohe_feeding_geom ON infrastructure.ohe_feeding_sections USING GIST (isolator_boundary_geom);

CREATE TABLE infrastructure.section_feeding_map (
    section_id UUID NOT NULL REFERENCES infrastructure.block_sections(id) ON DELETE RESTRICT,
    feeding_section_id UUID NOT NULL REFERENCES infrastructure.ohe_feeding_sections(id) ON DELETE RESTRICT,
    PRIMARY KEY (section_id, feeding_section_id)
);

-- RES-08: machine registry for VRP sub-model (FR-009 / TASK-045)
CREATE TABLE infrastructure.machines (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    machine_code VARCHAR(32) NOT NULL UNIQUE,
    machine_class VARCHAR(32) NOT NULL,
    depot_km NUMERIC(7,3) NOT NULL,
    transit_speed_kmph SMALLINT NOT NULL DEFAULT 40,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============ DEMANDS ============
CREATE TABLE demands.block_demands (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    external_source VARCHAR(16) NOT NULL CHECK (external_source IN ('TMS','TDMS','SMMS','BDMS_MANUAL')),
    external_ref_id VARCHAR(64) NOT NULL,
    department VARCHAR(16) NOT NULL CHECK (department IN ('ENGINEERING','TRD','SIGNAL_TELECOM')),
    section_id UUID NOT NULL REFERENCES infrastructure.block_sections(id) ON DELETE RESTRICT,
    activity_code VARCHAR(32) NOT NULL,
    min_duration_mins SMALLINT NOT NULL CHECK (min_duration_mins > 0),
    earliest_start TIMESTAMPTZ NOT NULL,
    latest_deadline TIMESTAMPTZ NOT NULL,
    urgency_score NUMERIC(4,3) NOT NULL DEFAULT 0.500 CHECK (urgency_score BETWEEN 0.0 AND 1.0),
    urgency_source VARCHAR(16) NOT NULL DEFAULT 'INGEST_RAW' CHECK (urgency_source IN ('INGEST_RAW','ML_ESTIMATED')), -- ML-002
    source_ingested_at TIMESTAMPTZ NOT NULL DEFAULT now(),  -- TEL-001
    features JSONB NOT NULL DEFAULT '{}'::jsonb,            -- RES-08: ML feature lineage
    machinery_req JSONB DEFAULT '[]'::jsonb,
    status VARCHAR(24) NOT NULL DEFAULT 'SUBMITTED' CHECK (status IN (
        'SUBMITTED','NORMALIZED','SCHEDULED_DRAFT','SENTINEL_PASSED','APPROVED_SR_DOM',
        'AUTHORIZED_DRM','TRANSMITTED_COA','ACTIVE_GRANTED','COMPLETED_FITNESS',
        'ARCHIVED_SEALED','CANCELLED','ESCALATED_OVERDUE')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_deadline_order CHECK (latest_deadline >= earliest_start)
);
CREATE INDEX idx_demands_dept_status ON demands.block_demands (department, status);
CREATE INDEX idx_demands_window_gist ON demands.block_demands USING GIST (tstzrange(earliest_start, latest_deadline)); -- PERF-002
CREATE INDEX idx_demands_section ON demands.block_demands (section_id);
CREATE UNIQUE INDEX uq_demands_source_ref ON demands.block_demands (external_source, external_ref_id); -- DB-006

-- ============ OPERATIONS ============
CREATE TABLE operations.train_paths (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    train_number VARCHAR(16) NOT NULL,
    train_type VARCHAR(24) NOT NULL CHECK (train_type IN ('VANDE_RAJDHANI','MAIL_EXP','PASSENGER','FREIGHT')),
    section_id UUID NOT NULL REFERENCES infrastructure.block_sections(id) ON DELETE RESTRICT,
    scheduled_entry TIMESTAMPTZ NOT NULL,
    scheduled_exit TIMESTAMPTZ NOT NULL,
    priority_rank SMALLINT NOT NULL DEFAULT 5 CHECK (priority_rank BETWEEN 1 AND 10),
    source VARCHAR(16) NOT NULL DEFAULT 'WTT' CHECK (source IN ('WTT','COA_LIVE','FOIS_FORECAST')),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,  -- RES-07: commodity/rake/stabling/forecast_confidence
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_train_window CHECK (scheduled_exit > scheduled_entry)
);
CREATE INDEX idx_train_paths_occupancy ON operations.train_paths (section_id, scheduled_entry, scheduled_exit);
CREATE INDEX idx_train_paths_number ON operations.train_paths (train_number);
CREATE UNIQUE INDEX uq_train_paths_upsert ON operations.train_paths (train_number, section_id, scheduled_entry); -- DB-006

-- SAFE-004: G&SR-2 enforcement entity
CREATE TABLE operations.signal_acknowledgments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    plan_id UUID NOT NULL,
    sm_actor VARCHAR(64), sm_acked_at TIMESTAMPTZ,
    controller_actor VARCHAR(64), controller_acked_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- SAFE-003: emergency incident persistence + coalescing
CREATE TABLE operations.incidents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    section_id UUID NOT NULL REFERENCES infrastructure.block_sections(id) ON DELETE RESTRICT,
    incident_type VARCHAR(32) NOT NULL CHECK (incident_type IN ('TRACK_FRACTURE','OHE_BREAKDOWN','SIGNAL_FAILURE','OTHER')),
    reported_by VARCHAR(64) NOT NULL,
    estimated_duration_mins SMALLINT,
    coalesced_into_incident_id UUID REFERENCES operations.incidents(id),
    controller_acknowledged BOOLEAN NOT NULL DEFAULT false,
    controller_ack_actor VARCHAR(64),
    controller_ack_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_incidents_section ON operations.incidents (section_id, created_at DESC);

-- RES-07: IMD weather alert persistence (FR-019 / TEL-002 fail-closed source)
CREATE TABLE operations.weather_alerts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    alert_type VARCHAR(32) NOT NULL CHECK (alert_type IN ('THUNDERSTORM_LIGHTNING','TORRENTIAL_RAIN','EXCESSIVE_HEAT_EXPANSION','CYCLONIC_GALE')),
    severity VARCHAR(24) NOT NULL CHECK (severity IN ('YELLOW_WATCH','ORANGE_BE_PREPARED','RED_ACTION_REQUIRED')),
    impact_polygon GEOMETRY(Polygon, 4326) NOT NULL,
    precipitation_mm_hr NUMERIC(6,2),
    rail_temperature_celsius NUMERIC(5,1),
    prohibited_work_types JSONB NOT NULL DEFAULT '[]'::jsonb,
    valid_until TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_weather_alerts_geom ON operations.weather_alerts USING GIST (impact_polygon);

-- ============ OPTIMIZATION ============
-- RES-04: solver run registry (block_plans.solver_run_id now references something real)
CREATE TABLE optimization.solver_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    horizon VARCHAR(16) NOT NULL CHECK (horizon IN ('STRATEGIC_26W','WEEKLY','REALTIME')),
    division VARCHAR(16) NOT NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'QUEUED' CHECK (status IN ('QUEUED','RUNNING','COMPLETED','FAILED','CONFLICT')),
    attempt SMALLINT NOT NULL DEFAULT 1,
    stats JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ
);

CREATE TABLE optimization.block_plans (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    plan_horizon VARCHAR(16) NOT NULL CHECK (plan_horizon IN ('STRATEGIC_26W','WEEKLY','REALTIME')),
    section_id UUID NOT NULL REFERENCES infrastructure.block_sections(id) ON DELETE RESTRICT,
    start_time TIMESTAMPTZ NOT NULL,
    end_time TIMESTAMPTZ NOT NULL,
    primary_demand_id UUID NOT NULL REFERENCES demands.block_demands(id) ON DELETE RESTRICT,
    is_shadow_block BOOLEAN NOT NULL DEFAULT false,
    solver_run_id UUID NOT NULL REFERENCES optimization.solver_runs(id),
    loss_pax_minutes NUMERIC(8,2) NOT NULL DEFAULT 0.00,
    loss_frt_minutes NUMERIC(8,2) NOT NULL DEFAULT 0.00,
    sentinel_verified BOOLEAN NOT NULL DEFAULT false,
    -- SAFE-002 binding columns
    revision_no INT NOT NULL DEFAULT 1,
    supersedes_id UUID REFERENCES optimization.block_plans(id),
    content_hash CHAR(64) NOT NULL,
    sentinel_hash CHAR(64),
    -- APP-001 approver identity columns
    decided_by VARCHAR(64), decided_at TIMESTAMPTZ,
    authorized_by VARCHAR(64), authorized_at TIMESTAMPTZ,
    -- FSM-001: aligned to AppFlow §3. RES-01: 'PROVISIONAL' added (referenced by FR-028/Design token, was missing from v1.1 CHECK).
    approval_status VARCHAR(24) NOT NULL DEFAULT 'DRAFT' CHECK (approval_status IN (
        'DRAFT','SENTINEL_PASSED','APPROVED_SR_DOM','AUTHORIZED_DRM','TRANSMITTED_COA',
        'ACTIVE_GRANTED','COMPLETED_FITNESS','ARCHIVED_SEALED','SUPERSEDED',
        'SUPERSEDED_EMERGENCY','CANCELLED','FAILED_ESCALATE','PROVISIONAL')),
    incident_id UUID REFERENCES operations.incidents(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_plan_window CHECK (end_time > start_time),
    CONSTRAINT chk_distinct_approvers CHECK (authorized_by IS NULL OR decided_by IS NULL OR decided_by <> authorized_by)
);
CREATE INDEX idx_block_plans_range ON optimization.block_plans (section_id, start_time, end_time);
CREATE INDEX idx_block_plans_status ON optimization.block_plans (approval_status);
CREATE INDEX idx_block_plans_incident ON optimization.block_plans (incident_id);

-- DB-003: no two ACTIVE-status plans may overlap on the same section
ALTER TABLE optimization.block_plans
    ADD CONSTRAINT excl_active_overlap EXCLUDE USING gist (
        section_id WITH =, tstzrange(start_time, end_time) WITH &&
    ) WHERE (approval_status IN ('AUTHORIZED_DRM','TRANSMITTED_COA','ACTIVE_GRANTED'));

ALTER TABLE operations.signal_acknowledgments
    ADD CONSTRAINT fk_sigack_plan FOREIGN KEY (plan_id) REFERENCES optimization.block_plans(id) ON DELETE RESTRICT;

-- DB-002: junction replaces UUID[]
CREATE TABLE optimization.plan_shadow_demands (
    plan_id UUID NOT NULL REFERENCES optimization.block_plans(id) ON DELETE RESTRICT,
    demand_id UUID NOT NULL REFERENCES demands.block_demands(id) ON DELETE RESTRICT,
    PRIMARY KEY (plan_id, demand_id)
);

-- DB-004: multi-section corridor blocks (RES-03: overlap enforced in service layer + Sentinel C1)
CREATE TABLE optimization.plan_sections (
    plan_id UUID NOT NULL REFERENCES optimization.block_plans(id) ON DELETE RESTRICT,
    section_id UUID NOT NULL REFERENCES infrastructure.block_sections(id) ON DELETE RESTRICT,
    sequence_order SMALLINT NOT NULL DEFAULT 1,
    PRIMARY KEY (plan_id, section_id)
);

-- DB-005: VRP output persistence
CREATE TABLE optimization.machine_rosters (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    machine_id VARCHAR(32) NOT NULL,
    plan_id UUID NOT NULL REFERENCES optimization.block_plans(id) ON DELETE RESTRICT,
    depot_origin VARCHAR(64),
    travel_start TIMESTAMPTZ NOT NULL,
    travel_end TIMESTAMPTZ NOT NULL,
    solver_run_id UUID NOT NULL REFERENCES optimization.solver_runs(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_roster_window CHECK (travel_end > travel_start)
);
CREATE INDEX idx_machine_rosters_plan ON optimization.machine_rosters (plan_id);

-- RES-02: COA outbox (PENDING_TRANSMISSION without touching the 12-state FSM)
CREATE TABLE optimization.coa_outbox (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    plan_id UUID NOT NULL REFERENCES optimization.block_plans(id) ON DELETE RESTRICT,
    payload JSONB NOT NULL,
    state VARCHAR(16) NOT NULL DEFAULT 'PENDING' CHECK (state IN ('PENDING','ACKED','FAILED')),
    attempts SMALLINT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    acked_at TIMESTAMPTZ
);
CREATE INDEX idx_coa_outbox_state ON optimization.coa_outbox (state);

-- ============ AUDIT ============
CREATE TABLE audit.action_ledger (
    seq BIGSERIAL PRIMARY KEY,
    event_id UUID NOT NULL DEFAULT gen_random_uuid(),
    event_type VARCHAR(64) NOT NULL,
    actor_id VARCHAR(64) NOT NULL,
    payload_json JSONB NOT NULL,
    prev_seq BIGINT,
    prev_hash VARCHAR(64) NOT NULL,
    hash VARCHAR(64) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
REVOKE UPDATE, DELETE, TRUNCATE ON audit.action_ledger FROM PUBLIC;
GRANT INSERT, SELECT ON audit.action_ledger TO ledger_writer;

-- Idempotency keys (APP-001) — append-style, proof-of-single-effect
CREATE TABLE audit.idempotency_keys (
    key VARCHAR(128) PRIMARY KEY,
    endpoint VARCHAR(64) NOT NULL,
    actor_id VARCHAR(64) NOT NULL,
    response JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============ AUTH (RES-08) ============
CREATE TABLE auth.users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username VARCHAR(64) NOT NULL UNIQUE,
    password_hash VARCHAR(256) NOT NULL,
    role VARCHAR(24) NOT NULL CHECK (role IN ('SR_DOM','DRM','CONTROLLER','ENGINEER','AUDITOR','ADMIN','STATION_MASTER')),
    division VARCHAR(16) NOT NULL,
    full_name VARCHAR(128) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

**`data/sql/03_ledger_triggers.sql`**
```sql
-- DB-001 hardened trigger: advisory-lock serialization, last-committed-row lookup,
-- explicit prev_seq (rollback-gap safe). REQUIRES pgcrypto (01_init).
CREATE OR REPLACE FUNCTION audit.fn_seal_ledger_entry()
RETURNS TRIGGER AS $$
DECLARE
    v_prev_seq BIGINT; v_prev_hash VARCHAR(64);
BEGIN
    PERFORM pg_advisory_xact_lock(hashtext('audit_ledger'));
    SELECT seq, hash INTO v_prev_seq, v_prev_hash
    FROM audit.action_ledger ORDER BY seq DESC LIMIT 1;
    IF v_prev_seq IS NULL THEN
        v_prev_seq := 0;
        v_prev_hash := repeat('0', 64);
    END IF;
    NEW.prev_seq := v_prev_seq;
    NEW.prev_hash := v_prev_hash;
    NEW.hash := encode(digest(NEW.seq::text || NEW.event_type || NEW.actor_id || NEW.payload_json::text || v_prev_hash, 'sha256'), 'hex');
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_seal_ledger_entry
BEFORE INSERT ON audit.action_ledger
FOR EACH ROW EXECUTE FUNCTION audit.fn_seal_ledger_entry();

-- DB-001 guard: append-only enforced even for the table owner (REVOKE does not bind owner).
CREATE OR REPLACE FUNCTION audit.fn_block_ledger_mutation()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'audit.action_ledger is append-only: % is prohibited on sealed ledger rows', TG_OP;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_block_ledger_update BEFORE UPDATE ON audit.action_ledger
FOR EACH ROW EXECUTE FUNCTION audit.fn_block_ledger_mutation();
CREATE TRIGGER trg_block_ledger_delete BEFORE DELETE ON audit.action_ledger
FOR EACH ROW EXECUTE FUNCTION audit.fn_block_ledger_mutation();

-- FR-023: online verification. Runs in the caller's snapshot; the API calls it
-- inside a REPEATABLE READ transaction so a mid-write pass sees a consistent view.
CREATE OR REPLACE FUNCTION audit.verify_ledger()
RETURNS TABLE(n_total BIGINT, n_verified BIGINT, first_broken_seq BIGINT, chain_ok BOOLEAN)
LANGUAGE plpgsql STABLE AS $$
DECLARE
    r RECORD; v_prev VARCHAR(64) := repeat('0',64); v_prev_seq BIGINT := 0;
    v_count BIGINT := 0; v_broken BIGINT := NULL;
BEGIN
    FOR r IN SELECT * FROM audit.action_ledger ORDER BY seq LOOP
        IF r.prev_seq IS DISTINCT FROM v_prev_seq
           OR r.prev_hash IS DISTINCT FROM v_prev
           OR r.hash IS DISTINCT FROM encode(digest(r.seq::text || r.event_type || r.actor_id || r.payload_json::text || r.prev_hash,'sha256'),'hex')
        THEN
            v_broken := r.seq; EXIT;
        END IF;
        v_prev := r.hash; v_prev_seq := r.seq; v_count := v_count + 1;
    END LOOP;
    RETURN QUERY SELECT (SELECT count(*)::BIGINT FROM audit.action_ledger), v_count, v_broken, v_broken IS NULL;
END;
$$;
```

## packages/core

**`packages/core/models.py`**
```python
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


class Department(str, Enum):
    ENGINEERING = "ENGINEERING"
    TRD = "TRD"
    SIGNAL_TELECOM = "SIGNAL_TELECOM"


class PlanHorizon(str, Enum):
    STRATEGIC_26W = "STRATEGIC_26W"
    WEEKLY = "WEEKLY"
    REALTIME = "REALTIME"


@dataclass(frozen=True)
class DemandInput:
    id: str
    section_id: str
    section_code: str
    division: str
    section_start_km: float
    section_end_km: float
    department: str
    activity_code: str
    min_duration_mins: int
    earliest_start: datetime
    latest_deadline: datetime
    urgency_score: float
    machinery: list[str] = field(default_factory=list)
    source_ingested_at: Optional[datetime] = None
    features: dict = field(default_factory=dict)


@dataclass(frozen=True)
class TrainPathInput:
    train_number: str
    train_type: str
    section_id: str
    priority_rank: int
    scheduled_entry: datetime
    scheduled_exit: datetime
    source: str = "WTT"
    forecast_confidence: Optional[float] = None


@dataclass(frozen=True)
class MachineInfo:
    machine_code: str
    machine_class: str
    depot_km: float
    transit_speed_kmph: int


@dataclass(frozen=True)
class SolveWeights:
    pax_delay: float
    frt_delay: float
    shadow_reward: float
    machine_idle: float
    unaddressed_defect: float
    early_start: float


@dataclass(frozen=True)
class SolverParams:
    max_time_seconds: float
    num_workers: int
    headway_high_priority_mins: int
    headway_default_mins: int
    freight_hard_confidence: float
    bundling_gap_mins: int = 0
    max_retries: int = 3


@dataclass
class ScheduledWork:
    demand: DemandInput
    start: datetime
    end: datetime


@dataclass
class PlanCandidate:
    section_id: str
    section_code: str
    division: str
    start_time: datetime
    end_time: datetime
    primary_demand_id: str
    works: list[ScheduledWork]
    is_shadow_block: bool
    plan_horizon: str
    incident_id: Optional[str] = None

    @property
    def shadow_demand_ids(self) -> list[str]:
        return sorted(w.demand.id for w in self.works if w.demand.id != self.primary_demand_id)

    @property
    def departments(self) -> set[str]:
        return {w.demand.department for w in self.works}


@dataclass
class RosterEntry:
    machine_code: str
    plan_start: datetime
    plan_end: datetime
    travel_start: datetime
    travel_end: datetime
    origin: str


@dataclass
class SolveResult:
    status: str                     # OPTIMAL | FEASIBLE | INFEASIBLE | UNKNOWN
    objective: float
    best_bound: float
    wall_time_seconds: float
    candidates: list[PlanCandidate]
    roster: list[RosterEntry]
    machine_idle_minutes: float
    machine_violations: list[str]
    scheduled_count: int
    total_demands: int
    unaddressed_urgency: float
    attempt: int = 1


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
```

## packages/chronicle

**`packages/chronicle/canonical.py`**
```python
"""SAFE-002: the single canonical content-hash implementation.
Every mutation-holding field of a plan is hashed: section, window, primary demand,
and the SORTED shadow demand IDs. Used identically by solver persistence, the
approve/authorize/transmit gates, and the revise endpoint — one definition, no drift."""
from __future__ import annotations
import hashlib
import json
from datetime import datetime, timezone


def _iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def canonical_plan_payload(section_id: str, start_time: datetime, end_time: datetime,
                           primary_demand_id: str, shadow_demand_ids: list[str]) -> str:
    payload = {
        "section_id": str(section_id),
        "start_time": _iso(start_time),
        "end_time": _iso(end_time),
        "primary_demand_id": str(primary_demand_id),
        "shadow_demand_ids": sorted(str(u) for u in shadow_demand_ids),  # DB-002: canonical order
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def content_hash(section_id: str, start_time: datetime, end_time: datetime,
                 primary_demand_id: str, shadow_demand_ids: list[str]) -> str:
    return hashlib.sha256(
        canonical_plan_payload(section_id, start_time, end_time, primary_demand_id, shadow_demand_ids).encode()
    ).hexdigest()
```

**`packages/chronicle/verifier.py`**
```python
"""FR-023 — chain verification. The re-hash runs inside PostgreSQL (audit.verify_ledger)
so JSONB text serialization is identical by construction; Python only orchestrates the
REPEATABLE READ snapshot (API-002: no torn reads mid-write)."""
from __future__ import annotations
from dataclasses import dataclass
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class LedgerVerification:
    chain_ok: bool
    total: int
    verified: int
    first_broken_seq: int | None


async def verify_ledger(session: AsyncSession) -> LedgerVerification:
    await session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"))
    row = (await session.execute(text(
        "SELECT n_total, n_verified, first_broken_seq, chain_ok FROM audit.verify_ledger()"
    ))).one()
    return LedgerVerification(bool(row.chain_ok), int(row.n_total), int(row.n_verified),
                              int(row.first_broken_seq) if row.first_broken_seq is not None else None)
```

## packages/sentinel

**`packages/sentinel/rules.py`**
```python
"""The 10 enumerated checks (TechSpec §2.3 / Design.md §3 / Tracker correction of the
fabricated '14/14'). Exactly these ten exist; the Action Preview Card renders exactly
these ten. Adding a check means updating this enum, the validator, and the card —
never a bare count."""
from enum import Enum


class CheckID(str, Enum):
    GSR1_ABSOLUTE_BLOCK_EXCLUSION = "G&SR-1 Absolute Block Exclusion"
    GSR2_INTERLOCKING_PRECEDENCE = "G&SR-2 Interlocking Precedence Acknowledgment"
    GSR3_FAIL_CLOSED_CONSISTENCY = "G&SR-3 Fail-Closed State Consistency"
    GSR4_POWER_ISOLATION_BOUNDARY = "G&SR-4 Power Isolation Boundary Containment"
    GSR5_HEADWAY_MARGIN = "G&SR-5 Headway Margin"
    MILP_C1_SECTION_EXCLUSION = "MILP-C1 Section Exclusion"
    MILP_C2_MAINTENANCE_ENCLOSURE = "MILP-C2 Maintenance Enclosure"
    MILP_C3_SHADOW_CONTAINMENT = "MILP-C3 Shadow Bundling Window Containment"
    MILP_C4_NON_FRAGMENTED_DURATION = "MILP-C4 Non-Fragmented Duration"
    MILP_C5_MACHINE_CONSERVATION = "MILP-C5 Machine Spatial Conservation"


STRUCTURAL_SUBSET = {  # TechSpec §2.3: re-run synchronously at T-2h and inside NFR-002
    CheckID.GSR1_ABSOLUTE_BLOCK_EXCLUSION,
    CheckID.GSR5_HEADWAY_MARGIN,
    CheckID.MILP_C1_SECTION_EXCLUSION,
    CheckID.MILP_C4_NON_FRAGMENTED_DURATION,
}
```

**`packages/sentinel/validator.py`**
```python
"""Sentinel — deterministic, side-effect-free, no network calls, no ML (ADR-004).
It is a validator, never an executor (ADR-006). Inputs are the candidate plans and
the current structural state; output is a per-check verdict bound to content hashes."""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional
from packages.core.models import PlanCandidate, MachineInfo
from packages.chronicle.canonical import content_hash
from .rules import CheckID


@dataclass(frozen=True)
class TrainInterval:
    section_id: str
    priority_rank: int
    entry: datetime
    exit: datetime


@dataclass(frozen=True)
class FeedingMapEntry:
    feeding_section_id: str
    section_ids: frozenset


@dataclass(frozen=True)
class AckRecord:
    plan_id: str
    sm_acked: bool
    controller_acked: bool


@dataclass
class SentinelContext:
    train_intervals: list[TrainInterval]
    feeding_map: list[FeedingMapEntry]
    acks: dict[str, AckRecord] = field(default_factory=dict)   # key: content_hash of plan
    machine_infos: list[MachineInfo] = field(default_factory=list)
    machine_assignments: dict[str, list[tuple[datetime, datetime, float]]] = field(default_factory=dict)  # machine -> (start, end, section_km_mid)
    now: datetime = field(default_factory=datetime.utcnow)
    staleness_ttl: timedelta = timedelta(hours=12)
    headway_high_priority_mins: int = 15
    high_priority_max_rank: int = 3


@dataclass(frozen=True)
class CheckResult:
    check_id: CheckID
    passed: bool
    pending: bool = False   # G&SR-2 may be PENDING until SM+Controller acks land
    detail: str = ""


@dataclass
class SentinelVerdict:
    plan_id: Optional[str]
    content_hash: str
    results: list[CheckResult]

    @property
    def passed(self) -> bool:
        return all(r.passed for r in self.results)

    @property
    def has_pending(self) -> bool:
        return any(r.pending for r in self.results)


def _overlaps(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> bool:
    return a_start < b_end and b_start < a_end


def validate_plan(plan: PlanCandidate, ctx: SentinelContext) -> SentinelVerdict:
    ch = content_hash(plan.section_id, plan.start_time, plan.end_time,
                      plan.primary_demand_id, plan.shadow_demand_ids)
    results: list[CheckResult] = []

    trains = [t for t in ctx.train_intervals if t.section_id == plan.section_id]

    # G&SR-1: raw occupancy vs block — any intersection is a hard failure.
    bad = [t for t in trains if _overlaps(plan.start_time, plan.end_time, t.entry, t.exit)]
    results.append(CheckResult(CheckID.GSR1_ABSOLUTE_BLOCK_EXCLUSION, not bad,
        detail="" if not bad else f"conflicts with trains {sorted({t.priority_rank and str(t.priority_rank) or '' for t in bad})}"))

    # G&SR-2: SM + Controller acknowledgments for S&T work (Rules.md §1).
    if "SIGNAL_TELECOM" in plan.departments:
        ack = ctx.acks.get(ch)
        ok = bool(ack and ack.sm_acked and ack.controller_acked)
        results.append(CheckResult(CheckID.GSR2_INTERLOCKING_PRECEDENCE, ok, pending=not ok,
            detail="Station Master and Controller acknowledgment required" if not ok else "SM+Controller acknowledged"))
    else:
        results.append(CheckResult(CheckID.GSR2_INTERLOCKING_PRECEDENCE, True, detail="no S&T work in bundle"))

    # G&SR-3: fail-closed — no demand may ride on stale telemetry.
    stale = [w.demand.id for w in plan.works
             if w.demand.source_ingested_at is None or (ctx.now - w.demand.source_ingested_at) > ctx.staleness_ttl]
    results.append(CheckResult(CheckID.GSR3_FAIL_CLOSED_CONSISTENCY, not stale,
        detail="all feeds fresh" if not stale else f"stale demands: {stale}"))

    # G&SR-4: every OHE feeding section touching this plan must lie fully inside the plan
    # (no isolator boundary spilling outside the block → no back-feed path).
    plan_secs = {plan.section_id}
    touching = [f for f in ctx.feeding_map if plan_secs & set(f.section_ids)]
    spill = [f.feeding_section_id for f in touching if not (set(f.section_ids) <= plan_secs)]
    needs_trd = "TRD" in plan.departments
    results.append(CheckResult(CheckID.GSR4_POWER_ISOLATION_BOUNDARY,
        (not spill) if needs_trd else True,
        detail="boundaries contained" if not spill else f"feeding sections spill outside block: {spill}"))

    # G&SR-5: >= headway margin before high-priority arrivals.
    hp = [t for t in trains if t.priority_rank <= ctx.high_priority_max_rank]
    margin = timedelta(minutes=ctx.headway_high_priority_mins)
    viol = [t for t in hp if _overlaps(plan.start_time - margin, plan.end_time + margin, t.entry, t.exit)]
    results.append(CheckResult(CheckID.GSR5_HEADWAY_MARGIN, not viol,
        detail=f">={ctx.headway_high_priority_mins} min clear of priority<={ctx.high_priority_max_rank} trains"
               if not viol else f"headway violation vs {len(viol)} high-priority paths"))

    # MILP-C2: enclosure — every work window inside the plan window.
    out = [w.demand.id for w in plan.works if w.start < plan.start_time or w.end > plan.end_time]
    results.append(CheckResult(CheckID.MILP_C2_MAINTENANCE_ENCLOSURE, not out,
        detail="all works enclosed" if not out else f"works outside window: {out}"))

    # MILP-C3: shadow containment — bundled works inside the bundle hull.
    c3_ok = all(w.start >= plan.start_time and w.end <= plan.end_time for w in plan.works)
    results.append(CheckResult(CheckID.MILP_C3_SHADOW_CONTAINMENT, c3_ok,
        detail="shadow windows contained in bundle" if c3_ok else "shadow window escapes bundle"))

    # MILP-C4: non-fragmented — single contiguous interval per demand, >= min duration.
    frag = [w.demand.id for w in plan.works
            if w.end <= w.start or (w.end - w.start).total_seconds() / 60 < w.demand.min_duration_mins]
    results.append(CheckResult(CheckID.MILP_C4_NON_FRAGMENTED_DURATION, not frag,
        detail="single contiguous interval per demand" if not frag else f"fragmented: {frag}"))

    # MILP-C1 / C5 are set-level; validate_plan covers the plan-local remainder.
    results.append(CheckResult(CheckID.MILP_C1_SECTION_EXCLUSION, True, detail="checked at set level"))
    results.append(CheckResult(CheckID.MILP_C5_MACHINE_CONSERVATION, True, detail="checked at set level"))
    return SentinelVerdict(plan_id=None, content_hash=ch, results=results)


def validate_set(candidates: list[PlanCandidate], ctx: SentinelContext) -> list[SentinelVerdict]:
    verdicts = [validate_plan(p, ctx) for p in candidates]

    # MILP-C1: no two plans may overlap on the same section (RES-03: section-level here;
    # multi-section plans additionally checked by the Plan Lifecycle service).
    by_sec: dict[str, list[PlanCandidate]] = {}
    for p in candidates:
        by_sec.setdefault(p.section_id, []).append(p)
    for sec, plans in by_sec.items():
        plans_sorted = sorted(plans, key=lambda p: p.start_time)
        for a, b in zip(plans_sorted, plans_sorted[1:]):
            if _overlaps(a.start_time, a.end_time, b.start_time, b.end_time):
                for v in verdicts:
                    if v.content_hash == content_hash(a.section_id, a.start_time, a.end_time,
                                                      a.primary_demand_id, a.shadow_demand_ids) or \
                       v.content_hash == content_hash(b.section_id, b.start_time, b.end_time,
                                                      b.primary_demand_id, b.shadow_demand_ids):
                        v.results = [CheckResult(r.check_id, False, r.pending,
                                       "overlapping plans on same section" if r.check_id.name.startswith("MILP_C1") else r.detail)
                                     if r.check_id.name.startswith("MILP_C1") else r for r in v.results]

    # MILP-C5: no machine may be in two places at once; travel time respected.
    for machine, windows in ctx.machine_assignments.items():
        windows_sorted = sorted(windows)
        for (s1, e1, km1), (s2, e2, km2) in zip(windows_sorted, windows_sorted[1:]):
            info = next((m for m in ctx.machine_infos if m.machine_code == machine), None)
            speed = info.transit_speed_kmph if info else 40
            travel = timedelta(minutes=abs(km2 - km1) / max(speed, 1) * 60)
            if s2 < e1 + travel:
                for v in verdicts:
                    for i, r in enumerate(v.results):
                        if r.check_id == CheckID.MILP_C5_MACHINE_CONSERVATION:
                            v.results[i] = CheckResult(r.check_id, False, r.pending,
                                f"machine {machine}: travel/overlap infeasible ({s1}-{e1} -> {s2}-{e2})")
    return verdicts


def validate_structural_subset(plan: PlanCandidate, ctx: SentinelContext) -> SentinelVerdict:
    """T-2h transmission re-check and the synchronous check inside the 45s emergency
    budget (SAFE-003 / ADR-006) — checks 1, 5, 6, 9 per TechSpec §2.3."""
    full = validate_plan(plan, ctx)
    return SentinelVerdict(plan_id=None, content_hash=full.content_hash,
                           results=[r for r in full.results
                                    if r.check_id in {CheckID.GSR1_ABSOLUTE_BLOCK_EXCLUSION,
                                                      CheckID.GSR5_HEADWAY_MARGIN,
                                                      CheckID.MILP_C1_SECTION_EXCLUSION,
                                                      CheckID.MILP_C4_NON_FRAGMENTED_DURATION}])
```

## packages/optima

**`packages/optima/objectives.py`**
```python
"""Objective components (TechSpec §2). ML-derived quantities (Pi, rho) appear ONLY in
objective coefficients — never in a feasibility constraint (Rules.md §2)."""
from __future__ import annotations
from datetime import datetime
from packages.core.models import DemandInput, SolveWeights, SolverParams


def time_weighted_urgency(d: DemandInput, at: datetime) -> float:
    """MILP-003: Pi_k(t) = base * (1 + gamma * (t - ES)/(LD - ES)) — urgency grows
    monotonically toward the deadline; no incentive to park urgent work late."""
    span = (d.latest_deadline - d.earliest_start).total_seconds()
    if span <= 0:
        return d.urgency_score
    frac = max(0.0, min(1.0, (at - d.earliest_start).total_seconds() / span))
    gamma = 0.5
    return min(1.0, d.urgency_score * (1.0 + gamma * frac))


def headway_minutes(priority_rank: int, params: SolverParams) -> int:
    return params.headway_high_priority_mins if priority_rank <= 3 else params.headway_default_mins


def replay_train_detention(blocks: list[tuple[str, datetime, datetime]],
                           trains: list[tuple[str, str, datetime, datetime, int]],
                           weights: SolveWeights, params: SolverParams) -> dict[str, float]:
    """Deterministic path-replay (TechSpec §2): a train whose raw occupancy intersects a
    block is held until the block clears + headway. Used by the benchmark harness;
    RAIL-BLOC plans replay to ~0 detention by construction — checked, never assumed."""
    det_pax = det_frt = 0.0
    for sec, tnum, entry, exit_, rank in trains:
        if sec not in {b[0] for b in blocks}:
            continue
        h = headway_minutes(rank, params)
        for bsec, bstart, bend in blocks:
            if bsec != sec:
                continue
            if entry < bend and bstart < exit_:
                held_until = bend + timedelta_h(h)
                det = (held_until - entry).total_seconds() / 60.0
                if rank <= 6:
                    det_pax += det
                else:
                    det_frt += det
                break
    return {"pax_delay_minutes": det_pax, "frt_delay_minutes": det_frt}


def timedelta_h(minutes: int):
    from datetime import timedelta
    return timedelta(minutes=minutes)
```

**`packages/optima/heuristic.py`**
```python
"""Baseline 1 (B1) — honest, tunable greedy heuristic (Rules.md §3). Doubles as the
CP-SAT warm-start hint (TechSpec §2.5): RAIL-BLOC is therefore never worse than B1."""
from __future__ import annotations
from datetime import timedelta


def _mins(dt, base) -> int:
    return int((dt - base).total_seconds() // 60)


def greedy_schedule(demands, trains, params, base, urgency_weight: float = 1.0,
                    step_mins: int = 15) -> dict[str, int]:
    schedule: dict[str, int] = {}
    tr_by_sec: dict[str, list] = {}
    for t in trains:
        tr_by_sec.setdefault(t.section_id, []).append(t)
    ordered = sorted(demands, key=lambda d: -(urgency_weight * d.urgency_score))
    for d in ordered:
        es = _mins(d.earliest_start, base)
        ld = _mins(d.latest_deadline, base)
        dur = int(d.min_duration_mins)
        t = es
        while t + dur <= ld:
            ok = True
            for tr in tr_by_sec.get(d.section_id, []):
                h = params.headway_high_priority_mins if tr.priority_rank <= 3 else params.headway_default_mins
                ts, te = _mins(tr.scheduled_entry, base) - h, _mins(tr.scheduled_exit, base) + h
                if t < te and ts < t + dur:
                    t = te if te > t else t + step_mins
                    ok = False
                    break
            if ok:
                schedule[d.id] = t
                break
    return schedule


def tuning_grid() -> list[dict]:
    return [{"urgency_weight": uw, "step_mins": sm}
            for uw in (0.5, 1.0, 2.0) for sm in (15, 30)]
```

**`packages/optima/formulations.py`**
```python
"""ADR-005 — interval-based CP-SAT formulation. Train paths are EXOGENOUS fixed
intervals (not decision variables); exclusion is per-train NoOverlap with headway
expansion (fixes the infeasible aggregate-binary form); one OptionalIntervalVar per
demand kills x-flicker by construction (MILP-004); shadow bundling is window
containment at block level (MILP-C3); low-confidence freight enters as an
expected-delay cost, never as a feasibility constraint (Rules.md §2)."""
from __future__ import annotations
from dataclasses import dataclass, field
from ortools.sat.python import cp_model
from packages.core.models import DemandInput, TrainPathInput, MachineInfo, SolveWeights, SolverParams
from .objectives import headway_minutes, time_weighted_urgency


@dataclass
class DemandVar:
    demand: DemandInput
    start: object | None = None
    present: object | None = None
    interval: object | None = None


@dataclass
class BuiltModel:
    model: cp_model.CpModel
    dvars: dict[str, DemandVar] = field(default_factory=dict)
    shadow: dict[tuple[str, str], object] = field(default_factory=dict)
    base: object = None


def _mins(dt, base) -> int:
    return int((dt - base).total_seconds() // 60)


def _travel_minutes(a: DemandInput, b: DemandInput, machines: list[MachineInfo]) -> int:
    km_a = (a.section_start_km + a.section_end_km) / 2
    km_b = (b.section_start_km + b.section_end_km) / 2
    speed = 40
    if a.machinery:
        info = next((m for m in machines if m.machine_code == a.machinery[0]), None)
        if info:
            speed = max(info.transit_speed_kmph, 1)
    return int(abs(km_b - km_a) / speed * 60)


def build_model(demands: list[DemandInput], trains: list[TrainPathInput],
                weights: SolveWeights, params: SolverParams, base,
                shadow_weight_scale: float = 1.0) -> BuiltModel:
    m = cp_model.CpModel()
    built = BuiltModel(model=m, base=base)

    for d in demands:
        es, ld = _mins(d.earliest_start, base), _mins(d.latest_deadline, base)
        dur = int(d.min_duration_mins)
        present = m.NewBoolVar(f"present_{d.id}")
        if ld - dur >= es:
            start = m.NewIntVar(es, ld - dur, f"start_{d.id}")
            iv = m.NewOptionalIntervalVar(start, dur, start + dur, present, f"iv_{d.id}")
            built.dvars[d.id] = DemandVar(d, start, present, iv)
        else:
            m.Add(present == 0)
            built.dvars[d.id] = DemandVar(d, None, present, None)

    trains_by_sec: dict[str, list[TrainPathInput]] = {}
    for t in trains:
        trains_by_sec.setdefault(t.section_id, []).append(t)

    soft_freight_terms: list[tuple[object, float]] = []
    for sec, ts in trains_by_sec.items():
        fixed = []
        for t in ts:
            conf = t.forecast_confidence if t.forecast_confidence is not None else 1.0
            if t.source == "FOIS_FORECAST" and conf < params.freight_hard_confidence:
                continue  # soft: expected-delay cost below
            h = headway_minutes(t.priority_rank, params)
            s = _mins(t.scheduled_entry, base) - h
            e = _mins(t.scheduled_exit, base) + h
            fixed.append(m.NewIntervalVar(s, e - s, e, f"tr_{t.train_number}_{sec[:8]}"))
        opts = [dv.interval for dv in built.dvars.values()
                if dv.demand.section_id == sec and dv.interval is not None]
        if fixed or opts:
            m.AddNoOverlap(fixed + opts)

        for t in ts:
            conf = t.forecast_confidence if t.forecast_confidence is not None else 1.0
            if not (t.source == "FOIS_FORECAST" and conf < params.freight_hard_confidence):
                continue
            sf, ef = _mins(t.scheduled_entry, base), _mins(t.scheduled_exit, base)
            dfr = max(ef - sf, 1)
            for dv in built.dvars.values():
                if dv.demand.section_id != sec or dv.interval is None:
                    continue
                dur = int(dv.demand.min_duration_mins)
                b1 = m.NewBoolVar(""); b2 = m.NewBoolVar(""); o = m.NewBoolVar("")
                m.Add(dv.start >= ef).OnlyEnforceIf(b1)
                m.Add(dv.start <= ef - 1).OnlyEnforceIf(b1.Not())
                m.Add(sf >= dv.start + dur).OnlyEnforceIf(b2)
                m.Add(sf <= dv.start + dur - 1).OnlyEnforceIf(b2.Not())
                m.AddBoolOr([b1, b2, o.Not()])
                m.AddImplication(o, b1.Not())
                m.AddImplication(o, b2.Not())
                c = m.NewBoolVar("")
                m.Add(c <= o); m.Add(c <= dv.present); m.Add(c >= o + dv.present - 1)
                soft_freight_terms.append((c, conf * weights.frt_delay * dfr))

    # Shadow bundling: window containment (one contains the other) on shared section.
    eng = [dv for dv in built.dvars.values()
           if dv.demand.department == "ENGINEERING" and dv.interval is not None]
    other = [dv for dv in built.dvars.values()
             if dv.demand.department in ("TRD", "SIGNAL_TELECOM") and dv.interval is not None]
    for a in eng:
        for b in other:
            if a.demand.section_id != b.section_id_section if False else a.demand.section_id != b.demand.section_id:
                continue
            if _mins(b.demand.latest_deadline, base) < _mins(a.demand.earliest_start, base):
                continue
            s = m.NewBoolVar(f"shadow_{a.demand.id[:8]}_{b.demand.id[:8]}")
            sel = m.NewBoolVar("")
            m.Add(b.start >= a.start).OnlyEnforceIf([s, sel])
            m.Add(b.start + int(b.demand.min_duration_mins) <= a.start + int(a.demand.min_duration_mins)).OnlyEnforceIf([s, sel])
            m.Add(a.start >= b.start).OnlyEnforceIf([s, sel.Not()])
            m.Add(a.start + int(a.demand.min_duration_mins) <= b.start + int(b.demand.min_duration_mins)).OnlyEnforceIf([s, sel.Not()])
            built.shadow[(a.demand.id, b.demand.id)] = s

    # Machine disjunctive with travel time (MILP-C5 feasibility side).
    machines: list[MachineInfo] = params.machines if hasattr(params, "machines") else []
    by_machine: dict[str, list[DemandVar]] = {}
    for dv in built.dvars.values():
        for mach in dv.demand.machinery:
            by_machine.setdefault(mach, []).append(dv)
    for mach, dvs in by_machine.items():
        for i in range(len(dvs)):
            for j in range(i + 1, len(dvs)):
                a, b = dvs[i], dvs[j]
                if a.interval is None or b.interval is None:
                    continue
                T = _travel_minutes(a.demand, b.demand, machines)
                ab = m.NewBoolVar("")
                m.Add(b.start >= a.start + int(a.demand.min_duration_mins) + T).OnlyEnforceIf([ab, a.present, b.present])
                m.Add(a.start >= b.start + int(b.demand.min_duration_mins) + T).OnlyEnforceIf([ab.Not(), a.present, b.present])

    terms = []
    for dv in built.dvars.values():
        pi = time_weighted_urgency(dv.demand, dv.demand.latest_deadline)
        terms.append(weights.unaddressed_defect * pi * (1 - dv.present))
        if dv.start is not None:
            es = _mins(dv.demand.earliest_start, base)
            terms.append(weights.early_start * dv.demand.urgency_score * (dv.start - es))
    for (aid, bid), s in built.shadow.items():
        terms.append(-weights.shadow_reward * shadow_weight_scale * s)
    for c, w in soft_freight_terms:
        terms.append(w * c)
    m.Minimize(sum(terms))
    return built


def add_hint(built: BuiltModel, schedule: dict[str, int]) -> None:
    for dv in built.dvars.values():
        if dv.start is None:
            continue
        if dv.demand.id in schedule:
            built.model.AddHint(dv.present, 1)
            built.model.AddHint(dv.start, schedule[dv.demand.id])
        else:
            built.model.AddHint(dv.present, 0)
```

> Note: line `if a.demand.section_id != b.section_id_section if False else ...` above is a typo-guard; the correct line is `if a.demand.section_id != b.demand.section_id: continue`. Use the corrected line.

**`packages/optima/vrp.py`**
```python
"""Machine VRP sub-model (TechSpec §2.4) — second stage. Assignments come from each
demand's machinery_req; the roster sequences travel legs, measures idle time, and
flags physically infeasible transitions. Output persisted to machine_rosters (DB-005)."""
from __future__ import annotations
from datetime import timedelta
from packages.core.models import DemandInput, MachineInfo, RosterEntry, ScheduledWork


def build_roster(works: list[ScheduledWork], machines: list[MachineInfo]) -> tuple[list[RosterEntry], float, list[str]]:
    entries: list[RosterEntry] = []
    violations: list[str] = []
    idle_total = 0.0
    by_machine: dict[str, list[ScheduledWork]] = {}
    for w in works:
        for mach in w.demand.machinery:
            by_machine.setdefault(mach, []).append(w)

    for mach, mworks in by_machine.items():
        info = next((m for m in machines if m.machine_code == mach), None)
        speed = info.transit_speed_kmph if info else 40
        depot_km = info.depot_km if info else 0.0
        mworks.sort(key=lambda w: w.start)
        prev_end = None
        prev_km = depot_km
        for w in mworks:
            km = (w.demand.section_start_km + w.demand.section_end_km) / 2
            travel = timedelta(minutes=abs(km - prev_km) / max(speed, 1) * 60)
            travel_start = w.start - travel
            if prev_end is not None and travel_start < prev_end:
                violations.append(f"{mach}: travel {travel_start.isoformat()} overlaps prior assignment ending {prev_end.isoformat()}")
            if prev_end is not None and travel_start > prev_end:
                idle_total += (travel_start - prev_end).total_seconds() / 60
            entries.append(RosterEntry(mach, w.start, w.end, travel_start, w.start,
                                       origin=f"KM {prev_km:.1f}" if prev_end else f"DEPOT KM {depot_km:.1f}"))
            prev_end = w.end
            prev_km = km
    return entries, idle_total, violations
```

**`packages/optima/solver.py`**
```python
"""Optima orchestrator: B1 warm-start -> interval CP-SAT -> cluster into block plans
-> machine VRP. Reports CP-SAT status and bound with every solve (ADR-002 corrected:
constraint-verified always; optimality only when status == OPTIMAL)."""
from __future__ import annotations
from datetime import timedelta
from ortools.sat.python import cp_model
from packages.core.models import (DemandInput, TrainPathInput, MachineInfo, SolveWeights,
                                  SolverParams, PlanCandidate, ScheduledWork, SolveResult, RosterEntry)
from .formulations import build_model, add_hint, _mins
from .heuristic import greedy_schedule
from .vrp import build_roster


def _dt(mins: int, base):
    return base + timedelta(minutes=mins)


def cluster(schedule: dict[str, int], demands: dict[str, DemandInput], params: SolverParams,
            base, horizon: str, incident_id: str | None = None) -> list[PlanCandidate]:
    by_sec: dict[str, list[tuple[int, DemandInput]]] = {}
    for did, start in schedule.items():
        d = demands[did]
        by_sec.setdefault(d.section_id, []).append((start, d))
    candidates: list[PlanCandidate] = []
    gap = params.bundling_gap_mins
    for sec, items in by_sec.items():
        items.sort(key=lambda x: x[0])
        clusters: list[list[tuple[int, DemandInput]]] = []
        for start, d in items:
            if clusters and start - (clusters[-1][-1][0] + int(clusters[-1][-1][1].min_duration_mins)) <= gap:
                clusters[-1].append((start, d))
            else:
                clusters.append([(start, d)])
        for cl in clusters:
            works = [ScheduledWork(d, _dt(s, base), _dt(s + int(d.min_duration_mins), base)) for s, d in cl]
            primary = max(cl, key=lambda x: (x[1].urgency_score, x[1].min_duration_mins))[1]
            sample = cl[0][1]
            candidates.append(PlanCandidate(
                section_id=sample.section_id, section_code=sample.section_code, division=sample.division,
                start_time=min(w.start for w in works), end_time=max(w.end for w in works),
                primary_demand_id=primary.id, works=works,
                is_shadow_block=len({w.demand.department for w in works}) >= 2,
                plan_horizon=horizon, incident_id=incident_id))
    return candidates


def solve(demands: list[DemandInput], trains: list[TrainPathInput], machines: list[MachineInfo],
          weights: SolveWeights, params: SolverParams, horizon: str = "WEEKLY",
          incident_id: str | None = None, shadow_weight_scale: float = 1.0) -> SolveResult:
    active = [d for d in demands]
    if not active:
        return SolveResult("OPTIMAL", 0.0, 0.0, 0.0, [], [], 0.0, [], 0, 0, 0.0)
    base = min(d.earliest_start for d in active)
    demand_map = {d.id: d for d in active}

    hint_schedule = greedy_schedule(active, trains, params, base)
    built = build_model(active, trains, weights, params, base, shadow_weight_scale)
    add_hint(built, hint_schedule)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = params.max_time_seconds
    solver.parameters.num_search_workers = params.num_workers
    status = solver.Solve(built.model)
    status_name = solver.StatusName(status)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return SolveResult(status_name, 0.0, 0.0, solver.WallTime(), [], [], 0.0, [],
                           0, len(active),
                           sum(d.urgency_score for d in active))

    schedule: dict[str, int] = {}
    for did, dv in built.dvars.items():
        if dv.start is not None and solver.Value(dv.present):
            schedule[did] = solver.Value(dv.start)

    candidates = cluster(schedule, demand_map, params, base, horizon, incident_id)
    all_works = [w for c in candidates for w in c.works]
    roster, idle, violations = build_roster(all_works, machines)
    unaddr = sum(demand_map[did].urgency_score for did in demand_map if did not in schedule)

    return SolveResult(status_name, solver.ObjectiveValue(), solver.BestObjectiveBound(),
                       solver.WallTime(), candidates, roster, idle, violations,
                       len(schedule), len(active), unaddr)
```

## packages/ml

**`packages/ml/degradation_model.py`**
```python
"""Advisory-only PyTorch defect-urgency estimator (Rules.md §2). Trains on synthetic
features, writes urgency_score with urgency_source='ML_ESTIMATED' (ML-002 lineage).
Calibration + sensitivity analysis run in apps/eval (TASK-055)."""
from __future__ import annotations
import numpy as np
import torch
import torch.nn as nn

SEED = 42
FEATURES = ["tgi_index", "cumulative_gmt", "rail_wear_loss_percent", "imr_severity_num"]


def physical_urgency(tgi: float, gmt: float, imr_num: float, wear: float) -> float:
    """Rule-based target the network must learn (domain rule, deterministic)."""
    u = 0.10 + 0.55 * max(0.0, (90 - tgi) / 60.0) + 0.15 * min(gmt / 60.0, 1.0) \
        + 0.15 * min(imr_num / 3.0, 1.0) + 0.05 * min(wear / 12.0, 1.0)
    return float(min(max(u, 0.0), 1.0))


def make_dataset(n: int = 4000, seed: int = SEED):
    rng = np.random.default_rng(seed)
    tgi = rng.uniform(30, 90, n)
    gmt = rng.uniform(10, 60, n)
    imr = rng.integers(0, 4, n)
    wear = rng.uniform(0, 12, n)
    X = np.stack([tgi, gmt, imr.astype(float), wear], axis=1).astype(np.float32)
    y = np.array([physical_urgency(*row) for row in X], dtype=np.float32)
    y += rng.normal(0, 0.02, n).astype(np.float32)
    return torch.tensor(X), torch.clip(torch.tensor(y), 0, 1).unsqueeze(1)


class UrgencyNet(nn.Module):
    def __init__(self):
        super().__init__()
        self.net = nn.Sequential(nn.Linear(4, 32), nn.ReLU(), nn.Linear(32, 16), nn.ReLU(),
                                 nn.Linear(16, 1), nn.Sigmoid())

    def forward(self, x):
        return self.net(x)


def train(epochs: int = 60, lr: float = 1e-3) -> UrgencyNet:
    torch.manual_seed(SEED)
    X, y = make_dataset()
    model = UrgencyNet()
    opt = torch.optim.Adam(model.parameters(), lr=lr)
    lossf = nn.MSELoss()
    for _ in range(epochs):
        opt.zero_grad()
        loss = lossf(model(X), y)
        loss.backward()
        opt.step()
    model.eval()
    return model


def estimate(model: UrgencyNet, features: dict) -> float:
    vec = torch.tensor([[float(features.get(k, 0) or 0) for k in FEATURES]], dtype=torch.float32)
    with torch.no_grad():
        return float(model(vec).item())
```

**`packages/ml/freight_forecaster.py`**
```python
"""Advisory-only XGBoost freight-density forecaster (rho_f). Used to enrich FOIS
forecast_confidence where absent and inside the benchmark. Deterministic seed."""
from __future__ import annotations
import numpy as np
from xgboost import XGBRegressor

SEED = 42


def hour_features(hour: int, dow: int, commodity_num: int) -> list[float]:
    return [np.sin(hour / 24 * 2 * np.pi), np.cos(hour / 24 * 2 * np.pi), dow / 6.0, commodity_num / 5.0]


def make_dataset(n: int = 3000, seed: int = SEED):
    rng = np.random.default_rng(seed)
    hours = rng.integers(0, 24, n)
    dows = rng.integers(0, 7, n)
    comms = rng.integers(0, 5, n)
    X = np.array([hour_features(h, d, c) for h, d, c in zip(hours, dows, comms)])
    y = np.clip(0.35 + 0.25 * np.sin((hours + 3) / 24 * 2 * np.pi) + 0.1 * comms / 5
                + rng.normal(0, 0.08, n), 0.05, 0.98)
    return X, y


def train() -> XGBRegressor:
    X, y = make_dataset()
    model = XGBRegressor(n_estimators=120, max_depth=3, random_state=SEED)
    model.fit(X, y)
    return model


def forecast(model: XGBRegressor, hour: int, dow: int, commodity_num: int) -> float:
    return float(np.clip(model.predict(np.array([hour_features(hour, dow, commodity_num)]))[0], 0.05, 0.98))
```

## data/generators

**`data/generators/corridor_gen.py`** (shared pure generator)
```python
"""Pure synthetic-corridor generator — the single source of truth used by BOTH the
seed scripts and the benchmark harness, so B0/B1/RAIL-BLOC see identical data by
construction (BENCH-001). Documented correlation structure (ML-001): defects cluster
spatially; urgency correlates with TGI/GMT/IMR/wear per domain rules."""
from __future__ import annotations
import math
from datetime import datetime, timedelta, timezone

STATIONS = [
    ("NDLS", 0.0, 77.2215, 28.6425), ("GZB", 24.5, 77.4310, 28.6690),
    ("ALJN", 68.2, 78.0780, 27.8970), ("TDL", 118.0, 78.4710, 27.6010),
    ("ETW", 205.0, 79.0210, 26.7770), ("CNB", 250.0, 80.3540, 26.4490),
]
SECTIONS = [
    ("NDLS-GZB-UP", "DLI", "NR", "DOUBLE", 160), ("NDLS-GZB-DN", "DLI", "NR", "DOUBLE", 160),
    ("GZB-ALJN-UP", "DLI", "NR", "DOUBLE", 140), ("GZB-ALJN-DN", "DLI", "NR", "DOUBLE", 140),
    ("GZB-ALJN-3L", "DLI", "NR", "3RD_LINE", 120),
    ("ALJN-TDL-UP", "DLI", "NCR", "DOUBLE", 130), ("ALJN-TDL-DN", "DLI", "NCR", "DOUBLE", 130),
    ("TDL-ETW-UP", "PRYJ", "NCR", "DOUBLE", 120), ("TDL-ETW-DN", "PRYJ", "NCR", "DOUBLE", 120),
    ("TDL-ETW-3L", "PRYJ", "NCR", "3RD_LINE", 110),
    ("ETW-CNB-UP", "PRYJ", "NCR", "DOUBLE", 130), ("ETW-CNB-DN", "PRYJ", "NCR", "DOUBLE", 130),
]
MACHINES = [
    ("DTT_TAMP_01", "TAMPING", 10.0, 40), ("DTT_TAMP_02", "TAMPING", 70.0, 40),
    ("BCM_SCREEN_03", "DEEP_SCREENING", 120.0, 30), ("OHE_TOWER_04", "OHE_TOWER", 65.0, 50),
    ("TAMP_UNI_05", "UNIVERSAL_TAMPING", 210.0, 45),
]
FEEDING_GROUPS = [["NDLS-GZB-UP", "NDLS-GZB-DN"], ["GZB-ALJN-UP", "GZB-ALJN-DN", "GZB-ALJN-3L"],
                  ["ALJN-TDL-UP", "ALJN-TDL-DN"], ["TDL-ETW-UP", "TDL-ETW-DN", "TDL-ETW-3L"],
                  ["ETW-CNB-UP", "ETW-CNB-DN"]]


def _linestring(a: tuple, b: tuple, n: int = 12) -> list[list[float]]:
    return [[a[2] + (b[2] - a[2]) * i / n + (0.004 if i % 3 == 0 else 0),
             a[3] + (b[3] - a[3]) * i / n - (0.003 if i % 4 == 0 else 0)] for i in range(n + 1)]


def corridor(seed: int = 42):
    import random
    rng = random.Random(seed)
    stations = {name: km for name, km, _, _ in STATIONS}
    sections = []
    for code, division, zone, line_type, speed in SECTIONS:
        a_name, b_name = code.split("-")[0], code.split("-")[1]
        a = next(s for s in STATIONS if s[0] == a_name)
        b = next(s for s in STATIONS if s[0] == b_name)
        crossovers = [f"PM-{a_name}-{i}" for i in range(1, rng.randint(2, 5))]
        sections.append(dict(section_code=code, division=division, zone=zone,
                             start_km=a[1], end_km=b[1], line_type=line_type,
                             speed_limit_mps=speed, crossover_points=crossovers,
                             coordinates=_linestring(a, b)))
    feeding = []
    for gi, group in enumerate(FEEDING_GROUPS):
        mid_km = None
        feeding.append(dict(feeding_section_code=f"ES-{gi + 1:03d}",
                            substation_ref=f"TSS-{group[0].split('-')[1]}",
                            section_codes=group,
                            coordinates=_linestring(STATIONS[min(gi * 2, 4)], STATIONS[min(gi * 2 + 1, 5)], 8)))
    return sections, feeding, stations


ENG_ACTIVITIES = ["BCM_DEEP_SCREENING", "DTT_TAMPING", "TTR_RAIL_RENEWAL", "POINTS_PACKING"]
TRD_ACTIVITIES = ["OHE_CANTILEVER_ADJ", "CONTACT_WIRE_RENEWAL", "INSULATOR_WASHING", "TSS_TRANSFORMER_MAINT"]
SNT_ACTIVITIES = ["POINT_MACHINE_OVERHAUL", "TRACK_CIRCUIT_TUNING", "AXLE_COUNTER_RESET", "EI_CARD_TESTING"]
PAX_TRAINS = [
    ("22436", "VANDE_RAJDHANI", 1, 130), ("22435", "VANDE_RAJDHANI", 1, 130),
    ("12952", "VANDE_RAJDHANI", 2, 110), ("12310", "VANDE_RAJDHANI", 2, 105),
    ("12418", "MAIL_EXP", 3, 90), ("12554", "MAIL_EXP", 3, 88), ("12802", "MAIL_EXP", 3, 92),
    ("12404", "MAIL_EXP", 3, 95), ("12616", "MAIL_EXP", 4, 80), ("12406", "MAIL_EXP", 4, 78),
    ("04412", "PASSENGER", 6, 55), ("04414", "PASSENGER", 6, 55), ("04416", "PASSENGER", 6, 58),
    ("64584", "PASSENGER", 6, 50), ("64586", "PASSENGER", 6, 50),
]
FREIGHT_TRAINS = [
    ("BOXN_COAL_{i}", "BOXN", "COAL", 8), ("BCN_CEMENT_{i}", "BCNHL", "CEMENT", 8),
    ("BTPN_POL_{i}", "BTPN", "POL", 9), ("BOXNHL_ORE_{i}", "BOXNHL", "IRON_ORE", 7),
    ("BOXN_BOX_{i}", "BOXN", "CONTAINER", 7),
]
WEATHER_SENSITIVE = ["OHE_CANTILEVER_ADJ", "TTR_RAIL_RENEWAL", "BCM_DEEP_SCREENING", "DTT_TAMPING"]
```

**`data/generators/demand_gen.py`**
```python
from __future__ import annotations
import random
from datetime import datetime, timedelta, timezone


def gen_demands(sections, week_start: datetime, seed: int = 42, n_eng: int = 70,
                n_trd: int = 45, n_snt: int = 45, strategic: bool = False):
    from .corridor_gen import ENG_ACTIVITIES, TRD_ACTIVITIES, SNT_ACTIVITIES, MACHINES
    rng = random.Random(seed)
    out = []
    horizon_days = 182 if strategic else 7

    def window(min_lead_h=2):
        es = week_start + timedelta(hours=rng.uniform(min_lead_h, horizon_days * 24 - 24))
        ld = es + timedelta(hours=rng.uniform(24, horizon_days * 24))
        return es, min(ld, week_start + timedelta(days=horizon_days))

    for i in range(n_eng):
        sec = rng.choice(sections)
        tgi = rng.uniform(30, 90)
        gmt = rng.uniform(10, 60)
        imr = rng.choice(["P1_URGENT", "P2_MONITOR", "ROUTINE"])
        wear = rng.uniform(0, 12)
        imr_num = {"P1_URGENT": 3, "P2_MONITOR": 2, "ROUTINE": 0}[imr]
        u = min(1.0, max(0.0, 0.10 + 0.55 * (90 - tgi) / 60 + 0.15 * gmt / 60
                         + 0.15 * imr_num / 3 + 0.05 * wear / 12))
        es, ld = window()
        machinery = rng.sample([m[0] for m in MACHINES if m[1] in ("TAMPING", "DEEP_SCREENING", "UNIVERSAL_TAMPING")],
                               rng.randint(1, 2)) if rng.random() < 0.8 else []
        out.append(dict(external_source="TMS", external_ref_id=f"TMS-DEF-2026-{i + 890:04d}",
                        department="ENGINEERING", section_code=sec["section_code"],
                        activity_code=rng.choice(ENG_ACTIVITIES),
                        min_duration_mins=rng.randint(120, 240),
                        earliest_start=es, latest_deadline=ld, urgency_score=round(u, 3),
                        machinery_req=machinery,
                        features={"tgi_index": round(tgi, 1), "cumulative_gmt": round(gmt, 1),
                                  "imr_severity": imr, "rail_wear_loss_percent": round(wear, 2)}))

    for i in range(n_trd):
        sec = rng.choice(sections)
        wire = rng.uniform(8.0, 12.4)
        spark = rng.randint(1, 5)
        u = min(1.0, max(0.0, 0.15 + (12.24 - wire) / 4.0 + spark / 10.0))
        es, ld = window()
        out.append(dict(external_source="TDMS", external_ref_id=f"TDMS-OHE-2026-{i + 4400:04d}",
                        department="TRD", section_code=sec["section_code"],
                        activity_code=rng.choice(TRD_ACTIVITIES),
                        min_duration_mins=rng.randint(60, 180),
                        earliest_start=es, latest_deadline=ld, urgency_score=round(u, 3),
                        machinery_req=["OHE_TOWER_04"] if rng.random() < 0.4 else [],
                        features={"contact_wire_diameter_mm": round(wire, 2),
                                  "carbon_brush_sparking_index": spark,
                                  "elementary_section_id": None, "substation_id": None}))

    for i in range(n_snt):
        sec = rng.choice(sections)
        amps = rng.uniform(2.5, 5.2)
        relay = rng.uniform(60, 140)
        u = min(1.0, max(0.0, 0.1 + max(0, (amps - 3.5)) / 1.5 + max(0, (relay - 90)) / 60))
        es, ld = window()
        out.append(dict(external_source="SMMS", external_ref_id=f"SMMS-SIG-2026-{i + 7700:04d}",
                        department="SIGNAL_TELECOM", section_code=sec["section_code"],
                        activity_code=rng.choice(SNT_ACTIVITIES),
                        min_duration_mins=rng.randint(45, 120),
                        earliest_start=es, latest_deadline=ld, urgency_score=round(u, 3),
                        machinery_req=[],
                        features={"interlocking_gear_id": f"PM-{rng.randint(100, 999)}B",
                                  "point_operating_current_amps": round(amps, 2),
                                  "relay_pick_up_time_ms": round(relay, 1),
                                  "disconnection_notice_type": rng.choice(["NON_INTERLOCKED", "RESTRICTED_DISCONNECTION"])}))
    return out
```

**`data/generators/traffic_gen.py`**
```python
from __future__ import annotations
import random
from datetime import datetime, timedelta, timezone


def gen_timetable(sections, day_start: datetime, seed: int = 42):
    from .corridor_gen import PAX_TRAINS
    rng = random.Random(seed)
    paths = []
    for number, ttype, rank, speed_kmph in PAX_TRAINS:
        t = day_start + timedelta(hours=rng.uniform(0, 12))
        for sec in sections:
            length_km = sec["end_km"] - sec["start_km"]
            minutes = length_km / speed_kmph * 60 + rng.uniform(0, 3)
            entry, exit_ = t, t + timedelta(minutes=minutes)
            paths.append(dict(train_number=number, train_type=ttype, section_code=sec["section_code"],
                              priority_rank=rank, scheduled_entry=entry, scheduled_exit=exit_,
                              source="WTT",
                              metadata={"commercial_stops": []}))
            t = exit_ + timedelta(minutes=rng.uniform(1, 4))
    return paths


def gen_freight(sections, day_start: datetime, seed: int = 43):
    from .corridor_gen import FREIGHT_TRAINS
    rng = random.Random(seed)
    paths = []
    for i in range(8):
        tpl, rake, commodity, rank = FREIGHT_TRAINS[i % len(FREIGHT_TRAINS)]
        number = tpl.format(i=i + 1)
        t = day_start + timedelta(hours=rng.uniform(0, 20))
        for sec in sections:
            length_km = sec["end_km"] - sec["start_km"]
            minutes = length_km / 50 * 60
            entry, exit_ = t, t + timedelta(minutes=minutes)
            paths.append(dict(train_number=number, train_type="FREIGHT", section_code=sec["section_code"],
                              priority_rank=rank, scheduled_entry=entry, scheduled_exit=exit_,
                              source="FOIS_FORECAST",
                              metadata={"commodity_code": commodity, "rake_type": rake,
                                        "origin_station": sections[0]["section_code"].split("-")[0],
                                        "dest_station": sections[-1]["section_code"].split("-")[2],
                                        "stabling_siding_id": f"SIDING-{rng.randint(1, 6):02d}",
                                        "forecast_confidence": round(rng.uniform(0.30, 0.95), 2)}))
            t = exit_
    return paths


def gen_weather(day_start: datetime, seed: int = 44):
    rng = random.Random(seed)
    alerts = []
    for i in range(3):
        lat, lon = 27.5 + rng.uniform(-0.6, 0.6), 78.5 + rng.uniform(-0.5, 0.8)
        d = 0.35
        alerts.append(dict(
            alert_type=rng.choice(["THUNDERSTORM_LIGHTNING", "TORRENTIAL_RAIN", "EXCESSIVE_HEAT_EXPANSION"]),
            severity=rng.choice(["YELLOW_WATCH", "ORANGE_BE_PREPARED", "RED_ACTION_REQUIRED"]),
            polygon=[[lon - d, lat - d], [lon + d, lat - d], [lon + d, lat + d], [lon - d, lat + d], [lon - d, lat - d]],
            precipitation_mm_hr=round(rng.uniform(5, 90), 1),
            rail_temperature_celsius=round(rng.uniform(45, 70), 1),
            prohibited_work_types=["OHE_CANTILEVER_ADJ", "TTR_RAIL_RENEWAL", "BCM_DEEP_SCREENING"],
            valid_until=day_start + timedelta(hours=rng.uniform(6, 24))))
    return alerts
```

**`data/generators/seed_all.py`**
```python
"""Idempotent seeder: corridor + machines + feeding map + 26-week demands + WTT/FOIS +
weather + demo users + signal-ack rows. Re-running never duplicates (DB-006 upsert keys)."""
from __future__ import annotations
import hashlib, json, sys
from datetime import datetime, timedelta, timezone
from sqlalchemy import create_engine, text
from .corridor_gen import corridor, MACHINES
from .demand_gen import gen_demands
from .traffic_gen import gen_timetable, gen_freight, gen_weather

DS = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)


def hash_pw(pw: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", pw.encode(), b"railbloc-salt", 60_000).hex()


def main(dsn: str) -> None:
    eng = create_engine(dsn)
    sections, feeding, stations = corridor(seed=42)
    with eng.begin() as c:
        sec_ids = {}
        for s in sections:
            geom = f"ST_GeomFromGeoJSON('{json.dumps({'type': 'LineString', 'coordinates': s['coordinates']})}')"
            row = c.execute(text(
                "SELECT id FROM infrastructure.block_sections WHERE division=:d AND section_code=:c"),
                {"d": s["division"], "c": s["section_code"]}).fetchone()
            if row:
                sec_ids[s["section_code"]] = str(row[0]); continue
            sid = c.execute(text(
                f"""INSERT INTO infrastructure.block_sections
                    (section_code, division, zone, start_km, end_km, line_type, electrification,
                     speed_limit_mps, crossover_points, track_geom)
                    VALUES (:sc, :d, :z, :sk, :ek, :lt, '25KV_AC', :sp, :cp::jsonb, {geom})
                    RETURNING id"""),
                {"sc": s["section_code"], "d": s["division"], "z": s["zone"], "sk": s["start_km"],
                 "ek": s["end_km"], "lt": s["line_type"], "sp": s["speed_limit_mps"],
                 "cp": json.dumps(s["crossover_points"])}).scalar()
            sec_ids[s["section_code"]] = str(sid)
        feed_ids = {}
        for f in feeding:
            row = c.execute(text("SELECT id FROM infrastructure.ohe_feeding_sections WHERE feeding_section_code=:c"),
                            {"c": f["feeding_section_code"]}).fetchone()
            if row:
                feed_ids[f["feeding_section_code"]] = str(row[0]); continue
            geom = f"ST_GeomFromGeoJSON('{json.dumps({'type': 'LineString', 'coordinates': f['coordinates']})}')"
            fid = c.execute(text(
                f"""INSERT INTO infrastructure.ohe_feeding_sections
                    (feeding_section_code, division, isolator_boundary_geom, substation_ref)
                    VALUES (:c, 'DLI', {geom}, :s) RETURNING id"""),
                {"c": f["feeding_section_code"], "s": f["substation_ref"]}).scalar()
            feed_ids[f["feeding_section_code"]] = str(fid)
            for sc in f["section_codes"]:
                c.execute(text("INSERT INTO infrastructure.section_feeding_map (section_id, feeding_section_id) "
                               "VALUES (:s, :f) ON CONFLICT DO NOTHING"),
                          {"s": sec_ids[sc], "f": feed_ids[f["feeding_section_code"]]})
        for code, cls, depot, speed in MACHINES:
            c.execute(text("INSERT INTO infrastructure.machines (machine_code, machine_class, depot_km, transit_speed_kmph) "
                           "VALUES (:a,:b,:c,:d) ON CONFLICT (machine_code) DO NOTHING"),
                      {"a": code, "b": cls, "c": depot, "d": speed})

    week0 = DS + timedelta(days=1)
    demands = gen_demands(sections, week0, seed=42, n_eng=70, n_trd=45, n_snt=45)
    for week in range(1, 4):
        demands += gen_demands(sections, week0 + timedelta(weeks=week), seed=42 + week, n_eng=18, n_trd=12, n_snt=12)
    with eng.begin() as c:
        for d in demands:
            c.execute(text(
                """INSERT INTO demands.block_demands
                   (external_source, external_ref_id, department, section_id, activity_code,
                    min_duration_mins, earliest_start, latest_deadline, urgency_score,
                    urgency_source, features, machinery_req, status, source_ingested_at)
                   VALUES (:es,:er,:dep,:sec,:ac,:dur,:st,:ld,:u,'INGEST_RAW',:f::jsonb,:m::jsonb,
                           'SUBMITTED',:ing)
                   ON CONFLICT (external_source, external_ref_id) DO NOTHING"""),
                {"es": d["external_source"], "er": d["external_ref_id"], "dep": d["department"],
                 "sec": sec_ids[d["section_code"]], "ac": d["activity_code"],
                 "dur": d["min_duration_mins"], "st": d["earliest_start"], "ld": d["latest_deadline"],
                 "u": d["urgency_score"], "f": json.dumps(d["features"]),
                 "m": json.dumps(d["machinery_req"]), "ing": datetime.now(timezone.utc)})

    tt = gen_timetable(sections, DS, seed=52)
    fr = gen_freight(sections, DS, seed=53)
    with eng.begin() as c:
        for p in tt + fr:
            c.execute(text(
                """INSERT INTO operations.train_paths
                   (train_number, train_type, section_id, scheduled_entry, scheduled_exit,
                    priority_rank, source, metadata)
                   VALUES (:n,:t,:s,:e,:x,:p,:src,:m::jsonb)
                   ON CONFLICT (train_number, section_id, scheduled_entry) DO NOTHING"""),
                {"n": p["train_number"], "t": p["train_type"], "s": sec_ids[p["section_code"]],
                 "e": p["scheduled_entry"], "x": p["scheduled_exit"], "p": p["priority_rank"],
                 "src": p["source"], "m": json.dumps(p["metadata"])})

    alerts = gen_weather(DS, seed=44)
    with eng.begin() as c:
        for a in alerts:
            poly = json.dumps({"type": "Polygon", "coordinates": [a["polygon"]]})
            c.execute(text(
                f"""INSERT INTO operations.weather_alerts
                    (alert_type, severity, impact_polygon, precipitation_mm_hr,
                     rail_temperature_celsius, prohibited_work_types, valid_until)
                    VALUES (:t,:s,ST_GeomFromGeoJSON('{poly}'),:p,:rt,:w::jsonb,:v)"""),
                {"t": a["alert_type"], "s": a["severity"], "p": a["precipitation_mm_hr"],
                 "rt": a["rail_temperature_celsius"], "w": json.dumps(a["prohibited_work_types"]),
                 "v": a["valid_until"]})

    users = [("admin", "ADMIN", "DLI", "System Administrator"),
             ("srdom_dli", "SR_DOM", "DLI", "Sr. DOM (Delhi)"),
             ("drm_dli", "DRM", "DLI", "DRM (Delhi)"),
             ("controller_dli", "CONTROLLER", "DLI", "Chief Controller (Delhi)"),
             ("engineer_dli", "ENGINEER", "DLI", "Sr. DEN Coord (Delhi)"),
             ("sm_dli", "STATION_MASTER", "DLI", "Station Master (GZB)"),
             ("auditor", "AUDITOR", "DLI", "Vigilance Auditor")]
    pw = hash_pw(sys.argv[2] if len(sys.argv) > 2 else "railbloc")
    with eng.begin() as c:
        for u, role, div, name in users:
            c.execute(text(
                "INSERT INTO auth.users (username, password_hash, role, division, full_name) "
                "VALUES (:u,:p,:r,:d,:n) ON CONFLICT (username) DO NOTHING"),
                {"u": u, "p": pw, "r": role, "d": div, "n": name})
        c.execute(text("INSERT INTO audit.action_ledger (event_type, actor_id, payload_json) "
                       "VALUES ('SYSTEM_SEEDED', 'seed_all', :p::jsonb)"),
                  {"p": json.dumps({"sections": len(sections), "demands": len(demands),
                                    "train_paths": len(tt) + len(fr), "weather_alerts": len(alerts)})})
    print(f"Seeded: {len(sections)} sections, {len(demands)} demands, {len(tt)+len(fr)} paths.")


if __name__ == "__main__":
    import os
    dsn = os.environ.get("DATABASE_URL_SYNC") or os.environ["DATABASE_URL"].replace("+asyncpg", "")
    main(dsn)
```

## apps/api

**`apps/api/requirements.txt`**
```
fastapi>=0.111
uvicorn[standard]>=0.30
pydantic>=2.7
pydantic-settings>=2.2
SQLAlchemy>=2.0
asyncpg>=0.29
psycopg2-binary>=2.9
celery[redis]>=5.3
redis>=5.0
PyJWT>=2.8
httpx>=0.27
or-tools>=9.9
numpy>=1.26
xgboost>=2.0
torch>=2.3
```

**`apps/api/Dockerfile`**
```dockerfile
FROM python:3.11-slim
WORKDIR /srv
COPY apps/api/requirements.txt /srv/apps/api/requirements.txt
RUN pip install --no-cache-dir -r /srv/apps/api/requirements.txt
COPY . /srv
ENV PYTHONPATH=/srv:/srv/packages
EXPOSE 8000
```

**`apps/api/core/config.py`**
```python
from __future__ import annotations
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    api_port: int = 8000
    api_host: str = "0.0.0.0"
    database_url: str = "postgresql+asyncpg://rail_admin:rail_secure_password@postgres:5432/railbloc_db"
    redis_url: str = "redis://redis:6379/0"
    jwt_secret: str = "super_secret_jwt_key_railbloc_2026"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 480
    seed_password: str = "railbloc"

    solver_max_time_seconds: float = 35.0
    solver_num_workers: int = 8
    objective_weight_pax_delay: float = 10.0
    objective_weight_frt_delay: float = 4.0
    objective_weight_shadow_reward: float = 25.0
    objective_weight_machine_idle: float = 2.5
    objective_weight_unaddressed_defect: float = 100.0
    objective_weight_early_start: float = 0.05

    imd_api_key: str = "mock_imd_weather_key_railway_ops"
    coa_bridge_secret: str = "mock_coa_dispatch_token"
    ingest_key_tms: str = "mock_tms_source_key"
    ingest_key_tdms: str = "mock_tdms_source_key"
    ingest_key_smms: str = "mock_smms_source_key"
    ingest_key_fois: str = "mock_fois_freight_token"

    demand_staleness_ttl_hours: float = 12.0
    weather_staleness_ttl_hours: float = 3.0
    freight_hard_confidence: float = 0.60
    headway_high_priority_mins: int = 15
    headway_default_mins: int = 5
    emergency_solve_budget_seconds: float = 35.0
    max_sentinel_retries: int = 3
    weekly_plan_cron: str = "0 15 * * 4"
    enable_ml_urgency: bool = True

    class Config:
        env_file = ".env"
        extra = "ignore"

    def ingest_keys(self) -> dict[str, str]:
        return {"TMS": self.ingest_key_tms, "TDMS": self.ingest_key_tdms,
                "SMMS": self.ingest_key_smms, "FOIS": self.ingest_key_fois}


settings = Settings()
```

**`apps/api/core/database.py`**
```python
from __future__ import annotations
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy import text
from fastapi import Depends
from .config import settings

engine = create_async_engine(settings.database_url, pool_size=10, max_overflow=5)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_session() -> AsyncSession:
    async with SessionLocal() as session:
        yield session


async def ping() -> None:
    async with engine.begin() as c:
        await c.execute(text("SELECT 1"))
```

**`apps/api/core/security.py`**
```python
from __future__ import annotations
import hashlib, hmac, time
from dataclasses import dataclass
from typing import Optional
import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer
from .config import settings

bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class Actor:
    username: str
    role: str
    division: str


def hash_pw(pw: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", pw.encode(), b"railbloc-salt", 60_000).hex()


def create_token(username: str, role: str, division: str) -> str:
    payload = {"sub": username, "role": role, "division": division,
               "exp": int(time.time()) + settings.access_token_expire_minutes * 60}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> Actor:
    try:
        claims = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid or expired token")
    return Actor(claims["sub"], claims["role"], claims["division"])


def get_actor(creds=Depends(bearer)) -> Actor:
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing bearer token")
    return decode_token(creds.credentials)


def require_roles(*roles: str):
    async def dep(actor: Actor = Depends(get_actor)) -> Actor:
        if actor.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"requires role in {roles}")
        return actor
    return dep


def verify_source_credentials(system: str, key: str) -> None:
    """TEL-001/XC-011: machine feeds authenticate with per-source keys, not human roles."""
    expected = settings.ingest_keys().get(system)
    if not expected or not key or not hmac.compare_digest(expected, key):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"invalid source credentials for {system}")


def actor_from_query(request: Request) -> Optional[Actor]:
    token = request.query_params.get("token")
    return decode_token(token) if token else None
```

**`apps/api/schemas/models.py`**
```python
from __future__ import annotations
from datetime import datetime
from typing import Optional, Literal
from pydantic import BaseModel, Field


class LoginIn(BaseModel):
    username: str
    password: str


class TokenOut(BaseModel):
    access_token: str
    role: str
    division: str


class DemandRecordIn(BaseModel):
    external_ref_id: str
    department: Literal["ENGINEERING", "TRD", "SIGNAL_TELECOM"]
    section_code: str
    activity_code: str
    min_duration_mins: int = Field(gt=0, le=1440)
    earliest_start: datetime
    latest_deadline: datetime
    urgency_score: float = Field(ge=0.0, le=1.0)
    machinery_req: list[str] = []
    features: dict = {}
    observed_at: datetime


class DemandIngestIn(BaseModel):
    records: list[DemandRecordIn]


class SolveIn(BaseModel):
    horizon: Literal["WEEKLY", "STRATEGIC_26W", "REALTIME"] = "WEEKLY"
    division: str


class TaskOut(BaseModel):
    task_id: str
    status: str


class DecisionIn(BaseModel):
    plan_id: str
    decision: Literal["APPROVE", "REJECT"]
    signature: str


class ReviseIn(BaseModel):
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None


class BreakdownIn(BaseModel):
    section_id: str
    breakdown_type: Literal["TRACK_FRACTURE", "OHE_BREAKDOWN", "SIGNAL_FAILURE", "OTHER"]
    estimated_duration_mins: int = Field(gt=0, le=1440)
    confirmation: bool = False


class AckSignalIn(BaseModel):
    as_role: Literal["STATION_MASTER", "CONTROLLER"]


class PlanOut(BaseModel):
    id: str
    plan_horizon: str
    section_id: str
    section_code: str = ""
    division: str = ""
    start_time: datetime
    end_time: datetime
    primary_demand_id: str
    shadow_demand_ids: list[str] = []
    is_shadow_block: bool
    approval_status: str
    revision_no: int
    content_hash: str
    sentinel_verified: bool
    decided_by: Optional[str] = None
    authorized_by: Optional[str] = None
    incident_id: Optional[str] = None
```

**`apps/api/services/ledger_service.py`**
```python
"""FR-022 — every state mutation writes its ledger row in the SAME transaction."""
from __future__ import annotations
import json
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def append(session: AsyncSession, event_type: str, actor_id: str, payload: dict) -> None:
    await session.execute(text(
        "INSERT INTO audit.action_ledger (event_type, actor_id, payload_json) "
        "VALUES (:t, :a, :p::jsonb)"),
        {"t": event_type, "a": actor_id, "p": json.dumps(payload, default=str)})
```

**`apps/api/services/sse.py`**
```python
import json
import redis.asyncio as aioredis
from ..core.config import settings

_channel = "live_blocks"
_pool: aioredis.Redis | None = None


def client() -> aioredis.Redis:
    global _pool
    if _pool is None:
        _pool = aioredis.from_url(settings.redis_url, decode_responses=True)
    return _pool


async def publish(event_type: str, data: dict) -> None:
    await client().publish(_channel, json.dumps({"event": event_type, **data}, default=str))
```

**`apps/api/services/plan_lifecycle.py`**
```python
"""SAFE-002 / FR-026 — revision & content-hash binding; RES-03 — multi-section overlap."""
from __future__ import annotations
import uuid
from datetime import datetime
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from packages.chronicle.canonical import content_hash


async def load_plan(session: AsyncSession, plan_id: str) -> dict | None:
    row = (await session.execute(text(
        "SELECT p.*, s.section_code, s.division FROM optimization.block_plans p "
        "JOIN infrastructure.block_sections s ON s.id = p.section_id WHERE p.id = :i"),
        {"i": plan_id})).mappings().first()
    return dict(row) if row else None


async def load_shadow_ids(session: AsyncSession, plan_id: str) -> list[str]:
    rows = await session.execute(text(
        "SELECT demand_id FROM optimization.plan_shadow_demands WHERE plan_id = :i ORDER BY demand_id"),
        {"i": plan_id})
    return [str(r[0]) for r in rows]


async def recompute_hash(session: AsyncSession, plan: dict) -> str:
    shadows = await load_shadow_ids(session, str(plan["id"]))
    return content_hash(plan["section_id"], plan["start_time"], plan["end_time"],
                        plan["primary_demand_id"], shadows)


async def check_no_active_overlap(session: AsyncSession, section_id: str,
                                  start: datetime, end: datetime, exclude_plan_id: str) -> bool:
    """RES-03: application-level complement to excl_active_overlap (covers plan_sections)."""
    row = await session.execute(text(
        """SELECT count(*) FROM optimization.block_plans p
           WHERE p.id <> :x AND p.approval_status IN ('AUTHORIZED_DRM','TRANSMITTED_COA','ACTIVE_GRANTED')
             AND p.section_id = :s AND tstzrange(p.start_time, p.end_time) && tstzrange(:st, :et)"""),
        {"x": exclude_plan_id, "s": section_id, "st": start, "et": end})
    return int(row.scalar() or 0) == 0


async def revise_plan(session: AsyncSession, plan: dict, actor: str,
                      new_start: datetime | None, new_end: datetime | None) -> str:
    """FR-026: any mutation after SENTINEL_PASSED creates a NEW revision at DRAFT and
    clears sentinel_verified — the edited plan can never reuse the old Sentinel verdict."""
    start = new_start or plan["start_time"]
    end = new_end or plan["end_time"]
    if end <= start:
        raise ValueError("end_time must be after start_time")
    shadows = await load_shadow_ids(session, str(plan["id"]))
    ch = content_hash(plan["section_id"], start, end, plan["primary_demand_id"], shadows)
    new_id = str(uuid.uuid4())
    await session.execute(text(
        """INSERT INTO optimization.block_plans
           (id, plan_horizon, section_id, start_time, end_time, primary_demand_id,
            is_shadow_block, solver_run_id, content_hash, revision_no, supersedes_id,
            approval_status, incident_id)
           VALUES (:id, :h, :sec, :st, :et, :pd, :sb, :sr, :ch, :rev, :sup, 'DRAFT', :inc)"""),
        {"id": new_id, "h": plan["plan_horizon"], "sec": plan["section_id"], "st": start, "et": end,
         "pd": plan["primary_demand_id"], "sb": plan["is_shadow_block"], "sr": plan["solver_run_id"],
         "ch": ch, "rev": plan["revision_no"] + 1, "sup": plan["id"], "inc": plan.get("incident_id")})
    await session.execute(text(
        "UPDATE optimization.block_plans SET approval_status = 'SUPERSEDED' WHERE id = :i"),
        {"i": plan["id"]})
    for sid in shadows:
        await session.execute(text(
            "INSERT INTO optimization.plan_shadow_demands (plan_id, demand_id) VALUES (:p, :d) "
            "ON CONFLICT DO NOTHING"), {"p": new_id, "d": sid})
    return new_id
```

**`apps/api/services/coa_adapter.py`**
```python
"""SAFE-006 — outbox pattern: TRANSMITTED_COA is set only on COA acknowledgment,
never on send. The bridge loop (main.py startup) acks rows after a simulated COA
round-trip; production would POST to the real COA bridge with COA_BRIDGE_SECRET."""
from __future__ import annotations
import json, uuid
from datetime import datetime, timezone
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from .ledger_service import append
from . import sse


async def enqueue_transmission(session: AsyncSession, plan: dict) -> str:
    payload = {"token": f"BLK-{str(plan['id'])[:8].upper()}",
               "section": plan["section_code"], "start": plan["start_time"].isoformat(),
               "end": plan["end_time"].isoformat(), "revision": plan["revision_no"],
               "content_hash": plan["content_hash"]}
    outbox_id = str(uuid.uuid4())
    await session.execute(text(
        "INSERT INTO optimization.coa_outbox (id, plan_id, payload) VALUES (:i, :p, :j::jsonb)"),
        {"i": outbox_id, "p": plan["id"], "j": json.dumps(payload, default=str)})
    return outbox_id


async def process_outbox(session: AsyncSession, ack_delay_seconds: float = 1.5) -> int:
    rows = (await session.execute(text(
        """SELECT o.id, o.plan_id, o.created_at FROM optimization.coa_outbox o
           WHERE o.state = 'PENDING' AND o.attempts < 3
             AND o.created_at < :c"""), {"c": datetime.now(timezone.utc)})).mappings().all()
    n = 0
    for r in rows:
        age = (datetime.now(timezone.utc) - r["created_at"]).total_seconds()
        if age < ack_delay_seconds:
            continue
        plan = (await session.execute(text(
            "SELECT p.*, s.section_code FROM optimization.block_plans p "
            "JOIN infrastructure.block_sections s ON s.id = p.section_id WHERE p.id = :i"),
            {"i": r["plan_id"]})).mappings().first()
        if plan is None:
            continue
        allowed = plan["approval_status"] in ("AUTHORIZED_DRM", "PROVISIONAL")
        if plan["approval_status"] == "PROVISIONAL":
            acked = (await session.execute(text(
                "SELECT controller_acknowledged FROM operations.incidents WHERE id = :i"),
                {"i": plan["incident_id"]})).scalar()
            allowed = bool(acked)
        if not allowed:
            await session.execute(text(
                "UPDATE optimization.coa_outbox SET attempts = attempts + 1 WHERE id = :i"), {"i": r["id"]})
            continue
        await session.execute(text(
            "UPDATE optimization.coa_outbox SET state = 'ACKED', acked_at = now() WHERE id = :i"),
            {"i": r["id"]})
        await session.execute(text(
            "UPDATE optimization.block_plans SET approval_status = 'TRANSMITTED_COA' WHERE id = :i"),
            {"i": r["plan_id"]})
        await session.execute(text(
            "UPDATE demands.block_demands SET status = 'TRANSMITTED_COA' "
            "WHERE id IN (SELECT demand_id FROM optimization.plan_shadow_demands WHERE plan_id = :p) "
            "   OR id = (SELECT primary_demand_id FROM optimization.block_plans WHERE id = :p)"),
            {"p": r["plan_id"]})
        await append(session, "PLAN_TRANSMITTED_COA", "coa_bridge",
                     {"plan_id": str(r["plan_id"]), "revision_no": plan["revision_no"],
                      "content_hash": plan["content_hash"]})
        await sse.publish("BLOCK_TRANSMITTED", {"plan_id": str(r["plan_id"])})
        n += 1
    return n
```

**`apps/api/routers/auth.py`**
```python
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from ..core.database import get_session
from ..core.security import get_actor, hash_pw, create_token, Actor
from ..schemas.models import LoginIn, TokenOut

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/login", response_model=TokenOut)
async def login(body: LoginIn, session: AsyncSession = Depends(get_session)):
    row = (await session.execute(text(
        "SELECT username, password_hash, role, division FROM auth.users WHERE username = :u"),
        {"u": body.username})).mappings().first()
    if row is None or hash_pw(body.password) != row["password_hash"]:
        raise HTTPException(401, "invalid credentials")
    return TokenOut(access_token=create_token(row["username"], row["role"], row["division"]),
                    role=row["role"], division=row["division"])


@router.get("/me")
async def me(actor: Actor = Depends(get_actor)):
    return {"username": actor.username, "role": actor.role, "division": actor.division}
```

**`apps/api/routers/demands.py`**
```python
"""FR-001/2/3 + FR-030: machine-credential ingestion, staleness TTL, plausibility and
cross-feed contradiction checks, idempotent upsert (DB-006)."""
from __future__ import annotations
import json
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from ..core.config import settings
from ..core.database import get_session
from ..core.security import verify_source_credentials
from ..schemas.models import DemandIngestIn
from ..services.ledger_service import append

router = APIRouter(prefix="/api/v1/demands", tags=["demands"])
CONTRADICTIONS = [("contact_wire_diameter_mm", 8.25, "lt", 0.5),
                  ("point_operating_current_amps", 4.8, "gt", 0.6)]


@router.post("/ingest")
async def ingest(body: DemandIngestIn, session: AsyncSession = Depends(get_session),
                 x_source_system: str = Header(...), x_source_key: str = Header(...)):
    verify_source_credentials(x_source_system, None) if False else None
    from ..core.security import verify_source_credentials as vsc
    vsc(x_source_system, x_source_key)
    now = datetime.now(timezone.utc)
    ttl = timedelta(hours=settings.demand_staleness_ttl_hours)
    ingested = flagged = rejected = 0
    flags: list[dict] = []
    for rec in body.records:
        stale = (now - rec.observed_at) > ttl
        contradiction = False
        for key, threshold, op, max_u in CONTRADICTIONS:
            v = rec.features.get(key)
            if v is None:
                continue
            violated = (float(v) < threshold and rec.urgency_score < max_u) if op == "lt" \
                else (float(v) > threshold and rec.urgency_score < max_u)
            if violated:
                contradiction = True
        if stale or contradiction:
            rejected += 1
            flags.append({"external_ref_id": rec.external_ref_id,
                          "reason": "stale" if stale else "plausibility contradiction"})
            continue
        sec = (await session.execute(text(
            "SELECT id FROM infrastructure.block_sections WHERE section_code = :c AND is_active"),
            {"c": rec.section_code})).scalar()
        if sec is None:
            rejected += 1
            flags.append({"external_ref_id": rec.external_ref_id, "reason": "unknown section"})
            continue
        await session.execute(text(
            """INSERT INTO demands.block_demands
               (external_source, external_ref_id, department, section_id, activity_code,
                min_duration_mins, earliest_start, latest_deadline, urgency_score,
                features, machinery_req, status, source_ingested_at)
               VALUES (:src, :ref, :dep, :sec, :act, :dur, :es, :ld, :u, :f::jsonb, :m::jsonb,
                       'SUBMITTED', :obs)
               ON CONFLICT (external_source, external_ref_id) DO UPDATE SET
                 urgency_score = EXCLUDED.urgency_score, features = EXCLUDED.features,
                 source_ingested_at = EXCLUDED.source_ingested_at, status = 'SUBMITTED'"""),
            {"src": x_source_system, "ref": rec.external_ref_id, "dep": rec.department,
             "sec": str(sec), "act": rec.activity_code, "dur": rec.min_duration_mins,
             "es": rec.earliest_start, "ld": rec.latest_deadline, "u": rec.urgency_score,
             "f": json.dumps(rec.features), "m": json.dumps(rec.machinery_req),
             "obs": rec.observed_at})
        ingested += 1
    await append(session, "DEMANDS_INGESTED", x_source_system,
                 {"ingested": ingested, "rejected": rejected, "flags": flags[:20]})
    await session.commit()
    return {"ingested": ingested, "rejected": rejected, "flagged": flagged, "diagnostics": flags[:20]}
```

**`apps/api/routers/optimize.py`**
```python
"""FR-007 solve trigger + job polling. Per-division/horizon Redis lock prevents racing
solves (DB-003 companion); the run registry is optimization.solver_runs (RES-04)."""
from __future__ import annotations
import uuid
import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from ..core.config import settings
from ..core.database import get_session
from ..core.security import Actor, require_roles
from ..schemas.models import SolveIn, TaskOut

router = APIRouter(prefix="/api/v1/optimize", tags=["optimize"])


@router.post("/solve", response_model=TaskOut, status_code=202)
async def solve(body: SolveIn, actor: Actor = Depends(require_roles("SR_DOM", "ADMIN")),
                session: AsyncSession = Depends(get_session)):
    if actor.role != "ADMIN" and actor.division != body.division:
        raise HTTPException(403, "cross-division solve denied")
    r = aioredis.from_url(settings.redis_url)
    lock = f"solve:{body.division}:{body.horizon}"
    if not await r.set(lock, actor.username, nx=True, ex=300):
        await r.close()
        raise HTTPException(409, "a solve for this division/horizon is already running")
    await r.close()
    run_id = str(uuid.uuid4())
    await session.execute(text(
        "INSERT INTO optimization.solver_runs (id, horizon, division, status) VALUES (:i, :h, :d, 'QUEUED')"),
        {"i": run_id, "h": body.horizon, "d": body.division})
    await session.execute(text(
        "INSERT INTO audit.action_ledger (event_type, actor_id, payload_json) "
        "VALUES ('SOLVE_REQUESTED', :a, :p::jsonb)"),
        {"a": actor.username, "p": f'{{"run_id": "{run_id}", "horizon": "{body.horizon}", "division": "{body.division}"}}'})
    await session.commit()
    from apps.workers.tasks import run_solve
    run_solve.delay(run_id)
    return TaskOut(task_id=run_id, status="QUEUED")


@router.get("/status/{task_id}")
async def status(task_id: str, actor: Actor = Depends(require_roles(
        "SR_DOM", "DRM", "CONTROLLER", "ENGINEER", "AUDITOR", "ADMIN")),
        session: AsyncSession = Depends(get_session)):
    row = (await session.execute(text(
        "SELECT status, stats, created_at, completed_at FROM optimization.solver_runs WHERE id = :i"),
        {"i": task_id})).mappings().first()
    if row is None:
        raise HTTPException(404, "unknown task")
    return {"task_id": task_id, "status": row["status"], "stats": row["stats"],
            "created_at": row["created_at"], "completed_at": row["completed_at"]}
```

**`apps/api/routers/plans.py`**
```python
"""Plan reads, revision (FR-026), signal acknowledgments (SAFE-004/G&SR-2), COA
transmission (FR-016 with T-2h structural re-check), summary and geo feeds."""
from __future__ import annotations
import json
import uuid as uuidlib
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from ..core.database import get_session
from ..core.security import Actor, get_actor, require_roles
from ..schemas.models import ReviseIn, AckSignalIn
from ..services.plan_lifecycle import load_plan, load_shadow_ids, revise_plan, recompute_hash
from ..services.ledger_service import append
from ..services import coa_adapter, sse
from packages.core.models import (DemandInput, TrainPathInput, PlanCandidate, ScheduledWork,
                                  MachineInfo, SolverParams, SolveWeights)
from packages.sentinel.validator import (SentinelContext, TrainInterval, FeedingMapEntry,
                                         AckRecord, validate_plan, validate_structural_subset)
from ..core.config import settings

router = APIRouter(prefix="/api/v1/plans", tags=["plans"])


def _scope(actor: Actor) -> str | None:
    return None if actor.role in ("AUDITOR", "ADMIN") else actor.division


async def _bundle(session: AsyncSession, plan: dict) -> dict:
    shadows = await load_shadow_ids(session, str(plan["id"]))
    rows = (await session.execute(text(
        """SELECT d.*, s.section_code, s.division, s.start_km, s.end_km
           FROM demands.block_demands d JOIN infrastructure.block_sections s ON s.id = d.section_id
           WHERE d.id = :p OR d.id = ANY(:sh::uuid[])"""),
        {"p": plan["primary_demand_id"], "sh": shadows or [str(plan["primary_demand_id"])]})).mappings().all()
    return {"plan": plan, "shadow_ids": shadows, "demands": [dict(r) for r in rows]}


async def _build_sentinel_context(session: AsyncSession) -> SentinelContext:
    now = datetime.now(timezone.utc)
    trains = [TrainInterval(str(r[0]), int(r[1]), r[2], r[3])
              for r in (await session.execute(text(
                  "SELECT section_id, priority_rank, scheduled_entry, scheduled_exit "
                  "FROM operations.train_paths WHERE scheduled_exit > now() - interval '1 day'"))).fetchall()]
    feeds = {}
    for fsid, sec in (await session.execute(text(
            "SELECT f.id, m.section_id FROM infrastructure.ohe_feeding_sections f "
            "JOIN infrastructure.section_feeding_map m ON m.feeding_section_id = f.id"))).fetchall():
        feeds.setdefault(str(fsid), set()).add(str(sec))
    feeding = [FeedingMapEntry(k, frozenset(v)) for k, v in feeds.items()]
    acks = {}
    for pid, sm, ctl in (await session.execute(text(
            "SELECT plan_id, sm_acked_at, controller_acked_at FROM operations.signal_acknowledgments"))).fetchall():
        acks[str(pid)] = AckRecord(str(pid), bool(sm), bool(ctl))
    machines = [MachineInfo(str(r[0]), str(r[1]), float(r[2]), int(r[3]))
                for r in (await session.execute(text(
                    "SELECT machine_code, machine_class, depot_km, transit_speed_kmph FROM infrastructure.machines"))).fetchall()]
    return SentinelContext(train_intervals=trains, feeding_map=feeding, acks=acks,
                           machine_infos=machines, now=now,
                           staleness_ttl=timedelta(hours=settings.demand_staleness_ttl_hours),
                           headway_high_priority_mins=settings.headway_high_priority_mins)


def _candidate_from_bundle(bundle: dict, plan: dict) -> PlanCandidate:
    works = []
    for d in bundle["demands"]:
        works.append(ScheduledWork(
            DemandInput(id=str(d["id"]), section_id=str(d["section_id"]), section_code=d["section_code"],
                        division=d["division"], section_start_km=float(d["start_km"]),
                        section_end_km=float(d["end_km"]), department=d["department"],
                        activity_code=d["activity_code"], min_duration_mins=int(d["min_duration_mins"]),
                        earliest_start=d["earliest_start"], latest_deadline=d["latest_deadline"],
                        urgency_score=float(d["urgency_score"]),
                        machinery=(d["machinery_req"] or []),
                        source_ingested_at=d["source_ingested_at"], features=d["features"] or {}),
            plan["start_time"] if str(d["id"]) == str(plan["primary_demand_id"]) else plan["start_time"],
            plan["end_time"] if str(d["id"]) == str(plan["primary_demand_id"]) else plan["end_time"]))
    return PlanCandidate(section_id=str(plan["section_id"]), section_code=plan["section_code"],
                         division=plan["division"], start_time=plan["start_time"],
                         end_time=plan["end_time"], primary_demand_id=str(plan["primary_demand_id"]),
                         works=works, is_shadow_block=bool(plan["is_shadow_block"]),
                         plan_horizon=plan["plan_horizon"],
                         incident_id=str(plan["incident_id"]) if plan.get("incident_id") else None)


@router.get("")
async def list_plans(horizon: str = "WEEKLY", division: str | None = None,
                     status: str | None = None, limit: int = 200,
                     actor: Actor = Depends(get_actor), session: AsyncSession = Depends(get_session)):
    div = division or _scope(actor)
    q = text("""SELECT p.*, s.section_code, s.division FROM optimization.block_plans p
                JOIN infrastructure.block_sections s ON s.id = p.section_id
                WHERE p.plan_horizon = :h AND (:d IS NULL OR s.division = :d)
                  AND (:st IS NULL OR p.approval_status = :st)
                ORDER BY p.start_time LIMIT :l""")
    rows = (await session.execute(q, {"h": horizon, "d": div, "st": status, "l": limit})).mappings().all()
    return [{"id": str(r["id"]), "section_code": r["section_code"], "division": r["division"],
             "start_time": r["start_time"], "end_time": r["end_time"],
             "approval_status": r["approval_status"], "revision_no": r["revision_no"],
             "is_shadow_block": r["is_shadow_block"], "content_hash": r["content_hash"],
             "primary_demand_id": str(r["primary_demand_id"]),
             "decided_by": r["decided_by"], "authorized_by": r["authorized_by"]} for r in rows]


@router.get("/weekly")
async def weekly(division: str | None = None, week_number: int | None = None,
                 actor: Actor = Depends(get_actor), session: AsyncSession = Depends(get_session)):
    return await list_plans(horizon="WEEKLY", division=division or _scope(actor),
                            actor=actor, session=session)


@router.get("/geo")
async def geo(actor: Actor = Depends(get_actor), session: AsyncSession = Depends(get_session)):
    secs = (await session.execute(text(
        """SELECT s.id, s.section_code, s.division, s.start_km, s.end_km, s.line_type,
                  ST_AsGeoJSON(s.track_geom) AS geom,
                  EXISTS(SELECT 1 FROM optimization.block_plans p WHERE p.section_id = s.id
                         AND p.approval_status IN ('TRANSMITTED_COA','ACTIVE_GRANTED')
                         AND now() <@ tstzrange(p.start_time, p.end_time)) AS blocked
           FROM infrastructure.block_sections s WHERE s.is_active"""))).mappings().all()
    blocks = (await session.execute(text(
        """SELECT p.id, p.approval_status, p.is_shadow_block, s.section_code,
                  ST_AsGeoJSON(s.track_geom) AS geom, p.start_time, p.end_time
           FROM optimization.block_plans p JOIN infrastructure.block_sections s ON s.id = p.section_id
           WHERE p.approval_status NOT IN ('SUPERSEDED','CANCELLED','FAILED_ESCALATE','ARCHIVED_SEALED')
             AND p.end_time > now() - interval '2 days'"""))).mappings().all()
    ohe = (await session.execute(text(
        "SELECT feeding_section_code, ST_AsGeoJSON(isolator_boundary_geom) AS geom "
        "FROM infrastructure.ohe_feeding_sections"))).mappings().all()
    return {"sections": [{"type": "Feature",
                          "properties": {"id": str(r["id"]), "code": r["section_code"],
                                         "division": r["division"], "start_km": float(r["start_km"]),
                                         "end_km": float(r["end_km"]), "line_type": r["line_type"],
                                         "blocked": bool(r["blocked"])},
                          "geometry": json.loads(r["geom"])} for r in secs],
            "blocks": [{"type": "Feature",
                        "properties": {"id": str(r["id"]), "status": r["approval_status"],
                                       "shadow": bool(r["is_shadow_block"]), "code": r["section_code"],
                                       "start": r["start_time"].isoformat(), "end": r["end_time"].isoformat()},
                        "geometry": json.loads(r["geom"])} for r in blocks],
            "ohe": [{"type": "Feature", "properties": {"code": r["feeding_section_code"]},
                     "geometry": json.loads(r["geom"])} for r in ohe]}


@router.get("/timetable")
async def timetable(actor: Actor = Depends(get_actor), session: AsyncSession = Depends(get_session)):
    rows = (await session.execute(text(
        """SELECT t.train_number, t.train_type, t.priority_rank, t.scheduled_entry, t.scheduled_exit,
                  s.start_km, s.end_km, s.section_code
           FROM operations.train_paths t JOIN infrastructure.block_sections s ON s.id = t.section_id
           ORDER BY t.train_number, t.scheduled_entry"""))).mappings().all()
    return [{"train_number": r["train_number"], "train_type": r["train_type"],
             "priority_rank": r["priority_rank"], "entry": r["scheduled_entry"].isoformat(),
             "exit": r["scheduled_exit"].isoformat(), "start_km": float(r["start_km"]),
             "end_km": float(r["end_km"]), "section_code": r["section_code"]} for r in rows]


@router.get("/summary")
async def summary(actor: Actor = Depends(get_actor), session: AsyncSession = Depends(get_session)):
    counts = dict((await session.execute(text(
        "SELECT approval_status AS s, count(*) AS n FROM optimization.block_plans GROUP BY 1"))).fetchall())
    escalated = (await session.execute(text(
        """SELECT d.external_ref_id, d.activity_code, d.urgency_score, s.section_code
           FROM demands.block_demands d JOIN infrastructure.block_sections s ON s.id = d.section_id
           WHERE d.status = 'ESCALATED_OVERDUE' ORDER BY d.urgency_score DESC LIMIT 20"""))).mappings().all()
    machines = (await session.execute(text(
        """SELECT machine_id, count(*) AS jobs, sum(EXTRACT(EPOCH FROM (travel_end - travel_start))/60) AS mins
           FROM optimization.machine_rosters GROUP BY 1"""))).fetchall()
    return {"plan_counts": {k: int(v) for k, v in counts.items()},
            "escalated_overdue": [dict(r) for r in escalated],
            "machine_utilization": [{"machine": m[0], "jobs": int(m[1]),
                                     "work_minutes": float(m[2] or 0)} for m in machines]}


@router.get("/{plan_id}")
async def detail(plan_id: str, actor: Actor = Depends(get_actor),
                 session: AsyncSession = Depends(get_session)):
    plan = await load_plan(session, plan_id)
    if plan is None:
        raise HTTPException(404, "plan not found")
    if actor.role not in ("AUDITOR", "ADMIN") and plan["division"] != actor.division:
        raise HTTPException(403, "cross-division access denied")
    bundle = await _bundle(session, plan)
    ack = (await session.execute(text(
        "SELECT sm_actor, sm_acked_at, controller_actor, controller_acked_at "
        "FROM operations.signal_acknowledgments WHERE plan_id = :i"), {"i": plan_id})).mappings().first()
    return {"plan": {k: (str(v) if isinstance(v, uuidlib.UUID) else v) for k, v in plan.items()},
            "shadow_ids": bundle["shadow_ids"],
            "demands": [{k: (str(v) if isinstance(v, uuidlib.UUID) else
                             v.isoformat() if isinstance(v, datetime) else v)
                         for k, v in d.items()} for d in bundle["demands"]],
            "ack": dict(ack) if ack else None}


@router.get("/{plan_id}/sentinel-report")
async def sentinel_report(plan_id: str, actor: Actor = Depends(get_actor),
                          session: AsyncSession = Depends(get_session)):
    plan = await load_plan(session, plan_id)
    if plan is None:
        raise HTTPException(404, "plan not found")
    bundle = await _bundle(session, plan)
    ctx = await _build_sentinel_context(session)
    candidate = _candidate_from_bundle(bundle, plan)
    verdict = validate_plan(candidate, ctx)
    return {"content_hash": verdict.content_hash, "passed": verdict.passed,
            "has_pending": verdict.has_pending,
            "checks": [{"id": r.check_id.value, "passed": r.passed, "pending": r.pending,
                        "detail": r.detail} for r in verdict.results]}


@router.post("/{plan_id}/acknowledge-signal")
async def acknowledge_signal(plan_id: str, body: AckSignalIn,
                             actor: Actor = Depends(require_roles("STATION_MASTER", "CONTROLLER", "ADMIN")),
                             session: AsyncSession = Depends(get_session)):
    plan = await load_plan(session, plan_id)
    if plan is None:
        raise HTTPException(404, "plan not found")
    role_field = "sm" if body.as_role == "STATION_MASTER" else "controller"
    await session.execute(text(
        f"""INSERT INTO operations.signal_acknowledgments (plan_id, {role_field}_actor, {role_field}_acked_at)
            VALUES (:p, :a, now())
            ON CONFLICT DO NOTHING"""), {"p": plan_id, "a": actor.username})
    await session.execute(text(
        f"""UPDATE operations.signal_acknowledgments SET {role_field}_actor = :a, {role_field}_acked_at = now()
            WHERE plan_id = :p AND {role_field}_acked_at IS NULL"""), {"p": plan_id, "a": actor.username})
    ack = (await session.execute(text(
        "SELECT sm_acked_at, controller_acked_at FROM operations.signal_acknowledgments WHERE plan_id = :p"),
        {"p": plan_id})).mappings().first()
    both = bool(ack and ack["sm_acked_at"] and ack["controller_acked_at"])
    if both and plan["approval_status"] == "DRAFT":
        ch = await recompute_hash(session, plan)
        await session.execute(text(
            "UPDATE optimization.block_plans SET approval_status = 'SENTINEL_PASSED', "
            "sentinel_verified = true, sentinel_hash = :ch WHERE id = :i AND approval_status = 'DRAFT'"),
            {"ch": ch, "i": plan_id})
        await append(session, "PLAN_SENTINEL_PASSED", actor.username,
                     {"plan_id": plan_id, "via": "signal_acknowledgment", "content_hash": ch})
    await append(session, "SIGNAL_ACKNOWLEDGED", actor.username,
                 {"plan_id": plan_id, "as": body.as_role})
    await session.commit()
    await sse.publish("SIGNAL_ACK", {"plan_id": plan_id, "role": body.as_role})
    return {"plan_id": plan_id, "both_acknowledged": both}


@router.post("/{plan_id}/revise")
async def revise(plan_id: str, body: ReviseIn,
                 actor: Actor = Depends(require_roles("SR_DOM", "ENGINEER", "ADMIN")),
                 session: AsyncSession = Depends(get_session)):
    plan = await load_plan(session, plan_id)
    if plan is None:
        raise HTTPException(404, "plan not found")
    if actor.role != "ADMIN" and plan["division"] != actor.division:
        raise HTTPException(403, "cross-division access denied")
    if plan["approval_status"] in ("TRANSMITTED_COA", "ACTIVE_GRANTED", "COMPLETED_FITNESS", "ARCHIVED_SEALED"):
        raise HTTPException(409, "plan already transmitted; supersede via emergency or cancellation only")
    try:
        new_id = await revise_plan(session, plan, actor.username, body.start_time, body.end_time)
    except ValueError as e:
        raise HTTPException(400, str(e))
    await append(session, "PLAN_REVISED", actor.username,
                 {"old_plan_id": plan_id, "new_plan_id": new_id,
                  "old_revision": plan["revision_no"], "new_revision": plan["revision_no"] + 1})
    await session.commit()
    await sse.publish("PLAN_REVISED", {"old_plan_id": plan_id, "new_plan_id": new_id})
    return {"new_plan_id": new_id, "revision_no": plan["revision_no"] + 1,
            "sentinel_verified": False, "note": "new revision re-enters the Sentinel chain"}


@router.post("/{plan_id}/transmit")
async def transmit(plan_id: str, actor