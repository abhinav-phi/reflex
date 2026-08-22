"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}

Forward-only during the buildathon (Schema §14). Every migration carries a down-doc
in comments even though downgrade() is not executable.
"""
from alembic import op
import sqlalchemy as sa

revision = ${repr(up_revision)}
down_revision = ${repr(down_revision)}
branch_labels = ${repr(branch_labels)}
depends_on = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    # Down-doc (not executable, forward-only): ${message}
    # To roll back manually: drop schemas eval/replay/runtime in reverse dependency order.
    raise NotImplementedError("Reflex migrations are forward-only during the buildathon.")
