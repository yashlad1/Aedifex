"""Rate limiter tests.

Split by what each part actually is. ``wait_seconds`` is arithmetic, so it is tested as arithmetic —
no clock, no threads, no elapsed time. The waiting behaviour is tested with an injected clock and a
sleeper that advances that clock instead of sleeping, so a fifteen-minute politeness delay is
verified in microseconds and the assertions are exact rather than approximate.

The concurrency ceilings are the exception: a semaphore that is only correct on one thread is not a
limit, so those tests use real threads and real blocking, with the rate limits set wide enough that
only concurrency is under test. Timing there is asserted through explicit events rather than sleeps,
so nothing depends on how fast the machine is.
"""

from __future__ import annotations

import itertools
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import pytest
from pydantic import AnyHttpUrl

from aedifex.acquisition.fetch.ratelimit import (
    RATE_WINDOW_SECONDS,
    RateLimiter,
    RateLimits,
    wait_seconds,
)
from aedifex.acquisition.fetch.timing import (
    MonotonicClock,
    TimeoutBudget,
    TimeoutBudgetExhaustedError,
    TimeoutPolicy,
)
from aedifex.acquisition.registry.models import (
    DataUsePolicy,
    RateLimitPolicy,
    RetrievalMethod,
    SourceCategory,
    SourceDefinition,
)
from aedifex.domain.documents import DocumentType
from aedifex.domain.files import FileFormat


class FakeClock:
    """A clock that only moves when a test moves it."""

    def __init__(self, start: float = 1000.0) -> None:
        self.current = start

    def now(self) -> float:
        return self.current

    def advance(self, seconds: float) -> None:
        self.current += seconds


@dataclass
class FakeSleeper:
    """Records what it was asked to wait for, and advances the clock instead of waiting.

    This is what lets a 300-second politeness delay be asserted exactly, in a test that takes no
    measurable time. A real sleep would make the suite slow *and* the assertion approximate.
    """

    clock: FakeClock
    slept: list[float] = field(default_factory=list)

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.clock.advance(seconds)


def bounded() -> TimeoutBudget:
    """A real-clock budget for the threaded tests, so a leaked slot fails instead of hanging.

    Without a deadline, ``semaphore.acquire()`` blocks forever, so a bug that loses a slot turns
    this suite into a hang rather than a failure — and a suite that hangs on a regression reports
    nothing at all. Found exactly that way: a mutation removing the release ran for ten minutes
    instead of failing in a second. Three seconds is far longer than any of these tests
    legitimately needs, so it cannot make them flaky.
    """
    return TimeoutBudget(
        policy=TimeoutPolicy(connect_seconds=0.5, read_seconds=1.0, total_seconds=3.0),
        clock=MonotonicClock(),
    )


POLITE = RateLimits(requests_per_minute=20, max_concurrency=2, min_delay_seconds=1.0)
UNRESTRICTED = RateLimits(requests_per_minute=600, max_concurrency=8, min_delay_seconds=0.0)


def budget(total: float, *, clock: FakeClock) -> TimeoutBudget:
    return TimeoutBudget(
        policy=TimeoutPolicy(connect_seconds=1.0, read_seconds=2.0, total_seconds=total),
        clock=clock,
    )


class TestWaitArithmetic:
    """Pure function, so every awkward case is cheap to state."""

    def test_a_first_request_waits_for_nothing(self) -> None:
        assert wait_seconds(now=1000.0, grants=[], limits=POLITE) == 0.0

    def test_the_minimum_delay_is_the_wait_when_it_has_not_elapsed(self) -> None:
        assert wait_seconds(now=1000.4, grants=[1000.0], limits=POLITE) == pytest.approx(0.6)

    def test_no_wait_once_the_minimum_delay_has_elapsed(self) -> None:
        assert wait_seconds(now=1001.0, grants=[1000.0], limits=POLITE) == 0.0
        assert wait_seconds(now=1005.0, grants=[1000.0], limits=POLITE) == 0.0

    def test_a_zero_minimum_delay_imposes_no_spacing(self) -> None:
        limits = RateLimits(requests_per_minute=600, max_concurrency=1, min_delay_seconds=0.0)
        assert wait_seconds(now=1000.0, grants=[1000.0], limits=limits) == 0.0

    def test_a_full_window_waits_for_the_oldest_request_to_age_out(self) -> None:
        """The rate ceiling, independent of spacing.

        Twenty requests spread across the first ten seconds; the twenty-first cannot go until the
        first one is a minute old.
        """
        limits = RateLimits(requests_per_minute=20, max_concurrency=2, min_delay_seconds=0.0)
        grants = [1000.0 + index * 0.5 for index in range(20)]
        assert wait_seconds(now=1010.0, grants=grants, limits=limits) == pytest.approx(50.0)

    def test_the_window_is_rolling_not_a_fixed_minute(self) -> None:
        """A fixed calendar minute would allow a double-rate burst across its boundary."""
        limits = RateLimits(requests_per_minute=3, max_concurrency=1, min_delay_seconds=0.0)
        grants = [1000.0, 1000.1, 1000.2]
        assert wait_seconds(now=1059.9, grants=grants, limits=limits) == pytest.approx(0.1)
        assert wait_seconds(now=1060.0, grants=grants, limits=limits) == 0.0

    def test_the_longer_of_the_two_limits_wins(self) -> None:
        """Satisfying one limit while violating the other is not politeness."""
        limits = RateLimits(requests_per_minute=3, max_concurrency=1, min_delay_seconds=30.0)
        grants = [1000.0, 1030.0, 1060.0]

        # Spacing wants 30s from the last grant; the window wants the 1000.0 grant to age out.
        assert wait_seconds(now=1061.0, grants=grants, limits=limits) == pytest.approx(29.0)

        wide_window = RateLimits(requests_per_minute=600, max_concurrency=1, min_delay_seconds=30.0)
        assert wait_seconds(now=1061.0, grants=grants, limits=wide_window) == pytest.approx(29.0)

    def test_only_the_most_recent_requests_count_towards_the_window(self) -> None:
        """History older than the limit cannot hold up a request."""
        limits = RateLimits(requests_per_minute=2, max_concurrency=1, min_delay_seconds=0.0)
        grants = [1.0, 2.0, 3.0, 1000.0, 1000.5]
        # Two requests are inside the window (1000.0 and 1000.5), so the next may go when the
        # older of those two ages out at 1060.0 — not when the ancient ones do.
        assert wait_seconds(now=1001.0, grants=grants, limits=limits) == pytest.approx(59.0)

    def test_a_wait_is_never_negative(self) -> None:
        """A clock reading far past every grant means go, not "go backwards"."""
        assert wait_seconds(now=99_999.0, grants=[1000.0, 1001.0], limits=POLITE) == 0.0

    @pytest.mark.parametrize("requests_per_minute", [1, 2, 5, 20, 600])
    def test_the_nth_request_is_permitted_and_the_next_is_not(
        self, requests_per_minute: int
    ) -> None:
        """The boundary itself, across the configurable range.

        Exactly ``requests_per_minute`` grants inside the window must block the next one, and one
        fewer must not — an off-by-one here would silently permit a rate above the configured
        ceiling for every source.
        """
        limits = RateLimits(
            requests_per_minute=requests_per_minute, max_concurrency=1, min_delay_seconds=0.0
        )
        at_capacity = [1000.0 + index * 0.001 for index in range(requests_per_minute)]
        # Just past the most recent grant. An earlier version of this test read the clock in
        # the middle of the grant history, which put some grants in the future — a state that
        # cannot occur, and which made the assertion test nothing meaningful.
        now = at_capacity[-1] + 0.001
        assert wait_seconds(now=now, grants=at_capacity, limits=limits) > 0.0
        assert wait_seconds(now=now, grants=at_capacity[:-1], limits=limits) == 0.0


class TestSpacingBehaviour:
    def test_consecutive_requests_are_spaced_by_the_minimum_delay(self) -> None:
        clock = FakeClock()
        sleeper = FakeSleeper(clock)
        limiter = RateLimiter(global_concurrency=4, clock=clock, sleeper=sleeper)

        observed: list[float] = []
        for _ in range(4):
            with limiter.slot("cpwd", POLITE):
                observed.append(clock.now())

        gaps = [second - first for first, second in itertools.pairwise(observed)]
        assert gaps == [1.0, 1.0, 1.0]
        assert sleeper.slept == [1.0, 1.0, 1.0]

    def test_no_wait_when_the_caller_is_already_slow_enough(self) -> None:
        """Politeness costs nothing when the work itself takes longer than the delay."""
        clock = FakeClock()
        sleeper = FakeSleeper(clock)
        limiter = RateLimiter(global_concurrency=4, clock=clock, sleeper=sleeper)

        for _ in range(3):
            with limiter.slot("cpwd", POLITE):
                clock.advance(5.0)

        assert sleeper.slept == []

    def test_the_rate_ceiling_is_enforced_after_the_window_fills(self) -> None:
        clock = FakeClock()
        sleeper = FakeSleeper(clock)
        limiter = RateLimiter(global_concurrency=4, clock=clock, sleeper=sleeper)
        limits = RateLimits(requests_per_minute=3, max_concurrency=1, min_delay_seconds=0.0)

        for _ in range(3):
            with limiter.slot("cpwd", limits):
                pass
        assert sleeper.slept == []

        started = clock.now()
        with limiter.slot("cpwd", limits):
            pass
        assert clock.now() - started == pytest.approx(RATE_WINDOW_SECONDS)

    def test_each_source_is_limited_independently(self) -> None:
        """One slow source must not impose its delay on another."""
        clock = FakeClock()
        sleeper = FakeSleeper(clock)
        limiter = RateLimiter(global_concurrency=4, clock=clock, sleeper=sleeper)

        with limiter.slot("cpwd", POLITE):
            pass
        with limiter.slot("nhai", POLITE):
            pass

        assert sleeper.slept == [], "a first request to a different source should not wait"

    def test_the_grant_history_does_not_grow_without_bound(self) -> None:
        """A limiter that runs for hours must not leak the history it no longer needs."""
        clock = FakeClock()
        sleeper = FakeSleeper(clock)
        limiter = RateLimiter(global_concurrency=4, clock=clock, sleeper=sleeper)
        limits = RateLimits(requests_per_minute=5, max_concurrency=1, min_delay_seconds=0.0)

        for _ in range(200):
            with limiter.slot("cpwd", limits):
                clock.advance(30.0)

        recorded = limiter._grants["cpwd"]
        assert len(recorded) <= limits.requests_per_minute + 1


class TestBudgetInteraction:
    def test_a_wait_longer_than_the_remaining_budget_abandons_instead_of_sleeping(self) -> None:
        """Same reasoning as a long ``Retry-After``: never park a worker on a doomed request."""
        clock = FakeClock()
        sleeper = FakeSleeper(clock)
        limiter = RateLimiter(global_concurrency=4, clock=clock, sleeper=sleeper)
        limits = RateLimits(requests_per_minute=20, max_concurrency=2, min_delay_seconds=30.0)

        with limiter.slot("cpwd", limits):
            pass

        with (
            pytest.raises(TimeoutBudgetExhaustedError, match="politeness requires waiting"),
            limiter.slot("cpwd", limits, deadline=budget(10.0, clock=clock)),
        ):
            pass

        assert sleeper.slept == [], "it must not have slept at all before abandoning"

    def test_a_wait_within_the_remaining_budget_is_taken(self) -> None:
        clock = FakeClock()
        sleeper = FakeSleeper(clock)
        limiter = RateLimiter(global_concurrency=4, clock=clock, sleeper=sleeper)

        with limiter.slot("cpwd", POLITE):
            pass
        with limiter.slot("cpwd", POLITE, deadline=budget(60.0, clock=clock)):
            pass

        assert sleeper.slept == [1.0]

    def test_an_already_exhausted_budget_is_refused(self) -> None:
        clock = FakeClock()
        limiter = RateLimiter(global_concurrency=4, clock=clock, sleeper=FakeSleeper(clock))
        deadline = budget(5.0, clock=clock)
        clock.advance(10.0)

        with (
            pytest.raises(TimeoutBudgetExhaustedError),
            limiter.slot("cpwd", POLITE, deadline=deadline),
        ):
            pass

    def test_no_deadline_means_the_wait_is_simply_taken(self) -> None:
        """A caller may opt out; the wait is still bounded by the configured limits."""
        clock = FakeClock()
        sleeper = FakeSleeper(clock)
        limiter = RateLimiter(global_concurrency=4, clock=clock, sleeper=sleeper)
        limits = RateLimits(requests_per_minute=20, max_concurrency=2, min_delay_seconds=300.0)

        with limiter.slot("cpwd", limits):
            pass
        with limiter.slot("cpwd", limits):
            pass

        assert sleeper.slept == [300.0]


class TestConcurrencyCeilings:
    """Real threads, because a semaphore that only works on one thread is not a limit.

    Rate limits are set wide here so nothing but concurrency is under test, and blocking is asserted
    through events rather than sleeps so the result does not depend on machine speed.
    """

    def test_per_source_concurrency_is_bounded(self) -> None:
        limiter = RateLimiter(global_concurrency=8)
        limits = RateLimits(requests_per_minute=600, max_concurrency=1, min_delay_seconds=0.0)
        first_inside = threading.Event()
        release_first = threading.Event()
        second_inside = threading.Event()

        def first() -> None:
            with limiter.slot("cpwd", limits, deadline=bounded()):
                first_inside.set()
                release_first.wait(5.0)

        def second() -> None:
            with limiter.slot("cpwd", limits, deadline=bounded()):
                second_inside.set()

        with ThreadPoolExecutor(max_workers=2) as pool:
            pool.submit(first)
            assert first_inside.wait(5.0)
            pool.submit(second)
            assert not second_inside.wait(0.2), "the second request entered while the cap was full"
            release_first.set()
            assert second_inside.wait(5.0), "the second request never got in after release"

    def test_the_global_ceiling_bounds_unrelated_sources(self) -> None:
        """Two different sources, so only the global cap can be what serialises them."""
        limiter = RateLimiter(global_concurrency=1)
        limits = RateLimits(requests_per_minute=600, max_concurrency=4, min_delay_seconds=0.0)
        first_inside = threading.Event()
        release_first = threading.Event()
        second_inside = threading.Event()

        def hold() -> None:
            with limiter.slot("cpwd", limits, deadline=bounded()):
                first_inside.set()
                release_first.wait(5.0)

        def other() -> None:
            with limiter.slot("nhai", limits, deadline=bounded()):
                second_inside.set()

        with ThreadPoolExecutor(max_workers=2) as pool:
            pool.submit(hold)
            assert first_inside.wait(5.0)
            pool.submit(other)
            assert not second_inside.wait(0.2), "the global ceiling did not bound a second source"
            release_first.set()
            assert second_inside.wait(5.0)

    def test_waiting_for_a_slot_respects_the_deadline(self) -> None:
        """A full ceiling must not park a worker past the request's own budget.

        This is the concurrency counterpart of the rate-wait check, and it was missing: a mutation
        making ``_acquire`` ignore the deadline entirely passed the whole suite, because every other
        test releases its slots promptly and so never waits. Blocking forever on a slot is the same
        failure as blocking forever on politeness, and needs its own assertion.
        """
        limiter = RateLimiter(global_concurrency=1)
        limits = RateLimits(requests_per_minute=600, max_concurrency=4, min_delay_seconds=0.0)
        holding = threading.Event()
        release = threading.Event()

        def hold() -> None:
            with limiter.slot("cpwd", limits, deadline=bounded()):
                holding.set()
                release.wait(5.0)

        tight = TimeoutBudget(
            policy=TimeoutPolicy(connect_seconds=0.05, read_seconds=0.1, total_seconds=0.3),
            clock=MonotonicClock(),
        )
        with ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(hold)
            assert holding.wait(5.0)
            try:
                with (
                    pytest.raises(TimeoutBudgetExhaustedError, match="without one becoming free"),
                    limiter.slot("nhai", limits, deadline=tight),
                ):
                    pass
            finally:
                release.set()

    def test_a_slot_is_released_when_the_caller_raises(self) -> None:
        """Otherwise one failure permanently removes capacity, and the crawl quietly stalls."""
        limiter = RateLimiter(global_concurrency=1)
        limits = RateLimits(requests_per_minute=600, max_concurrency=1, min_delay_seconds=0.0)

        class CallerFailureError(Exception):
            pass

        for _ in range(3):
            with (
                pytest.raises(CallerFailureError),
                limiter.slot("cpwd", limits, deadline=bounded()),
            ):
                raise CallerFailureError

        entered = False
        with limiter.slot("cpwd", limits, deadline=bounded()):
            entered = True
        assert entered, "capacity was not returned after a failure"

    def test_concurrent_first_use_of_one_source_shares_a_single_ceiling(self) -> None:
        """Two threads reaching a new source at once must not create two semaphores.

        Two would mean twice the configured concurrency for that source, which is the kind of race
        that only shows up under load against someone else's server.
        """
        limiter = RateLimiter(global_concurrency=16)
        limits = RateLimits(requests_per_minute=600, max_concurrency=1, min_delay_seconds=0.0)
        inside = threading.Semaphore(0)
        peak = 0
        current = 0
        lock = threading.Lock()
        start = threading.Barrier(8)

        def worker() -> None:
            nonlocal peak, current
            start.wait(5.0)
            with limiter.slot("cpwd", limits, deadline=bounded()):
                with lock:
                    current += 1
                    peak = max(peak, current)
                inside.release()
                with lock:
                    current -= 1

        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lambda _: worker(), range(8)))

        assert peak == 1, f"observed {peak} concurrent requests against a cap of 1"

    def test_many_threads_across_sources_all_complete(self) -> None:
        """Deadlock check.

        Both semaphores are always taken in the same order, which is what makes deadlock impossible
        rather than unlikely. This exercises the path that would hang if that ever stopped being
        true.
        """
        limiter = RateLimiter(global_concurrency=2)
        limits = RateLimits(requests_per_minute=600, max_concurrency=2, min_delay_seconds=0.0)
        completed: list[int] = []
        lock = threading.Lock()

        def worker(index: int) -> None:
            with limiter.slot(f"source-{index % 4}", limits, deadline=bounded()), lock:
                completed.append(index)

        with ThreadPoolExecutor(max_workers=12) as pool:
            list(pool.map(worker, range(48)))

        assert len(completed) == 48


class TestConfiguration:
    def test_limits_come_from_the_source_registry(self) -> None:
        """FR-130: politeness is a property of the source, not a global default."""
        policy = RateLimitPolicy(requests_per_minute=5, max_concurrency=1, min_delay_seconds=12.0)
        limits = RateLimits.from_policy(policy)
        assert limits.requests_per_minute == 5
        assert limits.max_concurrency == 1
        assert limits.min_delay_seconds == 12.0

    def test_limits_can_be_taken_straight_from_a_source_definition(self) -> None:
        """The path a crawler will actually use: registry entry in, politeness out."""
        source = SourceDefinition(
            id="cpwd",
            name="CPWD",
            category=SourceCategory.GOVERNMENT_PROCUREMENT,
            retrieval=RetrievalMethod.HTTP_CRAWL,
            base_url=AnyHttpUrl("https://cpwd.gov.in/"),
            data_use=DataUsePolicy(
                license="unknown (pending review)",
                allowed_use="Pending review; no collection permitted yet.",
            ),
            document_types=(DocumentType.TENDER_NOTICE,),
            file_formats=(FileFormat.PDF,),
            rate_limit=RateLimitPolicy(
                requests_per_minute=6, max_concurrency=1, min_delay_seconds=10.0
            ),
        )
        limits = RateLimits.from_source(source)
        assert (limits.requests_per_minute, limits.max_concurrency, limits.min_delay_seconds) == (
            6,
            1,
            10.0,
        )

    def test_the_registry_defaults_survive_the_translation(self) -> None:
        """A silent mismatch here would apply limits nobody configured."""
        policy = RateLimitPolicy()
        limits = RateLimits.from_policy(policy)
        assert (limits.requests_per_minute, limits.max_concurrency, limits.min_delay_seconds) == (
            policy.requests_per_minute,
            policy.max_concurrency,
            policy.min_delay_seconds,
        )

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"requests_per_minute": 0},
            {"requests_per_minute": -1},
            {"max_concurrency": 0},
            {"min_delay_seconds": -0.1},
        ],
    )
    def test_incoherent_limits_are_refused(self, kwargs: dict[str, float]) -> None:
        base = {"requests_per_minute": 20, "max_concurrency": 2, "min_delay_seconds": 1.0}
        with pytest.raises(ValueError, match=r"must (be at least|not be negative)"):
            RateLimits(**{**base, **kwargs})  # type: ignore[arg-type]

    @pytest.mark.parametrize("global_concurrency", [0, -1])
    def test_a_non_positive_global_ceiling_is_refused(self, global_concurrency: int) -> None:
        """Zero would block every request forever rather than meaning "unlimited"."""
        with pytest.raises(ValueError, match="global_concurrency must be at least 1"):
            RateLimiter(global_concurrency=global_concurrency)

    def test_limits_are_immutable(self) -> None:
        with pytest.raises(AttributeError):
            UNRESTRICTED.max_concurrency = 99  # type: ignore[misc]

    def test_the_configured_global_ceiling_is_reported(self) -> None:
        assert RateLimiter(global_concurrency=3).global_concurrency == 3
