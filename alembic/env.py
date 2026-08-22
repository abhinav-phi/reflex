"""Alembic environment. Migrations always run with the ADMIN url (needs DDL + role grants)."""

import os
import sys
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

config = context.config

if not config.get_main_option("sqlalchemy.url"):
    admin_url = os.environ.get("DATABASE_URL_ADMIN", "postgresql+psycopg://postgres:reflex_dev_pg@localhost:5432/reflex")
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
