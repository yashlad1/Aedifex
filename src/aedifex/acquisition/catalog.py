"""The corpus catalog: what we hold, where it came from, and how it got here.

A read model, not a table. Everything on the catalog's field list already exists across
``documents``, ``document_retrievals``, and ``discovered_urls`` — content identity, the URL asked
for, the URL that answered, retrieval time, media type, resolved format, storage location, and
verification. A catalog *table* would be a fourth copy of facts that are already recorded, and a
fourth copy is a thing that can disagree with the other three.

So this module is queries and typed rows. The join is the catalog:

.. code-block:: text

    documents            one row per unique payload, keyed by its digest
      ⋈ document_retrievals   every occasion we fetched it, append-only
      ⋈ discovered_urls       every URL it was ever found at, across sources

A document with several retrievals appears once, described by its **most recent** retrieval:
"where is this document and is it still there?" is the question a catalog is for. The full history
is one query away and is deliberately not flattened into this one.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.selectable import Subquery

from aedifex.domain.documents import DocumentState
from aedifex.domain.files import FileFormat
from aedifex.infrastructure.database.models import (
    CrawlJob,
    CrawlJobStatus,
    DiscoveredUrl,
    Document,
    DocumentRetrieval,
)

__all__ = [
    "CatalogEntry",
    "CorpusSummary",
    "RunSummary",
    "catalog_entries",
    "catalog_entry",
    "corpus_summary",
    "crawl_runs",
    "queue_depth_by_source",
]

_DEFAULT_PAGE: int = 50
_MAX_PAGE: int = 500


@dataclass(frozen=True, slots=True)
class CatalogEntry:
    """One document in the corpus, described by its most recent retrieval."""

    document_id: uuid.UUID
    sha256: str
    size_bytes: int
    file_format: FileFormat
    media_type: str | None
    original_filename: str | None
    state: DocumentState
    first_seen_at: datetime

    source_id: str
    requested_url: str
    final_url: str
    retrieved_at: datetime
    http_status: int
    attempt_count: int
    retrieval_count: int

    storage_bucket: str
    storage_key: str
    storage_version_id: str | None
    storage_verification: str

    @property
    def uri(self) -> str:
        return f"s3://{self.storage_bucket}/{self.storage_key}"

    @property
    def was_redirected(self) -> bool:
        return self.requested_url != self.final_url

    def describe(self) -> str:
        return (
            f"{self.sha256[:12]} {self.file_format.value:<5} {self.size_bytes:>10} bytes "
            f"{self.source_id} {self.final_url}"
        )


@dataclass(frozen=True, slots=True)
class CorpusSummary:
    """What the corpus holds in total. The answer to "is this thing working?"."""

    documents: int
    retrievals: int
    bytes_stored: int
    sources: int
    by_source: Mapping[str, int]
    by_format: Mapping[str, int]
    by_state: Mapping[str, int]
    urls_seen: int
    urls_downloaded: int
    urls_failed: int
    urls_dead_lettered: int
    first_seen_at: datetime | None
    last_retrieved_at: datetime | None

    @property
    def duplicate_url_rate(self) -> float:
        """How many URLs pointed at content we already had.

        Above zero is healthy: the same PDF genuinely is published at several URLs. Near one means a
        discovery strategy is finding the same documents over and over.
        """
        if self.urls_downloaded == 0:
            return 0.0
        return max(0.0, (self.urls_downloaded - self.documents) / self.urls_downloaded)

    def describe(self) -> str:
        return (
            f"{self.documents} documents, {self.bytes_stored} bytes, "
            f"from {self.sources} source(s); "
            f"{self.urls_seen} URLs seen, {self.urls_downloaded} downloaded, "
            f"{self.urls_failed} failed, {self.urls_dead_lettered} dead-lettered"
        )


@dataclass(frozen=True, slots=True)
class RunSummary:
    """One crawl run, as an operator wants to see it."""

    job_id: uuid.UUID
    source_id: str
    status: CrawlJobStatus
    stop_reason: str | None
    started_at: datetime
    finished_at: datetime | None
    urls_discovered: int
    urls_skipped: int
    documents_stored: int
    documents_duplicate: int
    documents_failed: int
    documents_quarantined: int
    bytes_downloaded: int
    software_version: str
    error_type: str | None

    @property
    def duration_seconds(self) -> float | None:
        if self.finished_at is None:
            return None
        return (self.finished_at - self.started_at).total_seconds()

    @property
    def documents_seen(self) -> int:
        return (
            self.documents_stored
            + self.documents_duplicate
            + self.documents_failed
            + self.documents_quarantined
        )

    @property
    def success_rate(self) -> float:
        """Stored or already held, over everything attempted. ``1.0`` when nothing was attempted."""
        seen = self.documents_seen
        return (self.documents_stored + self.documents_duplicate) / seen if seen else 1.0

    @property
    def duplicate_rate(self) -> float:
        seen = self.documents_seen
        return self.documents_duplicate / seen if seen else 0.0


def catalog_entries(
    session: Session,
    *,
    source_id: str | None = None,
    file_format: FileFormat | None = None,
    since: datetime | None = None,
    limit: int = _DEFAULT_PAGE,
    offset: int = 0,
) -> tuple[CatalogEntry, ...]:
    """The corpus, most recently retrieved first.

    Bounded by construction: ``limit`` is clamped, because an unbounded catalog query against a
    corpus of any size is a way to run a database out of memory from an HTTP request.
    """
    latest = _latest_retrieval_subquery()
    statement = (
        select(Document, DocumentRetrieval, latest.c.retrieval_count)
        .join(DocumentRetrieval, DocumentRetrieval.document_id == Document.id)
        .join(
            latest,
            (latest.c.document_id == DocumentRetrieval.document_id)
            & (latest.c.retrieved_at == DocumentRetrieval.retrieved_at),
        )
        .order_by(DocumentRetrieval.retrieved_at.desc(), Document.sha256)
        .limit(max(1, min(limit, _MAX_PAGE)))
        .offset(max(0, offset))
    )
    if source_id is not None:
        statement = statement.where(DocumentRetrieval.source_id == source_id)
    if file_format is not None:
        statement = statement.where(Document.file_format == file_format)
    if since is not None:
        statement = statement.where(DocumentRetrieval.retrieved_at >= since)

    return tuple(
        _entry(document, retrieval, count)
        for document, retrieval, count in session.execute(statement)
    )


def catalog_entry(session: Session, document_id: uuid.UUID) -> CatalogEntry | None:
    """One document by id, or ``None``. Never invents an entry for content we do not hold."""
    latest = _latest_retrieval_subquery()
    row = session.execute(
        select(Document, DocumentRetrieval, latest.c.retrieval_count)
        .join(DocumentRetrieval, DocumentRetrieval.document_id == Document.id)
        .join(
            latest,
            (latest.c.document_id == DocumentRetrieval.document_id)
            & (latest.c.retrieved_at == DocumentRetrieval.retrieved_at),
        )
        .where(Document.id == document_id)
        .limit(1)
    ).first()
    return _entry(row[0], row[1], row[2]) if row is not None else None


def corpus_summary(session: Session) -> CorpusSummary:
    """Totals across the whole corpus. Several small aggregates rather than one clever query."""
    documents, bytes_stored, first_seen = session.execute(
        select(
            func.count(Document.id),
            func.coalesce(func.sum(Document.size_bytes), 0),
            func.min(Document.first_seen_at),
        )
    ).one()
    retrievals, last_retrieved = session.execute(
        select(func.count(DocumentRetrieval.id), func.max(DocumentRetrieval.retrieved_at))
    ).one()

    by_source = _counts(session, DocumentRetrieval.source_id, DocumentRetrieval.document_id)
    by_format = _counts(session, Document.file_format, Document.id)
    by_state = _counts(session, Document.state, Document.id)
    urls = _url_counts(session)

    return CorpusSummary(
        documents=int(documents),
        retrievals=int(retrievals),
        bytes_stored=int(bytes_stored),
        sources=len(by_source),
        by_source=by_source,
        by_format=by_format,
        by_state=by_state,
        urls_seen=urls["seen"],
        urls_downloaded=urls["downloaded"],
        urls_failed=urls["failed"],
        urls_dead_lettered=urls["dead_lettered"],
        first_seen_at=first_seen,
        last_retrieved_at=last_retrieved,
    )


def crawl_runs(
    session: Session, *, source_id: str | None = None, limit: int = 20
) -> tuple[RunSummary, ...]:
    """Recent runs, newest first. The operational history of the crawler."""
    statement = (
        select(CrawlJob).order_by(CrawlJob.started_at.desc()).limit(max(1, min(limit, _MAX_PAGE)))
    )
    if source_id is not None:
        statement = statement.where(CrawlJob.source_id == source_id)
    return tuple(_run(job) for job in session.execute(statement).scalars())


def queue_depth_by_source(session: Session) -> Mapping[str, int]:
    """How much work is waiting, per source.

    Counts rows that are *available*: not dead-lettered, not already downloaded. A depth that
    included retired rows would never reach zero and so could never mean "done".
    """
    rows: Sequence[tuple[str, int]] = session.execute(  # type: ignore[assignment]
        select(DiscoveredUrl.source_id, func.count())
        .where(
            DiscoveredUrl.dead_lettered_at.is_(None),
            DiscoveredUrl.state.in_([DocumentState.DISCOVERED, DocumentState.FAILED]),
        )
        .group_by(DiscoveredUrl.source_id)
    ).all()
    return dict(rows)


def _latest_retrieval_subquery() -> Subquery:
    """Per document: when it was last retrieved, and how many times in total.

    A grouped subquery rather than a window function, because the join it feeds needs one row per
    document and a window would need a second pass to filter to it.
    """
    return (
        select(
            DocumentRetrieval.document_id.label("document_id"),
            func.max(DocumentRetrieval.retrieved_at).label("retrieved_at"),
            func.count(DocumentRetrieval.id).label("retrieval_count"),
        )
        .group_by(DocumentRetrieval.document_id)
        .subquery("latest")
    )


def _entry(document: Document, retrieval: DocumentRetrieval, retrieval_count: int) -> CatalogEntry:
    return CatalogEntry(
        document_id=document.id,
        sha256=document.sha256,
        size_bytes=document.size_bytes,
        file_format=document.file_format,
        media_type=document.media_type,
        original_filename=document.original_filename,
        state=document.state,
        first_seen_at=document.first_seen_at,
        source_id=retrieval.source_id,
        requested_url=retrieval.requested_url,
        final_url=retrieval.final_url,
        retrieved_at=retrieval.retrieved_at,
        http_status=retrieval.http_status,
        attempt_count=retrieval.attempt_count,
        retrieval_count=int(retrieval_count),
        storage_bucket=retrieval.storage_bucket,
        storage_key=retrieval.storage_key,
        storage_version_id=retrieval.storage_version_id,
        storage_verification=retrieval.storage_verification,
    )


def _run(job: CrawlJob) -> RunSummary:
    return RunSummary(
        job_id=job.id,
        source_id=job.source_id,
        status=job.status,
        stop_reason=job.stop_reason,
        started_at=job.started_at,
        finished_at=job.finished_at,
        urls_discovered=job.urls_discovered,
        urls_skipped=job.urls_skipped,
        documents_stored=job.documents_stored,
        documents_duplicate=job.documents_duplicate,
        documents_failed=job.documents_failed,
        documents_quarantined=job.documents_quarantined,
        bytes_downloaded=job.bytes_downloaded,
        software_version=job.software_version,
        error_type=job.error_type,
    )


def _counts(session: Session, group: Any, counted: Any) -> Mapping[str, int]:
    rows: Sequence[tuple[object, int]] = session.execute(  # type: ignore[assignment]
        select(group, func.count(func.distinct(counted))).group_by(group)
    ).all()
    return {str(getattr(key, "value", key)): int(count) for key, count in rows if key is not None}


def _url_counts(session: Session) -> Mapping[str, int]:
    """Four counts in one pass.

    ``failed`` counts rows in the ``FAILED`` state, not rows carrying an error label. The two differ
    and the difference is visible in output an operator reads: a retired listing page and a URL
    refused by ``robots.txt`` both carry a label while sitting in ``DISCOVERED``, so counting labels
    reported "3 failed" for one dead link and two pages that were read successfully.
    """
    seen, downloaded, failed, dead = session.execute(
        select(
            func.count(DiscoveredUrl.id),
            func.count(DiscoveredUrl.document_id),
            # count() ignores NULL, so a CASE with no ELSE counts exactly the matching rows.
            func.count(case((DiscoveredUrl.state == DocumentState.FAILED, 1))),
            func.count(DiscoveredUrl.dead_lettered_at),
        )
    ).one()
    return {
        "seen": int(seen or 0),
        "downloaded": int(downloaded or 0),
        "failed": int(failed or 0),
        "dead_lettered": int(dead or 0),
    }
