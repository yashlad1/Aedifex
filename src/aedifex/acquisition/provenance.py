"""Recording what was retrieved, from where, and how it was verified.

The last step of an acquisition, and the one that makes the rest citable. Object storage holds the
bytes; this holds the answer to "where did this come from, when, and what happened on the way".

.. code-block:: text

    DownloadedFile + StoredObject
        ↓  the document row, keyed by a UUIDv5 of the digest — so it is the same row every time
        ↓  the retrieval row, appended — so a second fetch does not erase the first
    (Document, DocumentRetrieval)

**The document row is found, not inserted twice.** Its id is derived from the content digest, so
re-ingesting the same bytes converges on one row rather than colliding on a unique constraint. What
that means in practice is that a second retrieval of a known document writes only the retrieval row,
and the function reports which happened.

**A digest that arrives with different metadata is a refusal.** Two payloads with one SHA-256 would
be a break in SHA-256 itself; far likelier is a caller that assembled a ``DownloadedFile`` by hand
with mismatched fields. Either way, writing it would corrupt the identity the whole corpus is keyed
on, so it stops.

**Nothing here commits.** The caller owns the transaction, because a retrieval is one part of a
larger unit of work — the frontier row is updated in the same breath — and a function that committed
on its own would make that impossible to do atomically.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from aedifex import __version__
from aedifex.acquisition.download import DownloadedFile
from aedifex.acquisition.fetch.controller import AttemptRecord
from aedifex.errors import AedifexError
from aedifex.infrastructure.database.models import Document, DocumentRetrieval
from aedifex.infrastructure.storage.objects import StoredObject

__all__ = ["ProvenanceConflictError", "RecordedRetrieval", "record_retrieval"]


class ProvenanceConflictError(AedifexError):
    """A digest already in the corpus arrived describing different content."""


@dataclass(frozen=True, slots=True)
class RecordedRetrieval:
    """What was written, and whether the document was already known."""

    document: Document
    retrieval: DocumentRetrieval
    document_was_new: bool

    def describe(self) -> str:
        state = "new document" if self.document_was_new else "known document"
        return (
            f"{state} {self.document.id} ({self.document.sha256[:12]}) retrieved from "
            f"{self.retrieval.final_url} in {self.retrieval.attempt_count} attempt(s)"
        )


def record_retrieval(
    session: Session,
    *,
    downloaded: DownloadedFile,
    stored: StoredObject,
    software_version: str = __version__,
) -> RecordedRetrieval:
    """Record ``downloaded`` and the object it became, without committing.

    Args:
        session: The caller's session. Flushed so the rows have identities and the database's own
            constraints are exercised here rather than at some later commit, but never committed.
        downloaded: The file as the downloader described it.
        stored: Where it went and how the upload was confirmed.
        software_version: Which build produced this record, for reproducibility.

    Raises:
        ProvenanceConflictError: if the digest is already present with different content metadata,
            or if the file and the stored object disagree about what was stored.
    """
    _check_consistent(downloaded, stored)

    document = session.get(Document, downloaded.identity.document_id)
    document_was_new = document is None
    if document is None:
        document = Document(
            id=downloaded.identity.document_id,
            sha256=downloaded.sha256,
            size_bytes=downloaded.size_bytes,
            file_format=downloaded.file_format,
            media_type=downloaded.declared_media_type,
            original_filename=downloaded.filename,
            storage_key=stored.key,
        )
        session.add(document)
    else:
        _check_matches_existing(document, downloaded)

    retrieval = DocumentRetrieval(
        document_id=document.id,
        source_id=downloaded.source_id,
        requested_url=downloaded.requested_url,
        final_url=downloaded.final_url,
        retrieved_at=downloaded.retrieved_at,
        http_status=downloaded.http_status,
        http_version=downloaded.http_version,
        response_headers=[[name, value] for name, value in downloaded.response_headers],
        declared_media_type=downloaded.declared_media_type,
        declared_content_length=downloaded.declared_content_length,
        attempts=[_attempt_as_json(record) for record in downloaded.attempts],
        # At least one request was made, whatever the history says. A fetch with an empty history
        # still happened, and the check constraint requires a positive count — recording zero would
        # be both false and a write failure.
        attempt_count=max(1, len(downloaded.attempts)),
        storage_bucket=stored.bucket,
        storage_key=stored.key,
        storage_version_id=stored.version_id,
        storage_verification=stored.verification.value,
        software_version=software_version,
    )
    session.add(retrieval)
    # Flush rather than commit: the caller's transaction may have more to do, but a constraint
    # violation should surface here, where the reason is still in scope.
    session.flush()
    return RecordedRetrieval(
        document=document, retrieval=retrieval, document_was_new=document_was_new
    )


def _attempt_as_json(record: AttemptRecord) -> dict[str, object]:
    """One attempt as a JSON object.

    Written out field by field rather than with ``asdict``, so a field added to
    :class:`AttemptRecord` does not silently change the shape of every row already written — and so
    it is obvious that no response body is among them.
    """
    return {
        "attempt": record.attempt,
        "outcome": record.outcome.value,
        "duration_ms": round(record.duration_ms, 3),
        "status_code": record.status_code,
        "error_type": record.error_type,
        "retry_after_seconds": record.retry_after_seconds,
        "delay_before_next_seconds": record.delay_before_next_seconds,
        "reason": record.reason,
    }


def _check_consistent(downloaded: DownloadedFile, stored: StoredObject) -> None:
    """The file and the stored object must describe the same thing.

    Cheap, and it catches the mistake of pairing up results from two different documents — which
    would otherwise write a row pointing at bytes it does not describe.
    """
    if downloaded.sha256 != stored.sha256:
        raise ProvenanceConflictError(
            f"the downloaded file has digest {downloaded.sha256} but the stored object has "
            f"{stored.sha256}; these are not the same document"
        )
    if downloaded.storage_key != stored.key:
        raise ProvenanceConflictError(
            f"the downloaded file's key is {downloaded.storage_key} but it was stored at "
            f"{stored.key}"
        )
    if downloaded.size_bytes != stored.size_bytes:
        raise ProvenanceConflictError(
            f"the downloaded file is {downloaded.size_bytes} bytes but the stored object is "
            f"{stored.size_bytes}"
        )


def _check_matches_existing(existing: Document, downloaded: DownloadedFile) -> None:
    """A known digest must arrive describing the content already recorded for it.

    Two different payloads with one SHA-256 would be a break in the hash function; a caller that
    assembled a ``DownloadedFile`` with mismatched fields is far likelier. Either way, writing it
    would corrupt the identity the corpus is keyed on.
    """
    if existing.sha256 != downloaded.sha256:
        raise ProvenanceConflictError(
            f"document {existing.id} is recorded with digest {existing.sha256} but this retrieval "
            f"carries {downloaded.sha256}; the document id no longer follows from the digest"
        )
    if existing.size_bytes != downloaded.size_bytes:
        raise ProvenanceConflictError(
            f"document {existing.sha256} is recorded as {existing.size_bytes} bytes but this "
            f"retrieval is {downloaded.size_bytes}; one digest cannot describe two payloads"
        )
    if existing.file_format is not downloaded.file_format:
        raise ProvenanceConflictError(
            f"document {existing.sha256} is recorded as {existing.file_format.value} but this "
            f"retrieval resolved it as {downloaded.file_format.value}"
        )
