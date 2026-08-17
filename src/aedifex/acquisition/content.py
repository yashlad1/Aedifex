"""Content identity and safety validation for downloaded bytes.

Two responsibilities, both deliberately free of I/O beyond the stream handed to them so
they can be exercised without a network or object store:

**Identity.** A document's identity is its content. :func:`hash_stream` computes a SHA-256
over the payload and derives a UUIDv5 document id from that digest, which makes ingestion
idempotent: re-downloading the same bytes from a different URL, or re-running a crawl,
yields the same id and therefore the same database row (FR-002, FR-014).

**Safety.** Every downloaded byte is untrusted. Payloads are size-capped *while streaming*
rather than after buffering, the declared media type is checked against the actual leading
bytes, and remote filenames are stripped to a safe basename before they ever reach a path.
"""

from __future__ import annotations

import hashlib
import io
import re
import unicodedata
import uuid
from collections.abc import Collection, Iterable
from dataclasses import dataclass
from typing import IO, Final

from aedifex.domain.files import (
    SNIFF_PREFIX_BYTES,
    FileFormat,
    canonical_extension,
    format_for_extension,
    format_for_media_type,
    formats_are_compatible,
    normalize_media_type,
    sniff_format,
)
from aedifex.errors import UnsafeContentError

__all__ = [
    "DOCUMENT_ID_NAMESPACE",
    "ContentIdentity",
    "digests_are_distinct",
    "document_id_for_digest",
    "hash_bytes",
    "hash_stream",
    "resolve_format",
    "safe_filename",
]

# uuid5(uuid.NAMESPACE_URL, "https://aedifex.dev/ns/document"). Pinned as a literal so the
# derivation cannot drift; ``tests/unit/test_content.py`` asserts it still matches.
DOCUMENT_ID_NAMESPACE: Final[uuid.UUID] = uuid.UUID("852e666c-780a-5903-85c4-d357129f3878")

_READ_CHUNK_BYTES: Final[int] = 1024 * 1024

_SHA256_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{64}$")

# Windows reserves these names regardless of extension; a stored object named after one
# would be unreadable if the corpus is ever mounted there.
_RESERVED_STEMS: Final[frozenset[str]] = frozenset(
    {
        "con",
        "prn",
        "aux",
        "nul",
        *(f"com{index}" for index in range(1, 10)),
        *(f"lpt{index}" for index in range(1, 10)),
    }
)

_UNSAFE_FILENAME_CHARS: Final[re.Pattern[str]] = re.compile(r"[^A-Za-z0-9._-]+")

_MAX_FILENAME_LENGTH: Final[int] = 128


@dataclass(frozen=True, slots=True)
class ContentIdentity:
    """The identity of a byte stream, derived entirely from its content."""

    sha256: str
    size_bytes: int
    document_id: uuid.UUID
    sniffed_format: FileFormat | None
    """Format confirmed from magic bytes, or ``None`` when unconfirmable (text formats)."""

    def short_digest(self, length: int = 12) -> str:
        """Return a truncated digest for log lines and human-facing references."""
        return self.sha256[:length]


def document_id_for_digest(sha256: str) -> uuid.UUID:
    """Derive the deterministic document id for a content digest.

    Raises:
        ValueError: if ``sha256`` is not a lowercase hex SHA-256 digest.
    """
    if not _SHA256_PATTERN.match(sha256):
        raise ValueError(f"not a lowercase hex sha-256 digest: {sha256!r}")
    return uuid.uuid5(DOCUMENT_ID_NAMESPACE, sha256)


def hash_stream(stream: IO[bytes], *, max_bytes: int) -> ContentIdentity:
    """Hash a byte stream, enforcing ``max_bytes`` as it reads.

    The cap is applied incrementally so a hostile or accidental multi-gigabyte response
    cannot exhaust memory or disk before being rejected.

    Raises:
        UnsafeContentError: if the payload exceeds ``max_bytes`` or is empty.
        ValueError: if ``max_bytes`` is not positive.
    """
    if max_bytes <= 0:
        raise ValueError(f"max_bytes must be positive, got {max_bytes}")

    digest = hashlib.sha256()
    size = 0
    prefix = bytearray()

    while chunk := stream.read(_READ_CHUNK_BYTES):
        size += len(chunk)
        if size > max_bytes:
            raise UnsafeContentError(
                f"payload exceeds the {max_bytes} byte limit (read {size} bytes so far)"
            )
        digest.update(chunk)
        if len(prefix) < SNIFF_PREFIX_BYTES:
            prefix.extend(chunk[: SNIFF_PREFIX_BYTES - len(prefix)])

    if size == 0:
        # An empty file is never valid evidence, and its digest would collide with every
        # other empty download, corrupting deduplication.
        raise UnsafeContentError("payload is empty")

    sha256 = digest.hexdigest()
    return ContentIdentity(
        sha256=sha256,
        size_bytes=size,
        document_id=document_id_for_digest(sha256),
        sniffed_format=sniff_format(bytes(prefix)),
    )


def hash_bytes(payload: bytes, *, max_bytes: int) -> ContentIdentity:
    """Hash an in-memory payload. See :func:`hash_stream` for the contract."""
    return hash_stream(io.BytesIO(payload), max_bytes=max_bytes)


def resolve_format(
    *,
    allowed: Collection[FileFormat],
    media_type: str | None = None,
    filename: str | None = None,
    sniffed: FileFormat | None = None,
) -> FileFormat:
    """Decide what a payload actually is, or reject it.

    Three signals are weighed. ``sniffed`` (magic bytes) is ground truth when present;
    ``media_type`` is the server's statement about the body; ``filename`` is the weakest,
    since URL extensions are frequently decorative.

    The check that matters most in practice is the mismatch case: portals routinely answer
    a request for ``report.pdf`` with an HTML session-expiry page and HTTP 200. Detecting
    that here is what stops a login page being stored as a construction document.

    Args:
        allowed: Formats the source is permitted to yield, from its registry definition.
        media_type: Raw ``Content-Type`` header value, if any.
        filename: Remote filename or URL basename, if any.
        sniffed: Format confirmed from magic bytes, from :class:`ContentIdentity`.

    Raises:
        UnsafeContentError: if the format cannot be determined, the signals contradict
            each other, or the result is not in ``allowed``.
        ValueError: if ``allowed`` is empty.
    """
    if not allowed:
        raise ValueError("allowed must contain at least one format")

    from_media_type = format_for_media_type(media_type) if media_type else None
    from_filename = format_for_extension(_extension_of(filename)) if filename else None

    # Contradiction between the two declared signals: the body is not what the URL
    # promised. Refuse rather than pick a winner.
    if (
        from_media_type is not None
        and from_filename is not None
        and not formats_are_compatible(from_filename, from_media_type)
        and not formats_are_compatible(from_media_type, from_filename)
    ):
        raise UnsafeContentError(
            f"declared media type {normalize_media_type(media_type or '')!r} "
            f"({from_media_type.value}) contradicts filename {filename!r} "
            f"({from_filename.value})"
        )

    declared = from_media_type or from_filename

    if sniffed is not None:
        if declared is None:
            resolved = sniffed
        elif formats_are_compatible(declared, sniffed):
            # Keep the more specific declared format: an .xlsx legitimately sniffs as ZIP.
            resolved = declared
        else:
            raise UnsafeContentError(
                f"content is actually {sniffed.value} but was declared as "
                f"{declared.value} (media_type={media_type!r}, filename={filename!r})"
            )
    elif declared is not None:
        resolved = declared
    else:
        raise UnsafeContentError(
            f"cannot determine format (media_type={media_type!r}, filename={filename!r}, "
            f"no recognisable magic bytes)"
        )

    if resolved not in allowed:
        permitted = ", ".join(sorted(item.value for item in allowed))
        raise UnsafeContentError(
            f"format {resolved.value!r} is not accepted from this source "
            f"(permitted: {permitted})"
        )
    return resolved


def safe_filename(candidate: str | None, *, fallback_format: FileFormat | None = None) -> str:
    """Reduce an untrusted remote filename to a safe basename.

    Remote filenames reach us from URLs and ``Content-Disposition`` headers and are
    attacker-controlled. This strips directory components, unicode trickery, and control
    characters, leaving a conservative ``[A-Za-z0-9._-]`` name. The result is only ever
    used as descriptive metadata; stored object paths are derived from content digests, so
    even a pathological name cannot influence where bytes land.

    Args:
        candidate: The untrusted name, or ``None``.
        fallback_format: Format whose canonical extension is appended when the candidate
            has no usable extension.

    Returns:
        A safe, non-empty filename. Falls back to ``"document"`` plus the fallback
        format's extension when nothing usable survives sanitisation.
    """
    stem_and_extension = _sanitize_filename(candidate)
    if stem_and_extension is None:
        base = "document"
        return f"{base}{canonical_extension(fallback_format)}" if fallback_format else base

    name = stem_and_extension
    if fallback_format is not None and format_for_extension(_extension_of(name)) is None:
        name = f"{name}{canonical_extension(fallback_format)}"
    return name


def _sanitize_filename(candidate: str | None) -> str | None:
    """Return a safe basename, or ``None`` if nothing usable remains."""
    if not candidate:
        return None

    # NFKC first so that width variants and compatibility characters normalise into ASCII
    # where possible, then drop anything still outside the allowlist.
    normalized = unicodedata.normalize("NFKC", candidate)

    # Take the basename against both separators: a Windows-style path arriving over HTTP
    # must not leave a "dir\name" component behind.
    for separator in ("/", "\\"):
        normalized = normalized.rsplit(separator, 1)[-1]

    normalized = normalized.replace("\x00", "")
    cleaned = _UNSAFE_FILENAME_CHARS.sub("_", normalized).strip("._-")
    if not cleaned:
        return None

    stem, dot, extension = cleaned.rpartition(".")
    if dot and stem.lower() in _RESERVED_STEMS:
        stem = f"{stem}_file"
        cleaned = f"{stem}.{extension}"
    elif not dot and cleaned.lower() in _RESERVED_STEMS:
        cleaned = f"{cleaned}_file"

    if len(cleaned) > _MAX_FILENAME_LENGTH:
        stem, dot, extension = cleaned.rpartition(".")
        if dot and len(extension) <= 8:
            keep = _MAX_FILENAME_LENGTH - len(extension) - 1
            cleaned = f"{stem[:keep]}.{extension}"
        else:
            cleaned = cleaned[:_MAX_FILENAME_LENGTH]
        cleaned = cleaned.strip("._-")

    return cleaned or None


def _extension_of(filename: str | None) -> str:
    """Return the lowercase extension of ``filename``, including the dot, or ``""``."""
    if not filename:
        return ""
    _, dot, extension = filename.rpartition(".")
    return f".{extension.lower()}" if dot else ""


def digests_are_distinct(digests: Iterable[str]) -> bool:
    """Return whether every digest in ``digests`` is unique.

    Used by dataset validation to assert a corpus contains no duplicate content.
    """
    seen: set[str] = set()
    for digest in digests:
        if digest in seen:
            return False
        seen.add(digest)
    return True
