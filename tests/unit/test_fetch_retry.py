"""Tests for retry classification.

The policy is pure, so every case is decidable without a server, a clock, or a sleep. Randomness is
injected, so a jittered delay is an exact expected value rather than a range.

Each status in the retryable and non-retryable sets is asserted individually. A table-level
assertion ("all 5xx retry") would hide precisely the distinctions the policy exists to make.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from aedifex.acquisition.fetch.retry import (
    NON_RETRYABLE_STATUSES,
    RETRYABLE_STATUSES,
    AttemptOutcome,
    AttemptResult,
    BackoffPolicy,
    RetryDecision,
    RetryPolicy,
    RetryVerdict,
)


class FixedRandom:
    """Returns a fixed fraction of the interval, so jitter is exact in tests."""

    def __init__(self, fraction: float = 1.0) -> None:
        self.fraction = fraction
        self.calls: list[tuple[float, float]] = []

    def uniform(self, low: float, high: float) -> float:
        self.calls.append((low, high))
        return low + (high - low) * self.fraction


def classify(
    outcome: AttemptOutcome,
    *,
    attempt: int = 1,
    status: int | None = None,
    retry_after: float | None = None,
    policy: RetryPolicy | None = None,
    fraction: float = 1.0,
    remaining: float | None = None,
) -> RetryDecision:
    return (policy or RetryPolicy()).classify(
        AttemptResult(
            outcome=outcome,
            attempt=attempt,
            status_code=status,
            retry_after_seconds=retry_after,
        ),
        randomness=FixedRandom(fraction),
        remaining_budget_seconds=remaining,
    )


class TestAttemptResultValidation:
    def test_attempt_is_one_based(self) -> None:
        with pytest.raises(ValueError, match="1-based"):
            AttemptResult(outcome=AttemptOutcome.SUCCESS, attempt=0)

    def test_an_http_status_outcome_requires_a_status_code(self) -> None:
        """Otherwise the policy would have to guess, and would fail closed on a real response."""
        with pytest.raises(ValueError, match="requires a status_code"):
            AttemptResult(outcome=AttemptOutcome.HTTP_STATUS, attempt=1)

    def test_is_immutable(self) -> None:
        result = AttemptResult(outcome=AttemptOutcome.SUCCESS, attempt=1)
        with pytest.raises(AttributeError):
            result.attempt = 2  # type: ignore[misc]


class TestSuccess:
    def test_success_is_not_retried(self) -> None:
        decision = classify(AttemptOutcome.SUCCESS)
        assert decision.verdict is RetryVerdict.DO_NOT_RETRY
        assert not decision.should_retry
        assert decision.delay_seconds == 0


class TestRetryableStatuses:
    @pytest.mark.parametrize("status", sorted(RETRYABLE_STATUSES))
    def test_each_retryable_status(self, status: int) -> None:
        decision = classify(AttemptOutcome.HTTP_STATUS, status=status)
        assert decision.should_retry, f"HTTP {status} should retry"

    def test_500_is_retried_deliberately(self) -> None:
        """A judgement, not an oversight: portals return 500 for transient overload, and these
        are idempotent GETs. The risk of hammering a broken endpoint is bounded by the attempt
        cap and per-source rate limiting rather than by refusing to retry."""
        assert classify(AttemptOutcome.HTTP_STATUS, status=500).should_retry

    def test_429_is_retried(self) -> None:
        assert classify(AttemptOutcome.HTTP_STATUS, status=429).should_retry

    def test_408_and_425_are_retried(self) -> None:
        assert classify(AttemptOutcome.HTTP_STATUS, status=408).should_retry
        assert classify(AttemptOutcome.HTTP_STATUS, status=425).should_retry


class TestNonRetryableStatuses:
    @pytest.mark.parametrize("status", sorted(NON_RETRYABLE_STATUSES))
    def test_each_non_retryable_status(self, status: int) -> None:
        decision = classify(AttemptOutcome.HTTP_STATUS, status=status)
        assert not decision.should_retry, f"HTTP {status} should not retry"

    def test_403_is_not_retried(self) -> None:
        """Retrying a 403 is what gets a crawler blocked."""
        decision = classify(AttemptOutcome.HTTP_STATUS, status=403)
        assert not decision.should_retry
        assert "permanent" in decision.reason

    def test_501_is_not_retried_despite_being_5xx(self) -> None:
        """The reason the retryable set is enumerated rather than derived from status class."""
        assert 501 in NON_RETRYABLE_STATUSES
        assert not classify(AttemptOutcome.HTTP_STATUS, status=501).should_retry


class TestUnknownStatuses:
    @pytest.mark.parametrize("status", [418, 299, 600, 100, 226, 507])
    def test_an_unfamiliar_status_fails_closed(self, status: int) -> None:
        """No policy means no retry. Retrying something we have no rule for risks hammering."""
        decision = classify(AttemptOutcome.HTTP_STATUS, status=status)
        assert not decision.should_retry
        assert "no retry policy" in decision.reason

    def test_the_two_status_sets_do_not_overlap(self) -> None:
        assert not (RETRYABLE_STATUSES & NON_RETRYABLE_STATUSES)


class TestTransportOutcomes:
    @pytest.mark.parametrize(
        "outcome",
        [
            AttemptOutcome.CONNECT_TIMEOUT,
            AttemptOutcome.READ_TIMEOUT,
            AttemptOutcome.CONNECTION_ERROR,
        ],
    )
    def test_transient_transport_failures_are_retried(self, outcome: AttemptOutcome) -> None:
        assert classify(outcome).should_retry

    def test_a_tls_failure_is_not_retried(self) -> None:
        """A certificate that did not verify means a misconfigured server or an interception
        attempt. Neither improves on a retry, and retrying would normalise it."""
        decision = classify(AttemptOutcome.TLS_ERROR)
        assert not decision.should_retry
        assert "decision" in decision.reason

    def test_a_dns_error_is_not_retried(self) -> None:
        """DNS is resolved once by the guard before any attempt, so this means the guard refused."""
        assert not classify(AttemptOutcome.DNS_ERROR).should_retry


class TestDecisionsAreNeverRetried:
    @pytest.mark.parametrize(
        "outcome",
        [
            AttemptOutcome.SSRF_REJECTED,
            AttemptOutcome.UNSAFE_CONTENT,
            AttemptOutcome.OVERSIZED_RESPONSE,
            AttemptOutcome.INVALID_REDIRECT,
            AttemptOutcome.CANCELLED,
            AttemptOutcome.BUDGET_EXHAUSTED,
        ],
    )
    def test_never_retried(self, outcome: AttemptOutcome) -> None:
        """Each represents a decision. Retrying a decision makes the same decision again."""
        decision = classify(outcome)
        assert not decision.should_retry
        assert decision.delay_seconds == 0

    def test_an_ssrf_rejection_is_not_retried_even_with_a_retry_after(self) -> None:
        """A hostile server must not be able to convert a refusal into a retry loop."""
        decision = classify(AttemptOutcome.SSRF_REJECTED, retry_after=1.0)
        assert not decision.should_retry


class TestAttemptCap:
    def test_the_final_attempt_is_not_retried(self) -> None:
        policy = RetryPolicy(backoff=BackoffPolicy(max_attempts=5))
        assert classify(
            AttemptOutcome.HTTP_STATUS, status=503, attempt=4, policy=policy
        ).should_retry
        decision = classify(AttemptOutcome.HTTP_STATUS, status=503, attempt=5, policy=policy)
        assert not decision.should_retry
        assert "limit of 5" in decision.reason

    def test_an_attempt_beyond_the_cap_is_not_retried(self) -> None:
        policy = RetryPolicy(backoff=BackoffPolicy(max_attempts=3))
        assert not classify(
            AttemptOutcome.HTTP_STATUS, status=503, attempt=9, policy=policy
        ).should_retry

    def test_the_cap_applies_before_the_status_check(self) -> None:
        """So an exhausted retry budget reports exhaustion rather than a status reason."""
        policy = RetryPolicy(backoff=BackoffPolicy(max_attempts=1))
        decision = classify(AttemptOutcome.HTTP_STATUS, status=503, attempt=1, policy=policy)
        assert "limit" in decision.reason


class TestBackoff:
    def test_ceilings_grow_exponentially(self) -> None:
        backoff = BackoffPolicy(base_seconds=1, factor=2, max_delay_seconds=60)
        assert [backoff.ceiling_for(n) for n in (1, 2, 3, 4, 5)] == [1, 2, 4, 8, 16]

    def test_ceilings_are_capped(self) -> None:
        backoff = BackoffPolicy(base_seconds=1, factor=2, max_delay_seconds=10)
        assert backoff.ceiling_for(10) == 10

    def test_full_jitter_spans_the_whole_interval(self) -> None:
        """Full jitter, not equal jitter: half-width jitter leaves workers clustered."""
        backoff = BackoffPolicy(base_seconds=1, factor=2)
        randomness = FixedRandom(0.5)
        backoff.delay_for(3, randomness)
        assert randomness.calls == [(0.0, 4.0)]

    def test_jitter_can_produce_zero(self) -> None:
        assert BackoffPolicy().delay_for(1, FixedRandom(0.0)) == 0.0

    def test_jitter_can_produce_the_ceiling(self) -> None:
        assert BackoffPolicy(base_seconds=2).delay_for(1, FixedRandom(1.0)) == 2.0

    @pytest.mark.parametrize(
        "construct",
        [
            lambda: BackoffPolicy(base_seconds=0),
            lambda: BackoffPolicy(base_seconds=-1),
            lambda: BackoffPolicy(factor=0.5),
            lambda: BackoffPolicy(max_delay_seconds=0.1),
            lambda: BackoffPolicy(max_attempts=0),
        ],
        ids=["zero-base", "negative-base", "factor-below-one", "cap-below-base", "zero-attempts"],
    )
    def test_invalid_parameters_are_rejected(self, construct: Callable[[], BackoffPolicy]) -> None:
        """Constructed via callables so each case stays type-checked rather than **kwargs."""
        with pytest.raises(ValueError):
            construct()

    def test_attempt_must_be_one_based(self) -> None:
        with pytest.raises(ValueError, match="1-based"):
            BackoffPolicy().ceiling_for(0)

    def test_the_delay_is_reported_on_the_decision(self) -> None:
        decision = classify(AttemptOutcome.HTTP_STATUS, status=503, attempt=2, fraction=1.0)
        assert decision.verdict is RetryVerdict.RETRY
        assert decision.delay_seconds == 2.0


class TestRetryAfterHandling:
    def test_a_server_delay_overrides_computed_backoff(self) -> None:
        decision = classify(AttemptOutcome.HTTP_STATUS, status=429, retry_after=7.5)
        assert decision.verdict is RetryVerdict.RETRY_AFTER
        assert decision.delay_seconds == 7.5
        assert "Retry-After" in decision.reason

    def test_a_zero_delay_is_honoured_as_immediate(self) -> None:
        decision = classify(AttemptOutcome.HTTP_STATUS, status=429, retry_after=0.0)
        assert decision.verdict is RetryVerdict.RETRY_AFTER
        assert decision.delay_seconds == 0.0

    def test_a_delay_over_the_cap_abandons_rather_than_sleeping(self) -> None:
        """A server asking for hours is saying "come back much later".

        Clamping down to the cap and sleeping would hold a worker and a connection slot for the
        full cap while ignoring what the server actually asked — so the request is abandoned.
        """
        decision = classify(AttemptOutcome.HTTP_STATUS, status=503, retry_after=86400.0)
        assert not decision.should_retry
        assert "over the" in decision.reason
        assert decision.delay_seconds == 0

    def test_the_cap_boundary(self) -> None:
        policy = RetryPolicy(max_server_requested_delay_seconds=300)
        assert classify(
            AttemptOutcome.HTTP_STATUS, status=503, retry_after=300.0, policy=policy
        ).should_retry
        assert not classify(
            AttemptOutcome.HTTP_STATUS, status=503, retry_after=300.1, policy=policy
        ).should_retry

    def test_a_retry_after_on_a_non_retryable_status_is_ignored(self) -> None:
        """A server cannot make a 404 retryable by attaching a header."""
        assert not classify(AttemptOutcome.HTTP_STATUS, status=404, retry_after=1.0).should_retry


class TestBudgetInteraction:
    def test_a_delay_that_does_not_fit_the_budget_abandons(self) -> None:
        """Sleeping past the budget wastes the wait: the retry it prepared for cannot happen."""
        decision = classify(
            AttemptOutcome.HTTP_STATUS, status=503, retry_after=30.0, remaining=10.0
        )
        assert not decision.should_retry
        assert "does not fit" in decision.reason

    def test_a_delay_that_fits_is_allowed(self) -> None:
        decision = classify(AttemptOutcome.HTTP_STATUS, status=503, retry_after=5.0, remaining=60.0)
        assert decision.should_retry

    def test_a_delay_exactly_equal_to_the_remainder_does_not_fit(self) -> None:
        decision = classify(
            AttemptOutcome.HTTP_STATUS, status=503, retry_after=10.0, remaining=10.0
        )
        assert not decision.should_retry

    def test_the_budget_check_is_optional(self) -> None:
        """The policy stays usable by a caller that tracks time elsewhere."""
        assert classify(AttemptOutcome.HTTP_STATUS, status=503, remaining=None).should_retry


class TestPurity:
    def test_classifying_performs_no_sleep_and_no_io(self) -> None:
        """Enforced by construction: the policy is handed randomness and a number, nothing else.

        If it could sleep or open a socket, its edge cases could not be exhaustively tested, which
        is the entire reason it is separated from the retry loop.
        """
        randomness = FixedRandom()
        policy = RetryPolicy()
        for _ in range(3):
            policy.classify(
                AttemptResult(outcome=AttemptOutcome.HTTP_STATUS, attempt=1, status_code=503),
                randomness=randomness,
            )
        assert len(randomness.calls) == 3

    def test_the_same_inputs_produce_the_same_decision(self) -> None:
        first = classify(AttemptOutcome.HTTP_STATUS, status=503, attempt=2, fraction=0.5)
        second = classify(AttemptOutcome.HTTP_STATUS, status=503, attempt=2, fraction=0.5)
        assert first == second

    def test_the_policy_is_immutable(self) -> None:
        policy = RetryPolicy()
        with pytest.raises(AttributeError):
            policy.backoff = BackoffPolicy()  # type: ignore[misc]
