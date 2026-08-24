"""TASK-055: message-generation LLM provenance — runtime.actions.llm_call_id FK.

Adds a nullable FK from actions to llm_calls so "which LLM call generated this
message?" is a simple join instead of a JSONB ledger-event scan (Schema §3).
Backfill-safe: NULL for template-fallback / RP-TM-only actions (no LLM span).

Down-doc (forward-only, Schema §14): ALTER TABLE runtime.actions
DROP COLUMN IF EXISTS llm_call_id;
"""
from alembic import op

revision = "0002_actions_llm_call_id"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE runtime.actions "
        "ADD COLUMN llm_call_id UUID REFERENCES runtime.llm_calls(id)"
    )
    op.execute(
        "CREATE INDEX idx_actions_llm_call ON runtime.actions (llm_call_id) "
        "WHERE llm_call_id IS NOT NULL"
    )
