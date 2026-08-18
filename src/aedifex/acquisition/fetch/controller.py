"""The retry controller: one fetch, several attempts, one budget.

Orchestration only. Every decision it acts on is made elsewhere — :class:`RetryPolicy` decides
whether to retry, :class:`TimeoutBudget` decides how much time is left, :class:`RateLimiter` decides
when a source may be contacted, and the transport decides nothing at all. This module's job is to
sequence them correctly, and its correctness is almost entirely about ordering.

.. code-block:: text

    attempt 1
      rate-limit slot  ──►  transport  ──►  503
                                             ↓
                              release slot, close response
                                             ↓
                                        RetryPolicy
                                             ↓
                              backoff (interruptible)
                                             ↓
    attempt 2
      rate-limit slot  ──►  transport  ──►  200  ──►  hand the open stream to the caller

Four properties, each of which is a bug if inverted:

**A slot per attempt, not per fetch.** A retry is a request the source has to serve. Taking one
slot and spending five attempts inside it would let a flaky server pull traffic straight through
the politeness limit it is configured with — precisely when the site is least able to cope.

**The slot is released before the backoff.** Sleeping while holding capacity would starve other work
for the duration of a delay that exists specifically to leave the source alone.

**One budget for the whole fetch.** The controller never constructs a
:class:`~aedifex.acquisition.fetch.timing.TimeoutBudget`; it is handed one and passes that same
object to every attempt, so attempts, backoffs, and rate-limit waits all draw down one allowance.
A budget rebuilt per attempt would make "30-second timeout" mean "30 seconds each, five times".

**Security refusals are absolute.** Classification comes from the error type's own ``outcome``, so
no status code and no ``Retry-After`` header can turn a TLS failure, an SSRF rejection, an
oversized response, or an exhausted budget into another attempt (rule 81d).

On ``Retry-After``, one deliberate difference from the obvious formula. The tempting rule is
``min(retry_after, max_delay, remaining_budget)`` — clamp and sleep. This does not clamp: a server
asking for longer than the cap causes the fetch to be **abandoned** rather than retried early.
Clamping would mean returning before the server said it would be ready, which is both impolite and
the most likely way to earn a block. Failing the fetch lets a scheduler decide to come back much
later, which is what the server actually asked for. Decided in ADR 0010 and implemented in
:meth:`RetryPolicy.classify`.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator, Mapping
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field
from typing import ClassVar, Protocol, runtime_checkable

from aedifex.acquisition.fetch.guard import ValidatedTarget
from aedifex.acquisition.fetch.ratelimit import RateLimiter, RateLimits
from aedifex.acquisition.fetch.retry import (
    AttemptOutcome,
    AttemptResult,
    RetryDecision,
    RetryPolicy,
)
from aedifex.acquisition.fetch.timing import (
    Clock,
    MonotonicClock,
    RandomSource,
    Sleeper,
    SystemRandomSource,
    SystemSleeper,
    TimeoutBudget,
    TimeoutBudgetExhaustedError,
    parse_retry_after,
)
from aedifex.acquisition.fetch.transport import (
    DEFAULT_MAX_RESPONSE_BYTES,
    RawResponse,
    Transport,
    TransportError,
    TransportTimeouts,
)
from aedifex.errors import AcquisitionError

__all__ = [
    "AttemptRecord",
    "Cancellation",
    "FetchCancelledError",
    "FetchFailedError",
    "FetchResult",
    "RetryController",
]

_ERROR_STATUS_FLOOR = 400
"""Statuses at or above this are treated as failed attempts and handed to the retry policy.

Below it — including every 3xx — the response is handed back to the caller. Redirects are not the
retry controller's business: following one is a new request that has to pass the guard, which is the
redirect controller's job. Whether a particular error status is *retryable* is decided by
:class:`RetryPolicy`, not here; this line only separates "the server answered" from "the attempt
failed".
"""


@runtime_checkable
class Cancellation(Protocol):
    """A shutdown signal a backoff can be interrupted by.

    ``threading.Event`` satisfies this structurally — ``Event.wait(timeout)`` returns ``True`` when
    the flag is set — so the worker shutdown flag that will exist anyway is the token, with no
    adapter and no new concept.

    The point is that a backoff must never be an uninterruptible ``sleep``. A worker asked to stop
    during a 60-second delay should stop, not finish its nap first.
    """

    def wait(self, timeout: float) -> bool:
        """Block for up to ``timeout`` seconds. Return ``True`` if cancellation was signalled."""
        ...


@dataclass(frozen=True, slots=True)
class AttemptRecord:
    """What happened on one attempt, kept whether or not the fetch eventually succeeded.

    Retained because the history is evidence. "Succeeded on attempt 3 after a 503 and a timeout" is
    a materially different provenance claim from "succeeded", and the difference matters when
    someone later asks whether a document was retrieved cleanly. Persisting it is the downloader's
    business; not throwing it away is this module's.
    """

    attempt: int
    outcome: AttemptOutcome
    duration_ms: float
    status_code: int | None = None
    error_type: str | None = None
    retry_after_seconds: float | None = None
    delay_before_next_seconds: float = 0.0
    reason: str = ""

    def describe(self) -> str:
        """One line for a log. Never includes a response body."""
        detail = f"HTTP {self.status_code}" if self.status_code is not None else self.outcome.value
        if self.error_type is not None:
            detail = f"{detail} ({self.error_type})"
        return f"attempt {self.attempt}: {detail} in {self.duration_ms:.0f}ms"


@dataclass(frozen=True, slots=True)
class FetchResult:
    """A response the caller may read, plus the history of getting it."""

    response: RawResponse
    attempts: tuple[AttemptRecord, ...] = field(default_factory=tuple)

    @property
    def attempt_count(self) -> int:
        return len(self.attempts)

    @property
    def was_retried(self) -> bool:
        return len(self.attempts) > 1


class FetchFailedError(AcquisitionError):
    """Every permitted attempt failed, or the first one failed permanently.

    Carries the whole attempt history and the final classification. The specific failure is the
    ``__cause__``; callers deciding what to do next should read :attr:`final_outcome`, because that
    is the single-sourced classification the retry policy itself uses — reaching for the Python
    exception type instead is how two layers end up disagreeing about whether something is
    retryable.
    """

    def __init__(
        self,
        message: str,
        *,
        final_outcome: AttemptOutcome,
        attempts: tuple[AttemptRecord, ...],
    ) -> None:
        super().__init__(message)
        self.final_outcome = final_outcome
        self.attempts = attempts


class FetchCancelledError(AcquisitionError):
    """Shutdown was signalled while waiting to retry."""

    outcome: ClassVar[AttemptOutcome] = AttemptOutcome.CANCELLED

    def __init__(self, message: str, *, attempts: tuple[AttemptRecord, ...]) -> None:
        super().__init__(message)
        self.attempts = attempts


class RetryController:
    """Performs one fetch, retrying according to policy, within a single budget."""

    def __init__(
        self,
        *,
        transport: Transport,
        limiter: RateLimiter,
        policy: RetryPolicy | None = None,
        randomness: RandomSource | None = None,
        clock: Clock | None = None,
        sleeper: Sleeper | None = None,
    ) -> None:
        self._transport = transport
        self._limiter = limiter
        self._policy = policy if policy is not None else RetryPolicy()
        self._randomness = randomness if randomness is not None else SystemRandomSource()
        self._clock = clock if clock is not None else MonotonicClock()
        self._sleeper = sleeper if sleeper is not None else SystemSleeper()

    @contextmanager
    def fetch(
        self,
        target: ValidatedTarget,
        *,
        limits: RateLimits,
        budget: TimeoutBudget,
        method: str = "GET",
        headers: Mapping[str, str] | None = None,
        max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
        cancellation: Cancellation | None = None,
        body: bytes | None = None,
    ) -> Iterator[FetchResult]:
        """Fetch ``target``, retrying transient failures, and yield the successful response.

        The source is taken from ``target.source_id`` rather than passed separately, so a request
        cannot be rate-limited against a different source than the one it was validated for.

        The response is yielded with its body unread and stays open for the duration of the ``with``
        block; the connection is released on exit, on every path.

        Raises:
            FetchFailedError: when no attempt succeeded. Carries the attempt history and the final
                outcome; the specific failure is the ``__cause__``.
            FetchCancelledError: when shutdown was signalled during a backoff.
        """
        history: list[AttemptRecord] = []
        attempt = 0

        while True:
            attempt += 1
            decision: RetryDecision | None = None
            failure: Exception | None = None
            record: AttemptRecord | None = None

            with ExitStack() as stack:
                started = self._clock.now()
                try:
                    # Capacity first, and per attempt. The slot is scoped to this stack, so it is
                    # returned before any backoff below.
                    stack.enter_context(
                        self._limiter.slot(target.source_id, limits, deadline=budget)
                    )
                    response = stack.enter_context(
                        self._transport.open(
                            target,
                            # The same budget object every time. Rebuilding it here is the defect
                            # this whole layer exists to prevent.
                            timeouts=TransportTimeouts.from_budget(budget),
                            method=method,
                            headers=headers,
                            max_response_bytes=max_response_bytes,
                            # The same bytes on every attempt. A retry that re-derived the body
                            # could send a different request than the one that failed.
                            body=body,
                        )
                    )
                except TransportError as error:
                    # Classification comes from the error type, never from anything this controller
                    # infers (rule 81d). BudgetExhaustedError arrives here too, and its outcome is
                    # already in the never-retry set.
                    decision, record = self._classify_failure(
                        error.outcome,
                        attempt=attempt,
                        started=started,
                        budget=budget,
                        error_type=type(error).__name__,
                    )
                    failure = error
                except TimeoutBudgetExhaustedError as error:
                    # Raised by the rate limiter or by from_budget, before any socket. Not a
                    # transport failure, but the same conclusion: the time for this fetch is gone.
                    decision, record = self._classify_failure(
                        AttemptOutcome.BUDGET_EXHAUSTED,
                        attempt=attempt,
                        started=started,
                        budget=budget,
                        error_type=type(error).__name__,
                    )
                    failure = error
                else:
                    status = response.status_code
                    retry_after = parse_retry_after(response.headers.get("retry-after"))

                    if status < _ERROR_STATUS_FLOOR:
                        history.append(
                            AttemptRecord(
                                attempt=attempt,
                                outcome=AttemptOutcome.SUCCESS,
                                duration_ms=self._elapsed_ms(started),
                                status_code=status,
                                reason="attempt succeeded",
                            )
                        )
                        yield FetchResult(response=response, attempts=tuple(history))
                        return

                    decision, record = self._classify_failure(
                        AttemptOutcome.HTTP_STATUS,
                        attempt=attempt,
                        started=started,
                        budget=budget,
                        status_code=status,
                        retry_after=retry_after,
                    )

            # The stack has closed: the slot is back and any response is shut. Only now may we wait.
            if decision is None or record is None:  # pragma: no cover - defensive
                raise AssertionError("an attempt produced neither a response nor a decision")

            if not decision.should_retry:
                history.append(record)
                raise FetchFailedError(
                    f"fetch of {target.describe()} failed after {attempt} attempt(s): "
                    f"{decision.reason}",
                    final_outcome=record.outcome,
                    attempts=tuple(history),
                ) from failure

            history.append(
                AttemptRecord(
                    attempt=record.attempt,
                    outcome=record.outcome,
                    duration_ms=record.duration_ms,
                    status_code=record.status_code,
                    error_type=record.error_type,
                    retry_after_seconds=record.retry_after_seconds,
                    delay_before_next_seconds=decision.delay_seconds,
                    reason=decision.reason,
                )
            )
            self._backoff(
                decision.delay_seconds,
                cancellation=cancellation,
                attempts=tuple(history),
                target=target,
            )

    def _classify_failure(
        self,
        outcome: AttemptOutcome,
        *,
        attempt: int,
        started: float,
        budget: TimeoutBudget,
        status_code: int | None = None,
        retry_after: float | None = None,
        error_type: str | None = None,
    ) -> tuple[RetryDecision, AttemptRecord]:
        """Ask the policy what to do, and record what happened."""
        decision = self._policy.classify(
            AttemptResult(
                outcome=outcome,
                attempt=attempt,
                status_code=status_code,
                retry_after_seconds=retry_after,
            ),
            randomness=self._randomness,
            # What is left *now*, so a delay that would not fit becomes a refusal rather than a
            # sleep that ends with no time to act.
            remaining_budget_seconds=budget.remaining_seconds,
        )
        record = AttemptRecord(
            attempt=attempt,
            outcome=outcome,
            duration_ms=self._elapsed_ms(started),
            status_code=status_code,
            error_type=error_type,
            retry_after_seconds=retry_after,
            reason=decision.reason,
        )
        return decision, record

    def _backoff(
        self,
        delay: float,
        *,
        cancellation: Cancellation | None,
        attempts: tuple[AttemptRecord, ...],
        target: ValidatedTarget,
    ) -> None:
        """Wait, interruptibly when a cancellation signal was supplied."""
        if delay <= 0.0:
            return
        if cancellation is None:
            self._sleeper.sleep(delay)
            return
        if cancellation.wait(delay):
            raise FetchCancelledError(
                f"shutdown signalled while waiting {delay:.3f}s to retry {target.describe()}",
                attempts=attempts,
            )

    def _elapsed_ms(self, started: float) -> float:
        return max(0.0, (self._clock.now() - started) * 1000.0)


def _event_is_cancellation() -> bool:
    """``threading.Event`` satisfies :class:`Cancellation`, asserted at import rather than in prose.

    A structural claim in a docstring rots silently; this one fails the build if it stops being
    true, which is the difference between documentation and a check.
    """
    return isinstance(threading.Event(), Cancellation)


if not _event_is_cancellation():  # pragma: no cover - a failure here is a build-time error
    raise TypeError("threading.Event no longer satisfies the Cancellation protocol")
