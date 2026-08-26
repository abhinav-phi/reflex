"""Alembic environment. Migrations always run with the ADMIN url (needs DDL + role grants)."""

import os
import sys
from pathlib import Path

from sqlalchemy import engine_from_config, pool

from alembic import context

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

config = context.config

if not config.get_main_option("sqlalchemy.url"):
    # Host port 15432 (compose maps 15432->5432); see docker-compose.yml + MANUAL_STEPS.md §10
    # CI needs ADMIN (postgres) — reflect that, Antideploy only provides DATABASE_URL (single) so fallback there.
    admin_url = os.environ.get("DATABASE_URL_ADMIN") or os.environ.get("DATABASE_URL") or "postgresql+psycopg://postgres:reflex_dev_pg@localhost:15432/reflex"
    # Neon/Antideploy injects postgresql:// (psycopg2) but local defaults use +psycopg (psycopg3);
    # normalize to +psycopg2 at runtime so both drivers work regardless of which is installed.
    # The live app already runs with psycopg2, so force that for migrations too.
    if admin_url.startswith("postgresql+psycopg://"):
        admin_url = admin_url.replace("postgresql+psycopg://", "postgresql+psycopg2://", 1)
    elif admin_url.startswith("postgresql://"):
        admin_url = admin_url.replace("postgresql://", "postgresql+psycopg2://", 1)
    elif admin_url.startswith("postgres://"):
        admin_url = admin_url.replace("postgres://", "postgresql+psycopg2://", 1)
    config.set_main_option("sqlalchemy.url", admin_url)

target_metadata = None  # raw-SQL baseline; forward-only during buildathon (Schema §14)


def run_migrations_offline() -> None:
    context.configure(url=config.get_main_option("sqlalchemy.url"), literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
