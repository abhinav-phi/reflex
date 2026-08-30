"""Enable pgcrypto for server-side ledger hashing.

The append path now derives the event hash INSIDE the INSERT statement itself
(see packages/ledger/chain.py): one atomic statement computes seq (nextval),
stores the event, and seals it with sha256(seq | prev_hash | event::text) using
pgcrypto's digest(). No follow-up UPDATE — the agent role's append-only grants
(no UPDATE/DELETE on the ledger) remain intact, and the head-read race between
concurrent writers is eliminated.

digest()/encode() come from pgcrypto; created idempotently here. First run
requires a role that can create extensions (true on CI, Railway, and the
compose setup — all connect as the postgres superuser).
"""

from alembic import op

revision = "0003_pgcrypto"
down_revision = "0002_actions_llm_call_id"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")


def downgrade() -> None:
    # keep the extension: existing ledger hashes depend on digest()
    pass
