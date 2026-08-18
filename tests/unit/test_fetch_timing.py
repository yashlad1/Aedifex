"""Tests for the timeout budget and Retry-After parsing.

No test here sleeps or reads real time. The clock is injected, which is the point: a budget that
consulted the wall clock internally could not be tested at its boundaries.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from aedifex.acquisition.fetch.timing import (
    MonotonicClock,
    SystemRandomSource,
    SystemSleeper,
    TimeoutBudget,
    TimeoutBudgetExhaustedError,
    TimeoutPolicy,
    parse_retry_after,
)


class FakeClock:
    """A clock that only moves when a test moves it."""

    def __init__(self, start: float = 1000.0) -> None:
        self.current = start

    def now(self) -> float:
        return self.current

    def advance(self, seconds: float) -> None:
        self.current += seconds


class TestTimeoutPolicy:
    def test_defaults_are_sane(self) -> None:
        policy = TimeoutPolicy()
        assert policy.connect_seconds < policy.read_seconds < policy.total_seconds

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"connect_seconds": 0},
            {"connect_seconds": -1},
            {"read_seconds": 0},
            {"total_seconds": 0},
        ],
    )
    def test_non_positive_timeouts_are_rejected(self, kwargs: dict[str, float]) -> None:
        with pytest.raises(ValueError, match="must be positive"):
            TimeoutPolicy(**kwargs)

    def test_a_total_smaller_than_one_attempt_is_rejected(self) -> None:
        """Otherwise the budget is a number that never permits a complete attempt."""
        with pytest.raises(ValueError, match="smaller than one attempt"):
            TimeoutPolicy(connect_seconds=10, read_seconds=30, total_seconds=20)

    def test_a_total_exactly_equal_to_one_attempt_is_accepted(self) -> None:
        assert TimeoutPolicy(connect_seconds=10, read_seconds=30, total_seconds=40)

    def test_is_immutable(self) -> None:
        with pytest.raises(AttributeError):
            TimeoutPolicy().read_seconds = 1  # type: ignore[misc]


class TestTimeoutBudget:
    def test_starts_with_the_full_allowance(self) -> None:
        budget = TimeoutBudget(TimeoutPolicy(total_seconds=100), FakeClock())
        assert budget.remaining_seconds == 100
        assert budget.elapsed_seconds == 0
        assert not budget.is_exhausted

    def test_elapsed_time_reduces_what_remains(self) -> None:
        clock = FakeClock()
        budget = TimeoutBudget(TimeoutPolicy(total_seconds=100), clock)
        clock.advance(30)
        assert budget.elapsed_seconds == 30
        assert budget.remaining_seconds == 70

    def test_becomes_exhausted(self) -> None:
        clock = FakeClock()
        budget = TimeoutBudget(TimeoutPolicy(total_seconds=100), clock)
        clock.advance(100)
        assert budget.is_exhausted
        assert budget.remaining_seconds == 0

    def test_overrun_does_not_produce_a_negative_remainder(self) -> None:
        clock = FakeClock()
        budget = TimeoutBudget(TimeoutPolicy(total_seconds=100), clock)
        clock.advance(500)
        assert budget.remaining_seconds == 0

    def test_check_raises_once_exhausted(self) -> None:
        clock = FakeClock()
        budget = TimeoutBudget(TimeoutPolicy(total_seconds=50), clock)
        budget.check()
        clock.advance(50)
        with pytest.raises(TimeoutBudgetExhaustedError, match="exhausted"):
            budget.check()

    def test_the_budget_does_not_reset_across_attempts(self) -> None:
        """The property this class exists for.

        Five retries at a 30s read timeout is a 150s operation that every individual timeout
        considered acceptable. Only a budget fixed at the start bounds what a caller waits for.
        """
        clock = FakeClock()
        budget = TimeoutBudget(
            TimeoutPolicy(connect_seconds=10, read_seconds=30, total_seconds=60), clock
        )
        for _ in range(2):
            connect, read = budget.attempt_timeouts()
            assert (connect, read) == (10, 30) or read < 30
            clock.advance(read)
        assert budget.is_exhausted
        with pytest.raises(TimeoutBudgetExhaustedError):
            budget.attempt_timeouts()


class TestAttemptTimeouts:
    def test_full_timeouts_when_the_budget_is_ample(self) -> None:
        budget = TimeoutBudget(
            TimeoutPolicy(connect_seconds=10, read_seconds=30, total_seconds=300), FakeClock()
        )
        assert budget.attempt_timeouts() == (10, 30)

    def test_timeouts_are_clamped_to_what_remains(self) -> None:
        """A 30s read timeout is meaningless with 4s of budget left."""
        clock = FakeClock()
        budget = TimeoutBudget(
            TimeoutPolicy(connect_seconds=10, read_seconds=30, total_seconds=40), clock
        )
        clock.advance(36)
        assert budget.attempt_timeouts() == (4, 4)

    def test_raises_rather_than_returning_a_zero_timeout(self) -> None:
        """A zero timeout would be passed to the transport and fail confusingly."""
        clock = FakeClock()
        budget = TimeoutBudget(TimeoutPolicy(total_seconds=40), clock)
        clock.advance(40)
        with pytest.raises(TimeoutBudgetExhaustedError):
            budget.attempt_timeouts()


class TestCanAfford:
    def test_a_delay_shorter_than_the_remainder_fits(self) -> None:
        budget = TimeoutBudget(TimeoutPolicy(total_seconds=100), FakeClock())
        assert budget.can_afford(50)

    def test_a_delay_equal_to_the_remainder_does_not_fit(self) -> None:
        """Sleeping until the budget is exactly empty wastes the wait: nothing can follow it."""
        budget = TimeoutBudget(TimeoutPolicy(total_seconds=100), FakeClock())
        assert not budget.can_afford(100)

    def test_a_delay_longer_than_the_remainder_does_not_fit(self) -> None:
        budget = TimeoutBudget(TimeoutPolicy(total_seconds=100), FakeClock())
        assert not budget.can_afford(101)

    def test_a_negative_delay_is_a_programming_error(self) -> None:
        budget = TimeoutBudget(TimeoutPolicy(total_seconds=100), FakeClock())
        with pytest.raises(ValueError, match="must not be negative"):
            budget.can_afford(-1)


class TestRetryAfterParsing:
    """The header is attacker-controlled, so the corpus is adversarial."""

    def test_absent_header(self) -> None:
        assert parse_retry_after(None) is None

    @pytest.mark.parametrize("value", ["", "   ", "\t"])
    def test_blank_header(self, value: str) -> None:
        assert parse_retry_after(value) is None

    @pytest.mark.parametrize(("value", "expected"), [("5", 5.0), ("0", 0.0), ("120", 120.0)])
    def test_delay_seconds(self, value: str, expected: float) -> None:
        assert parse_retry_after(value) == expected

    def test_a_very_large_delay_is_parsed_not_capped(self) -> None:
        """Capping is the caller's decision, taken against its own budget."""
        assert parse_retry_after("99999999") == 99999999.0

    @pytest.mark.parametrize(
        "value",
        # RUF001: the ambiguous ARABIC-INDIC DIGIT FIVE is deliberate — it is the input
        # under test, and Python's `\d` plus float() would otherwise accept it as 5.
        ["-1", "-100", "abc", "5 seconds", "soon", "5.5", "+5", "0x10", "1e5", "٥"],  # noqa: RUF001
    )
    def test_malformed_values_are_treated_as_absent(self, value: str) -> None:
        """Rejected rather than coerced: a "-1" must not become a delay of any kind."""
        assert parse_retry_after(value) is None

    def test_http_date_in_the_future(self) -> None:
        now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
        header = "Thu, 01 Jan 2026 12:01:00 GMT"
        assert parse_retry_after(header, now=now) == pytest.approx(60.0)

    def test_http_date_in_the_past_yields_zero_not_a_negative_delay(self) -> None:
        now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
        header = "Thu, 01 Jan 2026 11:00:00 GMT"
        assert parse_retry_after(header, now=now) == 0.0

    def test_http_date_without_a_zone_is_treated_as_utc(self) -> None:
        now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
        assert parse_retry_after("Thu, 01 Jan 2026 12:00:30", now=now) == pytest.approx(30.0)

    def test_duplicate_headers_take_the_first_value(self) -> None:
        """Joined by comma when duplicated. A server must not lengthen its own hold by appending."""
        assert parse_retry_after("5, 600") == 5.0

    def test_a_comma_inside_an_http_date_is_not_a_separator(self) -> None:
        """ "Thu, 01 Jan..." contains a comma; splitting on it blindly would break the date."""
        now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
        assert parse_retry_after("Thu, 01 Jan 2026 12:00:10 GMT", now=now) == pytest.approx(10.0)

    def test_whitespace_is_tolerated(self) -> None:
        assert parse_retry_after("  30  ") == 30.0

    def test_a_malformed_date_is_treated_as_absent(self) -> None:
        assert parse_retry_after("Thu, 99 Xxx 2026 99:99:99 GMT") is None

    def test_the_reference_time_defaults_to_now(self) -> None:
        future = datetime.now(UTC) + timedelta(seconds=45)
        header = future.strftime("%a, %d %b %Y %H:%M:%S GMT")
        parsed = parse_retry_after(header)
        assert parsed is not None
        assert 0 <= parsed <= 46


class TestProductionImplementations:
    def test_monotonic_clock_advances(self) -> None:
        clock = MonotonicClock()
        assert clock.now() <= clock.now()

    def test_sleeper_ignores_non_positive_durations(self) -> None:
        """So a clamped-to-zero delay does not become a syscall."""
        SystemSleeper().sleep(0)
        SystemSleeper().sleep(-1)

    def test_random_source_stays_within_bounds(self) -> None:
        randomness = SystemRandomSource()
        for _ in range(100):
            assert 0.0 <= randomness.uniform(0.0, 5.0) <= 5.0
