"""Politeness: how often we may ask a source for something, and how many at once.

This is the layer that decides whether Aedifex is a well-behaved client or a load generator
pointed at a public procurement portal. Those portals are frequently fragile, often run on modest
infrastructure, and are operated by people who are entirely within their rights to block us. The
limits therefore come from each source's registry entry rather than from a global default, because
politeness is a property of the relationship with a particular site.

Three limits, all enforced:

.. code-block:: text

    per-source concurrency    at most N requests in flight to one source   (max_concurrency)
    minimum delay             at least D seconds between consecutive ones  (min_delay_seconds)
    rolling rate              at most R requests in any 60-second window   (requests_per_minute)

plus a **global** concurrency ceiling across every source combined, so enabling twenty sources
cannot multiply into twenty simultaneous crawls (FR-132, FR-133).

The rate arithmetic is a pure function — :func:`wait_seconds` takes a clock reading and a history
and returns a number, with no I/O and no sleeping — so the awkward cases can be tested exhaustively
without threads or elapsed time. The stateful part around it does the smallest possible amount of
work: take a slot, wait if required, record the grant, release on the way out.

Ordering, and why it is this way
-------------------------------

.. code-block:: text

    acquire the per-source slot
        ↓  held while waiting, because the wait belongs to that source
    wait out the minimum delay and the rolling window
        ↓  grant recorded the moment the wait clears
    acquire the global slot
        ↓  held only for the request itself
    yield

The per-source slot is taken first and held across the wait: a source that must pause fifteen
seconds should occupy its own capacity, not everyone else's. The global slot is taken last, so a
slow source waiting on its own politeness rules cannot starve a fast one.

One consequence, stated rather than hidden: waiting for the global slot can push the real request
slightly later than the recorded grant, so the recorded rate is an *upper bound* on the true rate.
That errs towards being more polite than configured, which is the right direction for this control
to be wrong in.

Both semaphores are always acquired in the same order, which is what makes deadlock impossible
rather than unlikely.
"""

from __future__ import annotations

import threading
from collections import deque
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Final

from aedifex.acquisition.fetch.timing import (
    Clock,
    Deadline,
    MonotonicClock,
    Sleeper,
    SystemSleeper,
    TimeoutBudgetExhaustedError,
)
from aedifex.acquisition.registry.models import RateLimitPolicy, SourceDefinition

__all__ = [
    "RATE_WINDOW_SECONDS",
    "RateLimiter",
    "RateLimits",
    "wait_seconds",
]

RATE_WINDOW_SECONDS: Final[float] = 60.0
"""The window ``requests_per_minute`` is measured over.

A rolling window rather than a fixed one. A fixed calendar minute permits a double-rate burst
across its boundary — twenty requests at 11:59:59 and twenty more at 12:00:01 satisfies "twenty per
minute" while delivering forty requests in two seconds, which is exactly the behaviour a site
operator would call abusive.
"""


@dataclass(frozen=True, slots=True)
class RateLimits:
    """The politeness limits for one source, as the fetch layer sees them.

    A fetch-side value object rather than the registry model itself, matching
    :class:`~aedifex.acquisition.fetch.hosts.SourceHostPolicy` and
    :class:`~aedifex.acquisition.fetch.redirects.RedirectPolicy`. The registry is configuration;
    this is the shape the limiter needs. Keeping them separate is what stops a registry field
    rename from reaching into the middle of the fetch path.
    """

    requests_per_minute: int
    max_concurrency: int
    min_delay_seconds: float

    def __post_init__(self) -> None:
        if self.requests_per_minute < 1:
            raise ValueError(
                f"requests_per_minute must be at least 1, got {self.requests_per_minute}"
            )
        if self.max_concurrency < 1:
            raise ValueError(f"max_concurrency must be at least 1, got {self.max_concurrency}")
        if self.min_delay_seconds < 0:
            raise ValueError(
                f"min_delay_seconds must not be negative, got {self.min_delay_seconds}"
            )

    @classmethod
    def from_policy(cls, policy: RateLimitPolicy) -> RateLimits:
        return cls(
            requests_per_minute=policy.requests_per_minute,
            max_concurrency=policy.max_concurrency,
            min_delay_seconds=policy.min_delay_seconds,
        )

    @classmethod
    def from_source(cls, source: SourceDefinition) -> RateLimits:
        """Take the limits from the source's own registry entry (FR-130)."""
        return cls.from_policy(source.rate_limit)


def wait_seconds(*, now: float, grants: Sequence[float], limits: RateLimits) -> float:
    """How long to wait before the next request to this source may be made.

    Pure: no clock, no sleeping, no state. ``grants`` is the ascending history of times at which
    requests were permitted, and ``now`` is the current reading of the same clock.

    Both limits are evaluated and the longer wait wins, because they answer different questions —
    ``min_delay_seconds`` spaces requests out, ``requests_per_minute`` caps the total. Satisfying
    one while violating the other is not politeness.
    """
    if not grants:
        return 0.0

    spacing_wait = (grants[-1] + limits.min_delay_seconds) - now

    window_wait = 0.0
    if len(grants) >= limits.requests_per_minute:
        # The request that must age out of the window before another may be issued.
        oldest_relevant = grants[-limits.requests_per_minute]
        window_wait = (oldest_relevant + RATE_WINDOW_SECONDS) - now

    return max(0.0, spacing_wait, window_wait)


class RateLimiter:
    """Grants permission to make one request, waiting as long as politeness requires.

    Thread-safe: the crawler runs in worker threads, and a limiter that is only correct on one
    thread is not a limit. State is guarded by a lock; the concurrency ceilings are semaphores.

    One instance is shared across all sources for the process — a per-worker limiter would enforce
    nothing, since the point is to bound the total.
    """

    def __init__(
        self,
        *,
        global_concurrency: int,
        clock: Clock | None = None,
        sleeper: Sleeper | None = None,
    ) -> None:
        if global_concurrency < 1:
            raise ValueError(
                f"global_concurrency must be at least 1, got {global_concurrency}; zero would "
                "block every request forever rather than meaning 'unlimited'"
            )
        self._clock = clock if clock is not None else MonotonicClock()
        self._sleeper = sleeper if sleeper is not None else SystemSleeper()
        self._global_slots = threading.BoundedSemaphore(global_concurrency)
        self._global_concurrency = global_concurrency
        self._lock = threading.Lock()
        self._grants: dict[str, deque[float]] = {}
        self._source_slots: dict[str, threading.BoundedSemaphore] = {}

    @property
    def global_concurrency(self) -> int:
        return self._global_concurrency

    @contextmanager
    def slot(
        self,
        source_id: str,
        limits: RateLimits,
        *,
        deadline: Deadline | None = None,
    ) -> Iterator[None]:
        """Hold permission to make one request to ``source_id``.

        Call this once per *attempt*, not once per document: a retry and a redirect hop are each a
        request the source has to serve, and exempting them would let a failing crawl hammer a site
        precisely when it is least able to cope (FR-135).

        Raises:
            TimeoutBudgetExhaustedError: if the wait required exceeds the time the request has left.
                Waiting past the deadline would park a worker to make a request that must then be
                abandoned — the same reasoning that makes a long ``Retry-After`` abandon rather than
                sleep.
        """
        source_slots = self._slots_for(source_id, limits)
        self._acquire(source_slots, deadline=deadline, what=f"a {source_id} slot")
        try:
            self._wait_for_rate(source_id, limits, deadline=deadline)
            self._acquire(self._global_slots, deadline=deadline, what="a global slot")
            try:
                yield
            finally:
                self._global_slots.release()
        finally:
            source_slots.release()

    def _slots_for(self, source_id: str, limits: RateLimits) -> threading.BoundedSemaphore:
        """Return this source's semaphore, creating it on first use.

        Created under the lock because two threads reaching a new source at once must end up
        sharing one semaphore; two semaphores would mean twice the configured concurrency.
        """
        with self._lock:
            existing = self._source_slots.get(source_id)
            if existing is None:
                existing = threading.BoundedSemaphore(limits.max_concurrency)
                self._source_slots[source_id] = existing
            return existing

    def _acquire(
        self, semaphore: threading.BoundedSemaphore, *, deadline: Deadline | None, what: str
    ) -> None:
        if deadline is None:
            semaphore.acquire()
            return

        deadline.check()
        remaining = deadline.remaining_seconds
        if not semaphore.acquire(timeout=remaining):
            raise TimeoutBudgetExhaustedError(
                f"waited {remaining:.3f}s for {what} without one becoming free, which is the whole "
                "time this request had left"
            )

    def _wait_for_rate(
        self, source_id: str, limits: RateLimits, *, deadline: Deadline | None
    ) -> None:
        """Sleep until this source may be contacted, then record the grant.

        A loop rather than a single sleep, because other threads may take the slot we were waiting
        for: on waking, the wait is recomputed from the state as it now is. Computing once and
        trusting it would let two threads that waited concurrently both proceed, quietly doubling
        the configured rate.
        """
        while True:
            with self._lock:
                grants = self._grants.setdefault(source_id, deque())
                self._forget_expired(grants, limits)
                # One clock reading for both the decision and the record. Reading twice would let
                # the recorded grant sit slightly after the moment the decision was made, which
                # accumulates into a real rate drift over a long crawl.
                now = self._clock.now()
                wait = wait_seconds(now=now, grants=grants, limits=limits)
                if wait <= 0.0:
                    grants.append(now)
                    return

            if deadline is not None:
                deadline.check()
                if wait > deadline.remaining_seconds:
                    raise TimeoutBudgetExhaustedError(
                        f"politeness requires waiting {wait:.3f}s before contacting {source_id!r}, "
                        f"but only {deadline.remaining_seconds:.3f}s of this request's budget "
                        "remains; abandoning rather than parking a worker on a doomed request"
                    )
            self._sleeper.sleep(wait)

    @staticmethod
    def _forget_expired(grants: deque[float], limits: RateLimits) -> None:
        """Bound the history.

        Only the most recent ``requests_per_minute`` grants can affect the window, so anything older
        is dead weight. Without this the deque grows for the life of the process — a slow leak in
        the component designed to run for hours.
        """
        while len(grants) > limits.requests_per_minute:
            grants.popleft()
