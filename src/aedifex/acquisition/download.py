"""Turning an open response into a file on disk with an identity that can be checked.

The fetch layer's job ends with a response whose body has not been read. This module's job is
everything between that and a file that is safe to store:

.. code-block:: text

    an open response
        ↓  stream to a temporary file, hashing and sizing as the bytes go past
        ↓  no buffering: the payload is never held in memory
        ↓  compare what arrived against what was declared
        ↓  decide what the bytes actually are, and refuse if the source may not serve it
        ↓  atomically move into place under a content-addressed name
    DownloadedFile — path, digest, size, format, provenance

Four properties, each of which is a defect if inverted.

**Nothing is buffered.** The body is consumed chunk by chunk and written as it arrives, so a
256 MiB tender document costs one chunk of memory rather than 256 MiB. The digest is computed on
the same pass, because reading the file again to hash it would leave a window in which the bytes on
disk and the digest that identifies them could disagree.

**A partial download never survives.** Every failure path deletes the temporary file. A truncated
PDF that looks like a document is worse than no document: it would be stored, catalogued, and
eventually cited as evidence.

**The declared length is checked, not trusted.** A response that promised more bytes than it
delivered is a truncation, and a truncation that is silently accepted becomes a corrupt artifact
with a valid-looking digest. The comparison is skipped when the body was content-encoded, because
``Content-Length`` then describes the compressed size and a mismatch is expected rather than
suspicious.

**The format is resolved from the bytes, not the headers.** Portals routinely answer a request for
``tender.pdf`` with an HTML session-expiry page and HTTP 200. :func:`resolve_format` is what stops
that being stored as a construction document, and it is given the magic bytes as ground truth.

What this module deliberately does not do: it does not fetch (the caller hands it an open
response), it does not upload (that is the storage layer), and it does not record anything in a
database. Each of those is a separate boundary with its own failure modes, and a downloader that
did all four would have no testable seam between them.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final, Protocol, runtime_checkable
from urllib.parse import unquote, urlsplit

from aedifex.acquisition.content import (
    ContentAccumulator,
    ContentIdentity,
    resolve_format,
    safe_filename,
)
from aedifex.acquisition.fetch.controller import AttemptRecord
from aedifex.acquisition.fetch.transport import (
    DEFAULT_CHUNK_SIZE,
    DEFAULT_MAX_RESPONSE_BYTES,
    RawResponse,
)
from aedifex.acquisition.registry.models import SourceDefinition
from aedifex.domain.files import (
    FORMATS_WITH_A_SIGNATURE,
    FileFormat,
    canonical_extension,
)
from aedifex.errors import UnsafeContentError
from aedifex.infrastructure.storage.keys import raw_key

__all__ = [
    "DownloadPolicy",
    "DownloadedFile",
    "FetchedResponse",
    "download",
    "filename_from_disposition",
]

_ENCODING_PARAMETER: Final[str] = "utf-8''"


@runtime_checkable
class FetchedResponse(Protocol):
    """What the downloader needs from a fetch, and nothing more.

    A protocol rather than an import of
    :class:`~aedifex.acquisition.fetch.redirect_controller.ChainResult`, which satisfies it
    structurally. Two reasons: the downloader has no business knowing whether redirects were
    involved, and a test can hand it a response without standing up the fetch stack.
    """

    @property
    def response(self) -> RawResponse: ...

    @property
    def requested_url(self) -> str: ...

    @property
    def final_url(self) -> str: ...

    @property
    def attempts(self) -> tuple[AttemptRecord, ...]: ...


@dataclass(frozen=True, slots=True)
class DownloadPolicy:
    """What a source is allowed to yield, and how much of it.

    ``allowed_formats`` comes from the source's registry entry, so widening what a portal may
    serve is a configuration change with a review, not a code change.
    """

    allowed_formats: frozenset[FileFormat]
    max_bytes: int = DEFAULT_MAX_RESPONSE_BYTES

    def __post_init__(self) -> None:
        if not self.allowed_formats:
            raise ValueError(
                "allowed_formats must not be empty; a source that may serve nothing cannot be "
                "downloaded from, and an empty set would fail later with a confusing reason"
            )
        if self.max_bytes <= 0:
            raise ValueError(f"max_bytes must be positive, got {self.max_bytes}")

    @classmethod
    def from_source(
        cls, source: SourceDefinition, *, max_bytes: int | None = None
    ) -> DownloadPolicy:
        return cls(
            allowed_formats=frozenset(source.file_formats),
            max_bytes=max_bytes if max_bytes is not None else DEFAULT_MAX_RESPONSE_BYTES,
        )


@dataclass(frozen=True, slots=True)
class DownloadedFile:
    """A file on disk, its identity, and where it came from.

    Everything the storage and provenance layers need, assembled once at the point where all of
    it is known. The URL that was requested and the URL that answered are both kept, because a
    document retrieved after three redirects has a different provenance story from one retrieved
    directly, and only one of those two URLs appears in either version.
    """

    path: Path
    identity: ContentIdentity
    file_format: FileFormat
    storage_key: str
    source_id: str
    requested_url: str
    final_url: str
    filename: str
    """A sanitised basename, for humans. Never used to build a path — keys come from the digest."""
    declared_media_type: str | None
    declared_content_length: int | None
    http_status: int
    http_version: str
    response_headers: tuple[tuple[str, str], ...]
    attempts: tuple[AttemptRecord, ...]
    retrieved_at: datetime

    @property
    def sha256(self) -> str:
        return self.identity.sha256

    @property
    def size_bytes(self) -> int:
        return self.identity.size_bytes

    def describe(self) -> str:
        """One line for a log. Never includes a body."""
        return (
            f"{self.filename} ({self.file_format.value}, {self.size_bytes} bytes, "
            f"sha256={self.identity.short_digest()}) from {self.final_url}"
        )


def download(
    fetched: FetchedResponse,
    *,
    source_id: str,
    policy: DownloadPolicy,
    directory: Path,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
) -> DownloadedFile:
    """Stream ``fetched``'s body into ``directory`` and return what was stored.

    The body is consumed here, so this may be called once per response and the caller's ``with``
    block must still be open.

    On success the file sits at ``directory/<sha256><ext>``. Content-addressed, so downloading the
    same bytes twice converges on one file rather than accumulating copies, and the final move is
    atomic — a reader never sees a partially written document under that name.

    Args:
        fetched: An open response, body unread.
        source_id: The source being downloaded from, for the storage key.
        policy: Permitted formats and the size ceiling.
        directory: Staging directory. Created if absent; the temporary file is written inside it so
            the final move stays on one filesystem and therefore stays atomic.
        chunk_size: Read granularity. Bounds memory, not correctness.

    Raises:
        UnsafeContentError: if the payload is empty, exceeds ``policy.max_bytes``, is shorter than
            the server declared, or is not a format this source may serve.
        TransportError: if the body fails mid-stream. Propagated as-is — the retry controller
            classified what it could before handing the response over, and a stream that broke
            after the first byte is not something this layer can decide about.

    Every failure removes the temporary file before propagating.
    """
    response = fetched.response
    directory.mkdir(parents=True, exist_ok=True)

    accumulator = ContentAccumulator(max_bytes=policy.max_bytes)
    handle = tempfile.NamedTemporaryFile(  # noqa: SIM115 - closed explicitly below
        dir=directory, prefix=".partial-", delete=False
    )
    temporary = Path(handle.name)
    try:
        with handle:
            for chunk in response.iter_bytes(chunk_size):
                # Counted before it is written, so a chunk that breaches the ceiling is never
                # persisted at all. The order matters: the reverse would leave the limit
                # exceeded on disk by exactly one chunk.
                accumulator.update(chunk)
                handle.write(chunk)
        identity = accumulator.finish()
        _check_declared_length(response, identity)
        file_format = _resolve(response, fetched.final_url, policy, identity)
        final = _place(temporary, directory, identity, file_format)
    except BaseException:
        # BaseException, not Exception: a KeyboardInterrupt during a long download must not leave
        # a half-written document behind either.
        temporary.unlink(missing_ok=True)
        raise

    return DownloadedFile(
        path=final,
        identity=identity,
        file_format=file_format,
        storage_key=raw_key(source_id=source_id, sha256=identity.sha256, file_format=file_format),
        source_id=source_id,
        requested_url=fetched.requested_url,
        final_url=fetched.final_url,
        filename=safe_filename(
            _remote_filename(response.headers.get("content-disposition"), fetched.final_url),
            fallback_format=file_format,
        ),
        declared_media_type=response.headers.get("content-type"),
        declared_content_length=response.declared_content_length,
        http_status=response.status_code,
        http_version=response.http_version,
        response_headers=response.headers.items,
        attempts=fetched.attempts,
        retrieved_at=datetime.now(UTC),
    )


def _check_declared_length(response: RawResponse, identity: ContentIdentity) -> None:
    """Refuse a body shorter than the server said it would be.

    Skipped when the body was content-encoded: ``Content-Length`` then counts the compressed
    bytes while we counted the decompressed ones, so a mismatch there is arithmetic rather than
    truncation. Measured rather than assumed — httpx decodes transparently, so the size we see is
    always the decoded one.
    """
    declared = response.declared_content_length
    if declared is None:
        return
    encoding = (response.headers.get("content-encoding") or "identity").strip().lower()
    if encoding not in {"", "identity"}:
        return
    if identity.size_bytes != declared:
        raise UnsafeContentError(
            f"body is {identity.size_bytes} bytes but Content-Length declared {declared}; "
            "a truncated document with a valid digest is worse than no document"
        )


def _resolve(
    response: RawResponse,
    final_url: str,
    policy: DownloadPolicy,
    identity: ContentIdentity,
) -> FileFormat:
    """Decide what the bytes are, weighing the magic bytes above anything the server said.

    Two checks, and the second is the one that closes the case the module docstring promises.
    :func:`resolve_format` weighs the declared signals against a *confirmed* format, and can only
    see a contradiction when the content sniffs as something recognisable — but HTML has no magic
    bytes. A session-expiry page served as ``application/pdf`` for a ``.pdf`` URL therefore sniffs
    as nothing, every declared signal agrees, and it resolves cleanly as a PDF.

    So the absence of a signature is treated as evidence here, where it is known that the bytes
    *were* examined: a PDF always begins with ``%PDF-``, so a payload declared as one that carries
    no signature is something else. Only for the formats that always have one — for CSV, JSON, XML,
    and HTML there is nothing to be missing.
    """
    resolved = resolve_format(
        allowed=policy.allowed_formats,
        media_type=response.headers.get("content-type"),
        filename=_remote_filename(response.headers.get("content-disposition"), final_url),
        sniffed=identity.sniffed_format,
    )
    if identity.sniffed_format is None and resolved in FORMATS_WITH_A_SIGNATURE:
        raise UnsafeContentError(
            f"content resolved to {resolved.value} but carries no {resolved.value} signature; "
            f"a {resolved.value} always begins with one, so these bytes are something else — most "
            "often an HTML error or login page answered with HTTP 200"
        )
    return resolved


def _place(
    temporary: Path, directory: Path, identity: ContentIdentity, file_format: FileFormat
) -> Path:
    """Move the finished file to its content-addressed name, atomically.

    ``replace`` rather than ``rename``: an existing file under this name holds the same bytes by
    construction, since the name *is* the digest, so overwriting is idempotent rather than
    destructive. Doing nothing instead would be equally correct and would hide a partial file left
    by an interrupted earlier run.
    """
    destination = directory / f"{identity.sha256}{canonical_extension(file_format)}"
    temporary.replace(destination)
    return destination


def _remote_filename(disposition: str | None, final_url: str) -> str | None:
    """The name the server suggested, or the URL's last path segment.

    Both are untrusted and neither is used to build a path; the result is descriptive metadata,
    sanitised by :func:`~aedifex.acquisition.content.safe_filename` before it is kept.
    """
    from_header = filename_from_disposition(disposition)
    if from_header is not None:
        return from_header
    path = urlsplit(final_url).path
    segment = path.rsplit("/", 1)[-1]
    return segment or None


def filename_from_disposition(value: str | None) -> str | None:
    """Extract a filename from a ``Content-Disposition`` header, or ``None``.

    Handles both forms in RFC 6266: the plain ``filename="..."`` parameter and the extended
    ``filename*=UTF-8''...`` one, which is percent-encoded and takes precedence because it is the
    form that can carry a name outside ASCII. Anything else is treated as absent — this is a
    hostile input, and guessing at a malformed header is how a parser becomes an attack surface.

    The result is deliberately *not* sanitised here. That is
    :func:`~aedifex.acquisition.content.safe_filename`'s job, and splitting the two keeps one
    place responsible for deciding what characters may survive.
    """
    if not value:
        return None
    for parameter in _parameters(value):
        name, _, raw = parameter.partition("=")
        if name.strip().lower() != "filename*":
            continue
        candidate = raw.strip()
        if candidate.lower().startswith(_ENCODING_PARAMETER):
            return unquote(candidate[len(_ENCODING_PARAMETER) :]) or None
    for parameter in _parameters(value):
        name, _, raw = parameter.partition("=")
        if name.strip().lower() != "filename":
            continue
        return raw.strip().strip('"') or None
    return None


def _parameters(value: str) -> list[str]:
    """Split a header value on semicolons that are not inside a quoted string.

    A filename may legitimately contain a semicolon inside quotes, and splitting naively would cut
    it in half — producing a different name than the server sent, which is the one thing this
    function exists to avoid.
    """
    parts: list[str] = []
    current: list[str] = []
    quoted = False
    for character in value:
        if character == '"':
            quoted = not quoted
        if character == ";" and not quoted:
            parts.append("".join(current))
            current = []
            continue
        current.append(character)
    parts.append("".join(current))
    return parts
