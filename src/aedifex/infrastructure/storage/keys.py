"""Object-storage key layout.

Raw downloads are immutable and content-addressed. The key for a payload is derived
entirely from its SHA-256 digest and the source it came from, which gives three properties
the pipeline depends on:

* **Idempotent writes.** Re-running a crawl recomputes the same key, so a re-download
  overwrites itself byte-for-byte instead of creating a second copy (FR-014).
* **No attacker-controlled paths.** Remote filenames never appear in keys, so a hostile
  ``Content-Disposition`` cannot escape the prefix (SECURITY.md, path traversal).
* **Cheap sharding.** The two-character digest prefix spreads objects evenly, which keeps
  listing and lifecycle operations manageable as the corpus grows.

Derived artifacts (parsed text, OCR output, normalized records) are written under separate
top-level prefixes keyed by the same digest, so every processed artifact can be traced back
to the exact raw bytes it came from, and raw bytes are never mutated in place.
"""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Final

from aedifex.domain.files import FileFormat, canonical_extension

__all__ = ["StorageTier", "derived_key", "raw_key"]

_SHA256_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{64}$")
_SOURCE_ID_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[a-z][a-z0-9_]*$")
_STAGE_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[a-z][a-z0-9_]*$")


class StorageTier(StrEnum):
    """Top-level prefixes. ``RAW`` is write-once; the others are regenerable."""

    RAW = "raw"
    PROCESSED = "processed"
    NORMALIZED = "normalized"
    LABELED = "labeled"
    SYNTHETIC = "synthetic"


def raw_key(*, source_id: str, sha256: str, file_format: FileFormat) -> str:
    """Return the immutable storage key for a raw downloaded document.

    The layout is ``raw/<source_id>/<aa>/<bb>/<digest><ext>``, where ``aa``/``bb`` are the
    first two digest byte-pairs.

    Note that the key contains no timestamp. Wall-clock partitioning was rejected
    deliberately: the same document re-downloaded next month must land on the same key, and
    a digest-only path is what makes that true. Discovery and download times are recorded in
    the metadata database, which is where time-based queries belong.

    Raises:
        ValueError: if ``source_id`` or ``sha256`` is malformed.
    """
    _validate_source_id(source_id)
    _validate_digest(sha256)
    extension = canonical_extension(file_format)
    return f"{StorageTier.RAW.value}/{source_id}/{sha256[:2]}/{sha256[2:4]}/{sha256}{extension}"


def derived_key(
    *,
    tier: StorageTier,
    sha256: str,
    stage: str,
    extension: str,
) -> str:
    """Return the storage key for an artifact derived from a raw document.

    Args:
        tier: Destination tier. ``RAW`` is rejected, because raw bytes are write-once and
            derived output must never be able to overwrite its own input.
        sha256: Digest of the *raw source document*, tying the artifact to its origin.
        stage: Pipeline stage that produced it, e.g. ``"pdf_text"`` or ``"ocr"``.
        extension: Artifact extension, with or without a leading dot.

    Raises:
        ValueError: if any argument is malformed or ``tier`` is ``RAW``.
    """
    if tier is StorageTier.RAW:
        raise ValueError("derived artifacts cannot be written to the immutable raw tier")
    _validate_digest(sha256)
    if not _STAGE_PATTERN.match(stage):
        raise ValueError(f"stage must be lower_snake_case, got {stage!r}")

    normalized_extension = extension.strip().lower().lstrip(".")
    if not normalized_extension or not normalized_extension.isalnum():
        raise ValueError(f"extension must be alphanumeric, got {extension!r}")

    return f"{tier.value}/{stage}/{sha256[:2]}/{sha256[2:4]}/{sha256}.{normalized_extension}"


def _validate_digest(sha256: str) -> None:
    if not _SHA256_PATTERN.match(sha256):
        raise ValueError(f"not a lowercase hex sha-256 digest: {sha256!r}")


def _validate_source_id(source_id: str) -> None:
    if not _SOURCE_ID_PATTERN.match(source_id):
        raise ValueError(f"source_id must be lower_snake_case, got {source_id!r}")
