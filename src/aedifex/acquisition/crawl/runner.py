"""The crawl run: discovery, the frontier, and acquisition as one resumable loop.

.. code-block:: text

    open a job row                      RUNNING, or resume the one already open
      ↓  robots.txt fetched once per authority, Crawl-delay folded into the limits
      ↓  seeds enqueued at depth 0
      ↓  ┌ reclaim URLs whose worker died
         │ claim a batch                FOR UPDATE SKIP LOCKED
         │   page     → read, classify links, enqueue the new ones
         │   document → acquire: fetch, store, record provenance
         │ commit                       per URL
         └ until the frontier drains, a limit is reached, or shutdown is signalled
      ↓  close the job row              counters, stop reason, duration

**One transaction per URL.** A crash loses at most that URL's work, and its lease expires so another
worker picks it up. Committing per batch would be faster and would make an interrupted run's
bookkeeping a lie.

**Limits are evaluated against the job's durable counters, not this process's memory.** A run capped
at 100 documents and interrupted at 60 fetches 40 more when resumed, not 100. That works only
because the counters are on the row.

**A page is not a document and is never stored.** It is read, mined for links, and discarded; what
survives is ``discovered_via`` on the rows it produced. Which of the two a claimed URL is comes from
its extension and the source's permitted formats, so a resumed run reaches the same conclusion as
the run that queued it.

**Backpressure is structural** (rule 49). Discovery and acquisition are the same loop, so the
frontier cannot grow faster than URLs are drained from it — there is no separate producer to outrun
the consumer.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Final

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from aedifex.acquisition.crawl.discovery import (
    DiscoveryStrategy,
    LinkKind,
    is_document_url,
    strategy_for,
)
from aedifex.acquisition.crawl.frontier import Candidate, FrontierQueue
from aedifex.acquisition.crawl.pages import PageReader
from aedifex.acquisition.crawl.robots import RobotsGate, polite_limits
from aedifex.acquisition.fetch.controller import Cancellation, FetchFailedError
from aedifex.acquisition.fetch.redirect_controller import (
    RedirectController,
    RedirectRejectedError,
)
from aedifex.acquisition.fetch.timing import Clock, MonotonicClock
from aedifex.acquisition.fetch.transport import TransportError
from aedifex.acquisition.fetch.urls import SsrfRejectionError
from aedifex.acquisition.pipeline import Acquirer, AcquisitionPolicy, AcquisitionResult
from aedifex.acquisition.registry.models import SourceDefinition
from aedifex.domain.documents import DocumentState
from aedifex.infrastructure.database.models import CrawlJob, CrawlJobStatus, DiscoveredUrl
from aedifex.infrastructure.observability.logging import bind_job_context, get_logger

__all__ = ["CrawlLimits", "CrawlOutcome", "CrawlRunner", "StopReason"]

_log = get_logger(__name__)

_ERROR_MESSAGE_LIMIT: Final[int] = 2000

_RETRY_BASE_SECONDS: Final[float] = 300.0
_RETRY_CEILING_SECONDS: Final[float] = 6 * 3600.0


def _backoff(attempts: int) -> float:
    """How long to defer a URL that failed, so this run does not try it again.

    Retrying inside one run is almost always pointless and never polite: the portal that just
    answered 404 will answer 404 in two seconds, and the one that just timed out is not helped by
    another request. Retries belong to the *next* run, which is why the delay is measured in minutes
    and the wait lives in the database rather than in a sleep.

    Distinct from the fetch layer's backoff, which is between attempts within one acquisition and is
    measured in seconds. This is between acquisitions.
    """
    return min(_RETRY_CEILING_SECONDS, _RETRY_BASE_SECONDS * float(2 ** max(0, attempts - 1)))


class StopReason(StrEnum):
    """Why a run ended. Distinct from whether it succeeded.

    A run that stops at its document cap succeeded and has more to do; a run that drained the
    frontier succeeded and has not. Without recording which, a resumed crawl cannot tell "there is
    nothing left" from "we were told to stop", and an operator cannot tell a finished source from a
    throttled one.
    """

    FRONTIER_DRAINED = "frontier_drained"
    DOCUMENT_LIMIT = "document_limit"
    PAGE_LIMIT = "page_limit"
    TIME_LIMIT = "time_limit"
    CANCELLED = "cancelled"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class CrawlLimits:
    """What bounds one run. Every field is a ceiling; ``None`` means the registry decides.

    Rule 51: a crawl with no limit is a crawl that stops when the portal does.
    """

    max_documents: int | None = None
    max_pages: int | None = None
    max_seconds: float | None = None
    batch_size: int = 10
    """URLs claimed per round trip. Small, because each is committed separately anyway."""
    dry_run: bool = False
    """Discover, but download nothing.

    The rehearsal a new source gets before it is trusted with bytes: listing pages are read and
    the frontier is filled, and every document URL found is deferred instead of fetched. It answers
    "does discovery work here, and what would we have collected?" — the question to ask of a portal
    nobody has crawled before, and answering it costs the site only its listing pages.
    """

    def __post_init__(self) -> None:
        if self.batch_size < 1:
            raise ValueError(f"batch_size must be at least 1, got {self.batch_size}")

    def for_source(self, source: SourceDefinition) -> CrawlLimits:
        """Fill unset ceilings from the source's registry entry."""
        from dataclasses import replace

        return replace(
            self,
            max_documents=(
                self.max_documents
                if self.max_documents is not None
                else source.rate_limit.max_documents_per_run
            ),
            max_pages=self.max_pages if self.max_pages is not None else source.discovery.max_pages,
        )


@dataclass(frozen=True, slots=True)
class CrawlOutcome:
    """What one run did.

    Read back from the job row, so it reports what was persisted rather than what a counter in
    memory believed.
    """

    job_id: uuid.UUID
    source_id: str
    status: CrawlJobStatus
    stop_reason: StopReason
    urls_discovered: int
    urls_skipped: int
    documents_stored: int
    documents_duplicate: int
    documents_failed: int
    documents_quarantined: int
    bytes_downloaded: int
    pages_read: int
    duration_seconds: float
    error_type: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.status is CrawlJobStatus.SUCCEEDED

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
        """Stored or already-held, over everything attempted. ``1.0`` when nothing was attempted.

        A run that attempted nothing has not failed at anything, and reporting 0% would make an
        idle source look like a broken one.
        """
        seen = self.documents_seen
        if seen == 0:
            return 1.0
        return (self.documents_stored + self.documents_duplicate) / seen

    @property
    def duplicate_rate(self) -> float:
        """How much of what we fetched we already had. High is normal on a re-crawl."""
        seen = self.documents_seen
        return self.documents_duplicate / seen if seen else 0.0

    def describe(self) -> str:
        return (
            f"{self.source_id}: {self.status.value} ({self.stop_reason.value}) — "
            f"{self.urls_discovered} URLs found, {self.pages_read} pages read, "
            f"{self.documents_stored} stored, {self.documents_duplicate} already held, "
            f"{self.documents_failed} failed, {self.documents_quarantined} quarantined, "
            f"{self.urls_skipped} skipped, {self.bytes_downloaded} bytes, "
            f"{self.duration_seconds:.1f}s"
        )


class CrawlRunner:
    """Runs one source's crawl to completion, or to a limit, or to a clean stop."""

    def __init__(
        self,
        *,
        acquirer: Acquirer,
        redirects: RedirectController,
        sessions: sessionmaker[Session],
        software_version: str,
        worker: str = "runner",
        user_agent: str,
        clock: Clock | None = None,
        cancellation: Cancellation | None = None,
    ) -> None:
        self._acquirer = acquirer
        self._redirects = redirects
        self._sessions = sessions
        self._software_version = software_version
        self._worker = worker
        self._user_agent = user_agent
        self._clock = clock if clock is not None else MonotonicClock()
        self._cancellation = cancellation

    def run(self, source: SourceDefinition, *, limits: CrawlLimits | None = None) -> CrawlOutcome:
        """Crawl ``source`` until the frontier drains, a limit is reached, or shutdown is signalled.

        Resumes an already-open run for this source rather than starting a second one, so an
        interrupted crawl continues with its counters and its limits intact.

        Raises:
            SourceNotCollectableError: if the source is not enabled and approved. Nothing is
                written.
            CrawlDelayTooLongError: if ``robots.txt`` asks for a delay this project will not wait.
        """
        policy = AcquisitionPolicy.from_source(source)
        bounds = (limits or CrawlLimits()).for_source(source)
        strategy = strategy_for(source)
        started = self._clock.now()

        with self._sessions() as session:
            job = self._open_job(session, source)
            session.commit()
            job_id = job.id

        with bind_job_context(job_id=str(job_id), source_id=source.id):
            _log.info(
                "crawl.started", worker=self._worker, dry_run=bounds.dry_run, **_bounds(bounds)
            )
            try:
                reason = self._crawl(
                    source=source,
                    policy=policy,
                    strategy=strategy,
                    bounds=bounds,
                    job_id=job_id,
                    started=started,
                )
                status = (
                    CrawlJobStatus.CANCELLED
                    if reason is StopReason.CANCELLED
                    else CrawlJobStatus.SUCCEEDED
                )
                outcome = self._close_job(job_id, source.id, status, reason, started)
            except Exception as error:
                outcome = self._close_job(
                    job_id, source.id, CrawlJobStatus.FAILED, StopReason.FAILED, started, error
                )
                _log.error("crawl.failed", error_type=type(error).__name__)
                raise
            _log.info("crawl.finished", **_metrics(outcome))
            return outcome

    # -- the loop ----------------------------------------------------------

    def _crawl(
        self,
        *,
        source: SourceDefinition,
        policy: AcquisitionPolicy,
        strategy: DiscoveryStrategy,
        bounds: CrawlLimits,
        job_id: uuid.UUID,
        started: float,
    ) -> StopReason:
        robots = RobotsGate.from_source(
            source,
            redirects=self._redirects,
            user_agent=self._user_agent,
            host_policy=policy.host_policy,
            limits=policy.limits,
            timeouts=policy.timeouts,
        )
        frontier = FrontierQueue(source_id=source.id, worker=self._worker)

        with self._sessions() as session:
            self._seed(session, source, strategy, frontier, robots, job_id)
            frontier.reclaim_expired(session)
            session.commit()

        # Politeness is settled once, before the first document: Crawl-delay applies to the whole
        # authority, and re-deriving it per URL would let a cached miss change the rate mid-run.
        polite = polite_limits(policy.limits, robots.rules_for(str(source.base_url)))
        if polite is not policy.limits:
            _log.info(
                "crawl.crawl_delay_honoured",
                min_delay_seconds=polite.min_delay_seconds,
                requests_per_minute=polite.requests_per_minute,
            )
        from dataclasses import replace

        acquisition_policy = replace(policy, limits=polite)
        reader = PageReader(
            redirects=self._redirects,
            host_policy=policy.host_policy,
            limits=polite,
            timeouts=policy.timeouts,
        )

        # A dry run defers each document it finds rather than fetching it, and a short deferral can
        # expire inside a long run — so the same URL comes back around and is reported twice. Which
        # ones have already been inspected is therefore tracked for the duration of the run, and a
        # batch containing nothing new means the frontier has been walked.
        inspected: set[uuid.UUID] = set()
        formats = policy.download.allowed_formats

        while True:
            if self._cancelled():
                return StopReason.CANCELLED
            limit_reached = self._limit_reached(job_id, bounds, started)
            if limit_reached is not None:
                return limit_reached

            with self._sessions() as session:
                claimed = frontier.claim(session, limit=bounds.batch_size)
                session.commit()
            if not claimed:
                return StopReason.FRONTIER_DRAINED

            progressed = False
            for position, row in enumerate(claimed):
                # Re-checked per URL, not once per batch. Checking only at the top of the loop
                # lets a batch of ten sail past the ceiling: a live dry run asked for max_pages=3
                # and read eleven, which for a bounded first run against a real portal is the one
                # thing that must not be approximate.
                limit_reached = self._limit_reached(job_id, bounds, started)
                if limit_reached is not None:
                    self._give_back_all(frontier, claimed[position:])
                    return limit_reached
                if bounds.dry_run and is_document_url(row.url, formats):
                    if row.id in inspected:
                        continue
                    inspected.add(row.id)
                progressed = True
                if self._cancelled():
                    self._give_back_all(frontier, claimed[position:])
                    return StopReason.CANCELLED
                self._handle(
                    row=row,
                    policy=acquisition_policy,
                    strategy=strategy,
                    robots=robots,
                    reader=reader,
                    frontier=frontier,
                    job_id=job_id,
                    dry_run=bounds.dry_run,
                )
            if not progressed:
                # Every URL in this batch was one a dry run had already reported.
                return StopReason.FRONTIER_DRAINED

    def _handle(
        self,
        *,
        row: DiscoveredUrl,
        policy: AcquisitionPolicy,
        strategy: DiscoveryStrategy,
        robots: RobotsGate,
        reader: PageReader,
        frontier: FrontierQueue,
        job_id: uuid.UUID,
        dry_run: bool,
    ) -> None:
        """One URL, in one transaction. Nothing here is allowed to raise for an ordinary failure."""
        url = row.url
        with self._sessions() as session:
            attached = session.get(DiscoveredUrl, row.id)
            if attached is None:  # pragma: no cover - the row was just claimed
                return
            job = session.get(CrawlJob, job_id)
            assert job is not None  # noqa: S101 - opened by this run, in this transaction

            decision = robots.allows(url)
            if not decision.allowed:
                self._refuse(session, frontier, attached, job, reason=decision.reason)
                session.commit()
                return

            if is_document_url(url, policy.download.allowed_formats):
                if dry_run:
                    self._would_fetch(session, frontier, attached)
                    session.commit()
                    return
                result = self._acquire(session, attached, policy, job_id)
                self._count_acquisition(job, result)
                exhausted = frontier.settle(session, attached)
                if result.state is DocumentState.FAILED and not exhausted:
                    # Deferred, not left claimable. Without this the claim loop picks the row up
                    # again immediately and a single dead link costs one request per remaining
                    # attempt *within one run* — measured, on the first end-to-end run: five
                    # requests for one 404, recorded as five separate failures.
                    frontier.release(
                        session, attached, retry_after_seconds=_backoff(attached.attempts)
                    )
            else:
                self._read_page(
                    session,
                    row=attached,
                    job=job,
                    strategy=strategy,
                    reader=reader,
                    robots=robots,
                    frontier=frontier,
                    job_id=job_id,
                )
            session.commit()

    def _acquire(
        self,
        session: Session,
        row: DiscoveredUrl,
        policy: AcquisitionPolicy,
        job_id: uuid.UUID,
    ) -> AcquisitionResult:
        result = self._acquirer.acquire(session, url=row.url, policy=policy, job_id=job_id)
        _log.info(
            "crawl.document",
            url=row.url,
            state=result.state.value,
            error_type=result.error_type,
            already_stored=result.was_already_stored,
        )
        return result

    def _read_page(
        self,
        session: Session,
        *,
        row: DiscoveredUrl,
        job: CrawlJob,
        strategy: DiscoveryStrategy,
        reader: PageReader,
        robots: RobotsGate,
        frontier: FrontierQueue,
        job_id: uuid.UUID,
    ) -> None:
        """Read a listing page and queue what it offers. The page itself is never stored."""
        row.last_attempted_at = datetime.now(UTC)
        session.flush()
        try:
            page = reader.read(row.url, depth=row.depth, request=strategy.request_for(row.url))
        except (SsrfRejectionError, RedirectRejectedError, FetchFailedError, TransportError) as e:
            # A listing page that cannot be read is an ordinary failure of one URL, retryable like
            # any other: portals go down for an afternoon. It is *not* counted as a failed document,
            # because it is not a document. The row records it; runs report pages separately.
            row.state = DocumentState.FAILED
            row.attempts += 1
            row.error_type = _label(e)
            row.error_message = str(e)[:_ERROR_MESSAGE_LIMIT]
            if not frontier.settle(session, row):
                frontier.release(session, row, retry_after_seconds=_backoff(row.attempts))
            _log.warning("crawl.page_failed", url=row.url, error_type=row.error_type)
            return

        links = strategy.links(page)
        queueable = [link for link in links if link.is_queueable]
        result = frontier.enqueue(
            session,
            [
                Candidate(url=link.url, depth=link.depth, discovered_via=page.url)
                for link in queueable
                if robots.allows(link.url).allowed
            ],
            job_id=job_id,
        )
        refused = sum(1 for link in queueable if not robots.allows(link.url).allowed)
        ignored = sum(1 for link in links if link.kind is LinkKind.IGNORED)

        job.urls_discovered += result.accepted
        job.urls_skipped += ignored + refused + len(result.rejected)
        _retire(row, "page_read")
        frontier.settle(session, row)
        _pages_read(job, 1)
        _log.info(
            "crawl.page_read",
            url=page.url,
            links=len(links),
            queued=result.accepted,
            known=result.duplicates,
            skipped=ignored + refused,
        )

    # -- bookkeeping -------------------------------------------------------

    def _seed(
        self,
        session: Session,
        source: SourceDefinition,
        strategy: DiscoveryStrategy,
        frontier: FrontierQueue,
        robots: RobotsGate,
        job_id: uuid.UUID,
    ) -> None:
        seeds = strategy.seeds(source)
        permitted = [url for url in seeds if robots.allows(url).allowed]
        refused = len(seeds) - len(permitted)
        result = frontier.enqueue(
            session, [Candidate(url=url, depth=0) for url in permitted], job_id=job_id
        )
        job = session.get(CrawlJob, job_id)
        if job is not None:
            job.urls_discovered += result.accepted
            job.urls_skipped += refused + len(result.rejected)
            job.checkpoint = {"seeded": True, "seeds": list(seeds)}
        _log.info(
            "crawl.seeded", seeds=len(seeds), queued=result.accepted, refused_by_robots=refused
        )

    def _open_job(self, session: Session, source: SourceDefinition) -> CrawlJob:
        """Resume this source's open run if there is one, so an interruption continues it."""
        existing = session.execute(
            select(CrawlJob)
            .where(
                CrawlJob.source_id == source.id,
                CrawlJob.status == CrawlJobStatus.RUNNING,
            )
            .order_by(CrawlJob.started_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        if existing is not None:
            _log.info("crawl.resumed", job_id=str(existing.id))
            return existing
        job = CrawlJob(source_id=source.id, software_version=self._software_version)
        session.add(job)
        session.flush()
        return job

    def _close_job(
        self,
        job_id: uuid.UUID,
        source_id: str,
        status: CrawlJobStatus,
        reason: StopReason,
        started: float,
        error: Exception | None = None,
    ) -> CrawlOutcome:
        duration = self._clock.now() - started
        with self._sessions() as session:
            job = session.get(CrawlJob, job_id)
            assert job is not None  # noqa: S101 - opened by this run
            job.status = status
            job.stop_reason = reason.value
            job.finished_at = datetime.now(UTC)
            if error is not None:
                job.error_type = type(error).__name__[:128]
                job.error_message = str(error)[:_ERROR_MESSAGE_LIMIT]
            session.commit()
            return CrawlOutcome(
                job_id=job_id,
                source_id=source_id,
                status=status,
                stop_reason=reason,
                urls_discovered=job.urls_discovered,
                urls_skipped=job.urls_skipped,
                documents_stored=job.documents_stored,
                documents_duplicate=job.documents_duplicate,
                documents_failed=job.documents_failed,
                documents_quarantined=job.documents_quarantined,
                bytes_downloaded=job.bytes_downloaded,
                pages_read=_pages_read(job, 0),
                duration_seconds=duration,
                error_type=job.error_type,
            )

    @staticmethod
    def _count_acquisition(job: CrawlJob, result: AcquisitionResult) -> None:
        if result.already_acquired or result.was_already_stored:
            job.documents_duplicate += 1
        elif result.state is DocumentState.DOWNLOADED:
            job.documents_stored += 1
        elif result.state is DocumentState.QUARANTINED:
            job.documents_quarantined += 1
        else:
            job.documents_failed += 1
        if result.stored is not None and not result.stored.already_present:
            job.bytes_downloaded += result.stored.size_bytes

    @staticmethod
    def _would_fetch(session: Session, frontier: FrontierQueue, row: DiscoveredUrl) -> None:
        """Record a document a real run would have fetched, and touch nothing else.

        Deferred rather than released, or the claim loop would hand it straight back and a dry run
        would never finish. No attempt is charged and no state moves, so the frontier a dry run
        leaves behind is exactly what a real run would start from.
        """
        frontier.release(session, row, retry_after_seconds=1.0)
        _log.info("crawl.would_fetch", url=row.url)

    @staticmethod
    def _refuse(
        session: Session,
        frontier: FrontierQueue,
        row: DiscoveredUrl,
        job: CrawlJob,
        *,
        reason: str,
    ) -> None:
        """A URL robots.txt forbids. Recorded, never retried: robots will say the same tomorrow."""
        _retire(row, "robots_disallowed", detail=reason)
        job.urls_skipped += 1
        frontier.settle(session, row)
        _log.info("crawl.robots_refused", url=row.url, reason=reason)

    def _give_back_all(self, frontier: FrontierQueue, rows: Sequence[DiscoveredUrl]) -> None:
        """Return leases on URLs this run will not get to, so the next one starts on them at once.

        Without this the remainder of a claimed batch stays leased until it expires, and a run
        stopped by a limit would leave up to a batch of URLs untouchable for the lease duration —
        which looks exactly like a crashed worker to whatever comes next.
        """
        if not rows:
            return
        with self._sessions() as session:
            for row in rows:
                attached = session.get(DiscoveredUrl, row.id)
                if attached is not None:
                    frontier.release(session, attached)
            session.commit()

    def _cancelled(self) -> bool:
        return self._cancellation is not None and self._cancellation.wait(0)

    def _limit_reached(
        self, job_id: uuid.UUID, bounds: CrawlLimits, started: float
    ) -> StopReason | None:
        """Checked against the job's persisted counters, so limits survive a resume."""
        if bounds.max_seconds is not None and self._clock.now() - started >= bounds.max_seconds:
            return StopReason.TIME_LIMIT
        with self._sessions() as session:
            job = session.get(CrawlJob, job_id)
            if job is None:  # pragma: no cover - opened by this run
                return None
            if bounds.max_documents is not None:
                attempted = (
                    job.documents_stored
                    + job.documents_duplicate
                    + job.documents_failed
                    + job.documents_quarantined
                )
                if attempted >= bounds.max_documents:
                    return StopReason.DOCUMENT_LIMIT
            if bounds.max_pages is not None and _pages_read(job, 0) >= bounds.max_pages:
                return StopReason.PAGE_LIMIT
        return None


def _retire(row: DiscoveredUrl, reason: str, *, detail: str | None = None) -> None:
    """Take a URL out of the queue for good without calling it a failed document.

    Two cases need this: a listing page that was read and discarded, and a URL ``robots.txt``
    forbids. Neither is a failed download, and neither is content.

    The state is left as ``DISCOVERED`` — true enough: the URL was seen and nothing was downloaded
    from it — and no attempt is charged, because in the robots case nothing was attempted. What
    takes it out of the queue is ``dead_lettered_at``: the claim query skips those rows, which is
    the behaviour wanted.

    That column is named for the case it was added for, exhausted retries, and this is a second
    meaning for it: "never claim this again". Recorded here rather than papered over, because the
    honest alternatives were worse — marking a successfully read page ``FAILED`` would put every
    listing page a crawl reads into the failure queries an operator relies on, and a ``DOWNLOADED``
    page would violate the check constraint requiring content-bearing states to name a document.
    """
    row.error_type = reason
    row.error_message = detail[:_ERROR_MESSAGE_LIMIT] if detail else None
    row.dead_lettered_at = datetime.now(UTC)


def _pages_read(job: CrawlJob, add: int) -> int:
    """Pages read, kept in the job's checkpoint.

    In the checkpoint rather than as a column because it is the one counter that is a property of a
    *strategy* — an API source reads no pages — and a column meaningless for half the sources is a
    column that gets misread.
    """
    checkpoint = dict(job.checkpoint or {})
    current = checkpoint.get("pages_read")
    total = (current if isinstance(current, int) else 0) + add
    if add:
        checkpoint["pages_read"] = total
        job.checkpoint = checkpoint
    return total


def _label(error: Exception) -> str:
    outcome = getattr(error, "final_outcome", None) or getattr(error, "outcome", None)
    label = getattr(outcome, "value", None)
    return label[:128] if isinstance(label, str) else type(error).__name__[:128]


def _bounds(limits: CrawlLimits) -> dict[str, object]:
    """The ceilings a run is operating under, for its opening log line."""
    return {
        "max_documents": limits.max_documents,
        "max_pages": limits.max_pages,
        "max_seconds": limits.max_seconds,
        "batch_size": limits.batch_size,
    }


def _metrics(outcome: CrawlOutcome) -> dict[str, object]:
    """Run metrics for one structured log line.

    Bounded cardinality on purpose (rule 62): counts and rates only, no URLs and no document ids.
    Those belong in the per-URL events above, which are logs rather than metrics.
    """
    return {
        "status": outcome.status.value,
        "stop_reason": outcome.stop_reason.value,
        "urls_discovered": outcome.urls_discovered,
        "urls_skipped": outcome.urls_skipped,
        "pages_read": outcome.pages_read,
        "documents_stored": outcome.documents_stored,
        "documents_duplicate": outcome.documents_duplicate,
        "documents_failed": outcome.documents_failed,
        "documents_quarantined": outcome.documents_quarantined,
        "bytes_downloaded": outcome.bytes_downloaded,
        "success_rate": round(outcome.success_rate, 4),
        "duplicate_rate": round(outcome.duplicate_rate, 4),
        "duration_seconds": round(outcome.duration_seconds, 3),
    }
