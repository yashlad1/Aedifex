"""Tests for redirect policy.

Pure decisions, no network. The property that matters most: a followable decision returns a URL
and says it must be re-validated — it never confers permission. Validation of the first hop grants
nothing to later hops, because the second destination is chosen by the remote server.
"""

from __future__ import annotations

import pytest

from aedifex.acquisition.fetch.redirects import (
    REDIRECT_STATUSES,
    RedirectDecision,
    RedirectPolicy,
)
from aedifex.acquisition.fetch.urls import RejectionReason, SsrfRejectionError

CURRENT = "https://example.com/a/b"


def evaluate(
    location: str | None,
    *,
    status: int = 302,
    current: str = CURRENT,
    scheme: str = "https",
    history: tuple[str, ...] = (CURRENT,),
    policy: RedirectPolicy | None = None,
) -> RedirectDecision:
    return (policy or RedirectPolicy()).evaluate(
        status_code=status,
        location=location,
        current_url=current,
        current_scheme=scheme,
        history=history,
    )


class TestFollowableStatuses:
    @pytest.mark.parametrize("status", sorted(REDIRECT_STATUSES))
    def test_each_redirect_status_is_followable(self, status: int) -> None:
        assert evaluate("https://example.com/c", status=status).should_follow

    @pytest.mark.parametrize("status", [200, 204, 300, 400, 404, 500, 503])
    def test_non_redirect_statuses_are_not_followed(self, status: int) -> None:
        assert not evaluate("https://example.com/c", status=status).should_follow

    def test_300_is_excluded_deliberately(self) -> None:
        """Multiple Choices has no single canonical target; following it means guessing."""
        assert 300 not in REDIRECT_STATUSES
        assert not evaluate("https://example.com/c", status=300).should_follow

    def test_303_requests_a_method_rewrite(self) -> None:
        """A no-op today since only GET/HEAD are issued, but omitting it becomes a bug if POST
        is ever added."""
        assert evaluate("https://example.com/c", status=303).rewrite_method_to_get is True
        assert evaluate("https://example.com/c", status=307).rewrite_method_to_get is False


class TestMissingLocation:
    @pytest.mark.parametrize("location", [None, "", "   "])
    def test_a_redirect_without_a_target_is_rejected(self, location: str | None) -> None:
        """A broken response, not an invitation to guess."""
        decision = evaluate(location)
        assert not decision.should_follow
        assert "no Location" in decision.reason


class TestRelativeResolution:
    @pytest.mark.parametrize(
        ("location", "expected"),
        [
            ("/c", "https://example.com/c"),
            ("c", "https://example.com/a/c"),
            ("./c", "https://example.com/a/c"),
            ("../c", "https://example.com/c"),
            ("?x=1", "https://example.com/a/b?x=1"),
            ("https://example.com/abs", "https://example.com/abs"),
        ],
    )
    def test_relative_targets_resolve_against_the_current_url(
        self, location: str, expected: str
    ) -> None:
        """A relative Location must become a complete absolute URL before validation."""
        decision = evaluate(location)
        assert decision.should_follow
        assert decision.url == expected

    def test_a_cross_host_absolute_target_resolves_unchanged(self) -> None:
        decision = evaluate("https://other.test/x")
        assert decision.url == "https://other.test/x"

    def test_the_decision_states_that_re_validation_is_required(self) -> None:
        """The policy grants no permission; it yields a URL that must go back through the guard."""
        decision = evaluate("https://other.test/x")
        assert "re-validation" in decision.reason

    @pytest.mark.parametrize(
        "location",
        ["//other.test/x", "javascript:alert(1)", "mailto:a@b.test", "?", "#frag"],
    )
    def test_targets_that_cannot_become_absolute_http_urls(self, location: str) -> None:
        """Rejected here or by the guard; either way never followed.

        Scheme filtering is deliberately left to the guard rather than duplicated, so the rules
        cannot drift apart between two implementations.
        """
        decision = evaluate(location)
        if decision.should_follow:
            assert decision.url is not None
            assert decision.url.startswith(("http://", "https://"))

    @pytest.mark.parametrize(
        "location",
        ["https://x.test/\nHost: evil", "https://x.test/\r\nX: y", "https://x.test/\x00"],
    )
    def test_control_characters_are_rejected(self, location: str) -> None:
        """Header injection or a split response; never resolved."""
        decision = evaluate(location)
        assert not decision.should_follow
        assert "could not be resolved" in decision.reason


class TestHopLimit:
    def test_a_chain_within_the_limit_is_followed(self) -> None:
        history = tuple(f"https://example.com/{n}" for n in range(3))
        assert evaluate("https://example.com/next", history=history).should_follow

    def test_a_chain_at_the_limit_is_rejected(self) -> None:
        policy = RedirectPolicy(max_hops=3)
        history = tuple(f"https://example.com/{n}" for n in range(4))
        decision = evaluate("https://example.com/next", history=history, policy=policy)
        assert not decision.should_follow
        assert "exceeded 3 hops" in decision.reason

    def test_the_default_limit_is_five(self) -> None:
        assert RedirectPolicy().max_hops == 5

    def test_a_zero_hop_limit_is_rejected_at_construction(self) -> None:
        with pytest.raises(ValueError, match="at least 1"):
            RedirectPolicy(max_hops=0)


class TestLoopDetection:
    def test_a_target_already_visited_is_rejected(self) -> None:
        """Detected explicitly rather than left to the hop cap.

        Exhausting five hops around a two-URL cycle wastes time and reports the wrong reason.
        """
        history = ("https://example.com/a", "https://example.com/b")
        decision = evaluate("https://example.com/a", history=history)
        assert not decision.should_follow
        assert "loop" in decision.reason

    def test_self_redirect_is_a_loop(self) -> None:
        decision = evaluate(CURRENT, history=(CURRENT,))
        assert not decision.should_follow
        assert "loop" in decision.reason

    def test_loop_detection_uses_the_resolved_url(self) -> None:
        """A relative Location pointing back at a visited URL must still be caught."""
        decision = evaluate(
            "b", current="https://example.com/a/b", history=("https://example.com/a/b",)
        )
        assert not decision.should_follow
        assert "loop" in decision.reason


class TestTransportDowngrade:
    def test_https_to_http_is_rejected_by_default(self) -> None:
        """Evidence fetched over a tamperable channel is weak evidence."""
        decision = evaluate("http://example.com/c", scheme="https")
        assert not decision.should_follow
        assert "downgrades transport" in decision.reason
        assert "allow_insecure_transport" in decision.reason

    def test_https_to_http_is_allowed_when_the_source_accepted_it(self) -> None:
        """Permission comes from the registry, never from an HTTP library's default."""
        policy = RedirectPolicy(allow_transport_downgrade=True)
        assert evaluate("http://example.com/c", scheme="https", policy=policy).should_follow

    def test_http_to_https_is_always_allowed(self) -> None:
        """An upgrade needs no permission."""
        assert evaluate(
            "https://example.com/c", current="http://example.com/a/b", scheme="http"
        ).should_follow

    def test_https_to_https_is_allowed(self) -> None:
        assert evaluate("https://other.test/c", scheme="https").should_follow

    def test_http_to_http_is_allowed(self) -> None:
        """The source already accepted plain HTTP to be here at all."""
        assert evaluate(
            "http://other.test/c", current="http://example.com/a", scheme="http"
        ).should_follow

    def test_the_downgrade_check_is_case_insensitive(self) -> None:
        assert not evaluate("HTTP://example.com/c", scheme="HTTPS").should_follow


class TestAssertCanFollow:
    def test_returns_the_url_when_following(self) -> None:
        policy = RedirectPolicy()
        decision = evaluate("https://example.com/c")
        assert policy.assert_can_follow(decision) == "https://example.com/c"

    def test_raises_a_typed_rejection_for_a_loop(self) -> None:
        policy = RedirectPolicy()
        decision = evaluate("https://example.com/a", history=("https://example.com/a",))
        with pytest.raises(SsrfRejectionError) as error:
            policy.assert_can_follow(decision)
        assert error.value.reason is RejectionReason.REDIRECT_LOOP

    def test_raises_a_typed_rejection_for_too_many_hops(self) -> None:
        policy = RedirectPolicy(max_hops=1)
        history = ("https://example.com/a", "https://example.com/b")
        decision = evaluate("https://example.com/c", history=history, policy=policy)
        with pytest.raises(SsrfRejectionError) as error:
            policy.assert_can_follow(decision)
        assert error.value.reason is RejectionReason.TOO_MANY_REDIRECTS

    def test_raises_for_a_missing_location(self) -> None:
        policy = RedirectPolicy()
        with pytest.raises(SsrfRejectionError):
            policy.assert_can_follow(evaluate(None))


class TestImmutability:
    def test_the_policy_is_immutable(self) -> None:
        policy = RedirectPolicy()
        with pytest.raises(AttributeError):
            policy.max_hops = 100  # type: ignore[misc]

    def test_a_decision_is_immutable(self) -> None:
        decision = evaluate("https://example.com/c")
        with pytest.raises(AttributeError):
            # mypy correctly rejects this; the point is that it also fails at runtime, so a
            # validated-and-refused target cannot be edited into a followable one.
            decision.url = "https://evil.test/"  # type: ignore[misc]

    def test_a_rejecting_decision_carries_no_url(self) -> None:
        """So a caller cannot accidentally use a target that was refused."""
        assert evaluate("http://example.com/c", scheme="https").url is None
        assert evaluate(None).url is None
        assert evaluate("https://example.com/c", status=200).url is None
