"""Alembic environment.

The database URL comes from application settings, so no credential is committed and a migration
run with no arguments cannot go somewhere unexpected. An explicit ``sqlalchemy.url`` on the Alembic
config does win, being the more specific instruction — the integration fixtures rely on it to
migrate a dedicated test database, and before it was honoured they created one and then migrated
the application's database instead.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine

from aedifex.config import get_settings
from aedifex.infrastructure.database.models import Base
from aedifex.infrastructure.database.session import build_engine

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _database_url() -> str:
    """The URL to migrate: an explicit Alembic config value if given, otherwise the settings.

    The config value wins because it is the more specific instruction. Without this, a caller that
    set ``sqlalchemy.url`` was silently ignored and its migration went to whatever
    ``AEDIFEX_DATABASE_URL`` named — which is how the integration fixtures created a dedicated test
    database and then migrated the *production* one instead, leaving the tests to run against a
    schema that did not exist.
    """
    configured = config.get_main_option("sqlalchemy.url")
    return configured or str(get_settings().database_url)


def run_migrations_offline() -> None:
    """Emit SQL to stdout without connecting, for review or manual application."""
    context.configure(
        url=_database_url(),
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
    settings = get_settings()
    url = _database_url()
    engine = (
        build_engine(settings)
        if url == str(settings.database_url)
        else create_engine(url, pool_pre_ping=True)
    )
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
