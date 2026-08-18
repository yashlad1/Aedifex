"""Time, randomness, and the request timeout budget.

Clock, sleeper, and randomness are injected rather than called directly, for one reason that
matters more than testing convenience: a retry policy that reads the wall clock and calls
``random()`` internally cannot be exhaustively tested, so its edge cases go unverified. Tests here
never sleep and never depend on real time.

The budget is the piece worth reading carefully. A per-attempt timeout bounds one attempt; it does
nothing to bound an *operation*. Five retries at a 30-second read timeout, with backoff between
them, is a 150-second operation that every individual timeout considered acceptable. So the total
budget is fixed at the start, and both attempts and backoff sleeps are drawn from it.
"""

from __future__ import annotations

import random
import re
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Final, Protocol

from aedifex.errors import AcquisitionError

__all__ = [
    "MAX_SERVER_REQUESTED_DELAY_SECONDS",
    "Clock",
    "MonotonicClock",
    "RandomSource",
    "Sleeper",
    "SystemRandomSource",
    "SystemSleeper",
    "TimeoutBudget",
    "TimeoutBudgetExhaustedError",
    "TimeoutPolicy",
    "parse_retry_after",
]

# A hostile or misconfigured server must not be able to park a worker. Any server-requested delay
# beyond this is treated as "come back much later", which means abandoning the request rather than
# holding a worker and a connection slot.
MAX_SERVER_REQUESTED_DELAY_SECONDS: Final[float] = 300.0

# ASCII digits only, deliberately not `\d`. Python's `\d` matches Unicode decimal digits and
# `float()` accepts them, so an Arabic-Indic digit five would otherwise parse as a
# 5-second delay. HTTP header values are ASCII; interpreting non-ASCII digits would make our parse
# differ from every other parser's, which is the disagreement this package exists to avoid.
_DIGITS: Final[re.Pattern[str]] = re.compile(r"^[0-9]{1,10}$")


class Clock(Protocol):
    """A monotonic time source, in seconds."""

    def now(self) -> float:
        """Return a monotonically increasing timestamp."""
        ...


class Sleeper(Protocol):
    """Suspends execution. Separated from :class:`Clock` so tests can assert sleeps never happen."""

    def sleep(self, seconds: float) -> None: ...


class RandomSource(Protocol):
    """Randomness for jitter."""

    def uniform(self, low: float, high: float) -> float: ...


class MonotonicClock:
    """Production clock. Monotonic, so a wall-clock adjustment cannot shorten or extend a budget."""

    def now(self) -> float:
        return time.monotonic()


class SystemSleeper:
    """Production sleeper."""

    def sleep(self, seconds: float) -> None:
        if seconds > 0:
            time.sleep(seconds)


class SystemRandomSource:
    """Production randomness. Not cryptographic; jitter only needs to decorrelate workers."""

    def uniform(self, low: float, high: float) -> float:
        return random.uniform(low, high)  # noqa: S311 - jitter, not security


class TimeoutBudgetExhaustedError(AcquisitionError):
    """The total time allowed for a request was consumed.

    Distinct from a per-attempt timeout: this means the *operation* is over, so the caller must
    stop rather than retry.
    """


@dataclass(frozen=True, slots=True)
class TimeoutPolicy:
    """Per-phase timeouts plus the ceiling on the whole operation.

    ``total_seconds`` covers everything: every attempt, every backoff sleep, and every redirect
    hop. It is the only value that bounds what a caller actually waits for.
    """

    connect_seconds: float = 10.0
    read_seconds: float = 30.0
    total_seconds: float = 300.0

    def __post_init__(self) -> None:
        for name in ("connect_seconds", "read_seconds", "total_seconds"):
            value: float = getattr(self, name)
            if value <= 0:
                raise ValueError(f"{name} must be positive, got {value}")
        if self.total_seconds < self.connect_seconds + self.read_seconds:
            # Otherwise the first attempt alone could exceed the budget, and the budget would be
            # a number that never permits a complete attempt.
            raise ValueError(
                f"total_seconds={self.total_seconds} is smaller than one attempt "
                f"(connect {self.connect_seconds} + read {self.read_seconds})"
            )


@dataclass(slots=True)
class TimeoutBudget:
    """Tracks how much of a request's total time allowance remains.

    Deliberately mutable and single-use: it represents the progress of one operation. Create a new
    one per request; never reset one, because resetting is exactly the bug this class prevents.
    """

    policy: TimeoutPolicy
    clock: Clock
    _started_at: float = field(init=False)

    def __post_init__(self) -> None:
        self._started_at = self.clock.now()

    @property
    def elapsed_seconds(self) -> float:
        return max(0.0, self.clock.now() - self._started_at)

    @property
    def remaining_seconds(self) -> float:
        return max(0.0, self.policy.total_seconds - self.elapsed_seconds)

    @property
    def is_exhausted(self) -> bool:
        return self.remaining_seconds <= 0.0

    def check(self) -> None:
        """Raise if the budget is spent.

        Raises:
            TimeoutBudgetExhaustedError: when no time remains.
        """
        if self.is_exhausted:
            raise TimeoutBudgetExhaustedError(
                f"request budget of {self.policy.total_seconds}s exhausted after "
                f"{self.elapsed_seconds:.3f}s"
            )

    def attempt_timeouts(self) -> tuple[float, float]:
        """Return ``(connect, read)`` timeouts for the next attempt, clamped to what remains.

        Clamping is the point: a 30-second read timeout is meaningless when 4 seconds of budget
        are left, and passing the unclamped value would let one attempt overrun the whole
        operation.

        Raises:
            TimeoutBudgetExhaustedError: when no time remains.
        """
        self.check()
        remaining = self.remaining_seconds
        return (
            min(self.policy.connect_seconds, remaining),
            min(self.policy.read_seconds, remaining),
        )

    def can_afford(self, seconds: float) -> bool:
        """Return whether ``seconds`` of waiting still fits, leaving room to act afterwards.

        Used before a backoff sleep: sleeping until the budget is exactly empty wastes the wait,
        because the retry it was preparing for could not then be attempted.
        """
        if seconds < 0:
            raise ValueError(f"seconds must not be negative, got {seconds}")
        return self.remaining_seconds > seconds


def parse_retry_after(value: str | None, *, now: datetime | None = None) -> float | None:
    """Parse a ``Retry-After`` header into seconds, or ``None`` if unusable.

    Accepts both forms in the specification — delay-seconds and HTTP-date — and treats anything
    else as absent rather than guessing. The value is attacker-controlled, so:

    * A past date yields ``0.0`` (retry immediately), not a negative delay.
    * Duplicate headers arrive joined as ``"5, 10"``; the first value wins, since honouring the
      larger would let a server extend its own hold.
    * The result is **not** capped here. Capping is the caller's decision, taken against its
      remaining budget, and keeping this function pure keeps it exhaustively testable.

    Args:
        value: Raw header value, or ``None``.
        now: Reference time for HTTP-date parsing. Injected for determinism.

    Returns:
        A non-negative delay in seconds, or ``None`` when the value cannot be interpreted.
    """
    if value is None:
        return None
    candidate = value.strip()
    if not candidate:
        return None

    # Duplicate headers are joined by comma. Take the first: a hostile server should not be able
    # to lengthen its own hold by appending a larger value.
    if "," in candidate:
        first = candidate.split(",", 1)[0].strip()
        # An HTTP-date legitimately contains a comma ("Wed, 21 Oct 2015 07:28:00 GMT"), so only
        # treat the comma as a separator when the first part looks like a delay-seconds value.
        candidate = first if _DIGITS.match(first) else candidate

    if _DIGITS.match(candidate):
        return float(candidate)

    # A negative or non-integer numeric value is malformed per the specification. Rejected rather
    # than coerced, so a "-1" cannot become a delay of any kind.
    if candidate.lstrip("+-").replace(".", "", 1).isdigit():
        return None

    try:
        deadline = parsedate_to_datetime(candidate)
    except (TypeError, ValueError):
        return None
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=UTC)

    reference = now or datetime.now(UTC)
    return max(0.0, (deadline - reference).total_seconds())
