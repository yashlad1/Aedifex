"""Read and validate ``config/india_runner.yaml``, the India runner's run list.

The manifest names which already-approved sources this machine should run. It is deliberately
incapable of granting anything: every source it names is looked up in the real registry, and one
that is not both ``enabled`` and ``approved`` stops the run here with an explanation. That check is
a *second* refusal rather than the only one -- :class:`CrawlRunner` raises
``SourceNotCollectableError`` for the same case and nothing modifies state before it does. Failing
early exists so the operator reads one sentence instead of watching a crawl start and stop.

Three modes, all read-only:

.. code-block:: text

    check      validate the manifest and the registry; the run stops here if anything is wrong
    shell      emit the settings the shell stages need, already quoted
    sources    emit one line per source: id, then the CLI arguments for `aedifex-crawl crawl`

Errors print one human sentence and exit non-zero. Nothing here raises into an operator's terminal.
"""

from __future__ import annotations

import shlex
import sys
from pathlib import Path
from typing import Any, Final

import yaml
from pydantic import ValidationError

from aedifex.acquisition.registry import get_registry
from aedifex.acquisition.registry.models import SourceDefinition
from aedifex.config import Settings
from aedifex.errors import AedifexError

MANIFEST_PATH: Final[Path] = Path("config/india_runner.yaml")
SUPPORTED_SCHEMA: Final[int] = 1

# Limits the manifest may set per source, mapped to the flags `aedifex-crawl crawl` already accepts.
# Only these four: anything else an operator could vary is reviewed configuration and belongs in the
# registry, not in a run list.
_LIMIT_FLAGS: Final[dict[str, str]] = {
    "max_documents": "--max-documents",
    "max_pages": "--max-pages",
    "max_seconds": "--max-seconds",
    "batch_size": "--batch-size",
}


class ManifestError(Exception):
    """A manifest a human has to fix. The message is written for that human."""


class RunSource:
    """One entry in the run list, and the crawl arguments it produces."""

    def __init__(self, source_id: str, limits: dict[str, int]) -> None:
        self.source_id = source_id
        self.limits = limits

    def crawl_arguments(self) -> list[str]:
        args: list[str] = []
        for key, flag in _LIMIT_FLAGS.items():
            value = self.limits.get(key)
            if value is not None:
                args.extend([flag, str(value)])
        return args


class Manifest:
    """The validated run list."""

    def __init__(
        self, user_agent: str, bucket: str, endpoint_url: str, sources: list[RunSource]
    ) -> None:
        self.user_agent = user_agent
        self.bucket = bucket
        self.endpoint_url = endpoint_url
        self.sources = sources


def load(path: Path = MANIFEST_PATH) -> Manifest:
    """Parse and validate the manifest's own contents. The registry is not consulted here."""
    if not path.exists():
        raise ManifestError(f"The run list is missing: {path}")
    try:
        raw = yaml.safe_load(path.read_text())
    except yaml.YAMLError as error:
        raise ManifestError(f"The run list is not valid YAML: {_compact(str(error))}") from error
    if not isinstance(raw, dict):
        raise ManifestError(f"The run list must be a mapping, not {type(raw).__name__}.")

    schema = raw.get("schema_version")
    if schema != SUPPORTED_SCHEMA:
        raise ManifestError(
            f"The run list declares schema_version {schema!r}, but this runner understands "
            f"only {SUPPORTED_SCHEMA}. The runner and the run list are different versions."
        )

    user_agent = _validated_user_agent(raw.get("user_agent"))
    bucket, endpoint = _validated_storage(raw.get("storage"))
    return Manifest(user_agent, bucket, endpoint, _validated_sources(raw.get("sources")))


def _validated_user_agent(value: object) -> str:
    """Require a contact a site operator could actually reach, using the application's own test.

    Reusing ``Settings`` rather than pattern-matching here is the point: the placeholder rule is one
    rule with one implementation, and a second copy could drift into being more permissive.
    """
    if not isinstance(value, str) or not value.strip():
        raise ManifestError("The run list has no `user_agent`. See config/india_runner.yaml.")
    try:
        settings = Settings(user_agent=value)
    except ValidationError as error:
        raise ManifestError(
            f"The `user_agent` in the run list is not usable: {_compact(str(error))}"
        ) from error
    if not settings.user_agent_names_a_real_contact():
        raise ManifestError(
            "The `user_agent` in the run list still carries the placeholder contact address. "
            "A crawl of a real portal must offer a contact a site operator can reach "
            "(DATA_SOURCES.md lists this under hard limits). Set `user_agent` in "
            f"{MANIFEST_PATH} to a real URL and address, then commit it."
        )
    return value


def _validated_storage(value: object) -> tuple[str, str]:
    if not isinstance(value, dict):
        raise ManifestError("The run list has no `storage` section.")
    bucket = value.get("bucket")
    endpoint = value.get("endpoint_url")
    if not isinstance(bucket, str) or not bucket.strip():
        raise ManifestError("The run list has no `storage.bucket`.")
    if not isinstance(endpoint, str) or not endpoint.strip():
        raise ManifestError("The run list has no `storage.endpoint_url`.")
    return bucket, endpoint


def _validated_sources(value: object) -> list[RunSource]:
    if not isinstance(value, list) or not value:
        raise ManifestError("The run list names no sources under `sources`.")
    sources: list[RunSource] = []
    seen: set[str] = set()
    for index, entry in enumerate(value, start=1):
        if not isinstance(entry, dict):
            raise ManifestError(f"Source {index} in the run list is not a mapping.")
        source_id = entry.get("id")
        if not isinstance(source_id, str) or not source_id.strip():
            raise ManifestError(f"Source {index} in the run list has no `id`.")
        if source_id in seen:
            raise ManifestError(f"The run list names {source_id!r} twice.")
        seen.add(source_id)
        sources.append(RunSource(source_id, _validated_limits(source_id, entry)))
    return sources


def _validated_limits(source_id: str, entry: dict[str, Any]) -> dict[str, int]:
    limits: dict[str, int] = {}
    for key in entry:
        if key == "id":
            continue
        if key not in _LIMIT_FLAGS:
            raise ManifestError(
                f"Source {source_id!r} sets {key!r}, which is not a limit this runner accepts. "
                f"Allowed: {', '.join(sorted(_LIMIT_FLAGS))}."
            )
        raw = entry[key]
        if not isinstance(raw, int) or isinstance(raw, bool) or raw <= 0:
            raise ManifestError(
                f"Source {source_id!r} sets {key}={raw!r}; expected a whole number."
            )
        limits[key] = raw
    return limits


def check_collectable(manifest: Manifest) -> list[str]:
    """Confirm every named source is approved and enabled. Returns human-readable problems.

    This grants nothing. It reads the registry the crawler reads, and can only refuse.
    """
    problems: list[str] = []
    registry = get_registry()
    for source in manifest.sources:
        try:
            definition: SourceDefinition = registry.get(source.source_id)
        except AedifexError:
            problems.append(
                f"{source.source_id!r} is named in the run list but is not registered at all. "
                f"Sources are defined in config/sources/."
            )
            continue
        if not definition.is_collectable:
            problems.append(
                f"{source.source_id!r} may not be collected from: enabled="
                f"{definition.enabled}, verification_status="
                f"{definition.verification_status.value}. Its terms of use must be reviewed and "
                f"recorded in DATA_SOURCES.md before it can run. The runner cannot override this."
            )
    return problems


def _compact(message: str) -> str:
    return " ".join(message.split())[:300]


def _emit_shell(manifest: Manifest) -> None:
    print(f"INDIA_USER_AGENT={shlex.quote(manifest.user_agent)}")
    print(f"INDIA_STORAGE_BUCKET={shlex.quote(manifest.bucket)}")
    print(f"INDIA_STORAGE_ENDPOINT={shlex.quote(manifest.endpoint_url)}")
    print(f"INDIA_SOURCE_COUNT={len(manifest.sources)}")


def _emit_sources(manifest: Manifest) -> None:
    for source in manifest.sources:
        print(f"{source.source_id}\t{' '.join(source.crawl_arguments())}")


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    mode = arguments[0] if arguments else "check"
    if mode not in {"check", "shell", "sources"}:
        print(f"usage: {Path(__file__).name} [check|shell|sources]", file=sys.stderr)
        return 2
    try:
        manifest = load()
        if mode == "check":
            problems = check_collectable(manifest)
            if problems:
                for problem in problems:
                    print(problem, file=sys.stderr)
                return 3
            print(f"{len(manifest.sources)} source(s) approved and ready")
        elif mode == "shell":
            _emit_shell(manifest)
        else:
            _emit_sources(manifest)
    except ManifestError as error:
        print(str(error), file=sys.stderr)
        return 3
    except AedifexError as error:
        print(_compact(str(error)), file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
