"""Redirect controller tests.

The property under test is a security property, and it is stated in one sentence: **a redirect
cannot reach a destination that the first URL could not have reached.** Everything else here is in
service of proving that, from several directions at once.

So the tests are built on two recording fakes rather than a live server:

* :class:`MappingResolver` scripts DNS and writes down every lookup. That is what makes "the
  redirect target was resolved and then refused" distinguishable from "it was refused before DNS",
  which matters because the two failures live at different points in the validation order.
* :class:`ScriptedTransport` writes down every URL, method, and header set it was asked for. The
  central assertion of the security tests is a *negative* one — the transport was never asked for
  the forbidden target — and a negative claim about a call that must not happen can only be checked
  by something that records the calls that did.

A live server cannot be made to answer ``302 Location: https://169.254.169.254/`` on demand, and a
mock that only checks "an exception was raised" would pass even if the request had already been
sent. Recording is what turns these from assertions about error types into assertions about
behaviour.

Nothing sleeps and nothing waits: the clock is injected and the sleeper advances it.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass, field
from ipaddress import ip_address

import pytest

from aedifex.acquisition.fetch.controller import FetchFailedError, RetryController
from aedifex.acquisition.fetch.guard import ValidatedTarget
from aedifex.acquisition.fetch.hosts import SourceHostPolicy
from aedifex.acquisition.fetch.ratelimit import RateLimiter, RateLimits
from aedifex.acquisition.fetch.redirect_controller import (
    ChainResult,
    RedirectController,
    RedirectHop,
    RedirectRejectedError,
    _crosses_host,
)
from aedifex.acquisition.fetch.redirects import RedirectPolicy
from aedifex.acquisition.fetch.resolver import ResolvedAddress
from aedifex.acquisition.fetch.retry import AttemptOutcome, BackoffPolicy, RetryPolicy
from aedifex.acquisition.fetch.timing import TimeoutBudget, TimeoutPolicy
from aedifex.acquisition.fetch.transport import (
    ConnectionFailedError,
    RawResponse,
    ResponseHeaders,
    TransportTimeouts,
)

# The source may be fetched from its own domain and its subdomains, plus one CDN host by exact
# match. Both halves of the asymmetry matter below.
HOSTS = SourceHostPolicy(
    source_id="cpwd",
    base_hosts=frozenset({"cpwd.test"}),
    exact_hosts=frozenset({"cdn.example.test"}),
)

FAST_LIMITS = RateLimits(requests_per_minute=600, max_concurrency=4, min_delay_seconds=0.0)

# A caller-supplied header, so "was it carried across a host change?" is a question with an
# observable answer.
TRACE: Mapping[str, str] = {"X-Aedifex-Trace": "abc123"}

PUBLIC = "93.184.216.34"

# Scripted DNS. The forbidden entries are the point: each is a hostname the *host policy* permits,
# which resolves to an address the *address policy* forbids. That combination is the real SSRF
# vector — an allowlisted name is not a safe destination, only a permitted one.
DNS: Mapping[str, tuple[str, ...]] = {
    "cpwd.test": (PUBLIC,),
    "docs.cpwd.test": (PUBLIC,),
    "static.cpwd.test": (PUBLIC,),
    "cdn.example.test": (PUBLIC,),
    # Resolvable, and deliberately not permitted: the refusal must come from policy, not from a
    # failed lookup, or the test would pass for the wrong reason.
    "evilcpwd.test": (PUBLIC,),
    "other.example.test": (PUBLIC,),
    "files.cdn.example.test": (PUBLIC,),
    "evil.test": (PUBLIC,),
    # Permitted names, forbidden addresses.
    "metadata.cpwd.test": ("169.254.169.254",),
    "loopback.cpwd.test": ("127.0.0.1",),
    "private.cpwd.test": ("10.0.0.5",),
    "cgnat.cpwd.test": ("100.64.1.1",),
    "sixloopback.cpwd.test": ("::1",),
    # One good address and one bad one. The whole answer must be refused, not filtered.
    "mixed.cpwd.test": (PUBLIC, "10.0.0.5"),
}


class MappingResolver:
    """Scripted DNS that records every lookup.

    An unmapped host raises rather than returning nothing, so a typo in a test hostname fails
    loudly instead of quietly becoming an unresolvable-host rejection that looks like a pass.
    """

    def __init__(self, mapping: Mapping[str, tuple[str, ...]]) -> None:
        self._mapping = mapping
        self.lookups: list[str] = []

    def resolve(self, hostname: str, port: int) -> Sequence[ResolvedAddress]:
        self.lookups.append(hostname)
        answers = self._mapping.get(hostname)
        if answers is None:
            raise OSError(f"no scripted DNS entry for {hostname!r}")
        return tuple(ResolvedAddress(ip=ip_address(answer), port=port) for answer in answers)


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
    """Jitter with the randomness removed, so backoff assertions are exact."""

    def uniform(self, low: float, high: float) -> float:
        return high


@dataclass
class Step:
    """One scripted response: a status, or an exception raised instead of answering."""

    status: int = 200
    headers: tuple[tuple[str, str], ...] = ()
    error: Exception | None = None
    takes_seconds: float = 0.0


def redirect(location: str, *, status: int = 302, takes_seconds: float = 0.0) -> Step:
    return Step(status=status, headers=(("Location", location),), takes_seconds=takes_seconds)


@dataclass(frozen=True)
class Request:
    """What the transport was asked to do, as evidence rather than as a mock expectation."""

    url: str
    method: str
    headers: Mapping[str, str] | None
    hostname: str
    ip: str


class ScriptedTransport:
    """Plays a scripted sequence, recording every request it was asked to make."""

    def __init__(self, script: list[Step], *, clock: FakeClock) -> None:
        self._script = script
        self._clock = clock
        self.requests: list[Request] = []
        self.timeouts_seen: list[TransportTimeouts] = []
        self.closed = 0

    @property
    def urls(self) -> list[str]:
        return [request.url for request in self.requests]

    @property
    def methods(self) -> list[str]:
        return [request.method for request in self.requests]

    @property
    def header_sets(self) -> list[Mapping[str, str] | None]:
        return [request.headers for request in self.requests]

    @contextmanager
    def open(
        self,
        target: ValidatedTarget,
        *,
        timeouts: TransportTimeouts,
        method: str = "GET",
        headers: Mapping[str, str] | None = None,
        max_response_bytes: int = 1024,
        body: bytes | None = None,
    ) -> Iterator[RawResponse]:
        index = len(self.requests)
        self.requests.append(
            Request(
                url=target.url,
                method=method,
                headers=dict(headers) if headers is not None else None,
                hostname=target.hostname,
                ip=str(target.ip_address),
            )
        )
        self.timeouts_seen.append(timeouts)
        if index >= len(self._script):
            raise AssertionError(
                f"transport called {index + 1} times for {target.url}; "
                f"the script has {len(self._script)} step(s)"
            )
        step = self._script[index]
        self._clock.advance(step.takes_seconds)
        if step.error is not None:
            raise step.error

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


class CountingLimiter(RateLimiter):
    """A real limiter that also counts how many slots were taken, and for whom."""

    def __init__(self, taken: list[str], **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self._taken = taken

    @contextmanager
    def slot(
        self,
        source_id: str,
        limits: RateLimits,
        *,
        deadline: object = None,
    ) -> Iterator[None]:
        self._taken.append(source_id)
        with super().slot(source_id, limits, deadline=deadline):  # type: ignore[arg-type]
            yield


@dataclass
class Harness:
    controller: RedirectController
    transport: ScriptedTransport
    resolver: MappingResolver
    clock: FakeClock
    sleeper: FakeSleeper
    slots_taken: list[str]

    def fetch(
        self,
        url: str,
        *,
        total: float = 300.0,
        limits: RateLimits = FAST_LIMITS,
        method: str = "GET",
        headers: Mapping[str, str] | None = None,
    ) -> AbstractContextManager[ChainResult]:
        budget = TimeoutBudget(
            policy=TimeoutPolicy(connect_seconds=10.0, read_seconds=30.0, total_seconds=total),
            clock=self.clock,
        )
        return self.controller.fetch(
            url,
            host_policy=HOSTS,
            limits=limits,
            budget=budget,
            method=method,
            headers=headers,
        )


def harness(
    script: list[Step],
    *,
    policy: RedirectPolicy | None = None,
    max_attempts: int = 5,
    dns: Mapping[str, tuple[str, ...]] | None = None,
) -> Harness:
    clock = FakeClock()
    sleeper = FakeSleeper(clock)
    resolver = MappingResolver(dns if dns is not None else DNS)
    transport = ScriptedTransport(script, clock=clock)
    slots_taken: list[str] = []
    limiter = CountingLimiter(slots_taken, global_concurrency=4, clock=clock, sleeper=sleeper)
    retry_controller = RetryController(
        transport=transport,
        limiter=limiter,
        policy=RetryPolicy(backoff=BackoffPolicy(max_attempts=max_attempts)),
        randomness=FixedRandom(),
        clock=clock,
        sleeper=sleeper,
    )
    controller = RedirectController(controller=retry_controller, resolver=resolver, policy=policy)
    return Harness(controller, transport, resolver, clock, sleeper, slots_taken)


# ---------------------------------------------------------------------------
# The first URL is not special
# ---------------------------------------------------------------------------


class TestTheFirstUrlIsValidatedToo:
    """One validation path, used by every hop including the first.

    A design where the caller validates the initial URL and the controller validates the rest has
    two paths where it needs one, and the forgotten one is the one that gets used.
    """

    def test_an_off_allowlist_first_url_never_reaches_the_transport(self) -> None:
        h = harness([Step(status=200)])
        with (
            pytest.raises(RedirectRejectedError) as caught,
            h.fetch("https://other.example.test/tender.pdf"),
        ):
            pass

        assert caught.value.final_outcome is AttemptOutcome.SSRF_REJECTED
        assert caught.value.chain == ()
        assert h.transport.requests == []

    def test_an_ip_literal_first_url_is_refused_without_dns(self) -> None:
        h = harness([Step(status=200)])
        with (
            pytest.raises(RedirectRejectedError) as caught,
            h.fetch("https://169.254.169.254/latest/meta-data/"),
        ):
            pass

        assert caught.value.final_outcome is AttemptOutcome.SSRF_REJECTED
        assert h.resolver.lookups == []
        assert h.transport.requests == []

    def test_a_permitted_first_url_is_fetched_and_reported_as_unredirected(self) -> None:
        h = harness([Step(status=200)])
        with h.fetch("https://cpwd.test/tender.pdf") as result:
            assert isinstance(result, ChainResult)
            assert result.response.status_code == 200
            assert b"".join(result.response.iter_bytes()) == b"payload"

        assert result.requested_url == "https://cpwd.test/tender.pdf"
        assert result.final_url == "https://cpwd.test/tender.pdf"
        assert result.was_redirected is False
        assert result.hop_count == 0
        assert [hop.status_code for hop in result.chain] == [200]
        assert result.chain[0].location is None

    def test_the_response_is_closed_when_the_caller_finishes(self) -> None:
        h = harness([Step(status=200)])
        with h.fetch("https://cpwd.test/a"):
            assert h.transport.closed == 0
        assert h.transport.closed == 1


# ---------------------------------------------------------------------------
# Security: every hop re-enters the gate
# ---------------------------------------------------------------------------


class TestEveryHopIsRevalidated:
    """FR-111. The redirect target is chosen by a remote server, so it is untrusted input."""

    @pytest.mark.parametrize(
        ("host", "address"),
        [
            ("metadata.cpwd.test", "169.254.169.254"),
            ("loopback.cpwd.test", "127.0.0.1"),
            ("private.cpwd.test", "10.0.0.5"),
            ("cgnat.cpwd.test", "100.64.1.1"),
            ("sixloopback.cpwd.test", "::1"),
            ("mixed.cpwd.test", "10.0.0.5"),
        ],
    )
    def test_a_permitted_name_resolving_to_a_forbidden_address_is_refused(
        self, host: str, address: str
    ) -> None:
        """The vector that matters: the allowlist says yes, the address policy says no.

        Every one of these hostnames is a subdomain of the source's own domain, so the host policy
        permits it. What refuses it is address classification, after resolution — which is only
        reached because the hop was re-validated rather than followed.
        """
        h = harness([redirect(f"https://{host}/x"), Step(status=200)])
        with (
            pytest.raises(RedirectRejectedError) as caught,
            h.fetch("https://cpwd.test/tender.pdf"),
        ):
            pass

        assert caught.value.final_outcome is AttemptOutcome.SSRF_REJECTED
        # Resolved, then refused: the lookup proves validation ran on the redirect target.
        assert h.resolver.lookups == ["cpwd.test", host]
        assert address in str(caught.value)
        # The assertion this whole file exists for.
        assert h.transport.urls == ["https://cpwd.test/tender.pdf"]

    @pytest.mark.parametrize(
        "target",
        [
            "https://169.254.169.254/latest/meta-data/",
            "https://127.0.0.1/admin",
            "https://10.0.0.5/",
            "https://100.64.1.1/",
            "https://[::1]/",
        ],
    )
    def test_a_redirect_to_an_address_literal_is_refused(self, target: str) -> None:
        """An address cannot satisfy a hostname allowlist, so it is refused before classification.

        ``https`` throughout on purpose: the plain-``http`` form of these would be caught by the
        downgrade rule first, and a test that passes for a different reason than it claims is worse
        than no test.
        """
        h = harness([redirect(target), Step(status=200)])
        with (
            pytest.raises(RedirectRejectedError) as caught,
            h.fetch("https://cpwd.test/tender.pdf"),
        ):
            pass

        assert caught.value.final_outcome is AttemptOutcome.SSRF_REJECTED
        assert h.resolver.lookups == ["cpwd.test"], "an address literal was sent to DNS"
        assert h.transport.urls == ["https://cpwd.test/tender.pdf"]

    def test_a_metadata_redirect_over_plain_http_is_also_refused(self) -> None:
        """Same destination, different rule. Either way it must not be contacted."""
        h = harness([redirect("http://169.254.169.254/latest/meta-data/"), Step(status=200)])
        with (
            pytest.raises(RedirectRejectedError) as caught,
            h.fetch("https://cpwd.test/tender.pdf"),
        ):
            pass

        assert caught.value.final_outcome is AttemptOutcome.INVALID_REDIRECT
        assert h.transport.urls == ["https://cpwd.test/tender.pdf"]

    def test_a_redirect_off_the_allowlist_is_refused_before_dns(self) -> None:
        """The host policy is checked first, so an unpermitted host is never even looked up."""
        h = harness([redirect("https://other.example.test/x"), Step(status=200)])
        with (
            pytest.raises(RedirectRejectedError) as caught,
            h.fetch("https://cpwd.test/tender.pdf"),
        ):
            pass

        assert caught.value.final_outcome is AttemptOutcome.SSRF_REJECTED
        assert "not permitted for source 'cpwd'" in str(caught.value)
        assert h.resolver.lookups == ["cpwd.test"]
        assert h.transport.urls == ["https://cpwd.test/tender.pdf"]

    def test_a_lookalike_host_is_refused(self) -> None:
        """``evilcpwd.test`` ends with ``cpwd.test``. Suffix matching would have allowed it.

        This is the case a naive ``host.endswith(base)`` gets wrong, and it is why the allowlist is
        DNS-label-aware. The host resolves perfectly well in the scripted DNS, so nothing but the
        policy stands between the redirect and the connection.
        """
        h = harness([redirect("https://evilcpwd.test/x"), Step(status=200)])
        with (
            pytest.raises(RedirectRejectedError) as caught,
            h.fetch("https://cpwd.test/tender.pdf"),
        ):
            pass

        assert caught.value.final_outcome is AttemptOutcome.SSRF_REJECTED
        assert h.transport.urls == ["https://cpwd.test/tender.pdf"]

    def test_credentials_in_a_redirect_target_are_refused(self) -> None:
        """``https://cpwd.test@evil.test/`` contacts ``evil.test`` while reading as the other."""
        h = harness([redirect("https://cpwd.test@evil.test/x"), Step(status=200)])
        with (
            pytest.raises(RedirectRejectedError) as caught,
            h.fetch("https://cpwd.test/tender.pdf"),
        ):
            pass

        assert caught.value.final_outcome is AttemptOutcome.SSRF_REJECTED
        assert "credentials" in str(caught.value)
        assert h.transport.urls == ["https://cpwd.test/tender.pdf"]

    def test_a_subdomain_of_the_source_domain_is_permitted(self) -> None:
        h = harness([redirect("https://docs.cpwd.test/a.pdf"), Step(status=200)])
        with h.fetch("https://cpwd.test/tender.pdf") as result:
            assert result.response.status_code == 200
        assert h.transport.urls == ["https://cpwd.test/tender.pdf", "https://docs.cpwd.test/a.pdf"]

    def test_an_exactly_declared_additional_host_is_permitted(self) -> None:
        h = harness([redirect("https://cdn.example.test/a.pdf"), Step(status=200)])
        with h.fetch("https://cpwd.test/tender.pdf") as result:
            assert result.final_url == "https://cdn.example.test/a.pdf"

    def test_a_subdomain_of_an_additional_host_is_refused(self) -> None:
        """An additional host is an exact match only: one CDN entry must not authorise every tenant.

        A shared object-storage domain is the case that makes this matter — permitting subdomains of
        it would authorise every other bucket on the same provider.
        """
        h = harness([redirect("https://files.cdn.example.test/a.pdf"), Step(status=200)])
        with (
            pytest.raises(RedirectRejectedError) as caught,
            h.fetch("https://cpwd.test/tender.pdf"),
        ):
            pass

        assert caught.value.final_outcome is AttemptOutcome.SSRF_REJECTED
        assert h.transport.urls == ["https://cpwd.test/tender.pdf"]

    def test_a_late_hop_is_validated_as_strictly_as_the_first(self) -> None:
        """Two legitimate hops earn no credit for the third.

        The failure mode this rules out is a controller that validates while it is being careful and
        then trusts the chain once it looks established.
        """
        h = harness(
            [
                redirect("https://docs.cpwd.test/a"),
                redirect("https://static.cpwd.test/b"),
                redirect("https://metadata.cpwd.test/c"),
                Step(status=200),
            ]
        )
        with (
            pytest.raises(RedirectRejectedError) as caught,
            h.fetch("https://cpwd.test/tender.pdf"),
        ):
            pass

        assert caught.value.final_outcome is AttemptOutcome.SSRF_REJECTED
        assert len(caught.value.chain) == 3
        assert h.transport.urls == [
            "https://cpwd.test/tender.pdf",
            "https://docs.cpwd.test/a",
            "https://static.cpwd.test/b",
        ]


# ---------------------------------------------------------------------------
# Redirect mechanics
# ---------------------------------------------------------------------------


class TestRelativeResolution:
    def test_a_relative_location_resolves_against_the_url_that_sent_it(self) -> None:
        h = harness([redirect("report.pdf"), Step(status=200)])
        with h.fetch("https://cpwd.test/docs/tender.html") as result:
            assert result.final_url == "https://cpwd.test/docs/report.pdf"

    def test_a_root_relative_location_resolves_against_the_authority(self) -> None:
        h = harness([redirect("/files/a.pdf"), Step(status=200)])
        with h.fetch("https://cpwd.test/docs/tender.html") as result:
            assert result.final_url == "https://cpwd.test/files/a.pdf"

    def test_a_scheme_relative_location_keeps_the_current_scheme(self) -> None:
        h = harness([redirect("//docs.cpwd.test/a.pdf"), Step(status=200)])
        with h.fetch("https://cpwd.test/tender.pdf") as result:
            assert result.final_url == "https://docs.cpwd.test/a.pdf"

    def test_a_relative_location_cannot_escape_the_allowlist(self) -> None:
        """Resolution is against the current URL, so a relative target stays on the current host."""
        h = harness([redirect("../../../etc/passwd"), Step(status=200)])
        with h.fetch("https://cpwd.test/docs/tender.html") as result:
            assert result.final_url.startswith("https://cpwd.test/")


class TestHopCap:
    def test_the_chain_stops_at_the_configured_cap(self) -> None:
        h = harness(
            [redirect(f"https://cpwd.test/hop{n}") for n in range(6)],
            policy=RedirectPolicy(max_hops=2),
        )
        with (
            pytest.raises(RedirectRejectedError) as caught,
            h.fetch("https://cpwd.test/start"),
        ):
            pass

        assert caught.value.final_outcome is AttemptOutcome.INVALID_REDIRECT
        assert "exceeded 2 hops" in str(caught.value)
        # One original request plus two followed redirects. The third redirect is refused.
        assert len(h.transport.urls) == 3

    def test_the_default_cap_is_five_hops(self) -> None:
        h = harness([redirect(f"https://cpwd.test/hop{n}") for n in range(8)])
        with (
            pytest.raises(RedirectRejectedError) as caught,
            h.fetch("https://cpwd.test/start"),
        ):
            pass

        assert "exceeded 5 hops" in str(caught.value)
        assert len(h.transport.urls) == 6

    def test_a_chain_within_the_cap_completes(self) -> None:
        h = harness(
            [
                redirect("https://cpwd.test/b"),
                redirect("https://cpwd.test/c"),
                redirect("https://cpwd.test/d"),
                redirect("https://cpwd.test/e"),
                redirect("https://cpwd.test/f"),
                Step(status=200),
            ]
        )
        with h.fetch("https://cpwd.test/a") as result:
            assert result.response.status_code == 200
        assert result.hop_count == 5


class TestLoopDetection:
    def test_a_two_url_cycle_is_reported_as_a_loop_rather_than_a_hop_exhaustion(self) -> None:
        """Burning five hops around a cycle wastes time and names the wrong cause."""
        h = harness([redirect("https://cpwd.test/b"), redirect("https://cpwd.test/a")])
        with (
            pytest.raises(RedirectRejectedError) as caught,
            h.fetch("https://cpwd.test/a"),
        ):
            pass

        assert caught.value.final_outcome is AttemptOutcome.INVALID_REDIRECT
        assert "loop" in str(caught.value)
        assert len(h.transport.urls) == 2

    def test_a_self_redirect_is_a_loop(self) -> None:
        h = harness([redirect("https://cpwd.test/a")])
        with (
            pytest.raises(RedirectRejectedError) as caught,
            h.fetch("https://cpwd.test/a"),
        ):
            pass

        assert "loop" in str(caught.value)
        assert len(h.transport.urls) == 1

    def test_a_loop_disguised_by_an_explicit_default_port_is_caught(self) -> None:
        """The canonical check, not the string one.

        ``https://cpwd.test:443/a`` and ``https://cpwd.test/a`` are the same destination written two
        ways, so the policy's string comparison against the raw ``Location`` lets it through. What
        catches it is comparing the URL that *validation* produced against the chain — which is why
        that second check exists rather than being redundant with the first.
        """
        h = harness([redirect("https://cpwd.test:443/a"), Step(status=200)])
        with (
            pytest.raises(RedirectRejectedError) as caught,
            h.fetch("https://cpwd.test/a"),
        ):
            pass

        assert caught.value.final_outcome is AttemptOutcome.INVALID_REDIRECT
        assert "already requested in this chain" in str(caught.value)
        assert len(h.transport.urls) == 1

    def test_a_loop_disguised_by_host_casing_is_caught(self) -> None:
        h = harness([redirect("https://CPWD.TEST/a"), Step(status=200)])
        with (
            pytest.raises(RedirectRejectedError) as caught,
            h.fetch("https://cpwd.test/a"),
        ):
            pass

        assert "already requested in this chain" in str(caught.value)
        assert len(h.transport.urls) == 1


class TestMalformedRedirects:
    def test_a_redirect_status_with_no_location_is_refused(self) -> None:
        """A broken response, not an invitation to guess where it meant."""
        h = harness([Step(status=302)])
        with (
            pytest.raises(RedirectRejectedError) as caught,
            h.fetch("https://cpwd.test/a"),
        ):
            pass

        assert caught.value.final_outcome is AttemptOutcome.INVALID_REDIRECT
        assert "no Location" in str(caught.value)

    @pytest.mark.parametrize("location", ["", "   ", "\t"])
    def test_an_empty_location_is_refused(self, location: str) -> None:
        h = harness([redirect(location)])
        with (
            pytest.raises(RedirectRejectedError) as caught,
            h.fetch("https://cpwd.test/a"),
        ):
            pass
        assert caught.value.final_outcome is AttemptOutcome.INVALID_REDIRECT

    @pytest.mark.parametrize(
        "location",
        [
            "https://docs.cpwd.test/a\r\nX-Injected: 1",
            "https://docs.cpwd.test/a\nX-Injected: 1",
            "https://docs.cpwd.test/a\x00",
            "/next\r\nSet-Cookie: session=stolen",
        ],
    )
    def test_a_location_carrying_control_characters_is_never_resolved(self, location: str) -> None:
        """Header injection or a split response. Refused rather than sanitised.

        Sanitising would mean deciding which half of a smuggled header was meant, and the answer
        is neither.
        """
        h = harness([redirect(location), Step(status=200)])
        with (
            pytest.raises(RedirectRejectedError) as caught,
            h.fetch("https://cpwd.test/a"),
        ):
            pass

        assert caught.value.final_outcome is AttemptOutcome.INVALID_REDIRECT
        assert len(h.transport.urls) == 1

    def test_a_malformed_ipv6_location_is_refused_rather_than_raising(self) -> None:
        """``urljoin`` raises ``ValueError`` here; that must surface as a refusal, not a crash."""
        h = harness([redirect("https://[::1/a"), Step(status=200)])
        with (
            pytest.raises(RedirectRejectedError) as caught,
            h.fetch("https://cpwd.test/a"),
        ):
            pass

        assert caught.value.final_outcome is AttemptOutcome.INVALID_REDIRECT
        assert "could not be resolved" in str(caught.value)

    @pytest.mark.parametrize("location", ["mailto:someone@cpwd.test", "javascript:alert(1)"])
    def test_a_non_http_location_is_refused(self, location: str) -> None:
        h = harness([redirect(location), Step(status=200)])
        with (
            pytest.raises(RedirectRejectedError) as caught,
            h.fetch("https://cpwd.test/a"),
        ):
            pass

        assert caught.value.final_outcome in {
            AttemptOutcome.INVALID_REDIRECT,
            AttemptOutcome.SSRF_REJECTED,
        }
        assert len(h.transport.urls) == 1


class TestNonFollowedStatuses:
    def test_300_is_handed_back_rather_than_followed(self) -> None:
        """Multiple Choices has no single target, so following it means guessing.

        Note what happens instead: it is returned to the caller as the answer, because a 300 *is* a
        response. The redirect machinery declining to act on it is not the same as failing.
        """
        h = harness([Step(status=300, headers=(("Location", "https://docs.cpwd.test/a"),))])
        with h.fetch("https://cpwd.test/a") as result:
            assert result.response.status_code == 300

        assert result.was_redirected is False
        assert len(h.transport.urls) == 1

    def test_304_is_handed_back_rather_than_followed(self) -> None:
        h = harness([Step(status=304)])
        with h.fetch("https://cpwd.test/a") as result:
            assert result.response.status_code == 304
        assert result.was_redirected is False


# ---------------------------------------------------------------------------
# Transport downgrade
# ---------------------------------------------------------------------------


class TestTransportDowngrade:
    def test_http_to_https_is_followed_without_permission(self) -> None:
        """An upgrade needs no opt-in; refusing it would punish a site for doing the right thing."""
        h = harness([redirect("https://cpwd.test/a"), Step(status=200)])
        with h.fetch("http://cpwd.test/a") as result:
            assert result.final_url == "https://cpwd.test/a"
        assert h.transport.urls == ["http://cpwd.test/a", "https://cpwd.test/a"]

    def test_https_to_http_is_refused_by_default(self) -> None:
        """Evidence fetched over a tamperable channel is weak evidence."""
        h = harness([redirect("http://cpwd.test/a"), Step(status=200)])
        with (
            pytest.raises(RedirectRejectedError) as caught,
            h.fetch("https://cpwd.test/b"),
        ):
            pass

        assert caught.value.final_outcome is AttemptOutcome.INVALID_REDIRECT
        assert "downgrades transport" in str(caught.value)
        assert len(h.transport.urls) == 1

    def test_https_to_http_is_followed_when_the_source_accepted_that(self) -> None:
        """``allow_insecure_transport`` is a source's decision, and it is honoured when made."""
        h = harness(
            [redirect("http://cpwd.test/a"), Step(status=200)],
            policy=RedirectPolicy(allow_transport_downgrade=True),
        )
        with h.fetch("https://cpwd.test/b") as result:
            assert result.final_url == "http://cpwd.test/a"
        assert h.transport.urls == ["https://cpwd.test/b", "http://cpwd.test/a"]

    def test_a_downgrade_to_another_host_is_still_a_downgrade(self) -> None:
        h = harness([redirect("http://docs.cpwd.test/a"), Step(status=200)])
        with (
            pytest.raises(RedirectRejectedError) as caught,
            h.fetch("https://cpwd.test/b"),
        ):
            pass
        assert "downgrades transport" in str(caught.value)

    def test_http_to_http_is_not_a_downgrade(self) -> None:
        h = harness([redirect("http://docs.cpwd.test/a"), Step(status=200)])
        with h.fetch("http://cpwd.test/b") as result:
            assert result.final_url == "http://docs.cpwd.test/a"


# ---------------------------------------------------------------------------
# Method and headers
# ---------------------------------------------------------------------------


class TestMethodRewriting:
    def test_303_rewrites_the_method_to_get(self) -> None:
        """Currently a no-op for GET, and recorded anyway: HEAD must not survive a 303."""
        h = harness([redirect("https://cpwd.test/b", status=303), Step(status=200)])
        with h.fetch("https://cpwd.test/a", method="HEAD"):
            pass
        assert h.transport.methods == ["HEAD", "GET"]

    @pytest.mark.parametrize("status", [301, 302, 307, 308])
    def test_every_other_redirect_preserves_the_method(self, status: int) -> None:
        h = harness([redirect("https://cpwd.test/b", status=status), Step(status=200)])
        with h.fetch("https://cpwd.test/a", method="HEAD"):
            pass
        assert h.transport.methods == ["HEAD", "HEAD"]

    def test_a_rewrite_persists_for_the_rest_of_the_chain(self) -> None:
        h = harness(
            [
                redirect("https://cpwd.test/b", status=303),
                redirect("https://cpwd.test/c", status=307),
                Step(status=200),
            ]
        )
        with h.fetch("https://cpwd.test/a", method="HEAD"):
            pass
        assert h.transport.methods == ["HEAD", "GET", "GET"]

    def test_get_is_the_default_method(self) -> None:
        h = harness([Step(status=200)])
        with h.fetch("https://cpwd.test/a"):
            pass
        assert h.transport.methods == ["GET"]


class TestHeadersAcrossHosts:
    """FR-114. Headers are rebuilt on a host change, not carried over.

    Nothing sends credentials today, which is exactly when this is cheap to get right: the rule
    should already be in place before there is anything worth leaking to whichever host a remote
    server names.
    """

    def test_headers_are_dropped_when_the_host_changes(self) -> None:
        h = harness([redirect("https://docs.cpwd.test/a"), Step(status=200)])
        with h.fetch("https://cpwd.test/a", headers=TRACE):
            pass
        assert h.transport.header_sets == [TRACE, None]

    def test_headers_are_kept_on_a_same_host_redirect(self) -> None:
        h = harness([redirect("https://cpwd.test/b"), Step(status=200)])
        with h.fetch("https://cpwd.test/a", headers=TRACE):
            pass
        assert h.transport.header_sets == [TRACE, TRACE]

    def test_a_case_difference_in_the_host_is_not_a_host_change(self) -> None:
        h = harness([redirect("https://CPWD.TEST/b"), Step(status=200)])
        with h.fetch("https://cpwd.test/a", headers=TRACE):
            pass
        assert h.transport.header_sets == [TRACE, TRACE]

    def test_an_explicit_default_port_is_not_a_host_change(self) -> None:
        h = harness([redirect("https://cpwd.test:443/b"), Step(status=200)])
        with h.fetch("https://cpwd.test/a", headers=TRACE):
            pass
        assert h.transport.header_sets == [TRACE, TRACE]

    def test_headers_stay_dropped_for_the_remainder_of_the_chain(self) -> None:
        """Returning to the original host later must not resurrect them.

        The chain has already passed through a host chosen by a remote server; treating a later hop
        as trustworthy because its name looks familiar would undo the whole point.
        """
        h = harness(
            [
                redirect("https://docs.cpwd.test/a"),
                redirect("https://docs.cpwd.test/b"),
                Step(status=200),
            ]
        )
        with h.fetch("https://cpwd.test/a", headers=TRACE):
            pass
        assert h.transport.header_sets == [TRACE, None, None]

    def test_no_headers_stays_no_headers(self) -> None:
        h = harness([redirect("https://docs.cpwd.test/a"), Step(status=200)])
        with h.fetch("https://cpwd.test/a"):
            pass
        assert h.transport.header_sets == [None, None]


class TestCrossesHost:
    """The host comparison, checked directly on inputs the policy cannot currently produce.

    Two of these — an authority with no scheme, and an unterminated IPv6 literal — cannot reach
    ``_crosses_host`` today, because the redirect policy resolves and rejects them first. They are
    tested anyway: the function's job is to fail in the safe direction when it cannot tell, and a
    fail-safe default that is never exercised is a claim rather than a behaviour.
    """

    @pytest.mark.parametrize(
        "next_url",
        [
            "https://docs.cpwd.test/a",
            "https://cpwd.test@evil.test/a",
            "https://[::1]/a",
            "https://[::1/a",
            "https:///a",
            "not-a-url",
            "",
        ],
    )
    def test_anything_not_provably_the_same_host_counts_as_a_crossing(self, next_url: str) -> None:
        assert _crosses_host("cpwd.test", next_url) is True

    @pytest.mark.parametrize(
        "next_url",
        [
            "https://cpwd.test/a",
            "https://CPWD.TEST/a",
            "https://cpwd.test:443/a",
            "http://cpwd.test/a",
            "https://cpwd.test/a?x=1",
        ],
    )
    def test_the_same_host_is_not_a_crossing(self, next_url: str) -> None:
        assert _crosses_host("cpwd.test", next_url) is False

    def test_the_userinfo_does_not_decide_who_receives_a_header(self) -> None:
        """``https://cpwd.test@evil.test/`` sends to ``evil.test``. The decoy decides nothing."""
        assert _crosses_host("cpwd.test", "https://cpwd.test@evil.test/a") is True
        assert _crosses_host("evil.test", "https://cpwd.test@evil.test/a") is False


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------


class TestChainProvenance:
    """FR-115. What was asked for and what answered are both retained."""

    def test_the_requested_and_final_urls_are_both_kept(self) -> None:
        h = harness(
            [
                redirect("https://docs.cpwd.test/a"),
                redirect("https://static.cpwd.test/b"),
                Step(status=200),
            ]
        )
        with h.fetch("https://cpwd.test/tender.pdf") as result:
            pass

        assert result.requested_url == "https://cpwd.test/tender.pdf"
        assert result.final_url == "https://static.cpwd.test/b"
        assert result.was_redirected is True
        assert result.hop_count == 2

    def test_the_requested_url_is_kept_verbatim_and_the_chain_is_canonical(self) -> None:
        """The caller's string is provenance; the canonical form is what was actually contacted."""
        h = harness([Step(status=200)])
        with h.fetch("https://CPWD.TEST:443/a") as result:
            pass

        assert result.requested_url == "https://CPWD.TEST:443/a"
        assert result.final_url == "https://cpwd.test/a"
        assert result.chain[0].url == "https://cpwd.test/a"

    def test_every_hop_records_its_status_and_raw_location(self) -> None:
        h = harness(
            [
                redirect("https://docs.cpwd.test/a", status=301),
                redirect("/b", status=302),
                Step(status=200),
            ]
        )
        with h.fetch("https://cpwd.test/tender.pdf") as result:
            pass

        assert [hop.status_code for hop in result.chain] == [301, 302, 200]
        assert [hop.location for hop in result.chain] == [
            "https://docs.cpwd.test/a",
            # Kept exactly as sent, unresolved. The resolved form is the next hop's url.
            "/b",
            None,
        ]
        assert [hop.url for hop in result.chain] == [
            "https://cpwd.test/tender.pdf",
            "https://docs.cpwd.test/a",
            "https://docs.cpwd.test/b",
        ]

    def test_attempt_history_from_every_hop_is_collected_in_order(self) -> None:
        """Retries inside a hop and redirects across hops compose into one history.

        Hop 1 is served a 503 and then a redirect; hop 2 answers. The provenance claim is
        "retrieved after a 503, one redirect, and three requests in total", and every part of that
        has to survive.
        """
        h = harness(
            [
                Step(status=503),
                redirect("https://docs.cpwd.test/a"),
                Step(status=200),
            ]
        )
        with h.fetch("https://cpwd.test/tender.pdf") as result:
            pass

        assert len(result.chain) == 2
        assert [record.outcome for record in result.chain[0].attempts] == [
            AttemptOutcome.HTTP_STATUS,
            AttemptOutcome.SUCCESS,
        ]
        assert [record.outcome for record in result.chain[1].attempts] == [AttemptOutcome.SUCCESS]
        assert [record.outcome for record in result.attempts] == [
            AttemptOutcome.HTTP_STATUS,
            AttemptOutcome.SUCCESS,
            AttemptOutcome.SUCCESS,
        ]
        assert result.attempts[0].status_code == 503
        assert h.sleeper.slept == [1.0], "the retry inside the hop took its backoff"

    def test_a_rejected_chain_carries_what_happened_before_the_rejection(self) -> None:
        """ "Refused at hop 3" and "refused immediately" are different diagnoses."""
        h = harness(
            [
                redirect("https://docs.cpwd.test/a"),
                redirect("https://metadata.cpwd.test/b"),
                Step(status=200),
            ]
        )
        with (
            pytest.raises(RedirectRejectedError) as caught,
            h.fetch("https://cpwd.test/tender.pdf"),
        ):
            pass

        assert [hop.url for hop in caught.value.chain] == [
            "https://cpwd.test/tender.pdf",
            "https://docs.cpwd.test/a",
        ]
        assert caught.value.chain[-1].location == "https://metadata.cpwd.test/b"

    def test_an_empty_chain_reports_no_hops_and_no_attempts(self) -> None:
        """The dataclass arithmetic, stated rather than inferred from a chain that has hops."""
        target = ValidatedTarget(
            url="https://cpwd.test/a",
            scheme="https",
            hostname="cpwd.test",
            port=443,
            ip_address=ip_address(PUBLIC),
            source_id="cpwd",
            validated_addresses=(ip_address(PUBLIC),),
        )
        response = RawResponse(
            target=target,
            status_code=200,
            http_version="HTTP/1.1",
            headers=ResponseHeaders(),
            stream=lambda _size: iter([]),
            close=lambda: None,
        )
        empty = ChainResult(
            response=response,
            requested_url=target.url,
            final_url=target.url,
        )
        assert empty.chain == ()
        assert empty.attempts == ()
        assert empty.hop_count == 0
        assert empty.was_redirected is False

        hop = RedirectHop(url=target.url, status_code=302)
        assert hop.location is None
        assert hop.attempts == ()


# ---------------------------------------------------------------------------
# One budget, one politeness slot per hop
# ---------------------------------------------------------------------------


class TestBudgetSpansTheWholeChain:
    def test_the_timeouts_shrink_across_hops(self) -> None:
        """Five hops each with a fresh 30s allowance is five times the timeout the caller asked for.

        With a 40s total and hops costing 15s each, the read timeout has to track what remains:
        30 → 25 → 10. A constant 30 would mean the budget had been rebuilt per hop.
        """
        h = harness(
            [
                redirect("https://docs.cpwd.test/a", takes_seconds=15.0),
                redirect("https://static.cpwd.test/b", takes_seconds=15.0),
                Step(status=200, takes_seconds=1.0),
            ]
        )
        with h.fetch("https://cpwd.test/tender.pdf", total=40.0):
            pass

        reads = [timeouts.read_seconds for timeouts in h.transport.timeouts_seen]
        assert reads == [30.0, 25.0, 10.0], reads

    def test_the_same_budget_object_reaches_every_hop(self) -> None:
        h = harness(
            [
                redirect("https://docs.cpwd.test/a"),
                redirect("https://static.cpwd.test/b"),
                Step(status=200),
            ]
        )
        with h.fetch("https://cpwd.test/tender.pdf"):
            pass

        deadlines = {id(timeouts.deadline) for timeouts in h.transport.timeouts_seen}
        assert len(deadlines) == 1, "a hop was given a budget of its own"

    def test_a_chain_that_runs_out_of_time_stops_rather_than_continuing(self) -> None:
        """The redirect is valid and permitted. There is simply no time left to follow it."""
        h = harness(
            [
                redirect("https://docs.cpwd.test/a", takes_seconds=41.0),
                Step(status=200),
            ]
        )
        with (
            pytest.raises(FetchFailedError) as caught,
            h.fetch("https://cpwd.test/tender.pdf", total=40.0),
        ):
            pass

        assert caught.value.final_outcome is AttemptOutcome.BUDGET_EXHAUSTED
        assert len(h.transport.urls) == 1, "a hop was attempted with no budget left"


class TestPolitenessPerHop:
    def test_every_hop_takes_its_own_rate_limit_slot(self) -> None:
        """A redirect is a request the source has to serve, so it is charged like one."""
        h = harness(
            [
                redirect("https://docs.cpwd.test/a"),
                redirect("https://static.cpwd.test/b"),
                Step(status=200),
            ]
        )
        with h.fetch("https://cpwd.test/tender.pdf"):
            pass
        assert h.slots_taken == ["cpwd", "cpwd", "cpwd"]

    def test_a_chain_completes_under_a_concurrency_limit_of_one(self) -> None:
        """A hop's slot must be released before the next hop asks for one.

        If the controller held the slot across hops this would deadlock, so the assertion is really
        that the test terminates at all. The budget is kept small so a regression fails in seconds
        with a verdict rather than hanging until CI gives up (rule 81g).
        """
        h = harness(
            [
                redirect("https://docs.cpwd.test/a"),
                redirect("https://static.cpwd.test/b"),
                Step(status=200),
            ]
        )
        serial = RateLimits(requests_per_minute=600, max_concurrency=1, min_delay_seconds=0.0)
        with h.fetch("https://cpwd.test/tender.pdf", total=40.0, limits=serial) as result:
            assert result.response.status_code == 200
        assert len(h.slots_taken) == 3


# ---------------------------------------------------------------------------
# Failures inside a hop
# ---------------------------------------------------------------------------


class TestHopFailures:
    def test_a_permanent_status_on_a_later_hop_propagates(self) -> None:
        h = harness([redirect("https://docs.cpwd.test/a"), Step(status=404)])
        with (
            pytest.raises(FetchFailedError) as caught,
            h.fetch("https://cpwd.test/tender.pdf"),
        ):
            pass

        assert caught.value.final_outcome is AttemptOutcome.HTTP_STATUS
        # The failure names the hop it happened on, which is the diagnosis the chain would give.
        assert "docs.cpwd.test" in str(caught.value)
        assert len(caught.value.attempts) == 1

    def test_a_transport_failure_is_retried_within_the_hop_before_giving_up(self) -> None:
        h = harness(
            [
                redirect("https://docs.cpwd.test/a"),
                Step(error=ConnectionFailedError("connection refused")),
                Step(error=ConnectionFailedError("connection refused")),
            ],
            max_attempts=2,
        )
        with (
            pytest.raises(FetchFailedError) as caught,
            h.fetch("https://cpwd.test/tender.pdf"),
        ):
            pass

        assert caught.value.final_outcome is AttemptOutcome.CONNECTION_ERROR
        assert len(caught.value.attempts) == 2
        assert h.transport.urls == [
            "https://cpwd.test/tender.pdf",
            "https://docs.cpwd.test/a",
            "https://docs.cpwd.test/a",
        ]

    def test_a_retry_inside_a_hop_reuses_the_validated_target(self) -> None:
        """Re-validation happens per hop, not per attempt: the address is already fixed.

        Resolving again for a retry would reopen the DNS-rebinding window that validating once and
        connecting to the validated address exists to close.
        """
        h = harness(
            [
                Step(error=ConnectionFailedError("connection refused")),
                Step(status=200),
            ]
        )
        with h.fetch("https://cpwd.test/tender.pdf"):
            pass

        assert h.resolver.lookups == ["cpwd.test"], "a retry resolved the host a second time"
        assert {request.ip for request in h.transport.requests} == {PUBLIC}

    def test_the_connection_goes_to_the_validated_address_with_the_hostname_intact(self) -> None:
        """The invariant the guard states, checked at the last hop rather than only the first."""
        h = harness([redirect("https://docs.cpwd.test/a"), Step(status=200)])
        with h.fetch("https://cpwd.test/tender.pdf"):
            pass

        assert [request.hostname for request in h.transport.requests] == [
            "cpwd.test",
            "docs.cpwd.test",
        ]
        assert [request.ip for request in h.transport.requests] == [PUBLIC, PUBLIC]
