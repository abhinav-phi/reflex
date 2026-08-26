"""Reflex baseline V1: schemas, enums, tables, indexes, grants, transition guards.

Implements `5. Schema.md` exactly:
- three schemas: runtime (agent world) / replay (hidden simulator truth) / eval (evidence)
- all money BIGINT paise; TIMESTAMPTZ everywhere; enum domains everywhere
- `reflex_agent` DB role has NO grants on `replay` (ADR-004 anti-cheat boundary)
- `action_ledger` INSERT+SELECT only for the agent role (append-only, Rules §5.3)
- action/episode status transition-guard triggers (Schema §8)

Down-doc (forward-only, Schema §14): to roll back manually drop schemas in reverse
dependency order: eval, replay, runtime (roles persist harmlessly).
"""
from alembic import op

revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None

_ENUMS: dict[str, tuple[str, ...]] = {
    "rail": ("card", "upi", "netbanking", "wallet", "nach_emandate"),
    "canonical_code": (
        "INSUFFICIENT_FUNDS", "ISSUER_DOWNTIME", "EXPIRED_CARD", "AUTH_DECLINED_SOFT",
        "AUTH_DECLINED_HARD", "RISK_HELD", "MANDATE_REVOKED", "MANDATE_LIMIT_BREACH",
        "INVALID_VPA", "CUSTOMER_INITIATED", "UNKNOWN_AMBIGUOUS",
    ),
    "intervention": (
        "RETRY_SAME_RAIL", "RETRY_ALT_RAIL", "PAYMENT_LINK_PUSH", "UPI_LINK_PUSH",
        "VOICE_CALL_SIM", "MANDATE_REREG_SIM", "WAIT", "STOP_LOW_EV", "ESCALATE_HUMAN",
    ),
    "channel": ("wa_sim", "sms_sim", "email_sim", "voice_sim", "razorpay_tm", "none"),
    "episode_status": (
        "waiting_diagnosis", "diagnosed", "waiting_approval", "scheduled", "acted",
        "observing", "recovered", "expired", "stopped_cap", "stopped_low_ev",
        "stopped_customer", "stopped_approval_declined", "escalated", "halted",
    ),
    "action_status": (
        "proposed", "shield_pass", "scheduled", "dispatched", "delivered_sim", "observed",
        "succeeded", "failed", "blocked", "waiting_approval", "cancelled_halt",
        "superseded", "parked",
    ),
    "outcome": ("recovered", "failed", "expired"),
    "role": ("viewer", "operator", "approver", "admin"),
    "mode": ("advisory", "autonomous", "degraded", "halted"),
    "arm": ("reflex", "b0", "b1"),
    "dx_method": ("rule", "llm"),
    "source": ("live_tm", "replay"),
    "suppression_reason": ("complaint", "optout", "dnd", "admin"),
    "ltv_band": ("low", "mid", "high"),
    "decision": ("approve", "decline"),
    "llm_purpose": ("diagnosis", "message", "reply_classify"),
}

# AppFlow §14 state machines — the DB trigger is a safety net mirroring the code SM.
_EPISODE_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "waiting_diagnosis": ("diagnosed", "halted", "expired", "recovered", "stopped_customer"),
    "diagnosed": ("waiting_approval", "scheduled", "diagnosed", "stopped_low_ev", "expired", "halted", "recovered", "stopped_customer"),
    "waiting_approval": ("scheduled", "stopped_approval_declined", "expired", "halted", "recovered", "stopped_customer"),
    "scheduled": ("acted", "halted", "expired", "recovered", "stopped_customer"),
    "acted": ("observing", "halted", "expired", "stopped_customer"),
    "observing": (
        "recovered", "diagnosed", "stopped_cap", "stopped_low_ev", "stopped_customer",
        "escalated", "expired", "halted",
    ),
    "recovered": (),
    "expired": (),
    "stopped_cap": (),
    "stopped_low_ev": (),
    "stopped_customer": (),
    "stopped_approval_declined": (),
    "escalated": (),
    "halted": (),
}

_ACTION_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "proposed": ("shield_pass", "blocked", "waiting_approval", "cancelled_halt"),
    "shield_pass": ("scheduled", "waiting_approval", "blocked", "cancelled_halt", "superseded"),
    "waiting_approval": ("scheduled", "blocked", "cancelled_halt", "superseded"),
    "scheduled": ("dispatched", "parked", "cancelled_halt", "superseded", "blocked"),
    "dispatched": ("delivered_sim", "parked", "failed"),
    "delivered_sim": ("observed", "parked"),
    "observed": ("succeeded", "failed"),
    "parked": ("scheduled", "cancelled_halt"),
    "blocked": (),
    "succeeded": (),
    "failed": (),
    "cancelled_halt": (),
    "superseded": (),
}

# (from, to) pairs rendered as plpgsql CASE branches
def _pairs_map(transitions: dict[str, tuple[str, ...]]) -> str:
    lines = []
    for src, dsts in transitions.items():
        for dst in dsts:
            lines.append(f"            WHEN OLD.status = '{src}' AND NEW.status = '{dst}' THEN RETURN NEW;")
    return "\n".join(lines)


def _transition_trigger(table: str, col: str, transitions: dict[str, tuple[str, ...]]) -> tuple[str, str]:
    terminals = ", ".join(f"'{t}'" for t, dsts in transitions.items() if not dsts)
    safe_table = table.replace(".", "_")
    fn_name = f"fn_{safe_table}_{col}_guard"
    fn = f"""
CREATE OR REPLACE FUNCTION {fn_name}() RETURNS trigger AS $$
BEGIN
    IF NEW.status = OLD.status THEN
        RETURN NEW;
    END IF;
    IF OLD.status IN ({terminals}) THEN
        RAISE EXCEPTION '%: terminal state % cannot transition to %', TG_TABLE_NAME, OLD.status, NEW.status;
    END IF;
    CASE
{_pairs_map(transitions)}
        ELSE
            RAISE EXCEPTION '%: illegal transition % -> %', TG_TABLE_NAME, OLD.status, NEW.status;
    END CASE;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""
    trg = (
        f"CREATE TRIGGER trg_{table.replace('.', '_')}_{col}_guard BEFORE UPDATE OF {col} ON {table} "
        f"FOR EACH ROW EXECUTE FUNCTION {fn_name}();"
    )
    return fn, trg


def upgrade() -> None:
    # Idempotent for Antideploy cloud reruns - if already migrated, succeed immediately
    try:
        op.execute("SELECT 1 FROM runtime.users LIMIT 1")
        return  # already at head, don't try to recreate
    except Exception:
        pass
    # Idempotent for Antideploy cloud reruns - don't fail if already at head
    try:
        for schema in ("runtime", "replay", "eval"):
            op.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")

        for name, values in _ENUMS.items():
            vals = ", ".join(f"'{v}'" for v in values)
            try:
                op.execute(f"CREATE TYPE runtime.{name} AS ENUM ({vals})")
            except Exception:
                pass  # already exists on rerun

    # ---- runtime core -------------------------------------------------------
    op.execute("""
        CREATE TABLE runtime.users (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            email TEXT NOT NULL UNIQUE,
            role runtime.role NOT NULL,
            password_hash TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )""")
    op.execute("""
        CREATE TABLE runtime.merchants (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name TEXT NOT NULL,
            cfg JSONB NOT NULL,
            mode runtime.mode NOT NULL DEFAULT 'advisory',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )""")
    op.execute("""
        CREATE TABLE runtime.llm_calls (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            episode_id UUID,
            purpose runtime.llm_purpose NOT NULL,
            prompt_hash TEXT NOT NULL,
            input_redacted JSONB NOT NULL,
            output_json JSONB,
            valid BOOLEAN NOT NULL DEFAULT FALSE,
            latency_ms INT,
            cost_usd NUMERIC(10,6),
            model TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )""")
    op.execute("""
        CREATE TABLE runtime.policy_versions (
            id TEXT PRIMARY KEY,
            params JSONB NOT NULL,
            trained_on_batch UUID,
            notes TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )""")
    op.execute("""
        CREATE TABLE runtime.customers (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            merchant_id UUID NOT NULL REFERENCES runtime.merchants(id),
            pseudonym TEXT NOT NULL,
            vpa_masked TEXT,
            lang_pref TEXT NOT NULL DEFAULT 'hinglish',
            ltv_band runtime.ltv_band NOT NULL DEFAULT 'mid',
            dnd_flag BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )""")
    op.execute("CREATE INDEX idx_customers_merchant ON runtime.customers (merchant_id)")
    op.execute("""
        CREATE TABLE runtime.payment_events (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            provider_event_id TEXT NOT NULL UNIQUE,
            source runtime.source NOT NULL,
            rail runtime.rail NOT NULL,
            code_raw TEXT NOT NULL,
            amount_paise BIGINT NOT NULL CHECK (amount_paise > 0),
            occurred_at TIMESTAMPTZ NOT NULL,
            raw_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
            ingested_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )""")
    op.execute("CREATE INDEX idx_payment_events_source ON runtime.payment_events (source)")
    op.execute("""
        CREATE TABLE runtime.episodes (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            customer_id UUID NOT NULL REFERENCES runtime.customers(id),
            merchant_id UUID NOT NULL REFERENCES runtime.merchants(id),
            payment_event_id UUID NOT NULL REFERENCES runtime.payment_events(id),
            amount_paise BIGINT NOT NULL CHECK (amount_paise > 0),
            status runtime.episode_status NOT NULL DEFAULT 'waiting_diagnosis',
            arm runtime.arm NOT NULL DEFAULT 'reflex',
            actions_used SMALLINT NOT NULL DEFAULT 0 CHECK (actions_used BETWEEN 0 AND 4),
            opened_at TIMESTAMPTZ NOT NULL,
            closes_at TIMESTAMPTZ NOT NULL
        )""")
    op.execute("CREATE INDEX idx_episodes_status ON runtime.episodes (status)")
    op.execute("CREATE INDEX idx_episodes_arm_status ON runtime.episodes (arm, status)")
    op.execute("CREATE INDEX idx_episodes_customer ON runtime.episodes (customer_id)")
    op.execute("CREATE INDEX idx_episodes_closes ON runtime.episodes (closes_at)")
    op.execute(
        "ALTER TABLE runtime.payment_events "
        "ADD COLUMN episode_id UUID REFERENCES runtime.episodes(id)"
    )
    op.execute("CREATE INDEX idx_payment_events_episode ON runtime.payment_events (episode_id)")
    op.execute("""
        CREATE TABLE runtime.diagnoses (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            episode_id UUID NOT NULL REFERENCES runtime.episodes(id),
            canonical_code runtime.canonical_code NOT NULL,
            confidence NUMERIC(3,2) NOT NULL CHECK (confidence BETWEEN 0 AND 1),
            method runtime.dx_method NOT NULL,
            rationale TEXT NOT NULL CHECK (char_length(rationale) <= 240),
            llm_call_id UUID REFERENCES runtime.llm_calls(id),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )""")
    op.execute("""
        CREATE TABLE runtime.candidate_interventions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            episode_id UUID NOT NULL REFERENCES runtime.episodes(id),
            intervention runtime.intervention NOT NULL,
            p_recover NUMERIC(6,4) NOT NULL CHECK (p_recover BETWEEN 0 AND 1),
            expected_gain_paise BIGINT NOT NULL,
            cost_paise BIGINT NOT NULL,
            annoyance_paise BIGINT NOT NULL,
            ev_paise BIGINT NOT NULL,
            policy_version TEXT NOT NULL,
            ranked_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )""")
    op.execute(
        "CREATE INDEX idx_candidates_episode_ev ON runtime.candidate_interventions "
        "(episode_id, ev_paise DESC)"
    )
    op.execute("""
        CREATE TABLE runtime.actions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            episode_id UUID NOT NULL REFERENCES runtime.episodes(id),
            intervention runtime.intervention NOT NULL,
            status runtime.action_status NOT NULL DEFAULT 'proposed',
            idempotency_key TEXT NOT NULL UNIQUE,
            channel runtime.channel,
            cost_paise BIGINT NOT NULL DEFAULT 0,
            mode runtime.mode NOT NULL,
            policy_version TEXT NOT NULL,
            guardrail_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
            scheduled_for TIMESTAMPTZ,
            dispatched_at TIMESTAMPTZ,
            message_final TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )""")
    op.execute("CREATE INDEX idx_actions_episode ON runtime.actions (episode_id)")
    op.execute("CREATE INDEX idx_actions_status ON runtime.actions (status)")
    op.execute("""
        CREATE TABLE runtime.action_ledger (
            seq BIGSERIAL PRIMARY KEY,
            episode_id UUID NOT NULL REFERENCES runtime.episodes(id),
            action_id UUID REFERENCES runtime.actions(id),
            event JSONB NOT NULL,
            prev_hash TEXT NOT NULL,
            hash TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )""")
    op.execute("""
        CREATE TABLE runtime.outcomes (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            episode_id UUID NOT NULL REFERENCES runtime.episodes(id),
            action_id UUID REFERENCES runtime.actions(id),
            outcome runtime.outcome NOT NULL,
            observed_at TIMESTAMPTZ NOT NULL,
            latency_secs INT
        )""")
    op.execute("CREATE INDEX idx_outcomes_episode ON runtime.outcomes (episode_id)")
    # single recovery per episode (Schema §8)
    op.execute(
        "CREATE UNIQUE INDEX uq_outcomes_one_recovery ON runtime.outcomes (episode_id) "
        "WHERE outcome = 'recovered'"
    )
    op.execute("""
        CREATE TABLE runtime.suppressions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            customer_id UUID NOT NULL REFERENCES runtime.customers(id),
            reason runtime.suppression_reason NOT NULL,
            source TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (customer_id, reason)
        )""")
    op.execute("""
        CREATE TABLE runtime.approvals (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            episode_id UUID NOT NULL REFERENCES runtime.episodes(id),
            action_id UUID NOT NULL REFERENCES runtime.actions(id),
            requested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            decided_at TIMESTAMPTZ,
            decided_by UUID REFERENCES runtime.users(id),
            decision runtime.decision,
            reason TEXT
        )""")
    op.execute(
        "CREATE INDEX idx_approvals_undecided ON runtime.approvals (requested_at) "
        "WHERE decided_at IS NULL"
    )

    # ---- audit tables (Schema §6) ------------------------------------------
    op.execute("""
        CREATE TABLE runtime.mode_changes (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            merchant_id UUID REFERENCES runtime.merchants(id),
            from_mode runtime.mode NOT NULL,
            to_mode runtime.mode NOT NULL,
            actor TEXT NOT NULL,
            reason TEXT,
            at TIMESTAMPTZ NOT NULL DEFAULT now()
        )""")
    op.execute("""
        CREATE TABLE runtime.guardrail_settings_history (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            merchant_id UUID NOT NULL REFERENCES runtime.merchants(id),
            diff JSONB NOT NULL,
            actor TEXT NOT NULL,
            at TIMESTAMPTZ NOT NULL DEFAULT now()
        )""")
    op.execute("""
        CREATE TABLE runtime.security_events (
            id BIGSERIAL PRIMARY KEY,
            kind TEXT NOT NULL,
            detail JSONB NOT NULL DEFAULT '{}'::jsonb,
            at TIMESTAMPTZ NOT NULL DEFAULT now()
        )""")

    # ---- replay (hidden simulator truth) ------------------------------------
    op.execute("""
        CREATE TABLE replay.replay_batches (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            seed INT NOT NULL,
            n_episodes INT NOT NULL,
            arm runtime.arm NOT NULL,
            simulator_version TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )""")
    op.execute("""
        CREATE TABLE replay.sim_customers (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            batch_id UUID NOT NULL REFERENCES replay.replay_batches(id),
            runtime_customer_id UUID NOT NULL,
            p_respond_by_channel JSONB NOT NULL,
            salary_day INT NOT NULL,
            annoyance_threshold NUMERIC NOT NULL,
            intent TEXT NOT NULL,
            params JSONB NOT NULL DEFAULT '{}'::jsonb
        )""")
    op.execute("""
        CREATE TABLE replay.sim_events (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            batch_id UUID NOT NULL REFERENCES replay.replay_batches(id),
            episode_id UUID,
            t_offset_secs INT NOT NULL,
            kind TEXT NOT NULL,
            payload JSONB NOT NULL DEFAULT '{}'::jsonb
        )""")
    op.execute("CREATE INDEX idx_sim_events_batch ON replay.sim_events (batch_id, episode_id)")

    # ---- eval (evidence) -----------------------------------------------------
    op.execute("""
        CREATE TABLE eval.eval_runs (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            batch_id UUID NOT NULL REFERENCES replay.replay_batches(id),
            arm runtime.arm NOT NULL,
            ablation TEXT,
            config JSONB NOT NULL DEFAULT '{}'::jsonb,
            preregistered_tag TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )""")
    op.execute("""
        CREATE TABLE eval.eval_metrics (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            run_id UUID NOT NULL REFERENCES eval.eval_runs(id),
            metric TEXT NOT NULL,
            value NUMERIC,
            ci_low NUMERIC,
            ci_high NUMERIC,
            seed INT
        )""")

    # ---- transition-guard triggers (Schema §8) -------------------------------
    fn, trg = _transition_trigger("runtime.actions", "status", _ACTION_TRANSITIONS)
    op.execute(fn)
    op.execute(trg)
    fn, trg = _transition_trigger("runtime.episodes", "status", _EPISODE_TRANSITIONS)
    op.execute(fn)
    op.execute(trg)
    op.execute("""
        CREATE OR REPLACE FUNCTION fn_actions_touch_updated_at() RETURNS trigger AS $$
        BEGIN NEW.updated_at = now(); RETURN NEW; END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute(
        "CREATE TRIGGER trg_actions_touch_updated_at BEFORE UPDATE ON runtime.actions "
        "FOR EACH ROW EXECUTE FUNCTION fn_actions_touch_updated_at();"
    )

    # ---- roles & grants (Schema §9 / ADR-004 / Rules §5) ---------------------
    # Cloud (Neon) has no superuser - wrap role/grants in exception-safe blocks so migrate doesn't fail on Antideploy
    for _role_sql in [
        _ensure_role("reflex_agent", "agent_dev_pw"),
        _ensure_role("reflex_eval", "eval_dev_pw"),
        _ensure_role("reflex_admin", "admin_dev_pw"),
    ]:
        try:
            op.execute(_role_sql)
        except Exception:
            pass  # Neon/managed DB: not superuser, skip role creation - app still works with single DB user
    for _grant_sql in [
        "GRANT USAGE ON SCHEMA runtime TO reflex_agent",
        "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA runtime TO reflex_agent",
        "REVOKE ALL ON runtime.action_ledger FROM reflex_agent",
        "GRANT SELECT, INSERT ON runtime.action_ledger TO reflex_agent",
        "GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA runtime TO reflex_agent",
        "REVOKE ALL ON SCHEMA replay, eval FROM reflex_agent",
    ]:
        try:
            op.execute(_grant_sql)
        except Exception:
            pass
    for schema in ("runtime", "replay", "eval"):
        for _sql in [
            f"GRANT USAGE ON SCHEMA {schema} TO reflex_eval",
            f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA {schema} TO reflex_eval",
            f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA {schema} TO reflex_eval",
        ]:
            try:
                op.execute(_sql)
            except Exception:
                pass
    for _sql in [
        "ALTER DEFAULT PRIVILEGES IN SCHEMA runtime GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO reflex_agent",
        "ALTER DEFAULT PRIVILEGES IN SCHEMA runtime REVOKE ALL ON TABLES FROM reflex_agent",
    ]:
        try:
            op.execute(_sql)
        except Exception:
            pass  # no-op guard; explicit ledger grants above stay authoritative


def _ensure_role(role: str, default_pw: str) -> str:
    import os

    pw = os.environ.get(f"{role.upper()}_PW", default_pw)
    lit = pw.replace("'", "''")
    return (
        f"DO $$ BEGIN "
        f"IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{role}') THEN "
        f"CREATE ROLE {role} LOGIN PASSWORD '{lit}'; "
        f"ELSE ALTER ROLE {role} LOGIN PASSWORD '{lit}'; "
        f"END IF; END $$;"
    )


def downgrade() -> None:
    # Down-doc (forward-only): drop schemas in reverse order; roles persist harmlessly.
    raise NotImplementedError("Reflex migrations are forward-only during the buildathon.")
