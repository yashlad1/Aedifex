"""Offline check that the Alembic migrations and the ORM models agree.

CI runs the authoritative check (``alembic upgrade head`` then ``alembic check`` against real
PostgreSQL). This test exists because that feedback loop needs a database, and schema drift
introduced during development should fail in a plain ``pytest`` run instead.

The approach: render the migration chain to PostgreSQL DDL in Alembic's offline mode, render
the same DDL from ``Base.metadata``, then compare tables, columns, and constraints as
normalized sets. Ordering differences within a ``CREATE TABLE`` body are irrelevant to the
resulting schema, so the comparison is order-insensitive.

``ALTER TABLE`` is replayed as well as ``CREATE TABLE``, and it has to be: a migration that adds a
column to an existing table contributes nothing to a ``CREATE TABLE`` statement, so a comparison
that read only creates would report a clean match while the schema and the models disagreed about
every column added after the table was first made. Revisions are therefore applied base to head, in
order, with each ``ALTER`` mutating the table it names.

The replay has to understand every form of ``ALTER`` the migrations actually use, and an unhandled
one fails *closed* — as a mismatch — which is how ``SET DEFAULT`` came to be added: a migration
changed a column default and this file reported the schema and the models as disagreeing when they
did not.
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
        # walk_revisions yields head first, so it is reversed: an ALTER must be replayed after the
        # CREATE TABLE it modifies, or the column it adds is applied to a table that does not exist
        # yet and is silently dropped from the comparison.
        for revision in reversed(list(script.walk_revisions(base="base", head="heads"))):
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
    """Extract ``{table_name: {column and constraint definitions}}`` from rendered DDL.

    Two passes: every ``CREATE TABLE``, then every ``ALTER TABLE`` in the order it was emitted. The
    second pass is what makes this comparison mean anything once a migration modifies an existing
    table — a column added by ``ALTER`` appears in no ``CREATE TABLE`` statement, so reading only
    creates would report a clean match while the schema and the models disagreed about it.

    Two passes rather than one interleaved walk because revisions run base to head, so a table is
    always created before it is altered.
    """
    tables: dict[str, set[str]] = {}
    for match in re.finditer(
        r"CREATE TABLE (\w+) \((.*?)\n\)", ddl, flags=re.DOTALL | re.IGNORECASE
    ):
        tables[match.group(1)] = set(_split_top_level(match.group(2)))

    for match in re.finditer(r"ALTER TABLE (\w+) ([^;]+);", ddl, flags=re.IGNORECASE):
        table, action = match.group(1), _normalize(match.group(2))
        if table in tables:
            _apply_alter(tables[table], action)
    return tables


def _apply_alter(definitions: set[str], action: str) -> None:
    """Mutate one table's definition set by one ``ALTER TABLE`` action."""
    add_column = re.match(r"ADD COLUMN (.*)$", action, flags=re.IGNORECASE)
    if add_column is not None:
        definitions.add(_normalize(add_column.group(1)))
        return

    add_constraint = re.match(r"ADD (CONSTRAINT .*)$", action, flags=re.IGNORECASE)
    if add_constraint is not None:
        definitions.add(_normalize(add_constraint.group(1)))
        return

    drop_constraint = re.match(r"DROP CONSTRAINT (\w+)", action, flags=re.IGNORECASE)
    if drop_constraint is not None:
        _discard_matching(definitions, rf"CONSTRAINT {drop_constraint.group(1)}\b")
        return

    drop_column = re.match(r"DROP COLUMN (\w+)", action, flags=re.IGNORECASE)
    if drop_column is not None:
        _discard_matching(definitions, rf"{drop_column.group(1)}\b")
        return

    # ALTER COLUMN ... SET/DROP DEFAULT. Added when a migration first changed a default —
    # `finding_reviews.reviewed_at` from now() to clock_timestamp() — and this checker reported the
    # models and the migrations as disagreeing because it replayed every other kind of ALTER and
    # silently ignored this one. The type and nullability are not restated in this form of the
    # statement, so the existing definition is rewritten rather than replaced.
    default = re.match(
        r"ALTER COLUMN (\w+) (?:SET DEFAULT (.+)|DROP DEFAULT)$", action, flags=re.IGNORECASE
    )
    if default is not None:
        column, expression = default.group(1), default.group(2)
        for definition in [
            item for item in definitions if re.match(rf"{column}\b", item, flags=re.IGNORECASE)
        ]:
            definitions.discard(definition)
            suffix = " NOT NULL" if definition.upper().endswith(" NOT NULL") else ""
            body = definition[: len(definition) - len(suffix)] if suffix else definition
            body = re.sub(r"\s+DEFAULT\s+.*$", "", body, flags=re.IGNORECASE)
            rebuilt = body if expression is None else f"{body} DEFAULT {expression}"
            definitions.add(_normalize(f"{rebuilt}{suffix}"))
        return

    # ALTER COLUMN ... DROP/SET NOT NULL. The column keeps its type and only its nullability
    # changes, so the existing definition is rewritten rather than replaced -- the type is not
    # restated in this form of the statement and cannot be recovered from it.
    nullability = re.match(r"ALTER COLUMN (\w+) (DROP|SET) NOT NULL", action, flags=re.IGNORECASE)
    if nullability is not None:
        column, direction = nullability.group(1), nullability.group(2).upper()
        for definition in [
            item for item in definitions if re.match(rf"{column}\b", item, flags=re.IGNORECASE)
        ]:
            definitions.discard(definition)
            without = re.sub(r"\s+NOT NULL$", "", definition, flags=re.IGNORECASE)
            definitions.add(without if direction == "DROP" else f"{without} NOT NULL")


def _discard_matching(definitions: set[str], pattern: str) -> None:
    for definition in [
        item for item in definitions if re.match(pattern, item, flags=re.IGNORECASE)
    ]:
        definitions.discard(definition)


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
