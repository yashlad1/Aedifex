"""Retry controller tests.

The controller's correctness is almost entirely about ordering, so the tests are built around a
transport that records the sequence of things that happened to it. A scripted transport is the right
tool here, unlike in the transport's own tests: what is under test is *when* the controller calls
things and *what it does between calls*, and a real server cannot be made to fail on command in a
prescribed order.

Nothing sleeps. The clock is injected and the sleeper advances it, so a five-attempt sequence with
60-second backoffs is asserted exactly, in microseconds.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from ipaddress import ip_address

import pytest

from aedifex.acquisition.fetch.controller import (
    AttemptRecord,
    Cancellation,
    FetchCancelledError,
    FetchFailedError,
    FetchResult,
    RetryController,
)
from aedifex.acquisition.fetch.guard import ValidatedTarget
from aedifex.acquisition.fetch.ratelimit import RateLimiter, RateLimits
from aedifex.acquisition.fetch.retry import (
    AttemptOutcome,
    BackoffPolicy,
    RetryPolicy,
)
from aedifex.acquisition.fetch.timing import (
    TimeoutBudget,
    TimeoutPolicy,
)
from aedifex.acquisition.fetch.transport import (
    BudgetExhaustedError,
    ConnectionFailedError,
    RawResponse,
    ReadTimeoutError,
    ResponseHeaders,
    ResponseTooLargeError,
    TlsVerificationError,
    TransportError,
    TransportTimeouts,
    UnclassifiedTransportError,
)

TARGET = ValidatedTarget(
    url="https://cpwd.test/tender.pdf",
    scheme="https",
    hostname="cpwd.test",
    port=443,
    ip_address=ip_address("93.184.216.34"),
    source_id="cpwd",
    validated_addresses=(ip_address("93.184.216.34"),),
)

FAST_LIMITS = RateLimits(requests_per_minute=600, max_concurrency=4, min_delay_seconds=0.0)


class FakeClock:
    def __init__(self, start: float = 1000.0) -> None:
        self.current = start

    def now(self) -> float:
        return self.current

    def advance(self, seconds: float) -> None:
        self.current += seconds


@dataclass
class FakeSleeper:
    clock: FakeClock
    slept: list[float] = field(default_factory=list)

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.clock.advance(seconds)


@dataclass
class FixedRandom:
    """Jitter with the randomness removed, so backoff assertions are exact.

    Returns the top of the interval, which is the worst case for budget arithmetic — the value most
    likely to expose a delay that does not fit.
    """

    def uniform(self, low: float, high: float) -> float:
        return high


@dataclass
class ScriptedResponse:
    """One scripted outcome: a status, or an exception to raise instead."""

    status: int | None = None
    error: Exception | None = None
    headers: tuple[tuple[str, str], ...] = ()
    takes_seconds: float = 0.0


class ScriptedTransport:
    """Plays a scripted sequence and records what the controller did, in order.

    ``events`` is the point of this class. Assertions about "a slot per attempt" and "released
    before the backoff" are about interleaving, and interleaving is only visible if something
    writes it down.
    """

    def __init__(self, script: list[ScriptedResponse], *, clock: FakeClock) -> None:
        self._script = script
        self._clock = clock
        self.events: list[str] = []
        self.timeouts_seen: list[TransportTimeouts] = []
        self.closed = 0

    @contextmanager
    def open(
        self,
        target: ValidatedTarget,
        *,
        timeouts: TransportTimeouts,
        method: str = "GET",
        headers: Mapping[str, str] | None = None,
        max_response_bytes: int = 1024,
    ) -> Iterator[RawResponse]:
        index = len(self.timeouts_seen)
        self.timeouts_seen.append(timeouts)
        if index >= len(self._script):
            raise AssertionError(
                f"transport called {index + 1} times; script has {len(self._script)}"
            )
        step = self._script[index]
        self.events.append(f"open#{index + 1}")
        self._clock.advance(step.takes_seconds)

        if step.error is not None:
            self.events.append(f"raise#{index + 1}:{type(step.error).__name__}")
            raise step.error

        assert step.status is not None
        response = RawResponse(
            target=target,
            status_code=step.status,
            http_version="HTTP/1.1",
            headers=ResponseHeaders(step.headers),
            stream=lambda _size: iter([b"payload"]),
            close=lambda: None,
        )
        try:
            yield response
        finally:
            self.closed += 1
            self.events.append(f"close#{index + 1}")


class RecordingLimiter(RateLimiter):
    """A real limiter that also notes when a slot is taken and returned."""

    def __init__(self, events: list[str], **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self._events = events

    @contextmanager
    def slot(
        self,
        source_id: str,
        limits: RateLimits,
        *,
        deadline: object = None,
    ) -> Iterator[None]:
        self._events.append(f"slot-acquired:{source_id}")
        with super().slot(source_id, limits, deadline=deadline):  # type: ignore[arg-type]
            try:
                yield
            finally:
                self._events.append(f"slot-released:{source_id}")


@dataclass
class Harness:
    controller: RetryController
    transport: ScriptedTransport
    clock: FakeClock
    sleeper: FakeSleeper
    events: list[str]

    def budget(self, total: float = 300.0) -> TimeoutBudget:
        return TimeoutBudget(
            policy=TimeoutPolicy(connect_seconds=10.0, read_seconds=30.0, total_seconds=total),
            clock=self.clock,
        )


def harness(script: list[ScriptedResponse], *, max_attempts: int = 5) -> Harness:
    clock = FakeClock()
    sleeper = FakeSleeper(clock)
    events: list[str] = []
    transport = ScriptedTransport(script, clock=clock)
    limiter = RecordingLimiter(events, global_concurrency=4, clock=clock, sleeper=sleeper)
    controller = RetryController(
        transport=transport,
        limiter=limiter,
        policy=RetryPolicy(backoff=BackoffPolicy(max_attempts=max_attempts)),
        randomness=FixedRandom(),
        clock=clock,
        sleeper=sleeper,
    )
    # The limiter shares the transport's event log, so ordering across both is one sequence.
    transport.events = events
    return Harness(controller, transport, clock, sleeper, events)


class TestSuccessPath:
    def test_a_first_attempt_success_is_handed_to_the_caller(self) -> None:
        h = harness([ScriptedResponse(status=200)])
        with h.controller.fetch(TARGET, limits=FAST_LIMITS, budget=h.budget()) as result:
            assert isinstance(result, FetchResult)
            assert result.response.status_code == 200
            assert b"".join(result.response.iter_bytes()) == b"payload"

        assert result.attempt_count == 1
        assert result.was_retried is False
        assert h.sleeper.slept == []

    def test_the_response_is_closed_after_the_caller_finishes(self) -> None:
        h = harness([ScriptedResponse(status=200)])
        with h.controller.fetch(TARGET, limits=FAST_LIMITS, budget=h.budget()):
            assert h.transport.closed == 0
        assert h.transport.closed == 1

    @pytest.mark.parametrize("status", [200, 201, 204, 301, 302, 304, 307, 399])
    def test_anything_below_400_is_handed_back_rather_than_retried(self, status: int) -> None:
        """Redirects included: following one is a new request that must pass the guard."""
        h = harness([ScriptedResponse(status=status)])
        with h.controller.fetch(TARGET, limits=FAST_LIMITS, budget=h.budget()) as result:
            assert result.response.status_code == status
        assert len(h.transport.timeouts_seen) == 1


class TestRetryOrdering:
    def test_every_attempt_takes_its_own_rate_limit_slot(self) -> None:
        """The property that keeps a flaky server from exceeding a source's configured traffic."""
        h = harness(
            [
                ScriptedResponse(status=503),
                ScriptedResponse(status=503),
                ScriptedResponse(status=200),
            ]
        )
        with h.controller.fetch(TARGET, limits=FAST_LIMITS, budget=h.budget()) as result:
            assert result.response.status_code == 200

        acquisitions = [event for event in h.events if event.startswith("slot-acquired")]
        assert len(acquisitions) == 3, h.events

    def test_the_slot_is_released_before_the_backoff_is_taken(self) -> None:
        """Sleeping while holding capacity would starve other work during a deliberate pause.

        Asserted on the interleaving: every release must appear before the sleep that follows it.
        """
        h = harness([ScriptedResponse(status=503), ScriptedResponse(status=200)])
        sleeper = h.sleeper
        original_sleep = sleeper.sleep

        def recording_sleep(seconds: float) -> None:
            h.events.append(f"sleep:{seconds:.3f}")
            original_sleep(seconds)

        sleeper.sleep = recording_sleep  # type: ignore[method-assign]

        with h.controller.fetch(TARGET, limits=FAST_LIMITS, budget=h.budget()):
            pass

        release_index = h.events.index("slot-released:cpwd")
        sleep_index = next(i for i, event in enumerate(h.events) if event.startswith("sleep:"))
        assert release_index < sleep_index, h.events

    def test_a_failed_response_is_closed_before_the_next_attempt(self) -> None:
        h = harness([ScriptedResponse(status=503), ScriptedResponse(status=200)])
        with h.controller.fetch(TARGET, limits=FAST_LIMITS, budget=h.budget()):
            pass

        first_close = h.events.index("close#1")
        second_open = h.events.index("open#2")
        assert first_close < second_open, h.events


class TestBudgetDominatesRetries:
    def test_one_budget_is_shared_by_every_attempt(self) -> None:
        """Each attempt's timeouts must be derived from what remains, not from a fresh allowance.

        With a 100s total and attempts that each burn 20s plus backoff, the read timeout handed to
        the transport has to shrink. If it were constant at 30s, the budget would have been rebuilt.
        """
        h = harness(
            [
                ScriptedResponse(status=503, takes_seconds=20.0),
                ScriptedResponse(status=503, takes_seconds=20.0),
                ScriptedResponse(status=200, takes_seconds=1.0),
            ]
        )
        with h.controller.fetch(TARGET, limits=FAST_LIMITS, budget=h.budget(50.0)):
            pass

        # 50s total, attempts costing 20s each plus backoff. The read timeout is the configured 30s
        # while that much remains, then tracks the remaining budget down: 30 → 29 → 7. A constant 30
        # would mean the budget had been rebuilt per attempt.
        reads = [timeouts.read_seconds for timeouts in h.transport.timeouts_seen]
        assert reads == [30.0, 29.0, 7.0], reads
        assert reads[2] < reads[1] < 30.0

    def test_the_same_deadline_object_is_passed_every_time(self) -> None:
        h = harness([ScriptedResponse(status=503), ScriptedResponse(status=200)])
        budget = h.budget()
        with h.controller.fetch(TARGET, limits=FAST_LIMITS, budget=budget):
            pass

        deadlines = {id(timeouts.deadline) for timeouts in h.transport.timeouts_seen}
        assert deadlines == {id(budget)}, "a fresh budget was created for an attempt"

    def test_a_retry_is_abandoned_when_the_backoff_would_not_fit(self) -> None:
        """Sleeping until the budget is empty wastes the wait: there is then no time to act."""
        # The attempt consumes all but half a second, so the 1s first backoff cannot fit.
        h = harness([ScriptedResponse(status=503, takes_seconds=39.5)])
        with (
            pytest.raises(FetchFailedError) as caught,
            h.controller.fetch(TARGET, limits=FAST_LIMITS, budget=h.budget(40.0)),
        ):
            pass

        assert "does not fit" in str(caught.value)
        assert h.sleeper.slept == []
        assert caught.value.final_outcome is AttemptOutcome.HTTP_STATUS

    def test_an_exhausted_budget_stops_the_sequence(self) -> None:
        h = harness([ScriptedResponse(status=503), ScriptedResponse(status=200)])
        budget = h.budget(40.0)

        def eat_the_budget(seconds: float) -> None:
            h.clock.advance(50.0)

        h.sleeper.sleep = eat_the_budget  # type: ignore[method-assign]

        with (
            pytest.raises(FetchFailedError) as caught,
            h.controller.fetch(TARGET, limits=FAST_LIMITS, budget=budget),
        ):
            pass
        assert caught.value.final_outcome in {
            AttemptOutcome.BUDGET_EXHAUSTED,
            AttemptOutcome.HTTP_STATUS,
        }

    def test_a_transport_budget_exhaustion_is_not_retried(self) -> None:
        h = harness(
            [
                ScriptedResponse(error=BudgetExhaustedError("out of time")),
                ScriptedResponse(status=200),
            ]
        )
        with (
            pytest.raises(FetchFailedError) as caught,
            h.controller.fetch(TARGET, limits=FAST_LIMITS, budget=h.budget()),
        ):
            pass

        assert caught.value.final_outcome is AttemptOutcome.BUDGET_EXHAUSTED
        assert len(h.transport.timeouts_seen) == 1, "it retried an exhausted budget"


class TestSecurityRefusalsAreAbsolute:
    """Rule 81d through the controller, not just through the policy in isolation."""

    @pytest.mark.parametrize(
        "error",
        [
            TlsVerificationError("certificate did not verify"),
            ResponseTooLargeError("too big", limit_bytes=1024, declared=True),
            BudgetExhaustedError("no time left"),
            UnclassifiedTransportError("something unrecognised"),
        ],
    )
    def test_a_refusal_stops_immediately(self, error: TransportError) -> None:
        h = harness([ScriptedResponse(error=error), ScriptedResponse(status=200)])
        with (
            pytest.raises(FetchFailedError) as caught,
            h.controller.fetch(TARGET, limits=FAST_LIMITS, budget=h.budget()),
        ):
            pass

        assert caught.value.final_outcome is error.outcome
        assert len(h.transport.timeouts_seen) == 1, "a security refusal was retried"
        assert h.sleeper.slept == []
        assert caught.value.__cause__ is error

    @pytest.mark.parametrize("retry_after", ["1", "0", "30"])
    def test_a_retry_after_header_cannot_rescue_a_refusal(self, retry_after: str) -> None:
        """A hostile server offering a friendly header must not reopen a closed decision.

        The refusal arrives as an exception, so there is no response to carry a header — which is
        itself the structural reason this cannot happen. Asserted anyway, because the same guarantee
        stated as "the code path makes it impossible" is worth one test that would notice if a
        future
        version started consulting headers before classifying.
        """
        h = harness(
            [
                ScriptedResponse(error=TlsVerificationError("bad cert")),
                ScriptedResponse(status=200, headers=(("Retry-After", retry_after),)),
            ]
        )
        with (
            pytest.raises(FetchFailedError) as caught,
            h.controller.fetch(TARGET, limits=FAST_LIMITS, budget=h.budget()),
        ):
            pass
        assert caught.value.final_outcome is AttemptOutcome.TLS_ERROR

    def test_a_non_retryable_status_stops_without_a_backoff(self) -> None:
        h = harness([ScriptedResponse(status=404), ScriptedResponse(status=200)])
        with (
            pytest.raises(FetchFailedError) as caught,
            h.controller.fetch(TARGET, limits=FAST_LIMITS, budget=h.budget()),
        ):
            pass
        assert "permanent" in str(caught.value)
        assert len(h.transport.timeouts_seen) == 1
        assert h.sleeper.slept == []


class TestRetryAfterHandling:
    def test_a_server_requested_delay_is_honoured(self) -> None:
        h = harness(
            [
                ScriptedResponse(status=503, headers=(("Retry-After", "12"),)),
                ScriptedResponse(status=200),
            ]
        )
        with h.controller.fetch(TARGET, limits=FAST_LIMITS, budget=h.budget()):
            pass
        assert h.sleeper.slept == [12.0]

    def test_an_absurd_server_delay_abandons_rather_than_parking_a_worker(self) -> None:
        """``Retry-After: 86400``. A worker must not disappear for a day.

        Note what this does *not* do: it does not clamp to the cap and retry early. Returning before
        the server said it would be ready is impolite and the most likely way to get blocked. The
        fetch fails and a scheduler can come back later, which is what the server asked for.
        """
        h = harness(
            [
                ScriptedResponse(status=503, headers=(("Retry-After", "86400"),)),
                ScriptedResponse(status=200),
            ]
        )
        with (
            pytest.raises(FetchFailedError) as caught,
            h.controller.fetch(TARGET, limits=FAST_LIMITS, budget=h.budget()),
        ):
            pass

        assert "over the" in str(caught.value)
        assert h.sleeper.slept == [], "a worker was parked on an absurd server request"
        assert len(h.transport.timeouts_seen) == 1

    def test_a_zero_second_retry_after_retries_without_waiting(self) -> None:
        """A server saying "come back now" must not be turned into a sleep of zero length."""
        h = harness(
            [
                ScriptedResponse(status=503, headers=(("Retry-After", "0"),)),
                ScriptedResponse(status=200),
            ]
        )
        with h.controller.fetch(TARGET, limits=FAST_LIMITS, budget=h.budget()) as result:
            assert result.response.status_code == 200
        assert h.sleeper.slept == [], "a zero delay should not reach the sleeper at all"
        assert result.attempts[0].delay_before_next_seconds == 0.0

    def test_a_malformed_retry_after_falls_back_to_backoff(self) -> None:
        """Unparseable means "no instruction", not "wait forever" and not "retry immediately"."""
        h = harness(
            [
                ScriptedResponse(status=503, headers=(("Retry-After", "soon please"),)),
                ScriptedResponse(status=200),
            ]
        )
        with h.controller.fetch(TARGET, limits=FAST_LIMITS, budget=h.budget()):
            pass
        assert h.sleeper.slept == [1.0], "expected the first backoff ceiling, not a server delay"

    def test_the_backoff_grows_and_is_bounded(self) -> None:
        h = harness([ScriptedResponse(status=503)] * 4 + [ScriptedResponse(status=200)])
        with h.controller.fetch(TARGET, limits=FAST_LIMITS, budget=h.budget(3600.0)):
            pass
        assert h.sleeper.slept == [1.0, 2.0, 4.0, 8.0]


class TestCancellation:
    def test_a_backoff_is_interrupted_by_a_shutdown_signal(self) -> None:
        h = harness([ScriptedResponse(status=503), ScriptedResponse(status=200)])
        stopping = threading.Event()
        stopping.set()

        with (
            pytest.raises(FetchCancelledError) as caught,
            h.controller.fetch(
                TARGET, limits=FAST_LIMITS, budget=h.budget(), cancellation=stopping
            ),
        ):
            pass

        assert caught.value.attempts[0].outcome is AttemptOutcome.HTTP_STATUS
        assert len(h.transport.timeouts_seen) == 1, "it attempted again after cancellation"
        assert h.sleeper.slept == [], "the uninterruptible sleeper was used despite a token"

    def test_an_unset_signal_does_not_interrupt(self) -> None:
        h = harness([ScriptedResponse(status=503), ScriptedResponse(status=200)])
        stopping = threading.Event()

        with h.controller.fetch(
            TARGET, limits=FAST_LIMITS, budget=h.budget(), cancellation=stopping
        ) as result:
            assert result.response.status_code == 200
        assert result.attempt_count == 2

    def test_a_threading_event_satisfies_the_protocol(self) -> None:
        """The claim the module asserts at import time, restated where a reader will look."""
        assert isinstance(threading.Event(), Cancellation)


class TestAttemptHistory:
    def test_the_history_records_each_attempt_in_order(self) -> None:
        """attempt 1 → 503, attempt 2 → timeout, attempt 3 → 200."""
        h = harness(
            [
                ScriptedResponse(status=503),
                ScriptedResponse(error=ReadTimeoutError("slow")),
                ScriptedResponse(status=200),
            ]
        )
        with h.controller.fetch(TARGET, limits=FAST_LIMITS, budget=h.budget()) as result:
            pass

        outcomes = [record.outcome for record in result.attempts]
        assert outcomes == [
            AttemptOutcome.HTTP_STATUS,
            AttemptOutcome.READ_TIMEOUT,
            AttemptOutcome.SUCCESS,
        ]
        assert [record.attempt for record in result.attempts] == [1, 2, 3]
        assert result.attempts[0].status_code == 503
        assert result.attempts[1].error_type == "ReadTimeoutError"
        assert result.attempts[2].status_code == 200

    def test_the_history_records_the_delay_that_followed_each_attempt(self) -> None:
        h = harness([ScriptedResponse(status=503), ScriptedResponse(status=200)])
        with h.controller.fetch(TARGET, limits=FAST_LIMITS, budget=h.budget()) as result:
            pass

        assert result.attempts[0].delay_before_next_seconds == 1.0
        assert result.attempts[1].delay_before_next_seconds == 0.0

    def test_the_history_survives_a_total_failure(self) -> None:
        """The evidence of what went wrong is exactly what a failed fetch needs to report."""
        h = harness([ScriptedResponse(status=503)] * 3, max_attempts=3)
        with (
            pytest.raises(FetchFailedError) as caught,
            h.controller.fetch(TARGET, limits=FAST_LIMITS, budget=h.budget(3600.0)),
        ):
            pass

        assert len(caught.value.attempts) == 3
        assert {record.status_code for record in caught.value.attempts} == {503}
        assert caught.value.attempts[-1].reason != ""

    def test_durations_are_recorded_per_attempt(self) -> None:
        h = harness(
            [
                ScriptedResponse(status=503, takes_seconds=2.0),
                ScriptedResponse(status=200, takes_seconds=0.5),
            ]
        )
        with h.controller.fetch(TARGET, limits=FAST_LIMITS, budget=h.budget()) as result:
            pass
        assert result.attempts[0].duration_ms == pytest.approx(2000.0)
        assert result.attempts[1].duration_ms == pytest.approx(500.0)

    def test_a_record_describes_itself_without_a_body(self) -> None:
        record = AttemptRecord(
            attempt=2,
            outcome=AttemptOutcome.CONNECTION_ERROR,
            duration_ms=1234.0,
            error_type="ConnectionFailedError",
        )
        described = record.describe()
        assert "attempt 2" in described
        assert "ConnectionFailedError" in described
        assert "1234ms" in described

        # Without an error type, the outcome itself carries the meaning.
        status_only = AttemptRecord(
            attempt=1, outcome=AttemptOutcome.HTTP_STATUS, duration_ms=12.0, status_code=503
        )
        assert status_only.describe() == "attempt 1: HTTP 503 in 12ms"

        outcome_only = AttemptRecord(
            attempt=1, outcome=AttemptOutcome.CONNECT_TIMEOUT, duration_ms=9.0
        )
        assert outcome_only.describe() == "attempt 1: connect_timeout in 9ms"


class TestAttemptCap:
    def test_attempts_stop_at_the_configured_limit(self) -> None:
        h = harness([ScriptedResponse(error=ConnectionFailedError("refused"))] * 9, max_attempts=3)
        with (
            pytest.raises(FetchFailedError) as caught,
            h.controller.fetch(TARGET, limits=FAST_LIMITS, budget=h.budget(3600.0)),
        ):
            pass

        assert len(h.transport.timeouts_seen) == 3
        assert len(caught.value.attempts) == 3
        assert "limit of 3" in str(caught.value)

    def test_the_source_is_taken_from_the_validated_target(self) -> None:
        """So a request cannot be charged against a different source's politeness budget."""
        h = harness([ScriptedResponse(status=200)])
        with h.controller.fetch(TARGET, limits=FAST_LIMITS, budget=h.budget()):
            pass
        assert "slot-acquired:cpwd" in h.events
