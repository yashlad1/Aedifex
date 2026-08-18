"""The crawl frontier: a durable queue in the table that already held the state.

``discovered_urls`` has always been the frontier. This makes it the *queue* as well — claims,
leases, backoff, and dead-lettering — rather than adding a broker beside it (ADR 0012). The state a
queue needs was already here: per-URL state, an attempt counter, and a job id.

.. code-block:: text

    enqueue          ON CONFLICT DO NOTHING on (source, canonical URL digest)
       ↓
    claim            FOR UPDATE SKIP LOCKED, lease committed before the network
       ↓
    the acquirer     DISCOVERED/FAILED → DOWNLOADING → DOWNLOADED | FAILED | QUARANTINED
       ↓
    settle           lease cleared; dead-lettered if the attempts are spent
       ↓
    reclaim_expired  a worker that died mid-URL does not hold it forever

**Delivery is at-least-once, made effectively-once by content addressing.** A worker that dies after
fetching but before committing loses its lease, the URL is claimed again, and the second attempt
re-downloads the same bytes: the digest is the same, so the object store reports the key already
present and the document row is found rather than inserted. What *is* appended is a second retrieval
row, which is correct — it happened.

**A claim is a lease, not a state change.** The acquirer owns the document state machine, and having
two things move a row through it would mean two places to get it wrong. A lease says only "a worker
is looking at this until then", which is a different fact from "this URL is being downloaded", and
the difference is what lets a crashed worker be detected at all.

**Traversal is deterministic.** Claims are ordered by depth, then discovery time, then id — so a
resumed crawl continues where it left off rather than in whatever order the planner produced, and
two runs over the same frontier visit URLs in the same order. ``UPDATE … RETURNING`` does not
promise an order, so the rows are re-sorted after the claim rather than trusted.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final

from sqlalchemy import Select, case, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from aedifex.acquisition.canonical import canonical_url, url_digest
from aedifex.acquisition.fetch.urls import SsrfRejectionError
from aedifex.domain.documents import DocumentState
from aedifex.infrastructure.database.models import DiscoveredUrl

__all__ = [
    "DEFAULT_LEASE_SECONDS",
    "DEFAULT_MAX_ATTEMPTS",
    "Candidate",
    "EnqueueResult",
    "FrontierQueue",
]

DEFAULT_LEASE_SECONDS: Final[float] = 900.0
"""How long a claim is honoured before another worker may take the URL.

Comfortably longer than the fetch layer's own total budget, so a lease never expires under a request
that is still running — an expiry that races a live download produces two workers on one URL, which
at-least-once delivery tolerates but which wastes a request against a portal we are being polite to.
"""

DEFAULT_MAX_ATTEMPTS: Final[int] = 5
"""Attempts before a URL is dead-lettered for a human to look at (rule 47).

Distinct from the fetch layer's retry count, which is attempts *within* one acquisition. This counts
acquisitions: five separate occasions on which we tried this URL and something went wrong.
"""

_CLAIMABLE_STATES: Final[tuple[DocumentState, ...]] = (
    DocumentState.DISCOVERED,
    DocumentState.FAILED,
)
"""``FAILED`` is claimable because a retry is a legal transition out of it, by design (FR-053).

``QUARANTINED`` is not, and neither is ``DOWNLOADED``: the first is terminal until a human
releases it, and the second is already done.
"""


@dataclass(frozen=True, slots=True)
class Candidate:
    """A URL that discovery wants queued, with where it came from."""

    url: str
    depth: int = 0
    discovered_via: str | None = None


@dataclass(frozen=True, slots=True)
class EnqueueResult:
    """What one batch of candidates did to the frontier.

    ``duplicates`` is the number worth watching. A crawl where almost every discovered URL is
    already known is a crawl finding nothing new, which is either a finished source or a broken
    discovery strategy — and the two look identical without this number.
    """

    accepted: int = 0
    duplicates: int = 0
    rejected: tuple[tuple[str, str], ...] = ()
    """URLs that could not be queued at all, each with the reason. Malformed, or off-policy."""

    @property
    def seen(self) -> int:
        return self.accepted + self.duplicates + len(self.rejected)

    def describe(self) -> str:
        return (
            f"{self.accepted} new, {self.duplicates} already known, "
            f"{len(self.rejected)} rejected"
        )


class FrontierQueue:
    """One source's frontier, seen as a work queue by one worker."""

    def __init__(
        self,
        *,
        source_id: str,
        worker: str,
        lease_seconds: float = DEFAULT_LEASE_SECONDS,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    ) -> None:
        if not worker.strip():
            raise ValueError("worker must identify who holds a lease; an anonymous lease cannot")
        if lease_seconds <= 0:
            raise ValueError(f"lease_seconds must be positive, got {lease_seconds}")
        if max_attempts < 1:
            raise ValueError(f"max_attempts must be at least 1, got {max_attempts}")
        self._source_id = source_id
        self._worker = worker[:64]
        self._lease = timedelta(seconds=lease_seconds)
        self._max_attempts = max_attempts

    # -- filling it ---------------------------------------------------------

    def enqueue(
        self,
        session: Session,
        candidates: Iterable[Candidate],
        *,
        job_id: uuid.UUID | None = None,
    ) -> EnqueueResult:
        """Add candidates, ignoring any URL this source has already seen.

        Deduplication happens twice, and both are needed. Within the batch, by canonical digest,
        because one listing page routinely links the same document from a title and a thumbnail —
        and PostgreSQL would otherwise be asked to resolve a conflict against a row from the same
        statement. Across batches, by the unique constraint, because that is the only check that
        holds when two workers enqueue concurrently.

        Flushes; never commits. The caller owns the transaction, so enqueueing and updating a run's
        counters are one atomic act.
        """
        rejected: list[tuple[str, str]] = []
        batch: dict[str, Candidate] = {}
        canonical: dict[str, str] = {}

        for candidate in candidates:
            try:
                url = canonical_url(candidate.url)
            except SsrfRejectionError as error:
                # Refused now rather than stored and refused on every future pass.
                rejected.append((candidate.url, f"{error.reason.value}: {error}"))
                continue
            digest = url_digest(url)
            if digest in batch:
                continue
            batch[digest] = candidate
            canonical[digest] = url

        if not batch:
            return EnqueueResult(rejected=tuple(rejected))

        rows = [
            {
                "id": uuid.uuid4(),
                "source_id": self._source_id,
                "url": canonical[digest],
                "url_sha256": digest,
                "state": DocumentState.DISCOVERED,
                "depth": candidate.depth,
                "discovered_via": candidate.discovered_via,
                "job_id": job_id,
                "attempts": 0,
            }
            for digest, candidate in batch.items()
        ]
        statement = (
            insert(DiscoveredUrl)
            .values(rows)
            .on_conflict_do_nothing(index_elements=["source_id", "url_sha256"])
            .returning(DiscoveredUrl.id)
        )
        inserted = len(session.execute(statement).scalars().all())
        session.flush()
        return EnqueueResult(
            accepted=inserted,
            duplicates=len(rows) - inserted,
            rejected=tuple(rejected),
        )

    # -- draining it --------------------------------------------------------

    def claim(self, session: Session, *, limit: int = 1) -> tuple[DiscoveredUrl, ...]:
        """Take up to ``limit`` URLs, leasing them to this worker.

        ``FOR UPDATE SKIP LOCKED`` inside the subquery is what makes two workers safe: each skips
        rows the other has locked instead of blocking on them, so the queue scales by adding workers
        rather than by serialising them.

        The caller must commit for the lease to be visible to anyone else. Until then the rows are
        locked by this transaction, which is the same protection by a different mechanism.
        """
        if limit < 1:
            raise ValueError(f"limit must be at least 1, got {limit}")
        now = datetime.now(UTC)
        claimable = (
            self._claimable(now)
            .order_by(DiscoveredUrl.depth, DiscoveredUrl.discovered_at, DiscoveredUrl.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )

        statement = (
            update(DiscoveredUrl)
            .where(DiscoveredUrl.id.in_(claimable.scalar_subquery()))
            .values(lease_owner=self._worker, lease_expires_at=now + self._lease)
            .returning(DiscoveredUrl)
            .execution_options(synchronize_session=False)
        )
        claimed = list(session.execute(statement).scalars().all())
        # RETURNING makes no promise about order, and deterministic traversal is a requirement.
        claimed.sort(key=lambda row: (row.depth, row.discovered_at, str(row.id)))
        return tuple(claimed)

    def settle(self, session: Session, row: DiscoveredUrl) -> bool:
        """Release the lease once an outcome is recorded. Returns whether the URL was dead-lettered.

        Called after the acquirer has moved the row's state, so this decides one thing only:
        whether the URL has any attempts left. A URL that has spent them is dead-lettered rather
        than left claimable, so a permanently broken link stops consuming a request on every run and
        starts being something somebody can list.
        """
        row.lease_owner = None
        row.lease_expires_at = None
        exhausted = row.state is DocumentState.FAILED and row.attempts >= self._max_attempts
        if exhausted and row.dead_lettered_at is None:
            row.dead_lettered_at = datetime.now(UTC)
        session.flush()
        return exhausted

    def release(
        self, session: Session, row: DiscoveredUrl, *, retry_after_seconds: float | None = None
    ) -> None:
        """Give a URL back unattempted, optionally deferring it.

        Used on a clean shutdown, where the URL was never tried and must not be charged an
        attempt, and for backoff that has to survive a restart — a sleep in a worker does not.
        """
        row.lease_owner = None
        row.lease_expires_at = None
        if retry_after_seconds is not None:
            row.next_attempt_after = datetime.now(UTC) + timedelta(seconds=retry_after_seconds)
        session.flush()

    def reclaim_expired(self, session: Session) -> int:
        """Recover URLs whose worker stopped without recording an outcome. Returns how many.

        A crashed worker leaves a row in ``DOWNLOADING`` with a lease nobody will release, and
        that row is indistinguishable from one still in flight — which is exactly why the lease has
        an expiry. Recovery moves it to ``FAILED`` and charges it an attempt, which is the honest
        record: we tried, and we do not know what happened.

        Charging the attempt is what protects against a poison URL. A document that kills its worker
        every time — an unbounded response, a crash in a parser — would otherwise be reclaimed
        forever. Instead it dead-letters after ``max_attempts`` and waits for a person.
        """
        now = datetime.now(UTC)
        statement = (
            update(DiscoveredUrl)
            .where(
                DiscoveredUrl.source_id == self._source_id,
                DiscoveredUrl.state == DocumentState.DOWNLOADING,
                DiscoveredUrl.lease_expires_at.is_not(None),
                DiscoveredUrl.lease_expires_at < now,
            )
            .values(
                # DOWNLOADING -> FAILED is a legal transition; asserted in the domain tests rather
                # than checked per row, because this is one statement over many rows by design.
                state=DocumentState.FAILED,
                attempts=DiscoveredUrl.attempts + 1,
                error_type="lease_expired",
                error_message=(
                    "the worker holding this URL stopped without recording an outcome; "
                    "the lease expired and the URL was recovered"
                ),
                lease_owner=None,
                lease_expires_at=None,
                dead_lettered_at=case(
                    (DiscoveredUrl.attempts + 1 >= self._max_attempts, now), else_=None
                ),
            )
            .execution_options(synchronize_session=False)
        )
        result = session.execute(statement)
        session.flush()
        # rowcount is on the cursor result an UPDATE produces; Session.execute is typed as the
        # general Result, which does not carry it.
        return int(getattr(result, "rowcount", 0))

    # -- looking at it -----------------------------------------------------

    def pending(self, session: Session) -> int:
        """Queue depth: how many URLs could be claimed right now.

        Deliberately not "how many rows are unfinished". A URL deferred by backoff, or one
        dead-lettered, or one leased by another worker is not work this one can take, and a depth
        that counted them would never reach zero and so could never mean "done".
        """
        statement = select(func.count()).select_from(self._claimable(datetime.now(UTC)).subquery())
        return int(session.execute(statement).scalar_one())

    def counts_by_state(self, session: Session) -> Mapping[DocumentState, int]:
        """Every state this source's frontier is in, for a run summary."""
        rows: Sequence[tuple[DocumentState, int]] = session.execute(
            select(DiscoveredUrl.state, func.count())
            .where(DiscoveredUrl.source_id == self._source_id)
            .group_by(DiscoveredUrl.state)
        ).all()  # type: ignore[assignment]
        return dict(rows)

    def dead_lettered(self, session: Session, *, limit: int = 100) -> tuple[DiscoveredUrl, ...]:
        """URLs that exhausted their attempts, most recent first, for operator review."""
        return tuple(
            session.execute(
                select(DiscoveredUrl)
                .where(
                    DiscoveredUrl.source_id == self._source_id,
                    DiscoveredUrl.dead_lettered_at.is_not(None),
                )
                .order_by(DiscoveredUrl.dead_lettered_at.desc())
                .limit(limit)
            )
            .scalars()
            .all()
        )

    def _claimable(self, now: datetime) -> Select[tuple[uuid.UUID]]:
        """The claim predicate, in one place because three callers must agree on it."""
        return select(DiscoveredUrl.id).where(
            DiscoveredUrl.source_id == self._source_id,
            DiscoveredUrl.state.in_(_CLAIMABLE_STATES),
            DiscoveredUrl.dead_lettered_at.is_(None),
            DiscoveredUrl.attempts < self._max_attempts,
            or_(
                DiscoveredUrl.lease_expires_at.is_(None),
                DiscoveredUrl.lease_expires_at < now,
            ),
            or_(
                DiscoveredUrl.next_attempt_after.is_(None),
                DiscoveredUrl.next_attempt_after <= now,
            ),
        )
