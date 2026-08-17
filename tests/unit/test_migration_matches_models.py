"""Offline check that the Alembic migrations and the ORM models agree.

CI runs the authoritative check (``alembic upgrade head`` then ``alembic check`` against real
PostgreSQL). This test exists because that feedback loop needs a database, and schema drift
introduced during development should fail in a plain ``pytest`` run instead.

The approach: render the migration chain to PostgreSQL DDL in Alembic's offline mode, render
the same DDL from ``Base.metadata``, then compare tables, columns, and constraints as
normalized sets. Ordering differences within a ``CREATE TABLE`` body are irrelevant to the
resulting schema, so the comparison is order-insensitive.
"""

from __future__ import annotations

import io
import re
from collections import defaultdict
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

from aedifex.infrastructure.database.models import Base

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _render_migration_ddl() -> str:
    """Run every migration's ``upgrade()`` in offline mode and capture the emitted SQL."""
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    script = ScriptDirectory.from_config(config)

    buffer = io.StringIO()
    context = MigrationContext.configure(
        dialect_name="postgresql",
        opts={"as_sql": True, "output_buffer": buffer},
    )

    with Operations.context(context):
        # Walk base -> head so multi-revision chains are covered as they are added.
        for revision in script.walk_revisions(base="base", head="heads"):
            upgrade = revision.module.upgrade
            upgrade()

    return buffer.getvalue()


def _render_model_ddl() -> str:
    dialect = postgresql.dialect()  # type: ignore[no-untyped-call]
    statements: list[str] = []
    for table in Base.metadata.sorted_tables:
        statements.append(str(CreateTable(table).compile(dialect=dialect)))
        statements.extend(
            str(CreateIndex(index).compile(dialect=dialect)) for index in table.indexes
        )
    return "\n".join(statements)


def _split_top_level(body: str) -> list[str]:
    """Split a ``CREATE TABLE`` body on commas that are not inside parentheses."""
    items: list[str] = []
    depth = 0
    current: list[str] = []
    in_string = False

    for char in body:
        if char == "'":
            in_string = not in_string
        if not in_string:
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
            elif char == "," and depth == 0:
                items.append("".join(current))
                current = []
                continue
        current.append(char)

    if current:
        items.append("".join(current))
    return [_normalize(item) for item in items if _normalize(item)]


def _normalize(text: str) -> str:
    """Collapse whitespace and drop trailing separators so equal DDL compares equal."""
    return re.sub(r"\s+", " ", text).strip().rstrip(",").strip()


def _parse_tables(ddl: str) -> dict[str, set[str]]:
    """Extract ``{table_name: {column and constraint definitions}}`` from rendered DDL."""
    tables: dict[str, set[str]] = {}
    for match in re.finditer(
        r"CREATE TABLE (\w+) \((.*?)\n\)", ddl, flags=re.DOTALL | re.IGNORECASE
    ):
        tables[match.group(1)] = set(_split_top_level(match.group(2)))
    return tables


def _parse_indexes(ddl: str) -> dict[str, set[str]]:
    """Extract ``{table_name: {index definitions}}`` from rendered DDL."""
    indexes: dict[str, set[str]] = defaultdict(set)
    for match in re.finditer(
        r"CREATE (?:UNIQUE )?INDEX (\w+) ON (\w+) \(([^)]*)\)", ddl, flags=re.IGNORECASE
    ):
        name, table, columns = match.groups()
        indexes[table].add(_normalize(f"{name} ({columns})"))
    return dict(indexes)


@pytest.fixture(scope="module")
def migration_ddl() -> str:
    return _render_migration_ddl()


@pytest.fixture(scope="module")
def model_ddl() -> str:
    return _render_model_ddl()


def test_migration_creates_the_same_tables(migration_ddl: str, model_ddl: str) -> None:
    assert _parse_tables(migration_ddl).keys() == _parse_tables(model_ddl).keys()


@pytest.mark.parametrize("table_name", sorted(table.name for table in Base.metadata.sorted_tables))
def test_migration_table_definition_matches_model(
    table_name: str, migration_ddl: str, model_ddl: str
) -> None:
    """Every column, check, unique, foreign key, and primary key must match exactly."""
    from_migration = _parse_tables(migration_ddl)[table_name]
    from_models = _parse_tables(model_ddl)[table_name]

    missing = from_models - from_migration
    extra = from_migration - from_models
    assert not missing, f"{table_name}: migration is missing {sorted(missing)}"
    assert not extra, f"{table_name}: migration has unexpected {sorted(extra)}"


@pytest.mark.parametrize("table_name", sorted(table.name for table in Base.metadata.sorted_tables))
def test_migration_indexes_match_model(table_name: str, migration_ddl: str, model_ddl: str) -> None:
    from_migration = _parse_indexes(migration_ddl).get(table_name, set())
    from_models = _parse_indexes(model_ddl).get(table_name, set())
    assert from_migration == from_models, (
        f"{table_name}: index mismatch; "
        f"missing={sorted(from_models - from_migration)} "
        f"extra={sorted(from_migration - from_models)}"
    )


def test_every_migration_is_reversible() -> None:
    """Each revision must define a real ``downgrade``, not an empty stub.

    An irreversible migration cannot be safely deployed, so this is enforced rather than
    left to review.
    """
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    script = ScriptDirectory.from_config(config)

    for revision in script.walk_revisions(base="base", head="heads"):
        source = Path(revision.path).read_text(encoding="utf-8")
        downgrade_body = source.split("def downgrade()", 1)[1]
        assert "op." in downgrade_body, (
            f"revision {revision.revision} has no downgrade operations; "
            f"migrations must be reversible"
        )
