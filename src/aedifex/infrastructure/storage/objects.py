"""Putting a downloaded document into object storage, and proving it arrived intact.

The raw tier is write-once and content-addressed, which together give the two properties this
module is built around:

.. code-block:: text

    key = raw/<source>/<aa>/<bb>/<sha256><ext>      the digest *is* the address
        ↓
    already there with the same digest?  →  yes  →  nothing to do, and that is the correct answer
        ↓ no
    upload with the SHA-256 attached, so the *server* rejects a corrupted body
        ↓
    read the metadata back and compare
    StoredObject — bucket, key, version, size, and how the verification was done

**Idempotence comes from the key, not from a flag.** Re-running a crawl recomputes the same key from
the same bytes, so a second upload is either unnecessary or a no-op. It is skipped rather than
repeated: uploading 200 MiB again to overwrite it with itself costs bandwidth and proves nothing.

**A key that already holds different bytes is a refusal, never an overwrite.** The key contains the
digest, so the only ways this can happen are corruption in the store or something else having
written there. Both are situations to stop and look at, and overwriting would destroy the evidence
of whichever it was.

**Verification asks the server, not ourselves.** The upload carries an ``x-amz-checksum-sha256``, so
the store computes the digest independently and rejects the request if it disagrees — a corrupted
body fails at the store rather than being stored and trusted. Reading it back afterwards confirms
what is durably there. Echoing our own metadata back to ourselves would verify nothing but that the
round trip preserved a string we wrote.

That is measured rather than assumed, because the assumption was doubtful in a specific way: the
body here is an open file handle, and botocore's checksum handling for a stream is not obviously
the same as for a ``bytes`` payload. Probed against MinIO, both forms are rejected with
``XAmzContentChecksumMismatch``, and ``head_object`` returns the store's own checksum — so the
strong verification is the one that actually happens rather than the one that was hoped for. A
store returning no checksum downgrades the claim to :attr:`Verification.SIZE_AND_METADATA` rather
than silently presenting it as equivalent.

The client is injected. Not for testability — although the unit tests use a fake — but because
credentials, endpoints, and retry configuration are the caller's concern, and a module that builds
its own client from ambient settings cannot be told to talk to a different bucket.
"""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Final, Protocol, runtime_checkable

from botocore.exceptions import ClientError

from aedifex.domain.files import MEDIA_TYPES_BY_FORMAT
from aedifex.errors import AedifexError
from aedifex.infrastructure.storage.keys import StorageTier

if TYPE_CHECKING:  # pragma: no cover - typing only
    from mypy_boto3_s3.client import S3Client

    from aedifex.domain.files import FileFormat

__all__ = [
    "ObjectMetadata",
    "RawObjectStore",
    "StorableFile",
    "StorageError",
    "StoredObject",
    "Verification",
]

_SHA256_METADATA_KEY: Final[str] = "sha256"
"""Our own copy of the digest, alongside the server's checksum.

Redundant on purpose and cheap: the server's checksum is the verification, but a digest in plain
metadata is readable by anything that can list the bucket — including a human with the console open
and no tooling.
"""

_NOT_FOUND_CODES: Final[frozenset[str]] = frozenset({"404", "NoSuchKey", "NotFound"})


class StorageError(AedifexError):
    """An object could not be stored or retrieved, or what came back was not what went in."""


class Verification(StrEnum):
    """How an upload was confirmed."""

    SERVER_CHECKSUM = "server_checksum"
    """The store returned its own SHA-256 and it matched. The strong case."""
    SIZE_AND_METADATA = "size_and_metadata"
    """The store returned no checksum, so only the size and our own recorded digest were compared.

    A weaker claim, and reported as such rather than presented as equivalent. It means the store
    does not support checksum retrieval, not that the object is suspect.
    """


@dataclass(frozen=True, slots=True)
class ObjectMetadata:
    """What the store says about an object, without reading its body."""

    key: str
    size_bytes: int
    etag: str | None
    version_id: str | None
    sha256: str | None
    """From the store's own checksum if it provides one, else from our metadata."""
    checksum_from_server: bool


@dataclass(frozen=True, slots=True)
class StoredObject:
    """A document that is durably in the raw tier, and the evidence that it is."""

    bucket: str
    key: str
    sha256: str
    size_bytes: int
    version_id: str | None
    etag: str | None
    verification: Verification
    already_present: bool
    """True when the bytes were already there. A re-run reports this rather than a fresh upload."""

    @property
    def uri(self) -> str:
        return f"s3://{self.bucket}/{self.key}"

    def describe(self) -> str:
        state = "already present" if self.already_present else "uploaded"
        version = f" version={self.version_id}" if self.version_id else ""
        return f"{state} {self.uri}{version} ({self.size_bytes} bytes, {self.verification.value})"


@runtime_checkable
class StorableFile(Protocol):
    """What :meth:`RawObjectStore.put` actually requires of a file.

    Structural rather than a concrete class, because bytes reach the raw tier by more than one
    route: the crawler produces a ``DownloadedFile`` with an HTTP story attached, and manual
    ingestion produces an upload that has no HTTP story at all. Both are files with a digest, a size
    and a storage key, and that is all this class needs in order to store and verify one.

    Introduced so an upload does not have to invent a request that never happened in order to be
    stored. Nothing about the raw tier's guarantees changes: the key is still checked for the raw
    prefix, the digest is still sent to the server for verification, and the round trip is still
    read back.
    """

    @property
    def path(self) -> Path: ...

    @property
    def sha256(self) -> str: ...

    @property
    def size_bytes(self) -> int: ...

    @property
    def storage_key(self) -> str: ...

    @property
    def source_id(self) -> str: ...

    @property
    def file_format(self) -> FileFormat: ...

    @property
    def final_url(self) -> str:
        """Where the bytes came from, as a URI. ``file://`` for an ingested local file."""
        ...


class RawObjectStore:
    """The immutable raw tier of an S3-compatible bucket.

    Deliberately has no delete and no overwrite. Raw bytes are the evidence everything downstream
    cites; a module that could remove them would eventually be asked to.
    """

    def __init__(self, client: S3Client, *, bucket: str) -> None:
        if not bucket.strip():
            raise ValueError("bucket must be a non-empty name")
        self._client = client
        self._bucket = bucket

    @property
    def bucket(self) -> str:
        return self._bucket

    def put(self, downloaded: StorableFile) -> StoredObject:
        """Store ``downloaded`` in the raw tier, verify it, and return where it went.

        Idempotent: if the key already holds an object with the same digest and size, nothing is
        uploaded and the result reports ``already_present``.

        Raises:
            StorageError: if the key already holds *different* bytes, if the store rejects the
                upload, or if what is read back afterwards does not match what was sent.
            ValueError: if the file's storage key is not in the raw tier — which would mean it was
                built by something other than ``raw_key`` and has not been checked for the
                properties this class depends on.
        """
        key = downloaded.storage_key
        if not key.startswith(f"{StorageTier.RAW.value}/"):
            raise ValueError(
                f"storage key {key!r} is not in the {StorageTier.RAW.value!r} tier; this class "
                "stores immutable raw documents and derived output belongs elsewhere"
            )

        existing = self.head(key)
        if existing is not None:
            return self._confirm_existing(downloaded, existing)

        self._upload(downloaded, key)

        stored = self.head(key)
        if stored is None:
            raise StorageError(
                f"{key} was uploaded but is not there when read back; the store accepted a write "
                "it did not keep"
            )
        verification = self._verify(downloaded, stored)
        return StoredObject(
            bucket=self._bucket,
            key=key,
            sha256=downloaded.sha256,
            size_bytes=stored.size_bytes,
            version_id=stored.version_id,
            etag=stored.etag,
            verification=verification,
            already_present=False,
        )

    def head(self, key: str) -> ObjectMetadata | None:
        """Return what the store knows about ``key``, or ``None`` if it holds nothing.

        Raises:
            StorageError: for any error other than "not there". A permissions failure must not be
                mistaken for an absent object, which would turn a misconfiguration into a silent
                re-upload of the entire corpus.
        """
        try:
            response = self._client.head_object(
                Bucket=self._bucket, Key=key, ChecksumMode="ENABLED"
            )
        except ClientError as error:
            if _is_not_found(error):
                return None
            raise StorageError(f"could not read metadata for {key}: {error}") from error

        encoded = response.get("ChecksumSHA256")
        metadata = response.get("Metadata") or {}
        return ObjectMetadata(
            key=key,
            size_bytes=int(response.get("ContentLength", 0)),
            etag=_clean_etag(response.get("ETag")),
            version_id=response.get("VersionId"),
            sha256=_decode_checksum(encoded) or metadata.get(_SHA256_METADATA_KEY),
            checksum_from_server=_decode_checksum(encoded) is not None,
        )

    def download_to(self, key: str, destination: Path) -> Path:
        """Retrieve ``key`` into ``destination`` and return it.

        The other half of the round trip: an object that cannot be read back is not stored,
        whatever the upload reported. The caller is expected to re-hash the file — this deliberately
        does not, so the check and the fetch are not the same code trusting itself.

        Raises:
            StorageError: if the object is missing or cannot be read.
        """
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._client.download_file(self._bucket, key, str(destination))
        except ClientError as error:
            raise StorageError(f"could not retrieve {key}: {error}") from error
        return destination

    def ensure_bucket(self) -> None:
        """Create the bucket if absent and turn versioning on.

        For development and tests. Production buckets are created with their retention and lifecycle
        policies by whatever provisions infrastructure, and a client that quietly creates buckets is
        a client that hides a misconfigured name.

        Versioning is what makes the write-once claim enforceable rather than merely intended: even
        if something overwrote a raw object, the previous version would still be there.
        """
        try:
            self._client.head_bucket(Bucket=self._bucket)
        except ClientError as error:
            if not _is_not_found(error):
                raise StorageError(f"could not inspect bucket {self._bucket}: {error}") from error
            self._client.create_bucket(Bucket=self._bucket)
        self._client.put_bucket_versioning(
            Bucket=self._bucket, VersioningConfiguration={"Status": "Enabled"}
        )

    def versioning_enabled(self) -> bool:
        """Whether the bucket keeps previous versions."""
        try:
            response = self._client.get_bucket_versioning(Bucket=self._bucket)
        except ClientError as error:
            raise StorageError(f"could not read versioning for {self._bucket}: {error}") from error
        return response.get("Status") == "Enabled"

    def _upload(self, downloaded: StorableFile, key: str) -> None:
        """Send the file, with the digest attached so the store validates it for us."""
        try:
            with downloaded.path.open("rb") as handle:
                self._client.put_object(
                    Bucket=self._bucket,
                    Key=key,
                    Body=handle,
                    ContentType=_media_type_for(downloaded),
                    ChecksumAlgorithm="SHA256",
                    ChecksumSHA256=_encode_digest(downloaded.sha256),
                    Metadata={
                        _SHA256_METADATA_KEY: downloaded.sha256,
                        "source-id": downloaded.source_id,
                        "file-format": downloaded.file_format.value,
                        "final-url": downloaded.final_url[:1024],
                    },
                )
        except ClientError as error:
            raise StorageError(f"could not store {key}: {error}") from error

    def _confirm_existing(self, downloaded: StorableFile, existing: ObjectMetadata) -> StoredObject:
        """Decide whether an object already at this key is the one we have.

        The key contains the digest, so a mismatch is not a routine collision — it is corruption or
        an unrelated write. Refusing is the only safe answer: overwriting would destroy the evidence
        of which it was.
        """
        if existing.size_bytes != downloaded.size_bytes:
            raise StorageError(
                f"{existing.key} already holds {existing.size_bytes} bytes but this document is "
                f"{downloaded.size_bytes}; the key contains the digest, so the stored object is "
                "corrupt or was written by something else. Refusing to overwrite it"
            )
        if existing.sha256 is not None and existing.sha256 != downloaded.sha256:
            raise StorageError(
                f"{existing.key} already holds a different digest ({existing.sha256}); refusing to "
                "overwrite an immutable raw object"
            )
        return StoredObject(
            bucket=self._bucket,
            key=existing.key,
            sha256=downloaded.sha256,
            size_bytes=existing.size_bytes,
            version_id=existing.version_id,
            etag=existing.etag,
            verification=(
                Verification.SERVER_CHECKSUM
                if existing.checksum_from_server
                else Verification.SIZE_AND_METADATA
            ),
            already_present=True,
        )

    def _verify(self, downloaded: StorableFile, stored: ObjectMetadata) -> Verification:
        """Compare what the store now holds against what was sent.

        Raises:
            StorageError: on any disagreement.
        """
        if stored.size_bytes != downloaded.size_bytes:
            raise StorageError(
                f"{stored.key} is {stored.size_bytes} bytes in the store but "
                f"{downloaded.size_bytes} were sent"
            )
        if stored.sha256 is None:
            raise StorageError(
                f"{stored.key} came back with neither a checksum nor a recorded digest, so the "
                "upload cannot be confirmed. An unverifiable object is not a stored one"
            )
        if stored.sha256 != downloaded.sha256:
            raise StorageError(
                f"{stored.key} has digest {stored.sha256} in the store but {downloaded.sha256} "
                "was sent"
            )
        return (
            Verification.SERVER_CHECKSUM
            if stored.checksum_from_server
            else Verification.SIZE_AND_METADATA
        )


def _media_type_for(downloaded: StorableFile) -> str:
    """The media type to store the object under.

    Our own resolved format, not the server's ``Content-Type`` header. The header was one input to
    that decision and is frequently wrong; storing it would carry a portal's mistake forward into
    every consumer of the bucket.
    """
    return MEDIA_TYPES_BY_FORMAT[downloaded.file_format][0]


def _encode_digest(sha256: str) -> str:
    """Hex digest to the base64 form S3 checksums use."""
    return base64.b64encode(bytes.fromhex(sha256)).decode("ascii")


def _decode_checksum(encoded: str | None) -> str | None:
    """Base64 checksum back to a hex digest, or ``None`` if absent or unusable.

    A malformed value is treated as absent rather than raising: it means this store's checksum
    cannot be used for verification, which downgrades the claim to size-and-metadata instead of
    failing a legitimate upload. The digest we sent is still what gets compared.
    """
    if not encoded:
        return None
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        return None
    return raw.hex() if len(raw) == 32 else None


def _clean_etag(etag: str | None) -> str | None:
    """Strip the quotes S3 wraps an ETag in."""
    return etag.strip('"') if etag else None


def _is_not_found(error: ClientError) -> bool:
    """Whether a client error means "no such object or bucket" rather than a real failure."""
    detail = error.response.get("Error")
    code = str(detail.get("Code", "")) if detail else ""
    metadata = error.response.get("ResponseMetadata")
    status = metadata.get("HTTPStatusCode") if metadata else None
    return code in _NOT_FOUND_CODES or status == 404
