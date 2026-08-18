"""Raw object store tests.

The store's job is to put bytes somewhere durable and then prove they arrived, so the interesting
cases are all disagreements: the store holds a different size, a different digest, no checksum at
all, or nothing at the key it just accepted a write for. None of those can be produced on demand by
a real MinIO, which is why the client here is a fake that behaves like S3 including its failures.

The fake is not a stand-in for the real thing. ``tests/integration/test_object_storage.py`` runs the
same operations against MinIO, which is what keeps the fake honest — a fake that had drifted from
the real API would pass here and fail there.

What the fake reproduces deliberately: PascalCase keyword arguments, ``ClientError`` with the shape
botocore actually raises, and server-side checksum validation. That last one matters most, because
"the server rejected a corrupted upload" is the property the whole verification design rests on.
"""

from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from botocore.exceptions import ClientError

from aedifex.acquisition.content import ContentIdentity, document_id_for_digest
from aedifex.acquisition.download import DownloadedFile
from aedifex.domain.files import FileFormat
from aedifex.infrastructure.storage.keys import StorageTier, derived_key, raw_key
from aedifex.infrastructure.storage.objects import (
    ObjectMetadata,
    RawObjectStore,
    StorageError,
    StoredObject,
    Verification,
    _clean_etag,
    _decode_checksum,
    _encode_digest,
)

BUCKET = "aedifex-test"
SOURCE = "cpwd"
PDF = b"%PDF-1.7\n" + b"schedule of rates " * 32 + b"\n%%EOF\n"


def digest_of(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


@dataclass
class Blob:
    """One object in the fake store."""

    body: bytes
    content_type: str
    metadata: dict[str, str]
    checksum: str | None
    version_id: str


class FakeS3:
    """Enough of the S3 API for this module, including the ways it says no.

    ``returns_checksum`` models a store that does not support checksum retrieval on ``head_object``.
    Older MinIO builds and some S3-compatible implementations do not, and the store must then report
    a weaker verification rather than treat the object as suspect.
    """

    def __init__(self, *, returns_checksum: bool = True, versioning: bool = False) -> None:
        self.objects: dict[tuple[str, str], Blob] = {}
        self.buckets: set[str] = set()
        self.returns_checksum = returns_checksum
        self.versioning: dict[str, bool] = {}
        if versioning:
            self.versioning[BUCKET] = True
        self.put_keys: list[str] = []
        self.head_keys: list[str] = []
        self.downloads: list[str] = []
        self.head_object_error: ClientError | None = None
        self.head_bucket_error: ClientError | None = None
        self.versioning_error: ClientError | None = None
        self.drop_after_put = False
        self.next_version = 0

    # -- helpers ----------------------------------------------------------

    @staticmethod
    def _error(code: str, status: int, operation: str) -> ClientError:
        """A ClientError shaped the way botocore raises them, which is what the store reads."""
        response: Any = {
            "Error": {"Code": code, "Message": code},
            "ResponseMetadata": {"HTTPStatusCode": status},
        }
        return ClientError(response, operation)

    # -- the API ----------------------------------------------------------

    def head_object(self, *, Bucket: str, Key: str, **_kwargs: Any) -> dict[str, Any]:  # noqa: N803
        self.head_keys.append(Key)
        if self.head_object_error is not None:
            raise self.head_object_error
        blob = self.objects.get((Bucket, Key))
        if blob is None:
            raise self._error("404", 404, "HeadObject")
        response: dict[str, Any] = {
            "ContentLength": len(blob.body),
            "ETag": f'"{hashlib.md5(blob.body).hexdigest()}"',  # noqa: S324 - S3's ETag, not a hash we trust
            "Metadata": dict(blob.metadata),
            "VersionId": blob.version_id,
            "ContentType": blob.content_type,
            "LastModified": datetime.now(UTC),
        }
        if self.returns_checksum and blob.checksum is not None:
            response["ChecksumSHA256"] = blob.checksum
        return response

    def put_object(
        self,
        *,
        Bucket: str,  # noqa: N803
        Key: str,  # noqa: N803
        Body: Any,  # noqa: N803
        ContentType: str = "",  # noqa: N803
        ChecksumAlgorithm: str = "",  # noqa: N803
        ChecksumSHA256: str | None = None,  # noqa: N803
        Metadata: dict[str, str] | None = None,  # noqa: N803
    ) -> dict[str, Any]:
        payload = Body.read() if hasattr(Body, "read") else Body
        if ChecksumSHA256 is not None:
            expected = base64.b64encode(hashlib.sha256(payload).digest()).decode("ascii")
            if ChecksumSHA256 != expected:
                # What a real store does: the body did not match the checksum sent with it, so the
                # write is refused rather than kept and trusted.
                raise self._error("BadDigest", 400, "PutObject")
        self.put_keys.append(Key)
        if self.drop_after_put:
            return {}
        self.next_version += 1
        self.objects[(Bucket, Key)] = Blob(
            body=payload,
            content_type=ContentType,
            metadata=dict(Metadata or {}),
            checksum=ChecksumSHA256,
            version_id=f"v{self.next_version}",
        )
        return {"VersionId": f"v{self.next_version}"}

    def download_file(self, bucket: str, key: str, filename: str) -> None:
        self.downloads.append(key)
        blob = self.objects.get((bucket, key))
        if blob is None:
            raise self._error("404", 404, "HeadObject")
        Path(filename).write_bytes(blob.body)

    def head_bucket(self, *, Bucket: str) -> dict[str, Any]:  # noqa: N803
        if self.head_bucket_error is not None:
            raise self.head_bucket_error
        if Bucket not in self.buckets:
            raise self._error("404", 404, "HeadBucket")
        return {}

    def create_bucket(self, *, Bucket: str, **_kwargs: Any) -> dict[str, Any]:  # noqa: N803
        self.buckets.add(Bucket)
        return {}

    def put_bucket_versioning(
        self, *, Bucket: str, VersioningConfiguration: dict[str, str]  # noqa: N803
    ) -> dict[str, Any]:
        self.versioning[Bucket] = VersioningConfiguration.get("Status") == "Enabled"
        return {}

    def get_bucket_versioning(self, *, Bucket: str) -> dict[str, Any]:  # noqa: N803
        if self.versioning_error is not None:
            raise self.versioning_error
        return {"Status": "Enabled"} if self.versioning.get(Bucket) else {}


def staged(directory: Path, payload: bytes = PDF, *, source_id: str = SOURCE) -> DownloadedFile:
    """Write a file where the downloader would have put it, and describe it the same way."""
    sha256 = digest_of(payload)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{sha256}.pdf"
    path.write_bytes(payload)
    return DownloadedFile(
        path=path,
        identity=ContentIdentity(
            sha256=sha256,
            size_bytes=len(payload),
            document_id=document_id_for_digest(sha256),
            sniffed_format=FileFormat.PDF,
        ),
        file_format=FileFormat.PDF,
        storage_key=raw_key(source_id=source_id, sha256=sha256, file_format=FileFormat.PDF),
        source_id=source_id,
        requested_url="https://cpwd.test/tenders/notice.pdf",
        final_url="https://docs.cpwd.test/store/9931.pdf",
        filename="notice.pdf",
        declared_media_type="application/pdf",
        declared_content_length=len(payload),
        http_status=200,
        http_version="HTTP/1.1",
        response_headers=(("content-type", "application/pdf"),),
        attempts=(),
        retrieved_at=datetime.now(UTC),
    )


def store_with(client: FakeS3) -> RawObjectStore:
    return RawObjectStore(client, bucket=BUCKET)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Storing
# ---------------------------------------------------------------------------


class TestPut:
    def test_the_bytes_land_under_the_content_addressed_key(self, tmp_path: Path) -> None:
        client = FakeS3()
        document = staged(tmp_path)

        stored = store_with(client).put(document)

        assert stored.key == document.storage_key
        assert stored.key.startswith(f"{StorageTier.RAW.value}/{SOURCE}/")
        assert document.sha256 in stored.key
        assert client.objects[(BUCKET, stored.key)].body == PDF
        assert stored.uri == f"s3://{BUCKET}/{stored.key}"

    def test_the_upload_carries_the_digest_for_the_server_to_check(self, tmp_path: Path) -> None:
        """The property the whole verification design rests on.

        The store is given the SHA-256 with the body, so it computes the digest itself and refuses
        the write if they disagree. Without this, a body corrupted in transit would be stored and
        then "verified" against metadata that travelled with the corruption.
        """
        client = FakeS3()
        document = staged(tmp_path)

        store_with(client).put(document)

        blob = client.objects[(BUCKET, document.storage_key)]
        assert blob.checksum == _encode_digest(document.sha256)
        assert blob.metadata["sha256"] == document.sha256

    def test_a_body_that_does_not_match_its_checksum_is_refused_by_the_store(
        self, tmp_path: Path
    ) -> None:
        """Corruption between hashing and uploading. The store says no, and so do we."""
        client = FakeS3()
        document = staged(tmp_path)
        # The file changes after its identity was computed — a bad disk, or a bug elsewhere.
        document.path.write_bytes(PDF + b"corrupted")

        with pytest.raises(StorageError, match="could not store"):
            store_with(client).put(document)

        assert (BUCKET, document.storage_key) not in client.objects

    def test_the_object_is_stored_under_our_resolved_media_type(self, tmp_path: Path) -> None:
        """Not the server's ``Content-Type`` header, which was only one input to the decision."""
        client = FakeS3()
        document = staged(tmp_path)

        store_with(client).put(document)

        assert client.objects[(BUCKET, document.storage_key)].content_type == "application/pdf"

    def test_provenance_travels_with_the_object(self, tmp_path: Path) -> None:
        """So the bucket is legible on its own, without the database beside it."""
        client = FakeS3()
        document = staged(tmp_path)

        store_with(client).put(document)

        metadata = client.objects[(BUCKET, document.storage_key)].metadata
        assert metadata["source-id"] == SOURCE
        assert metadata["file-format"] == "pdf"
        assert metadata["final-url"] == document.final_url

    def test_the_version_id_is_reported(self, tmp_path: Path) -> None:
        client = FakeS3(versioning=True)
        stored = store_with(client).put(staged(tmp_path))
        assert stored.version_id == "v1"

    def test_a_derived_key_is_refused(self, tmp_path: Path) -> None:
        """This class stores immutable raw documents; derived output has its own tiers."""
        client = FakeS3()
        document = staged(tmp_path)
        wrong_tier = replace(
            document,
            storage_key=derived_key(
                tier=StorageTier.PROCESSED,
                sha256=document.sha256,
                stage="pdf_text",
                extension="txt",
            ),
        )

        with pytest.raises(ValueError, match="not in the 'raw' tier"):
            store_with(client).put(wrong_tier)
        assert client.put_keys == []

    def test_an_empty_bucket_name_is_a_programming_error(self) -> None:
        with pytest.raises(ValueError, match="non-empty"):
            RawObjectStore(FakeS3(), bucket="   ")  # type: ignore[arg-type]


class TestIdempotence:
    def test_storing_the_same_document_twice_uploads_once(self, tmp_path: Path) -> None:
        """Re-running a crawl must not re-send 200 MiB to overwrite it with itself."""
        client = FakeS3()
        store = store_with(client)
        document = staged(tmp_path)

        first = store.put(document)
        second = store.put(document)

        assert first.already_present is False
        assert second.already_present is True
        assert client.put_keys == [document.storage_key], "the body was uploaded twice"
        assert first.key == second.key
        assert first.sha256 == second.sha256

    def test_the_second_result_still_carries_the_version_and_size(self, tmp_path: Path) -> None:
        """An already-present object is a complete answer, not a degraded one."""
        client = FakeS3(versioning=True)
        store = store_with(client)
        document = staged(tmp_path)

        store.put(document)
        second = store.put(document)

        assert second.size_bytes == len(PDF)
        assert second.version_id == "v1"
        assert second.verification is Verification.SERVER_CHECKSUM

    def test_the_same_bytes_from_a_different_source_are_a_different_key(
        self, tmp_path: Path
    ) -> None:
        """Keys are per source, so two portals publishing one document are stored separately.

        Deliberate: the digest identifies the document, the key records where it came from, and
        provenance is the thing this platform exists to preserve.
        """
        client = FakeS3()
        store = store_with(client)
        first = store.put(staged(tmp_path / "a", source_id="cpwd"))
        second = store.put(staged(tmp_path / "b", source_id="nhai"))

        assert first.key != second.key
        assert first.sha256 == second.sha256
        assert len(client.put_keys) == 2


class TestRefusingToOverwrite:
    def test_a_key_holding_a_different_size_is_never_overwritten(self, tmp_path: Path) -> None:
        """The key contains the digest, so this is corruption or an unrelated write.

        Either way it is something to look at, and overwriting would destroy the evidence of which.
        """
        client = FakeS3()
        document = staged(tmp_path)
        client.objects[(BUCKET, document.storage_key)] = Blob(
            body=b"something else entirely",
            content_type="application/pdf",
            metadata={},
            checksum=None,
            version_id="v0",
        )

        with pytest.raises(StorageError, match="corrupt or was written by something else"):
            store_with(client).put(document)
        assert client.put_keys == []

    def test_a_key_holding_a_different_digest_at_the_same_size_is_refused(
        self, tmp_path: Path
    ) -> None:
        """A size match is not an identity match, and the digest is what identifies a document."""
        client = FakeS3()
        document = staged(tmp_path)
        impostor = bytes(len(PDF))
        client.objects[(BUCKET, document.storage_key)] = Blob(
            body=impostor,
            content_type="application/pdf",
            metadata={"sha256": digest_of(impostor)},
            checksum=base64.b64encode(hashlib.sha256(impostor).digest()).decode(),
            version_id="v0",
        )

        with pytest.raises(StorageError, match="different digest"):
            store_with(client).put(document)
        assert client.put_keys == []

    def test_the_store_offers_no_way_to_delete_an_object(self) -> None:
        """Raw bytes are the evidence everything downstream cites.

        Asserted structurally rather than promised in a docstring: a method that could remove them
        would eventually be called by something in a hurry.
        """
        for name in dir(RawObjectStore):
            assert "delete" not in name.lower()
            assert "remove" not in name.lower()


# ---------------------------------------------------------------------------
# Verifying
# ---------------------------------------------------------------------------


class TestVerification:
    def test_a_server_checksum_is_the_strong_case(self, tmp_path: Path) -> None:
        stored = store_with(FakeS3()).put(staged(tmp_path))
        assert stored.verification is Verification.SERVER_CHECKSUM

    def test_a_store_without_checksum_retrieval_reports_the_weaker_claim(
        self, tmp_path: Path
    ) -> None:
        """Reported as weaker rather than presented as equivalent.

        It means the store does not return checksums, not that the object is suspect — the upload
        was still validated against the digest we sent.
        """
        stored = store_with(FakeS3(returns_checksum=False)).put(staged(tmp_path))
        assert stored.verification is Verification.SIZE_AND_METADATA

    def test_an_object_that_comes_back_with_no_digest_at_all_is_not_stored(
        self, tmp_path: Path
    ) -> None:
        """An unverifiable object is not a stored one."""
        client = FakeS3(returns_checksum=False)
        document = staged(tmp_path)

        original = client.put_object

        def strip_metadata(**kwargs: Any) -> dict[str, Any]:
            kwargs["Metadata"] = {}
            return original(**kwargs)

        client.put_object = strip_metadata  # type: ignore[method-assign]

        with pytest.raises(StorageError, match="neither a checksum nor a recorded digest"):
            store_with(client).put(document)

    def test_a_size_disagreement_after_upload_is_a_failure(self, tmp_path: Path) -> None:
        client = FakeS3()
        document = staged(tmp_path)

        original = client.put_object

        def truncate(**kwargs: Any) -> dict[str, Any]:
            result = original(**kwargs)
            client.objects[(BUCKET, kwargs["Key"])].body = PDF[:10]
            return result

        client.put_object = truncate  # type: ignore[method-assign]

        with pytest.raises(StorageError, match="bytes in the store but"):
            store_with(client).put(document)

    def test_a_digest_disagreement_after_upload_is_a_failure(self, tmp_path: Path) -> None:
        """The store kept something other than what it was sent, at the same size."""
        client = FakeS3()
        document = staged(tmp_path)
        replacement = bytes(len(PDF))

        original = client.put_object

        def substitute(**kwargs: Any) -> dict[str, Any]:
            result = original(**kwargs)
            blob = client.objects[(BUCKET, kwargs["Key"])]
            blob.body = replacement
            blob.checksum = base64.b64encode(hashlib.sha256(replacement).digest()).decode()
            blob.metadata["sha256"] = digest_of(replacement)
            return result

        client.put_object = substitute  # type: ignore[method-assign]

        with pytest.raises(StorageError, match="in the store but"):
            store_with(client).put(document)

    def test_an_upload_the_store_does_not_keep_is_a_failure(self, tmp_path: Path) -> None:
        """A write reported as accepted and then absent. Silence here would lose a document."""
        client = FakeS3()
        client.drop_after_put = True

        with pytest.raises(StorageError, match="is not there when read back"):
            store_with(client).put(staged(tmp_path))


# ---------------------------------------------------------------------------
# Reading back
# ---------------------------------------------------------------------------


class TestHead:
    def test_a_missing_object_is_reported_as_absent(self) -> None:
        assert store_with(FakeS3()).head("raw/cpwd/aa/bb/nothing.pdf") is None

    def test_metadata_describes_what_is_there(self, tmp_path: Path) -> None:
        client = FakeS3(versioning=True)
        document = staged(tmp_path)
        store = store_with(client)
        store.put(document)

        metadata = store.head(document.storage_key)

        assert isinstance(metadata, ObjectMetadata)
        assert metadata.size_bytes == len(PDF)
        assert metadata.sha256 == document.sha256
        assert metadata.checksum_from_server is True
        assert metadata.version_id == "v1"
        assert metadata.etag is not None
        assert '"' not in metadata.etag

    def test_a_permissions_failure_is_not_mistaken_for_an_absent_object(self) -> None:
        """The distinction that stops a misconfiguration re-uploading the entire corpus.

        If ``AccessDenied`` read as "not there", every ``put`` would decide the object was missing
        and try to write it again.
        """
        client = FakeS3()
        client.head_object_error = FakeS3._error("AccessDenied", 403, "HeadObject")

        with pytest.raises(StorageError, match="could not read metadata"):
            store_with(client).head("raw/cpwd/aa/bb/x.pdf")

    def test_the_digest_falls_back_to_our_metadata_when_no_checksum_comes_back(
        self, tmp_path: Path
    ) -> None:
        client = FakeS3(returns_checksum=False)
        document = staged(tmp_path)
        store = store_with(client)
        store.put(document)

        metadata = store.head(document.storage_key)
        assert metadata is not None
        assert metadata.sha256 == document.sha256
        assert metadata.checksum_from_server is False


class TestDownloadTo:
    def test_an_object_can_be_read_back_byte_for_byte(self, tmp_path: Path) -> None:
        """The other half of the round trip. An object that cannot be read back is not stored."""
        client = FakeS3()
        document = staged(tmp_path / "staging")
        store = store_with(client)
        store.put(document)

        destination = store.download_to(document.storage_key, tmp_path / "out" / "notice.pdf")

        assert destination.read_bytes() == PDF
        assert digest_of(destination.read_bytes()) == document.sha256

    def test_the_destination_directory_is_created(self, tmp_path: Path) -> None:
        client = FakeS3()
        document = staged(tmp_path / "staging")
        store = store_with(client)
        store.put(document)

        destination = store.download_to(
            document.storage_key, tmp_path / "deep" / "nested" / "out.pdf"
        )
        assert destination.is_file()

    def test_a_missing_object_fails_loudly(self, tmp_path: Path) -> None:
        with pytest.raises(StorageError, match="could not retrieve"):
            store_with(FakeS3()).download_to("raw/cpwd/aa/bb/absent.pdf", tmp_path / "x.pdf")


# ---------------------------------------------------------------------------
# The bucket itself
# ---------------------------------------------------------------------------


class TestBucketSetup:
    def test_ensure_bucket_creates_it_and_turns_versioning_on(self) -> None:
        """Versioning is what makes write-once enforceable rather than merely intended."""
        client = FakeS3()
        store = store_with(client)

        assert store.versioning_enabled() is False
        store.ensure_bucket()

        assert BUCKET in client.buckets
        assert store.versioning_enabled() is True

    def test_an_existing_bucket_is_not_recreated(self) -> None:
        client = FakeS3()
        client.buckets.add(BUCKET)
        store = store_with(client)

        store.ensure_bucket()
        assert client.buckets == {BUCKET}
        assert store.versioning_enabled() is True

    def test_a_real_failure_inspecting_the_bucket_is_not_swallowed(self) -> None:
        client = FakeS3()
        client.head_bucket_error = FakeS3._error("AccessDenied", 403, "HeadBucket")

        with pytest.raises(StorageError, match="could not inspect bucket"):
            store_with(client).ensure_bucket()

    def test_a_failure_reading_versioning_is_not_swallowed(self) -> None:
        client = FakeS3()
        client.versioning_error = FakeS3._error("AccessDenied", 403, "GetBucketVersioning")

        with pytest.raises(StorageError, match="could not read versioning"):
            store_with(client).versioning_enabled()

    def test_the_bucket_name_is_exposed(self) -> None:
        assert store_with(FakeS3()).bucket == BUCKET


# ---------------------------------------------------------------------------
# The small conversions
# ---------------------------------------------------------------------------


class TestChecksumEncoding:
    def test_a_digest_round_trips_through_the_s3_encoding(self) -> None:
        digest = digest_of(PDF)
        assert _decode_checksum(_encode_digest(digest)) == digest

    def test_the_encoding_is_base64_of_the_raw_digest_not_of_the_hex(self) -> None:
        """The distinction S3 actually cares about; the hex form is 64 bytes, the raw one 32."""
        encoded = _encode_digest(digest_of(PDF))
        assert len(base64.b64decode(encoded)) == 32

    @pytest.mark.parametrize("value", [None, "", "not base64!!", "c2hvcnQ="])
    def test_an_unusable_checksum_is_treated_as_absent(self, value: str | None) -> None:
        """Absent means the store's checksum cannot be used, not that the upload failed.

        Failing here instead would reject a legitimate document because the store answered with
        something unexpected — and the digest we sent is still what gets compared.
        """
        assert _decode_checksum(value) is None

    def test_an_etag_loses_its_quotes(self) -> None:
        assert _clean_etag('"abc123"') == "abc123"
        assert _clean_etag(None) is None


class TestStoredObjectDescription:
    def test_an_upload_describes_itself(self) -> None:
        stored = StoredObject(
            bucket=BUCKET,
            key="raw/cpwd/aa/bb/aabb.pdf",
            sha256="aa" * 32,
            size_bytes=1234,
            version_id="v7",
            etag="etag",
            verification=Verification.SERVER_CHECKSUM,
            already_present=False,
        )
        described = stored.describe()
        assert described.startswith("uploaded s3://aedifex-test/raw/cpwd/")
        assert "version=v7" in described
        assert "1234 bytes" in described
        assert "server_checksum" in described

    def test_an_already_present_object_says_so(self) -> None:
        stored = StoredObject(
            bucket=BUCKET,
            key="raw/cpwd/aa/bb/aabb.pdf",
            sha256="aa" * 32,
            size_bytes=1,
            version_id=None,
            etag=None,
            verification=Verification.SIZE_AND_METADATA,
            already_present=True,
        )
        assert stored.describe().startswith("already present")
        assert "version=" not in stored.describe()
