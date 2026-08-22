"""Ingesting a local file as evidence, with provenance that says what actually happened.

The crawler acquires documents by fetching them; this acquires them by being handed a path. Both
produce the same immutable, content-addressed artifact, and both record how it arrived — but they
record *different* facts, which is why an upload gets its own provenance row rather than a
``document_retrievals`` entry with an invented HTTP 200 for a request nobody made.

Content addressing is identical to the crawl path: the digest decides the identity and the storage
key, so ingesting the same bytes twice stores no second artifact. The *upload* is a separate matter:
one is an event, and two people supplying the same bytes are two events, so a second uploader is
recorded rather than collapsed into the first. Ingesting a file that was
previously crawled would resolve to the same document, which is correct — it is the same evidence.

The source must be an approved ``manual_upload`` source. A file cannot be smuggled in under a source
whose terms permit crawling but say nothing about local ingestion.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from aedifex.acquisition.content import document_id_for_digest
from aedifex.acquisition.registry.models import RetrievalMethod, SourceDefinition
from aedifex.domain.documents import DocumentState, DocumentType
from aedifex.domain.files import FileFormat
from aedifex.errors import ExtractionError, SourceNotCollectableError
from aedifex.infrastructure.database.models import Document, DocumentUpload
from aedifex.infrastructure.observability.logging import get_logger
from aedifex.infrastructure.storage.keys import raw_key
from aedifex.infrastructure.storage.objects import RawObjectStore

__all__ = ["IngestOutcome", "UploadedFile", "ingest_file"]

_log = get_logger(__name__)

_MEDIA_TYPES: dict[FileFormat, str] = {
    FileFormat.XLSX: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    FileFormat.PDF: "application/pdf",
    # For an API response stored as evidence — the Consumer Price Index arrives no other way.
    FileFormat.JSON: "application/json",
}


@dataclass(frozen=True, slots=True)
class UploadedFile:
    """A local file presented to the raw tier, satisfying ``StorableFile``.

    Deliberately not a ``DownloadedFile``: that type carries an HTTP status, response headers, and a
    requested URL, none of which exist for a file someone handed us. ``final_url`` is a ``file://``
    URI, which is where the bytes genuinely came from — a URI, not a claim about a request.
    """

    path: Path
    sha256: str
    size_bytes: int
    storage_key: str
    source_id: str
    file_format: FileFormat

    @property
    def final_url(self) -> str:
        return self.path.resolve().as_uri()


@dataclass(frozen=True, slots=True)
class IngestOutcome:
    """One ingested file, and whether anything new was stored."""

    document: Document
    upload: DocumentUpload
    already_present: bool

    def describe(self) -> str:
        state = "already present" if self.already_present else "stored"
        return (
            f"{self.document.original_filename}  {state}  "
            f"{self.document.size_bytes} bytes  {self.document.sha256[:16]}…"
        )


def ingest_file(
    session: Session,
    store: RawObjectStore,
    path: Path,
    *,
    source: SourceDefinition,
    document_type: DocumentType,
    file_format: FileFormat,
    uploaded_by: str,
    software_version: str,
    is_synthetic: bool = False,
    note: str | None = None,
    original_path: str | None = None,
) -> IngestOutcome:
    """Store a local file as an immutable artifact and record how it got here.

    Args:
        source: Must be enabled, approved, and ``manual_upload``.
        document_type: Stated by the operator. For the synthetic corpus this is explicit rather than
            classified, which the milestone permits — a guessed type underneath a payment finding
            would be worse than a declared one.
        is_synthetic: Recorded on the upload so a query for real evidence can exclude generated data
            without knowing which sources happen to be synthetic today.
        original_path: What to record as where the file came from, when ``path`` is not it. An HTTP
            upload has no filesystem path — the bytes arrive in a request and are written to a
            temporary file purely so this function can hash and store them — so recording that
            temporary path would be a true statement about nothing. The caller passes what it
            actually knows, which is the name the client stated.

    Raises:
        SourceNotCollectableError: if the source is not an approved manual-upload source.
        ExtractionError: if the file is missing or empty.
    """
    if not source.is_collectable:
        raise SourceNotCollectableError(
            f"source {source.id!r} is not approved for collection: enabled={source.enabled}, "
            f"verification_status={source.verification_status.value}"
        )
    if source.retrieval is not RetrievalMethod.MANUAL_UPLOAD:
        raise SourceNotCollectableError(
            f"source {source.id!r} has retrieval={source.retrieval.value}; ingesting a local file "
            f"under it would record an upload for a source whose terms describe fetching"
        )
    if not path.is_file():
        raise ExtractionError(f"not a file: {path}")

    data = path.read_bytes()
    if not data:
        raise ExtractionError(f"refusing to ingest an empty file: {path}")

    digest = hashlib.sha256(data).hexdigest()
    document_id = document_id_for_digest(digest)
    key = raw_key(source_id=source.id, sha256=digest, file_format=file_format)

    stored = store.put(
        UploadedFile(
            path=path,
            sha256=digest,
            size_bytes=len(data),
            storage_key=key,
            source_id=source.id,
            file_format=file_format,
        )
    )

    document = session.get(Document, document_id)
    already_present = document is not None
    reclassified_from = (
        document.document_type
        if document is not None and document.document_type is not document_type
        else None
    )
    if document is None:
        document = Document(
            id=document_id,
            sha256=digest,
            size_bytes=len(data),
            file_format=file_format,
            media_type=_MEDIA_TYPES.get(file_format),
            original_filename=path.name[:128],
            storage_key=key,
            document_type=document_type,
            state=DocumentState.DOWNLOADED,
        )
        session.add(document)
        session.flush()
    elif reclassified_from is not None:
        # The operator is the authority on the declared type, and until 2026-08-21 a re-ingest
        # silently ignored them — which made a misclassification uncorrectable through the supported
        # path. Five documents needed exactly this: three CAG reports ingested as UNKNOWN before an
        # AUDIT_REPORT type existed, and two model concession agreements ingested as CONTRACT before
        # MODEL_AGREEMENT did. The type decides whether the extractor treats a quoted amount as a
        # fact about the document, so leaving it wrong keeps producing false facts.
        #
        # This is not a change to stored evidence. The bytes, the digest and the storage key are
        # untouched and unreachable from here; only the operator's own classification of them moves,
        # and the move is logged with both values so the record shows what was corrected.
        _log.info(
            "ingest.reclassified",
            document_id=str(document_id),
            source_id=source.id,
            was=reclassified_from.value,
            now=document_type.value,
        )
        document.document_type = document_type
        session.flush()

    # An upload is an event, and its identity is who supplied what, under which name. Keyed this
    # way rather than on (document, source) so two people handing us the same bytes are two rows —
    # possible the moment a shared `customer_provided` source existed — while one person re-running
    # the same ingest stays idempotent, which is what the narrower key was protecting.
    recorded_path = original_path or str(path)
    upload = session.execute(
        select(DocumentUpload).where(
            DocumentUpload.document_id == document_id,
            DocumentUpload.source_id == source.id,
            DocumentUpload.uploaded_by == uploaded_by,
            DocumentUpload.original_path == recorded_path,
        )
    ).scalar_one_or_none()
    if upload is None:
        upload = DocumentUpload(
            document_id=document_id,
            source_id=source.id,
            original_path=recorded_path,
            is_synthetic=is_synthetic,
            note=note,
            uploaded_by=uploaded_by,
            storage_bucket=store.bucket,
            storage_key=key,
            storage_verification=stored.verification,
            software_version=software_version,
        )
        session.add(upload)
        session.flush()
    elif reclassified_from is not None:
        # The note is where this upload's provenance is written in prose, and a reclassification is
        # part of that story: someone decided this document is a different kind of thing than was
        # first recorded, and a reader six months from now needs to see that without the log. Append
        # rather than replace — the original note says how the bytes arrived, which has not changed.
        entry = (
            f"RECLASSIFIED {reclassified_from.value} -> {document_type.value} "
            f"by {uploaded_by} (software {software_version})."
        )
        upload.note = (
            f"{upload.note}\n\n{entry} {note}".strip()
            if note
            else (f"{upload.note}\n\n{entry}".strip())
        )
        session.flush()

    _log.info(
        "ingest.stored",
        document_id=str(document_id),
        source_id=source.id,
        document_type=document_type.value,
        bytes=len(data),
        already_present=already_present,
        is_synthetic=is_synthetic,
    )
    return IngestOutcome(document=document, upload=upload, already_present=already_present)
