"""Retry classification. Pure policy: no sleeping, no network, no I/O.

Keeping the decision separate from the loop that acts on it is what makes cases like
"429 with a hostile ``Retry-After``" or "TLS failure" exhaustively testable. A policy buried inside
a ``while`` loop with a ``time.sleep`` in it cannot be.

The retryable set is **enumerated, not derived from status class.** Treating all of 5xx alike is
the common shortcut and it is wrong: 501 means the server will never implement this, and retrying
it is pure waste. Likewise a blanket 4xx rule would miss 408 and 429, which are explicitly
retryable.

Three conditions are never retryable regardless of anything else, because each represents a
*decision* rather than a transient failure: an SSRF rejection, content rejected as unsafe, and an
invalid redirect. Retrying a decision just makes the same decision again, more loudly.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from aedifex.acquisition.fetch.timing import (
    MAX_SERVER_REQUESTED_DELAY_SECONDS,
    RandomSource,
)

__all__ = [
    "NON_RETRYABLE_STATUSES",
    "RETRYABLE_STATUSES",
    "AttemptOutcome",
    "AttemptResult",
    "BackoffPolicy",
    "RetryDecision",
    "RetryPolicy",
    "RetryVerdict",
]

# Enumerated deliberately. Each entry is a case where the same request may plausibly succeed later.
RETRYABLE_STATUSES: Final[frozenset[int]] = frozenset(
    {
        408,  # Request Timeout
        425,  # Too Early
        429,  # Too Many Requests
        500,  # Internal Server Error - see the note below
        502,  # Bad Gateway
        503,  # Service Unavailable
        504,  # Gateway Timeout
    }
)

# Enumerated so the policy is explicit about what it refuses, rather than "everything else".
# Anything absent from both sets is treated as non-retryable, because failing closed on an
# unfamiliar status is the safer default.
NON_RETRYABLE_STATUSES: Final[frozenset[int]] = frozenset(
    {
        400,  # Bad Request - our request is wrong; repeating it changes nothing
        401,  # Unauthorized - we never authenticate, so this is permanent
        403,  # Forbidden - retrying is what gets a crawler blocked
        404,  # Not Found
        405,  # Method Not Allowed
        410,  # Gone
        451,  # Unavailable For Legal Reasons
        501,  # Not Implemented - the server will not start implementing it
        505,  # HTTP Version Not Supported
    }
)

# 500 is retried, and that is a judgement rather than an obvious call. Public procurement portals
# return 500 for transient overload routinely, and the requests here are idempotent GETs, so a
# retry is cheap and often succeeds. The risk is hammering a genuinely broken endpoint, which is
# bounded by the attempt cap, the retry budget, and per-source rate limiting rather than by
# refusing to retry at all.


class AttemptOutcome(StrEnum):
    """What happened on one attempt.

    Transport-level failures are distinguished from each other because they retry differently: a
    connect timeout is worth retrying, a TLS verification failure is not.
    """

    SUCCESS = "success"
    HTTP_STATUS = "http_status"
    CONNECT_TIMEOUT = "connect_timeout"
    READ_TIMEOUT = "read_timeout"
    CONNECTION_ERROR = "connection_error"
    TLS_ERROR = "tls_error"
    DNS_ERROR = "dns_error"
    BUDGET_EXHAUSTED = "budget_exhausted"

    # Decisions, never transient failures.
    SSRF_REJECTED = "ssrf_rejected"
    UNSAFE_CONTENT = "unsafe_content"
    OVERSIZED_RESPONSE = "oversized_response"
    INVALID_REDIRECT = "invalid_redirect"
    CANCELLED = "cancelled"


# Outcomes that must never be retried, whatever the status code or headers say.
_NEVER_RETRY: Final[frozenset[AttemptOutcome]] = frozenset(
    {
        AttemptOutcome.SSRF_REJECTED,
        AttemptOutcome.UNSAFE_CONTENT,
        AttemptOutcome.OVERSIZED_RESPONSE,
        AttemptOutcome.INVALID_REDIRECT,
        AttemptOutcome.CANCELLED,
        AttemptOutcome.BUDGET_EXHAUSTED,
        # A TLS failure means the certificate did not verify for the hostname. That is either a
        # misconfigured server or an interception attempt; neither improves on a retry, and
        # retrying would normalise the failure.
        AttemptOutcome.TLS_ERROR,
        # DNS is resolved once by the guard, before any attempt. A DNS error here therefore means
        # the guard rejected the target, which is a decision.
        AttemptOutcome.DNS_ERROR,
    }
)

_TRANSPORT_RETRYABLE: Final[frozenset[AttemptOutcome]] = frozenset(
    {
        AttemptOutcome.CONNECT_TIMEOUT,
        AttemptOutcome.READ_TIMEOUT,
        AttemptOutcome.CONNECTION_ERROR,
    }
)


class RetryVerdict(StrEnum):
    """The three possible answers."""

    RETRY = "retry"
    """Retry after the policy's computed backoff delay."""
    RETRY_AFTER = "retry_after"
    """Retry after a delay the *server* asked for."""
    DO_NOT_RETRY = "do_not_retry"


@dataclass(frozen=True, slots=True)
class AttemptResult:
    """The outcome of one attempt, as the retry policy needs to see it.

    Carries no response body and no connection: the policy must not be able to touch the network.
    """

    outcome: AttemptOutcome
    attempt: int
    """1-based."""
    status_code: int | None = None
    retry_after_seconds: float | None = None
    """Already parsed from the header by :func:`~.timing.parse_retry_after`, uncapped."""
    detail: str = ""

    def __post_init__(self) -> None:
        if self.attempt < 1:
            raise ValueError(f"attempt is 1-based, got {self.attempt}")
        if self.outcome is AttemptOutcome.HTTP_STATUS and self.status_code is None:
            raise ValueError("outcome 'http_status' requires a status_code")


@dataclass(frozen=True, slots=True)
class RetryDecision:
    """What to do next, and why. The reason is carried so a log line can explain itself."""

    verdict: RetryVerdict
    delay_seconds: float
    reason: str

    @property
    def should_retry(self) -> bool:
        return self.verdict is not RetryVerdict.DO_NOT_RETRY


@dataclass(frozen=True, slots=True)
class BackoffPolicy:
    """Exponential backoff with **full** jitter.

    Full jitter (a uniform draw over the whole interval) rather than equal jitter, because the
    problem being solved is many workers retrying a struggling portal in lockstep. Half-width
    jitter still leaves them clustered; full jitter spreads them across the window.
    """

    base_seconds: float = 1.0
    factor: float = 2.0
    max_delay_seconds: float = 60.0
    max_attempts: int = 5

    def __post_init__(self) -> None:
        if self.base_seconds <= 0:
            raise ValueError(f"base_seconds must be positive, got {self.base_seconds}")
        if self.factor < 1:
            raise ValueError(f"factor must be at least 1, got {self.factor}")
        if self.max_delay_seconds < self.base_seconds:
            raise ValueError("max_delay_seconds must be at least base_seconds")
        if self.max_attempts < 1:
            raise ValueError(f"max_attempts must be at least 1, got {self.max_attempts}")

    def ceiling_for(self, attempt: int) -> float:
        """Return the un-jittered upper bound for ``attempt`` (1-based)."""
        if attempt < 1:
            raise ValueError(f"attempt is 1-based, got {attempt}")
        exponential = self.base_seconds * (self.factor ** (attempt - 1))
        return min(exponential, self.max_delay_seconds)

    def delay_for(self, attempt: int, randomness: RandomSource) -> float:
        """Return a jittered delay in ``[0, ceiling_for(attempt)]``."""
        return randomness.uniform(0.0, self.ceiling_for(attempt))


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Classifies attempts. Never sleeps, never performs I/O, never mutates anything."""

    backoff: BackoffPolicy = BackoffPolicy()
    max_server_requested_delay_seconds: float = MAX_SERVER_REQUESTED_DELAY_SECONDS

    def classify(
        self,
        result: AttemptResult,
        *,
        randomness: RandomSource,
        remaining_budget_seconds: float | None = None,
    ) -> RetryDecision:
        """Decide whether to retry ``result``, and after how long.

        Args:
            result: The attempt that just finished.
            randomness: Jitter source, injected so the decision is reproducible in tests.
            remaining_budget_seconds: What is left of the request's total allowance. When given, a
                delay that would not fit is converted into ``DO_NOT_RETRY`` rather than a sleep
                that ends with no time left to act.

        Returns:
            A :class:`RetryDecision`. Never raises for an ordinary outcome.
        """
        if result.outcome is AttemptOutcome.SUCCESS:
            return RetryDecision(RetryVerdict.DO_NOT_RETRY, 0.0, "attempt succeeded")

        if result.outcome in _NEVER_RETRY:
            return RetryDecision(
                RetryVerdict.DO_NOT_RETRY,
                0.0,
                f"{result.outcome.value} is a decision, not a transient failure",
            )

        if result.attempt >= self.backoff.max_attempts:
            return RetryDecision(
                RetryVerdict.DO_NOT_RETRY,
                0.0,
                f"attempt {result.attempt} reached the limit of {self.backoff.max_attempts}",
            )

        retryable, reason = self._is_retryable(result)
        if not retryable:
            return RetryDecision(RetryVerdict.DO_NOT_RETRY, 0.0, reason)

        verdict, delay, delay_reason = self._delay_for(result, randomness)

        if remaining_budget_seconds is not None and delay >= remaining_budget_seconds:
            return RetryDecision(
                RetryVerdict.DO_NOT_RETRY,
                0.0,
                f"{reason}, but a {delay:.3f}s delay does not fit in the "
                f"{remaining_budget_seconds:.3f}s of budget remaining",
            )

        return RetryDecision(verdict, delay, f"{reason}; {delay_reason}")

    def _is_retryable(self, result: AttemptResult) -> tuple[bool, str]:
        if result.outcome in _TRANSPORT_RETRYABLE:
            return True, f"{result.outcome.value} is transient"

        if result.outcome is AttemptOutcome.HTTP_STATUS:
            status = result.status_code
            if status is None:
                # Unreachable given AttemptResult's validation, handled rather than asserted:
                # `assert` is stripped under -O, and failing closed costs nothing here.
                return False, "http_status outcome carried no status code; treated as permanent"
            if status in RETRYABLE_STATUSES:
                return True, f"HTTP {status} is retryable"
            if status in NON_RETRYABLE_STATUSES:
                return False, f"HTTP {status} is permanent"
            # An unfamiliar status fails closed. Retrying something we have no policy for risks
            # hammering an endpoint for no reason.
            return False, f"HTTP {status} has no retry policy; treated as permanent"

        return False, f"{result.outcome.value} has no retry policy; treated as permanent"

    def _delay_for(
        self, result: AttemptResult, randomness: RandomSource
    ) -> tuple[RetryVerdict, float, str]:
        """Return the verdict, delay, and an explanation. Server requests take precedence."""
        requested = result.retry_after_seconds
        if requested is not None:
            if requested > self.max_server_requested_delay_seconds:
                # Not clamped down to the cap and slept through: a server asking for hours is
                # telling us to come back much later, and holding a worker meanwhile is the thing
                # the cap exists to prevent.
                return (
                    RetryVerdict.DO_NOT_RETRY,
                    0.0,
                    f"server asked for {requested:.0f}s, over the "
                    f"{self.max_server_requested_delay_seconds:.0f}s cap",
                )
            return (
                RetryVerdict.RETRY_AFTER,
                requested,
                f"honouring server Retry-After of {requested:.3f}s",
            )

        delay = self.backoff.delay_for(result.attempt, randomness)
        return (
            RetryVerdict.RETRY,
            delay,
            f"backoff {delay:.3f}s (jittered within "
            f"{self.backoff.ceiling_for(result.attempt):.3f}s)",
        )
