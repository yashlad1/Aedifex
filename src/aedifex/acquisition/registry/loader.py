"""Loading and validation of the YAML source registry.

The loader is deliberately strict and deliberately verbose: registry mistakes are
configuration bugs that would otherwise surface as a crawler hitting the wrong host or
collecting data we have no right to. All problems found across all files are reported in a
single error rather than failing on the first one, because fixing a registry one exception
at a time is miserable.
"""

from __future__ import annotations

from collections.abc import Collection, Iterator, Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from aedifex.acquisition.registry.models import (
    RetrievalMethod,
    SourceDefinition,
    SourceFile,
)
from aedifex.config import Settings, get_settings
from aedifex.errors import SourceRegistryError

__all__ = ["SourceRegistry", "get_registry", "load_registry"]

_REGISTRY_GLOBS = ("*.yaml", "*.yml")


@dataclass(frozen=True, slots=True)
class SourceRegistry:
    """An immutable, validated collection of source definitions."""

    _by_id: Mapping[str, SourceDefinition]

    def get(self, source_id: str) -> SourceDefinition:
        """Return the source with ``source_id``.

        Raises:
            SourceRegistryError: if no such source is registered.
        """
        try:
            return self._by_id[source_id]
        except KeyError as error:
            known = ", ".join(sorted(self._by_id)) or "<empty registry>"
            raise SourceRegistryError(
                f"unknown source {source_id!r}; registered sources are: {known}"
            ) from error

    def all(self) -> tuple[SourceDefinition, ...]:
        """Return every source, ordered by id."""
        return tuple(self._by_id[key] for key in sorted(self._by_id))

    def collectable(self) -> tuple[SourceDefinition, ...]:
        """Return only the sources a crawl run may currently fetch from."""
        return tuple(source for source in self.all() if source.is_collectable)

    def __iter__(self) -> Iterator[SourceDefinition]:
        return iter(self.all())

    def __len__(self) -> int:
        return len(self._by_id)

    def __contains__(self, source_id: object) -> bool:
        return source_id in self._by_id


def load_registry(
    directory: Path,
    *,
    known_crawlers: Collection[str] | None = None,
) -> SourceRegistry:
    """Load and validate every registry file in ``directory``.

    Args:
        directory: Directory containing ``*.yaml`` / ``*.yml`` source definitions.
        known_crawlers: Crawler implementation names that exist. When provided, any
            enabled source naming an unregistered crawler is rejected. Passing ``None``
            skips the check, which is what callers that only need metadata (for example
            the read-only API) want.

    Raises:
        SourceRegistryError: if the directory is missing, contains no definitions, or any
            definition is invalid.
    """
    if not directory.is_dir():
        raise SourceRegistryError(f"source registry directory does not exist: {directory}")

    paths = sorted(
        {path for pattern in _REGISTRY_GLOBS for path in directory.glob(pattern) if path.is_file()}
    )
    if not paths:
        raise SourceRegistryError(
            f"no source definitions found in {directory} "
            f"(expected files matching {' or '.join(_REGISTRY_GLOBS)})"
        )

    by_id: dict[str, SourceDefinition] = {}
    declaring_file: dict[str, Path] = {}
    problems: list[str] = []

    for path in paths:
        parsed = _parse_yaml_file(path, problems)
        if parsed is None:
            continue

        try:
            source_file = SourceFile.model_validate(parsed)
        except ValidationError as error:
            problems.extend(_format_validation_error(path, parsed, error))
            continue

        for source in source_file.sources:
            if source.id in by_id:
                problems.append(
                    f"{path.name}: duplicate source id {source.id!r} "
                    f"(already defined in {declaring_file[source.id].name})"
                )
                continue
            by_id[source.id] = source
            declaring_file[source.id] = path

    if known_crawlers is not None:
        problems.extend(_check_crawlers_exist(by_id, declaring_file, known_crawlers))

    if problems:
        raise SourceRegistryError(
            f"invalid source registry in {directory} "
            f"({len(problems)} problem(s)):\n  - " + "\n  - ".join(problems)
        )

    return SourceRegistry(_by_id=by_id)


def _parse_yaml_file(path: Path, problems: list[str]) -> dict[str, Any] | None:
    """Parse one registry file, appending to ``problems`` and returning ``None`` on error."""
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as error:
        problems.append(f"{path.name}: cannot be read ({error.strerror or error})")
        return None
    except UnicodeDecodeError as error:
        problems.append(f"{path.name}: is not valid UTF-8 ({error.reason})")
        return None

    try:
        # safe_load only: registry files are configuration, but arbitrary object
        # construction is never an acceptable capability for a file-driven loader.
        document = yaml.safe_load(raw)
    except yaml.YAMLError as error:
        problems.append(f"{path.name}: is not valid YAML ({_compact(str(error))})")
        return None

    if document is None:
        problems.append(f"{path.name}: is empty")
        return None
    if not isinstance(document, dict):
        problems.append(
            f"{path.name}: must contain a mapping with a 'sources' key, "
            f"found {type(document).__name__}"
        )
        return None
    return document


def _check_crawlers_exist(
    by_id: Mapping[str, SourceDefinition],
    declaring_file: Mapping[str, Path],
    known_crawlers: Collection[str],
) -> list[str]:
    """Report enabled sources whose crawler implementation is not registered."""
    problems: list[str] = []
    for source_id, source in sorted(by_id.items()):
        if not source.enabled or source.retrieval is RetrievalMethod.MANUAL_UPLOAD:
            continue
        if source.crawler is not None and source.crawler not in known_crawlers:
            available = ", ".join(sorted(known_crawlers)) or "<none registered>"
            problems.append(
                f"{declaring_file[source_id].name}: source {source_id!r} is enabled but "
                f"crawler {source.crawler!r} is not registered (available: {available})"
            )
    return problems


def _format_validation_error(
    path: Path, parsed: Mapping[str, Any], error: ValidationError
) -> list[str]:
    """Render a pydantic error into one line per problem, naming the offending source."""
    raw_sources = parsed.get("sources")
    messages: list[str] = []

    for detail in error.errors():
        location = detail["loc"]
        label = path.name

        # Identify the source by id where possible; an index alone is hard to act on.
        if len(location) >= 2 and location[0] == "sources" and isinstance(location[1], int):
            index = location[1]
            source_id = _source_id_at(raw_sources, index)
            label = f"{path.name}: sources[{index}]"
            if source_id is not None:
                label = f"{path.name}: source {source_id!r}"
            field_path = ".".join(str(part) for part in location[2:])
        else:
            field_path = ".".join(str(part) for part in location)

        suffix = f" field {field_path!r}:" if field_path else ":"
        messages.append(f"{label}{suffix} {detail['msg']}")

    return messages


def _source_id_at(raw_sources: object, index: int) -> str | None:
    """Best-effort lookup of a source id from the unvalidated YAML payload."""
    if not isinstance(raw_sources, list) or index >= len(raw_sources):
        return None
    entry = raw_sources[index]
    if not isinstance(entry, dict):
        return None
    source_id = entry.get("id")
    return source_id if isinstance(source_id, str) else None


def _compact(message: str) -> str:
    """Collapse a multi-line library message into one line for aggregated reporting."""
    return " ".join(message.split())


@lru_cache(maxsize=1)
def _cached_registry(directory: Path) -> SourceRegistry:
    return load_registry(directory)


def get_registry(settings: Settings | None = None) -> SourceRegistry:
    """Return the registry configured for this process, loading it at most once.

    Tests should call :func:`load_registry` directly to avoid the cache.
    """
    resolved = settings or get_settings()
    return _cached_registry(Path(resolved.source_registry_dir))
