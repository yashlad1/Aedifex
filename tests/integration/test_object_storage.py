"""Integration tests against a real S3-compatible store.

Skipped automatically when MinIO is not reachable, so ``make test`` stays runnable with no
infrastructure. CI provides MinIO as a service container and runs these.

These exist to check the things the unit tests structurally cannot. The unit suite drives a fake S3
that behaves the way the real API is *believed* to behave, which is exactly the assumption most
likely to be wrong — the checksum encoding, whether ``head_object`` returns a checksum at all,
whether versioning produces distinct version ids, and what error shape a missing object actually
raises. Every one of those was a guess until it ran here.

So the split is deliberate rather than duplicative: the fake covers the failure paths a real store
will not perform on demand, and this file covers the API surface the fake could be lying about.
"""

from __future__ import annotations

import hashlib
import os
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import boto3
import pytest
from botocore.config import Config as BotoConfig
from botocore.exceptions import BotoCoreError, ClientError

from aedifex.acquisition.content import ContentIdentity, document_id_for_digest
from aedifex.acquisition.download import DownloadedFile
from aedifex.config import Environment, Settings
from aedifex.domain.files import FileFormat
from aedifex.infrastructure.storage.keys import raw_key
from aedifex.infrastructure.storage.objects import (
    RawObjectStore,
    StorageError,
    Verification,
)

pytestmark = pytest.mark.integration

PDF = b"%PDF-1.7\n" + b"bill of quantities " * 512 + b"\n%%EOF\n"


def digest_of(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


@pytest.fixture(scope="module")
def settings() -> Settings:
    return Settings(environment=Environment.TEST)


@pytest.fixture(scope="module")
def store(settings: Settings) -> Iterator[RawObjectStore]:
    """A store against a real MinIO, skipping the module if none is reachable.

    When ``REQUIRE_INTEGRATION_TESTS=1`` the module fails instead of skipping, so a misconfigured
    service container cannot quietly turn this file into a no-op that still reports green. A skipped
    test must never look like a verified one (rule 81e).
    """
    # Read through Settings rather than os.environ, so this exercises the configuration layer the
    # application will use rather than a parallel path that could drift from it. The fallbacks are
    # the development stack's well-known placeholders, which Settings refuses in production.
    endpoint = settings.storage_endpoint_url or "http://localhost:9000"
    access_key = settings.storage_access_key_id
    secret_key = settings.storage_secret_access_key
    client = boto3.client(
        "s3",
        endpoint_url=endpoint,
        region_name=settings.storage_region,
        aws_access_key_id=access_key.get_secret_value() if access_key else "minioadmin",
        aws_secret_access_key=secret_key.get_secret_value() if secret_key else "minioadmin",
        # Short timeouts and no retries: a store that is not there should skip the module in a
        # second, not spend a minute retrying before deciding.
        config=BotoConfig(
            connect_timeout=2,
            read_timeout=5,
            retries={"max_attempts": 1},
            signature_version="s3v4",
        ),
    )
    # A bucket per run, so a leftover object from a previous run cannot make an idempotence test
    # pass for the wrong reason.
    bucket = f"aedifex-it-{uuid.uuid4().hex[:12]}"
    candidate = RawObjectStore(client, bucket=bucket)
    try:
        candidate.ensure_bucket()
    except (ClientError, BotoCoreError, StorageError) as error:
        message = f"MinIO is not reachable at {endpoint}: {type(error).__name__}"
        if os.environ.get("REQUIRE_INTEGRATION_TESTS") == "1":
            pytest.fail(
                f"{message}. REQUIRE_INTEGRATION_TESTS=1 forbids skipping; check that the MinIO "
                "service is running and AEDIFEX_STORAGE_ENDPOINT_URL is correct."
            )
        pytest.skip(message)
    yield candidate
    _empty_bucket(client, bucket)


def _empty_bucket(client: object, bucket: str) -> None:
    """Remove every version of every object, then the bucket.

    Versioning is on, so deleting an object leaves a delete marker and the bucket stays
    undeletable until every version is gone. Done here rather than in the store itself, which
    deliberately has no delete: the ability to remove raw evidence belongs in a test's teardown and
    nowhere else.
    """
    s3 = client  # narrowed only for readability; the type stubs make this awkward otherwise
    paginator = s3.get_paginator("list_object_versions")  # type: ignore[attr-defined]
    for page in paginator.paginate(Bucket=bucket):
        targets = [
            {"Key": entry["Key"], "VersionId": entry["VersionId"]}
            for group in ("Versions", "DeleteMarkers")
            for entry in page.get(group, [])
        ]
        if targets:
            s3.delete_objects(Bucket=bucket, Delete={"Objects": targets})  # type: ignore[attr-defined]
    s3.delete_bucket(Bucket=bucket)  # type: ignore[attr-defined]


def staged(directory: Path, payload: bytes, *, source_id: str = "cpwd") -> DownloadedFile:
    """A file on disk described exactly as the downloader would describe it."""
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


class TestTheRoundTrip:
    def test_a_document_stored_and_retrieved_is_byte_for_byte_identical(
        self, store: RawObjectStore, tmp_path: Path
    ) -> None:
        """The milestone assertion, against a real store rather than a fake one.

        Note what is compared: the digest of the file read back out, recomputed from scratch. Not
        the digest the store reported, and not the one we sent — either of those would be the upload
        path verifying itself.
        """
        document = staged(tmp_path / "staging", PDF)

        stored = store.put(document)
        retrieved = store.download_to(stored.key, tmp_path / "out" / "notice.pdf")

        assert retrieved.read_bytes() == PDF
        assert digest_of(retrieved.read_bytes()) == document.sha256
        assert stored.size_bytes == len(PDF)
        assert stored.already_present is False

    def test_the_store_computes_the_checksum_itself(
        self, store: RawObjectStore, tmp_path: Path
    ) -> None:
        """The assumption the whole verification design rests on, checked against a real store.

        If MinIO did not return its own SHA-256 this would report ``SIZE_AND_METADATA``, which is
        the weaker claim — and knowing which one we actually get is the point of running here.
        """
        document = staged(tmp_path, PDF + b" checksum case")

        stored = store.put(document)

        assert stored.verification is Verification.SERVER_CHECKSUM
        metadata = store.head(stored.key)
        assert metadata is not None
        assert metadata.checksum_from_server is True
        assert metadata.sha256 == document.sha256

    def test_a_corrupted_body_is_rejected_by_the_store_not_by_us(
        self, store: RawObjectStore, tmp_path: Path
    ) -> None:
        """A real server refusing a real mismatched checksum.

        The unit suite asserts this against a fake that was written to behave this way, which proves
        only that the fake does. Here the rejection comes from MinIO, and it took a probe to
        establish that it happens for a *streamed* body and not only for one passed as bytes.

        The payload is unique to this test on purpose. The bucket is module-scoped, so reusing
        another test's bytes would mean the key was already occupied — ``put`` would report
        ``already_present`` without uploading anything, and this would pass while proving nothing.
        """
        payload = PDF + b" corruption case"
        document = staged(tmp_path / "corrupt", payload)
        document.path.write_bytes(payload + b"tampered")

        with pytest.raises(StorageError, match="could not store"):
            store.put(document)

        assert store.head(document.storage_key) is None, "a corrupted body was stored anyway"

    def test_metadata_survives_the_round_trip(self, store: RawObjectStore, tmp_path: Path) -> None:
        """Object metadata keys are lowercased by S3; the store must read back what it wrote."""
        document = staged(tmp_path / "meta", PDF + b" metadata case")

        stored = store.put(document)
        metadata = store.head(stored.key)

        assert metadata is not None
        assert metadata.sha256 == document.sha256
        assert metadata.size_bytes == document.size_bytes
        assert metadata.etag is not None


class TestIdempotenceForReal:
    def test_storing_the_same_document_twice_leaves_one_object(
        self, store: RawObjectStore, tmp_path: Path
    ) -> None:
        payload = PDF + b" idempotence case"
        document = staged(tmp_path / "once", payload)

        first = store.put(document)
        second = store.put(staged(tmp_path / "twice", payload))

        assert first.key == second.key
        assert second.already_present is True
        assert first.sha256 == second.sha256
        # Versioning is on, so a second upload would have created a second version. It did not.
        assert second.version_id == first.version_id


class TestVersioning:
    def test_the_bucket_keeps_previous_versions(self, store: RawObjectStore) -> None:
        """FR-040's enforcement rather than its intention.

        The store refuses to overwrite a raw object, but versioning is what makes that recoverable
        if something else ever does.
        """
        assert store.versioning_enabled() is True

    def test_ensure_bucket_is_idempotent(self, store: RawObjectStore) -> None:
        store.ensure_bucket()
        store.ensure_bucket()
        assert store.versioning_enabled() is True


class TestAbsence:
    def test_a_missing_object_reads_as_absent_rather_than_raising(
        self, store: RawObjectStore
    ) -> None:
        """The error shape botocore raises for a missing object was a guess until it ran here."""
        assert store.head(f"raw/cpwd/aa/bb/{'0' * 64}.pdf") is None

    def test_retrieving_a_missing_object_fails_loudly(
        self, store: RawObjectStore, tmp_path: Path
    ) -> None:
        with pytest.raises(StorageError, match="could not retrieve"):
            store.download_to(f"raw/cpwd/aa/bb/{'1' * 64}.pdf", tmp_path / "absent.pdf")
