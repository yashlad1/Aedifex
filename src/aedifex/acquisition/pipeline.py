"""Acquiring one document: the five steps as a single unit of work.

Until now the pipeline existed only assembled by hand inside a test, which meant the composition
itself — the order, the failure mapping, the state the frontier is left in — was not something any
caller could rely on. This is that composition.

.. code-block:: text

    a URL
      ↓  frontier row: DISCOVERED → DOWNLOADING          state exists before the network does
      ↓  RedirectController   guard per hop, retries, one budget
      ↓  download             streamed to disk, hashed on the way past
      ↓  RawObjectStore       uploaded and verified by the store
      ↓  record_retrieval     document row and retrieval row
      ↓  frontier row: → DOWNLOADED                      or FAILED, or QUARANTINED
    AcquisitionResult

**Expected failures return; unexpected ones raise.** A crawler works through thousands of URLs and
most of what goes wrong is ordinary — a 404, a timeout, a portal serving a login page. Those are
recorded on the frontier row and returned, because a crawler that stopped at each one would never
finish a run. What does raise is a conflict in the corpus's identity: two payloads claiming one
digest means either SHA-256 is broken or the caller paired up results from different documents, and
continuing past that would corrupt every citation downstream.

**Unsafe content is quarantined, not failed.** The distinction is in the state machine and it
matters: ``FAILED`` re-enters the pipeline on retry, while ``QUARANTINED`` is terminal and released
only by a human decision. A portal that answers with a login page will answer with one again, so
retrying is pointless; and content that tripped a safety limit is exactly what someone should look
at before it is stored.

**The frontier is updated on every path.** A row left in ``DOWNLOADING`` after a crash is
indistinguishable from one still in flight, so the state is written before the network is touched,
and again once the outcome is known.

**Nothing here commits.** The caller owns the transaction — a crawl run updates its job counters in
the same breath — and a function that committed on its own would make that impossible to do
atomically.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Final, Protocol, runtime_checkable
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from aedifex.acquisition.download import DownloadedFile, DownloadPolicy, download
from aedifex.acquisition.fetch.controller import (
    Cancellation,
    FetchCancelledError,
    FetchFailedError,
)
from aedifex.acquisition.fetch.hosts import SourceHostPolicy
from aedifex.acquisition.fetch.ratelimit import RateLimits
from aedifex.acquisition.fetch.redirect_controller import (
    RedirectController,
    RedirectRejectedError,
)
from aedifex.acquisition.fetch.timing import MonotonicClock, TimeoutBudget, TimeoutPolicy
from aedifex.acquisition.fetch.transport import DEFAULT_CHUNK_SIZE, TransportError
from aedifex.acquisition.fetch.urls import SsrfRejectionError
from aedifex.acquisition.provenance import RecordedRetrieval, record_retrieval
from aedifex.acquisition.registry.models import RetrievalMethod, SourceDefinition
from aedifex.domain.documents import DocumentState, assert_transition_allowed
from aedifex.errors import SourceNotCollectableError, UnsafeContentError
from aedifex.infrastructure.database.models import DiscoveredUrl
from aedifex.infrastructure.storage.objects import StorageError, StoredObject

__all__ = ["Acquirer", "AcquisitionPolicy", "AcquisitionResult", "ObjectStore"]


@runtime_checkable
class ObjectStore(Protocol):
    """The one thing the acquirer needs from object storage.

    A protocol so a test can hand it a store that fails on demand: a real bucket cannot be asked to
    reject an upload at a chosen moment. ``RawObjectStore`` satisfies it structurally.
    """

    def put(self, downloaded: DownloadedFile) -> StoredObject: ...


_ERROR_MESSAGE_LIMIT: Final[int] = 2000
"""Enough to diagnose, bounded so a verbose exception cannot bloat a row.

Truncated rather than dropped: the first two thousand characters of a stack-free message are almost
always the useful part, and an empty column would send someone to the logs for something we already
had.
"""


@dataclass(frozen=True, slots=True)
class AcquisitionPolicy:
    """Everything a source's configuration decides about one acquisition.

    Assembled once per source and reused across its URLs. Grouped rather than passed as six
    arguments because the group *is* the source's policy — and because a caller mixing one source's
    host allowlist with another's rate limits is a mistake worth making hard to write.
    """

    host_policy: SourceHostPolicy
    limits: RateLimits
    download: DownloadPolicy
    # default_factory rather than a shared instance: TimeoutPolicy is frozen, but it is imported
    # from another module and ruff cannot prove that from here — and the day it stops being frozen,
    # a shared default would be one object mutated by every source.
    timeouts: TimeoutPolicy = field(default_factory=TimeoutPolicy)

    @classmethod
    def from_source(
        cls,
        source: SourceDefinition,
        *,
        max_bytes: int | None = None,
        timeouts: TimeoutPolicy | None = None,
    ) -> AcquisitionPolicy:
        """Assemble a source's entire fetch policy from its registry entry.

        The four pieces already knew how to build themselves from a definition; nothing assembled
        them, so every caller wired the four by hand and could mix one source's host allowlist with
        another's rate limits. This is the one door between registry data and network policy.

        Being the one door makes it the right place to enforce the review gate. A source that is not
        collectable cannot have a policy built for it at all, so "we never checked whether we are
        allowed to fetch from this portal" is not a check a caller can forget to make — there is no
        way to reach the network for that source. The registry schema already refuses to *enable* an
        unreviewed source (ADR 0006); this is the same rule at the point of use, because a valid
        definition saying ``enabled: false`` is a definition that must not produce traffic.

        Args:
            source: The registry definition. Must be enabled and approved.
            max_bytes: Payload ceiling, normally ``Settings.max_download_bytes``. Passed in rather
                than read here, so this stays a pure function of the registry and ``config`` keeps
                its monopoly on reading the environment.
            timeouts: Timeout budget for one URL. The registry declares no timeouts — they are a
                property of our patience, not of the source's licence — so this defaults.

        Raises:
            SourceNotCollectableError: if the source is disabled, unreviewed, or has nothing to
                fetch. Never caught by the acquirer, because it is not a failure of a URL.
        """
        if not source.is_collectable:
            raise SourceNotCollectableError(
                f"source {source.id!r} may not be collected from: enabled={source.enabled}, "
                f"verification_status={source.verification_status.value}. A source's terms must be "
                f"reviewed and recorded in its registry entry before it can produce any traffic "
                f"(see DATA_SOURCES.md)"
            )
        if source.retrieval is RetrievalMethod.MANUAL_UPLOAD:
            raise SourceNotCollectableError(
                f"source {source.id!r} has retrieval={source.retrieval.value} and therefore no "
                f"target to fetch; documents from it arrive by upload, not by request"
            )
        return cls(
            host_policy=SourceHostPolicy.from_source(source),
            limits=RateLimits.from_source(source),
            download=DownloadPolicy.from_source(source, max_bytes=max_bytes),
            timeouts=timeouts if timeouts is not None else TimeoutPolicy(),
        )

    @property
    def source_id(self) -> str:
        """Taken from the host policy, so a request cannot be charged to a different source."""
        return self.host_policy.source_id


@dataclass(frozen=True, slots=True)
class AcquisitionResult:
    """What happened to one URL, and where the record of it is.

    Carries the frontier row rather than a copy of its fields, so a caller updating job counters
    reads the same object the database will hold.
    """

    url: str
    source_id: str
    state: DocumentState
    frontier: DiscoveredUrl
    recorded: RecordedRetrieval | None = None
    stored: StoredObject | None = None
    error_type: str | None = None
    error_message: str | None = None
    already_acquired: bool = False
    """True when this URL had already been downloaded, so nothing was fetched at all."""

    @property
    def succeeded(self) -> bool:
        return self.state is DocumentState.DOWNLOADED

    @property
    def document_id(self) -> UUID | None:
        return self.recorded.document.id if self.recorded is not None else None

    @property
    def was_already_stored(self) -> bool:
        """True when the bytes were already in object storage. A re-run reports this."""
        return self.stored is not None and self.stored.already_present

    def describe(self) -> str:
        """One line for a log. Never includes a document body."""
        if self.succeeded and self.stored is not None:
            return f"{self.url} → {self.stored.uri} ({self.state.value})"
        return f"{self.url} → {self.state.value} ({self.error_type or 'no reason recorded'})"


class Acquirer:
    """Acquires one URL at a time, leaving the frontier and the corpus consistent either way."""

    def __init__(
        self,
        *,
        redirects: RedirectController,
        store: ObjectStore,
        staging: Path,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        cancellation: Cancellation | None = None,
    ) -> None:
        self._redirects = redirects
        self._store = store
        self._staging = staging
        self._chunk_size = chunk_size
        self._cancellation = cancellation

    def acquire(
        self,
        session: Session,
        *,
        url: str,
        policy: AcquisitionPolicy,
        job_id: UUID | None = None,
    ) -> AcquisitionResult:
        """Fetch ``url``, store it, and record it. Returns rather than raises for ordinary failures.

        Args:
            session: The caller's session. Flushed, never committed.
            url: The URL to acquire, untrusted. Validated by the guard before anything connects.
            policy: The source's host allowlist, rate limits, permitted formats, and timeouts.
            job_id: The crawl run this belongs to, when there is one.

        Raises:
            ProvenanceConflictError: if the corpus already holds this digest describing different
                content. Not caught, because continuing would corrupt every citation of it.
            FetchCancelledError: if shutdown was signalled. A worker being asked to stop is not a
                failure of the URL, and recording it as one would make a clean shutdown look like a
                portal outage.
        """
        frontier = self._frontier_row(session, url=url, source_id=policy.source_id, job_id=job_id)
        if frontier.state is DocumentState.DOWNLOADED and frontier.document_id is not None:
            # Already have it. Not merely an optimisation: the state machine has no
            # DOWNLOADED -> DOWNLOADING edge, and it is right not to — re-fetching a URL is a
            # different operation from acquiring it, because a *changed* document has a different
            # digest and is therefore a different document, not a new version of this one. Deciding
            # what that means for a content-addressed corpus is a real design question and not a
            # flag on this method, so for now a re-crawl skips what it already has (FR-072).
            return AcquisitionResult(
                url=url,
                source_id=policy.source_id,
                state=DocumentState.DOWNLOADED,
                frontier=frontier,
                already_acquired=True,
            )
        self._begin(session, frontier)

        try:
            downloaded = self._fetch(url, policy)
        except FetchCancelledError:
            # Put the row back where it was: not attempted, rather than attempted and failed.
            frontier.state = DocumentState.DISCOVERED
            session.flush()
            raise
        except UnsafeContentError as error:
            return self._quarantine(session, frontier, policy, error)
        except (
            SsrfRejectionError,
            RedirectRejectedError,
            FetchFailedError,
            TransportError,
        ) as error:
            return self._fail(session, frontier, policy, error)

        try:
            stored = self._store.put(downloaded)
        except StorageError as error:
            return self._fail(session, frontier, policy, error)
        finally:
            # The staged copy has served its purpose either way. On success the bytes are durably in
            # the store and re-downloading is idempotent; on failure keeping a file nobody will look
            # at only fills a disk. Missing is fine — the downloader removes its own partials.
            downloaded.path.unlink(missing_ok=True)

        recorded = record_retrieval(session, downloaded=downloaded, stored=stored)

        frontier.state = _advance(frontier, DocumentState.DOWNLOADED)
        frontier.document_id = recorded.document.id
        frontier.downloaded_at = datetime.now(UTC)
        frontier.http_status = downloaded.http_status
        frontier.attempts = max(1, len(downloaded.attempts))
        frontier.error_type = None
        frontier.error_message = None
        session.flush()

        return AcquisitionResult(
            url=url,
            source_id=policy.source_id,
            state=DocumentState.DOWNLOADED,
            frontier=frontier,
            recorded=recorded,
            stored=stored,
        )

    def _fetch(self, url: str, policy: AcquisitionPolicy) -> DownloadedFile:
        """Fetch and download together: the response must stay open while its body is read."""
        budget = TimeoutBudget(policy=policy.timeouts, clock=MonotonicClock())
        with self._redirects.fetch(
            url,
            host_policy=policy.host_policy,
            limits=policy.limits,
            budget=budget,
            # Passed through so a worker asked to stop during a backoff stops, rather than finishing
            # its wait first. Without this the FetchCancelledError branch below would be unreachable
            # — which it was, in the first version of this file.
            cancellation=self._cancellation,
        ) as chain:
            return download(
                chain,
                source_id=policy.source_id,
                policy=policy.download,
                directory=self._staging,
                chunk_size=self._chunk_size,
            )

    def _frontier_row(
        self, session: Session, *, url: str, source_id: str, job_id: UUID | None
    ) -> DiscoveredUrl:
        """Find this URL's frontier row, or create it.

        Keyed on the digest of the URL rather than its text, because procurement portals emit URLs
        long enough to exceed a btree index limit. Found rather than inserted blindly so that
        re-running a crawl updates the same row instead of accumulating one per attempt.
        """
        url_sha256 = hashlib.sha256(url.encode("utf-8")).hexdigest()
        existing = session.execute(
            select(DiscoveredUrl).where(
                DiscoveredUrl.source_id == source_id,
                DiscoveredUrl.url_sha256 == url_sha256,
            )
        ).scalar_one_or_none()
        if existing is not None:
            if job_id is not None:
                existing.job_id = job_id
            return existing
        row = DiscoveredUrl(source_id=source_id, url=url, url_sha256=url_sha256, job_id=job_id)
        session.add(row)
        session.flush()
        return row

    @staticmethod
    def _begin(session: Session, frontier: DiscoveredUrl) -> None:
        """Mark the row as being worked on before anything touches the network.

        Written first so a crash leaves evidence that this URL was attempted. The alternative — set
        the state after the fetch — leaves a crashed worker's URLs indistinguishable from ones never
        tried.
        """
        frontier.state = _advance(frontier, DocumentState.DOWNLOADING)
        frontier.last_attempted_at = datetime.now(UTC)
        session.flush()

    def _fail(
        self,
        session: Session,
        frontier: DiscoveredUrl,
        policy: AcquisitionPolicy,
        error: Exception,
    ) -> AcquisitionResult:
        """Record an ordinary failure. Retryable, because ``FAILED`` re-enters the pipeline."""
        return self._finish(session, frontier, policy, DocumentState.FAILED, error)

    def _quarantine(
        self,
        session: Session,
        frontier: DiscoveredUrl,
        policy: AcquisitionPolicy,
        error: UnsafeContentError,
    ) -> AcquisitionResult:
        """Record content that tripped a safety limit. Terminal until a human releases it.

        A portal answering a document request with a login page will answer with one again, so this
        is not a transient failure — and content that failed a safety check is precisely what should
        be looked at rather than retried into the corpus.
        """
        return self._finish(session, frontier, policy, DocumentState.QUARANTINED, error)

    @staticmethod
    def _finish(
        session: Session,
        frontier: DiscoveredUrl,
        policy: AcquisitionPolicy,
        state: DocumentState,
        error: Exception,
    ) -> AcquisitionResult:
        frontier.state = _advance(frontier, state)
        frontier.attempts += 1
        frontier.error_type = _classify(error)
        frontier.error_message = str(error)[:_ERROR_MESSAGE_LIMIT]
        # The status, when the failure was an HTTP one. Read from the last attempt rather than from
        # an attribute on the exception, because none of these errors carries one — an earlier
        # version reached for `error.http_status` and silently recorded nothing every time.
        if isinstance(error, FetchFailedError) and error.attempts:
            frontier.http_status = error.attempts[-1].status_code
        session.flush()
        return AcquisitionResult(
            url=frontier.url,
            source_id=policy.source_id,
            state=state,
            frontier=frontier,
            error_type=frontier.error_type,
            error_message=frontier.error_message,
        )


def _classify(error: Exception) -> str:
    """The label to record for a failure.

    An :class:`~aedifex.acquisition.fetch.retry.AttemptOutcome` when the error carries one, because
    that is a controlled vocabulary built for exactly this and it distinguishes cases a Python type
    name flattens: ``RedirectRejectedError`` covers both an SSRF refusal and a hop-cap breach, and
    "how many URLs were refused for SSRF" should not be a ``LIKE`` over error messages.

    Falls back to the exception's type name for the errors that carry no classification — content
    and storage failures — which is why the column is a string rather than an enum.
    """
    outcome = getattr(error, "final_outcome", None) or getattr(error, "outcome", None)
    label = getattr(outcome, "value", None)
    if isinstance(label, str):
        return label[:128]
    return type(error).__name__[:128]


def _advance(frontier: DiscoveredUrl, target: DocumentState) -> DocumentState:
    """Move the row's state, refusing an illegal move loudly.

    The state machine is checked here rather than trusted, because an illegal transition means the
    pipeline has lost track of where a URL is — and a silently corrupted frontier is how a crawl
    starts re-downloading things it already has, or stops looking at things it never fetched.
    """
    assert_transition_allowed(frontier.state, target)
    return target
