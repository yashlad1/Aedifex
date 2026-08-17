"""Alembic environment.

The database URL comes from application settings rather than ``alembic.ini`` so that
migrations cannot be pointed at a different database than the application uses, and so no
credential is committed.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context

from aedifex.config import get_settings
from aedifex.infrastructure.database.models import Base
from aedifex.infrastructure.database.session import build_engine

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Emit SQL to stdout without connecting, for review or manual application."""
    context.configure(
        url=str(get_settings().database_url),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Apply migrations against a live database."""
    engine = build_engine(get_settings())
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # Detect column type and server-default drift, so `alembic check` is a
            # meaningful CI gate rather than a table-existence test.
            compare_type=True,
            compare_server_default=True,
            transaction_per_migration=True,
        )
        with context.begin_transaction():
            context.run_migrations()

    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
