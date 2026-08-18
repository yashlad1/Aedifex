"""``robots.txt``: the parser exhaustively, and the gate through the real fetch stack.

Two halves, tested differently on purpose.

The **parser** is pure, so every awkward file shape is a one-line test. That is where the volume is,
because a robots parser is a parser of hostile-adjacent text: the file is written by someone else,
in a format with no schema, and a misreading is either "we crawled what we were asked not to" or "we
refused a site that welcomed us". Both are silent.

The **gate** is tested through a real :class:`RedirectController` over a scripted transport rather
than through a stub, because the behaviour it depends on is not obvious and had to be checked rather
than assumed: a 404 does not arrive as a response, it arrives as a ``FetchFailedError`` carrying the
status in its attempt history. A fake controller would have let me *assume* that mapping. The
scripted transport also records every request, which is what makes the strongest assertion here a
negative one — a source declaring ``robots_policy: not_applicable`` must produce no request at all.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from ipaddress import ip_address

import pytest

from aedifex.acquisition.crawl.robots import (
    MAX_HONOURABLE_CRAWL_DELAY_SECONDS,
    MAX_ROBOTS_BYTES,
    CrawlDelayTooLongError,
    RobotsGate,
    RobotsVerdict,
    parse_robots,
    polite_limits,
)
from aedifex.acquisition.fetch.controller import RetryController
from aedifex.acquisition.fetch.guard import ValidatedTarget
from aedifex.acquisition.fetch.hosts import SourceHostPolicy
from aedifex.acquisition.fetch.ratelimit import RateLimiter, RateLimits
from aedifex.acquisition.fetch.redirect_controller import RedirectController
from aedifex.acquisition.fetch.resolver import ResolvedAddress
from aedifex.acquisition.fetch.retry import BackoffPolicy, RetryPolicy
from aedifex.acquisition.fetch.transport import (
    ConnectionFailedError,
    RawResponse,
    ResponseHeaders,
    TransportTimeouts,
)

USER_AGENT = "AedifexBot/0.1 (+mailto:ops@example.org)"
PUBLIC = "93.184.216.34"

HOSTS = SourceHostPolicy(
    source_id="cpwd",
    base_hosts=frozenset({"cpwd.test"}),
    exact_hosts=frozenset({"cdn.example.test"}),
)
FAST = RateLimits(requests_per_minute=600, max_concurrency=4, min_delay_seconds=0.0)

DNS: Mapping[str, tuple[str, ...]] = {
    "cpwd.test": (PUBLIC,),
    "docs.cpwd.test": (PUBLIC,),
    "cdn.example.test": (PUBLIC,),
}


# ---------------------------------------------------------------------------
# The parser
# ---------------------------------------------------------------------------


def allows(text: str, path: str, *, user_agent: str = USER_AGENT) -> bool:
    return parse_robots(text, user_agent=user_agent).decide(path).allowed


class TestTheBasics:
    def test_a_disallowed_path_is_refused(self) -> None:
        assert not allows("User-agent: *\nDisallow: /private", "/private/file.pdf")

    def test_an_unmentioned_path_is_permitted(self) -> None:
        assert allows("User-agent: *\nDisallow: /private", "/public/file.pdf")

    def test_a_file_with_no_rules_permits_everything(self) -> None:
        assert allows("", "/anything")
        assert allows("# just a comment\n", "/anything")

    def test_disallow_slash_refuses_the_whole_site(self) -> None:
        text = "User-agent: *\nDisallow: /"
        assert not allows(text, "/")
        assert not allows(text, "/deep/nested/file.pdf")

    def test_an_empty_disallow_permits_everything(self) -> None:
        """``Disallow:`` with no value is the documented way to say "nothing is forbidden"."""
        parsed = parse_robots("User-agent: *\nDisallow:", user_agent=USER_AGENT)
        assert parsed.decide("/anything").allowed
        # And it counts as a directive, so the file is not mistaken for unreadable.
        assert parsed.saw_any_directive is True

    def test_directive_names_are_case_insensitive(self) -> None:
        assert not allows("USER-AGENT: *\nDISALLOW: /private", "/private")

    def test_comments_are_stripped(self) -> None:
        assert not allows("User-agent: *  # everyone\nDisallow: /private  # not this", "/private")

    def test_a_commented_out_rule_does_not_apply(self) -> None:
        assert allows("User-agent: *\n# Disallow: /private", "/private")

    @pytest.mark.parametrize("ending", ["\n", "\r\n", "\r"])
    def test_every_line_ending_is_understood(self, ending: str) -> None:
        """A file written on Windows or classic Mac is still a file."""
        text = ending.join(["User-agent: *", "Disallow: /private"])
        assert not allows(text, "/private")

    def test_a_byte_order_mark_does_not_hide_the_first_line(self) -> None:
        assert not allows("﻿User-agent: *\nDisallow: /private", "/private")

    def test_whitespace_around_names_and_values_is_ignored(self) -> None:
        assert not allows("  User-agent :  *  \n  Disallow :  /private  ", "/private")


class TestGroupSelection:
    def test_our_own_group_is_preferred_over_the_wildcard(self) -> None:
        text = "User-agent: *\nDisallow: /\n\nUser-agent: AedifexBot\nDisallow: /admin"
        assert allows(text, "/tenders/notice.pdf")
        assert not allows(text, "/admin")

    def test_another_crawlers_group_does_not_apply_to_us(self) -> None:
        text = "User-agent: GreedyBot\nDisallow: /\n\nUser-agent: *\nAllow: /"
        assert allows(text, "/tenders")

    def test_the_wildcard_applies_when_we_are_not_named(self) -> None:
        assert not allows("User-agent: *\nDisallow: /private", "/private")

    def test_agent_matching_is_case_insensitive(self) -> None:
        assert not allows("User-agent: AEDIFEXBOT\nDisallow: /private", "/private")

    def test_a_partial_agent_name_still_binds_us(self) -> None:
        """Ambiguity is resolved towards obeying more rules, not fewer.

        A file saying ``User-agent: aedifex`` was plainly written with us in mind, and an equality
        test would let us ignore it on a technicality.
        """
        assert not allows("User-agent: aedifex\nDisallow: /private", "/private")

    def test_the_most_specific_group_wins(self) -> None:
        text = (
            "User-agent: *\nDisallow: /\n\n"
            "User-agent: bot\nDisallow: /a\n\n"
            "User-agent: aedifexbot\nDisallow: /b"
        )
        # The longest matching agent token is ours, so only /b is refused.
        assert allows(text, "/a")
        assert not allows(text, "/b")

    def test_consecutive_agent_lines_share_one_rule_set(self) -> None:
        """The classic misreading: three agents listed, then one rule, applies to all three.

        Getting this wrong silently attaches the rules to the last agent only, which means we obey
        a file's restrictions whenever we happen to be named last and ignore them otherwise.
        """
        text = "User-agent: GreedyBot\nUser-agent: AedifexBot\nUser-agent: OtherBot\nDisallow: /x"
        assert not allows(text, "/x")

    def test_a_new_group_starts_after_a_rule(self) -> None:
        text = "User-agent: AedifexBot\nDisallow: /a\nUser-agent: OtherBot\nDisallow: /b"
        assert not allows(text, "/a")
        assert allows(text, "/b")

    def test_a_group_header_with_no_rules_leaves_us_unrestricted(self) -> None:
        parsed = parse_robots("User-agent: *\n", user_agent=USER_AGENT)
        assert parsed.decide("/anything").allowed
        assert parsed.saw_any_directive is False


class TestPatternMatching:
    def test_a_prefix_match_is_enough(self) -> None:
        assert not allows("User-agent: *\nDisallow: /doc", "/documents/a.pdf")

    def test_a_wildcard_matches_any_run_of_characters(self) -> None:
        text = "User-agent: *\nDisallow: /*/private/"
        assert not allows(text, "/anything/private/file.pdf")
        assert allows(text, "/anything/public/file.pdf")

    def test_a_dollar_anchors_the_end(self) -> None:
        text = "User-agent: *\nDisallow: /*.pdf$"
        assert not allows(text, "/documents/a.pdf")
        assert allows(text, "/documents/a.pdf.html")

    def test_a_pattern_may_include_a_query_string(self) -> None:
        text = "User-agent: *\nDisallow: /search?q="
        assert not allows(text, "/search?q=cement")
        assert allows(text, "/search")

    def test_regex_metacharacters_in_a_pattern_are_literal(self) -> None:
        """A pattern is not a regular expression. ``.`` and ``+`` mean themselves."""
        text = "User-agent: *\nDisallow: /a.b+c"
        assert not allows(text, "/a.b+c/file")
        assert allows(text, "/axbxc/file")

    def test_the_longest_matching_pattern_wins(self) -> None:
        text = "User-agent: *\nDisallow: /docs\nAllow: /docs/public"
        assert not allows(text, "/docs/private/a.pdf")
        assert allows(text, "/docs/public/a.pdf")

    def test_allow_beats_disallow_on_an_exact_tie(self) -> None:
        """The narrower reading of an ambiguous file: an operator who wrote both meant to permit.

        Resolving a tie the other way would refuse content the site explicitly offered, and there is
        no way for the operator to discover that we did.
        """
        assert allows("User-agent: *\nDisallow: /docs\nAllow: /docs", "/docs/a.pdf")

    def test_the_decision_names_the_rule_that_made_it(self) -> None:
        decision = parse_robots("User-agent: *\nDisallow: /private", user_agent=USER_AGENT).decide(
            "/private/a.pdf"
        )
        assert decision.verdict is RobotsVerdict.DISALLOWED
        assert decision.rule == "Disallow: /private"
        assert "robots.txt" in decision.describe()


class TestCrawlDelay:
    def test_a_delay_is_read(self) -> None:
        parsed = parse_robots("User-agent: *\nCrawl-delay: 10", user_agent=USER_AGENT)
        assert parsed.crawl_delay_seconds == 10.0

    def test_a_fractional_delay_is_read(self) -> None:
        parsed = parse_robots("User-agent: *\nCrawl-delay: 2.5", user_agent=USER_AGENT)
        assert parsed.crawl_delay_seconds == 2.5

    @pytest.mark.parametrize("value", ["", "soon", "-5", "0", "nan", "inf"])
    def test_an_unusable_delay_is_ignored_rather_than_guessed(self, value: str) -> None:
        parsed = parse_robots(f"User-agent: *\nCrawl-delay: {value}", user_agent=USER_AGENT)
        assert parsed.crawl_delay_seconds is None

    def test_the_longest_stated_delay_wins(self) -> None:
        text = "User-agent: *\nCrawl-delay: 2\nCrawl-delay: 30"
        assert parse_robots(text, user_agent=USER_AGENT).crawl_delay_seconds == 30.0

    def test_a_delay_in_another_agents_group_does_not_apply(self) -> None:
        text = "User-agent: GreedyBot\nCrawl-delay: 60\n\nUser-agent: *\nDisallow: /x"
        assert parse_robots(text, user_agent=USER_AGENT).crawl_delay_seconds is None

    def test_a_delay_counts_as_a_directive(self) -> None:
        """So a file containing only a delay is a robots file, not an unreadable body."""
        parsed = parse_robots("User-agent: *\nCrawl-delay: 5", user_agent=USER_AGENT)
        assert parsed.saw_any_directive


class TestUnrecognisedContent:
    def test_a_sitemap_is_collected(self) -> None:
        text = "Sitemap: https://cpwd.test/sitemap.xml\nUser-agent: *\nDisallow: /x"
        assert parse_robots(text, user_agent=USER_AGENT).sitemaps == (
            "https://cpwd.test/sitemap.xml",
        )

    def test_an_unknown_directive_is_ignored(self) -> None:
        text = "User-agent: *\nHost: cpwd.test\nDisallow: /private"
        assert not allows(text, "/private")

    def test_a_line_with_no_colon_is_ignored(self) -> None:
        assert not allows("User-agent: *\nthis is not a directive\nDisallow: /private", "/private")

    def test_html_declares_no_directives(self) -> None:
        """Which is how the gate tells "an empty file" from "not a robots file at all"."""
        body = "<!doctype html><html><body>Session expired. Please log in.</body></html>"
        assert parse_robots(body, user_agent=USER_AGENT).saw_any_directive is False

    def test_the_parser_never_raises(self) -> None:
        """Total by construction: a parser that throws on odd input becomes a fetch failure."""
        for hostile in (
            "\x00\x01\x02",
            "User-agent:\nDisallow:\n" * 100,
            "Disallow: /orphan-rule-with-no-agent",
            "User-agent: *\nDisallow: " + "/a" * 5000,
            ":" * 1000,
            "User-agent: *\nCrawl-delay: " + "9" * 500,
        ):
            parse_robots(hostile, user_agent=USER_AGENT)


class TestPoliteLimits:
    def test_no_delay_leaves_the_configuration_alone(self) -> None:
        rules_without = parse_robots("User-agent: *\nDisallow: /x", user_agent=USER_AGENT)
        assert polite_limits(FAST, rules_without) is FAST

    def test_a_shorter_delay_than_ours_is_ignored(self) -> None:
        """Our configured floor is a decision. A site asking us to hurry is not a reason to."""
        limits = RateLimits(requests_per_minute=10, max_concurrency=1, min_delay_seconds=5.0)
        parsed = parse_robots("User-agent: *\nCrawl-delay: 1", user_agent=USER_AGENT)
        assert polite_limits(limits, parsed) is limits

    def test_a_longer_delay_slows_us_down(self) -> None:
        limits = RateLimits(requests_per_minute=60, max_concurrency=4, min_delay_seconds=1.0)
        parsed = parse_robots("User-agent: *\nCrawl-delay: 10", user_agent=USER_AGENT)
        adjusted = polite_limits(limits, parsed)
        assert adjusted.min_delay_seconds == 10.0
        # The rate cap has to come down with the delay, or the two limits contradict each other.
        assert adjusted.requests_per_minute == 6
        assert adjusted.max_concurrency == 1

    def test_the_rate_never_drops_below_one_per_minute(self) -> None:
        """The limiter refuses zero, and a 90-second delay implies less than one a minute."""
        parsed = parse_robots("User-agent: *\nCrawl-delay: 90", user_agent=USER_AGENT)
        assert polite_limits(FAST, parsed).requests_per_minute == 1

    def test_a_delay_at_the_ceiling_is_honoured(self) -> None:
        parsed = parse_robots(
            f"User-agent: *\nCrawl-delay: {MAX_HONOURABLE_CRAWL_DELAY_SECONDS}",
            user_agent=USER_AGENT,
        )
        assert polite_limits(FAST, parsed).min_delay_seconds == MAX_HONOURABLE_CRAWL_DELAY_SECONDS

    def test_a_delay_beyond_the_ceiling_refuses_rather_than_being_clamped(self) -> None:
        """Clamping would be a decision to disobey, taken silently by a constant."""
        parsed = parse_robots("User-agent: *\nCrawl-delay: 86400", user_agent=USER_AGENT)
        with pytest.raises(CrawlDelayTooLongError, match="exceeds"):
            polite_limits(FAST, parsed)


# ---------------------------------------------------------------------------
# The gate, over the real fetch stack
# ---------------------------------------------------------------------------


class MappingResolver:
    """Scripted DNS.

    An unmapped host raises, so a typo in a test hostname fails loudly rather than quietly becoming
    an SSRF refusal that looks like a pass.
    """

    def __init__(self, mapping: Mapping[str, tuple[str, ...]]) -> None:
        self._mapping = mapping

    def resolve(self, hostname: str, port: int) -> Sequence[ResolvedAddress]:
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
    """Nothing waits: a retry's backoff advances the clock instead of the wall."""

    clock: FakeClock
    slept: list[float] = field(default_factory=list)

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.clock.advance(seconds)


@dataclass
class FixedRandom:
    def uniform(self, low: float, high: float) -> float:
        return high


@dataclass
class Step:
    status: int = 200
    body: bytes = b""
    content_type: str | None = "text/plain"
    error: Exception | None = None


def plain(body: str, *, status: int = 200) -> Step:
    return Step(status=status, body=body.encode("utf-8"))


class ScriptedTransport:
    """Plays a scripted sequence and records every request, so a negative claim is checkable."""

    def __init__(self, script: list[Step]) -> None:
        self._script = script
        self.urls: list[str] = []

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
        index = len(self.urls)
        self.urls.append(target.url)
        if index >= len(self._script):
            raise AssertionError(
                f"transport called {index + 1} times for {target.url}; "
                f"the script has {len(self._script)} step(s)"
            )
        step = self._script[index]
        if step.error is not None:
            raise step.error

        pairs: tuple[tuple[str, str], ...] = ()
        if step.content_type is not None:
            pairs = (("Content-Type", step.content_type),)

        def stream(size: int) -> Iterator[bytes]:
            for start in range(0, len(step.body), size):
                yield step.body[start : start + size]

        yield RawResponse(
            target=target,
            status_code=step.status,
            http_version="HTTP/1.1",
            headers=ResponseHeaders(pairs),
            stream=stream,
            close=lambda: None,
        )


class CountingLimiter(RateLimiter):
    """A real limiter that records who took a slot, so politeness can be asserted."""

    def __init__(self, taken: list[str], **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self._taken = taken

    @contextmanager
    def slot(
        self, source_id: str, limits: RateLimits, *, deadline: object = None
    ) -> Iterator[None]:
        self._taken.append(source_id)
        with super().slot(source_id, limits, deadline=deadline):  # type: ignore[arg-type]
            yield


@dataclass
class GateHarness:
    gate: RobotsGate
    transport: ScriptedTransport
    slots_taken: list[str]


def gate_for(
    script: list[Step],
    *,
    respect: bool = True,
    dns: Mapping[str, tuple[str, ...]] | None = None,
) -> GateHarness:
    clock = FakeClock()
    sleeper = FakeSleeper(clock)
    transport = ScriptedTransport(script)
    slots_taken: list[str] = []
    limiter = CountingLimiter(slots_taken, global_concurrency=4, clock=clock, sleeper=sleeper)
    controller = RetryController(
        transport=transport,
        limiter=limiter,
        policy=RetryPolicy(backoff=BackoffPolicy(max_attempts=5)),
        randomness=FixedRandom(),
        clock=clock,
        sleeper=sleeper,
    )
    redirects = RedirectController(
        controller=controller,
        resolver=MappingResolver(dns if dns is not None else {**DNS, "evilcpwd.test": (PUBLIC,)}),
    )
    gate = RobotsGate(
        redirects=redirects,
        user_agent=USER_AGENT,
        host_policy=HOSTS,
        limits=FAST,
        respect=respect,
    )
    return GateHarness(gate, transport, slots_taken)


class TestTheGateReadsTheFile:
    def test_a_disallowed_url_is_refused(self) -> None:
        harness = gate_for([plain("User-agent: *\nDisallow: /private")])
        decision = harness.gate.allows("https://cpwd.test/private/a.pdf")
        assert decision.verdict is RobotsVerdict.DISALLOWED
        assert decision.rule == "Disallow: /private"

    def test_a_permitted_url_is_allowed(self) -> None:
        harness = gate_for([plain("User-agent: *\nDisallow: /private")])
        assert harness.gate.allows("https://cpwd.test/tenders/a.pdf").allowed

    def test_it_asks_for_robots_txt_at_the_authority_root(self) -> None:
        harness = gate_for([plain("User-agent: *\nDisallow: /x")])
        harness.gate.allows("https://cpwd.test/deep/path/a.pdf?q=1")
        assert harness.transport.urls == ["https://cpwd.test/robots.txt"]

    def test_the_file_is_fetched_once_however_many_urls_are_checked(self) -> None:
        """The whole reason the gate is a class. A per-URL fetch would double every crawl."""
        harness = gate_for([plain("User-agent: *\nDisallow: /private")])
        for index in range(20):
            harness.gate.allows(f"https://cpwd.test/tenders/{index}.pdf")
        assert len(harness.transport.urls) == 1

    def test_each_authority_is_asked_separately(self) -> None:
        """Rules are per scheme-host-port. A subdomain's robots.txt is its own file."""
        harness = gate_for(
            [plain("User-agent: *\nDisallow: /a"), plain("User-agent: *\nAllow: /a")]
        )
        assert not harness.gate.allows("https://cpwd.test/a").allowed
        assert harness.gate.allows("https://docs.cpwd.test/a").allowed
        assert harness.transport.urls == [
            "https://cpwd.test/robots.txt",
            "https://docs.cpwd.test/robots.txt",
        ]

    def test_the_query_string_is_part_of_the_decision(self) -> None:
        harness = gate_for([plain("User-agent: *\nDisallow: /search?q=")])
        assert not harness.gate.allows("https://cpwd.test/search?q=cement").allowed

    def test_the_crawl_delay_is_available_to_the_caller(self) -> None:
        harness = gate_for([plain("User-agent: *\nCrawl-delay: 12")])
        assert harness.gate.crawl_delay("https://cpwd.test/a") == 12.0

    def test_the_fetch_is_charged_to_the_source(self) -> None:
        """Asking for robots.txt is asking the site for something, so it takes a slot."""
        harness = gate_for([plain("User-agent: *\nDisallow: /x")])
        harness.gate.allows("https://cpwd.test/a")
        assert harness.slots_taken == ["cpwd"]

    def test_only_the_first_500_kib_are_parsed(self) -> None:
        """RFC 9309 §2.3.1.1: parse at least 500 KiB and ignore the rest.

        Truncation rather than refusal, because a site that serves a bloated file has not thereby
        forbidden us anything — but a rule hiding past the limit is genuinely not seen, and that is
        worth stating out loud rather than discovering later.
        """
        padding = "# " + "p" * MAX_ROBOTS_BYTES
        harness = gate_for([plain(f"{padding}\nUser-agent: *\nDisallow: /late")])
        assert harness.gate.allows("https://cpwd.test/late").allowed


class TestWhatAnHttpStatusMeans:
    def test_a_missing_file_permits_everything(self) -> None:
        """A 404 is an answer: there are no rules. RFC 9309 §2.3.1.3."""
        harness = gate_for([Step(status=404)])
        decision = harness.gate.allows("https://cpwd.test/anything")
        assert decision.allowed
        assert "absent" in decision.reason

    def test_a_forbidden_robots_file_permits_everything(self) -> None:
        """403 is in the same 4xx class. Counter-intuitive, and it is what the RFC specifies."""
        assert gate_for([Step(status=403)]).gate.allows("https://cpwd.test/a").allowed

    def test_a_rate_limited_response_permits_nothing(self) -> None:
        """429 is the site asking us to slow down.

        Reading that as "no rules exist" would be the worst available reading of it, so it is
        grouped with the server errors rather than with the other 4xx.
        """
        harness = gate_for([Step(status=429) for _ in range(5)])
        decision = harness.gate.allows("https://cpwd.test/a")
        assert decision.verdict is RobotsVerdict.DISALLOWED
        assert "unreadable" in decision.reason

    def test_a_server_error_permits_nothing(self) -> None:
        """RFC 9309 §2.3.1.4. Silence is not consent."""
        harness = gate_for([Step(status=503) for _ in range(5)])
        assert not harness.gate.allows("https://cpwd.test/a").allowed

    def test_no_answer_at_all_permits_nothing(self) -> None:
        harness = gate_for([Step(error=ConnectionFailedError("refused")) for _ in range(5)])
        decision = harness.gate.allows("https://cpwd.test/a")
        assert not decision.allowed
        assert "unreadable" in decision.reason

    def test_a_host_the_source_may_not_use_permits_nothing(self) -> None:
        """The guard refuses the robots fetch, and an unreadable file denies.

        Not merely defence in depth: the URL would be refused by the guard anyway. It matters that
        the *robots* answer is also a refusal, because a decision of "allowed" here would be written
        into a frontier row as permission for a URL nobody may fetch.
        """
        harness = gate_for([plain("User-agent: *\nAllow: /")])
        assert not harness.gate.allows("https://evilcpwd.test/a").allowed
        assert harness.transport.urls == []


class TestWhenTheBodyIsNotARobotsFile:
    def test_html_is_treated_as_no_robots_file_at_all(self) -> None:
        """Measured against morth.gov.in, which answers every path with its app shell.

        Denying here would make every pushState single-page site permanently uncrawlable, which is
        not what a routing quirk means.
        """
        harness = gate_for(
            [Step(status=200, body=b"<!doctype html><html></html>", content_type="text/html")]
        )
        decision = harness.gate.allows("https://cpwd.test/a")
        assert decision.allowed
        assert "absent" in decision.reason
        assert "text/html" in decision.reason

    def test_markup_declared_as_plain_text_permits_nothing(self) -> None:
        """The case the media-type rule cannot catch. A parse failure rejects (rule 81b).

        We asked for robots.txt, something answered 200 text/plain, and what came back was a web
        page with no directives in it. We did not read the file, so we do not proceed.
        """
        harness = gate_for([Step(status=200, body=b"<!DOCTYPE html><html><body>404</body></html>")])
        decision = harness.gate.allows("https://cpwd.test/a")
        assert decision.verdict is RobotsVerdict.DISALLOWED
        assert "unreadable" in decision.reason

    def test_markup_that_also_carries_directives_is_still_obeyed(self) -> None:
        """Belt and braces: the markup rule fires only when nothing was parsed.

        A server that wraps a real robots.txt in a template is misconfigured, but the rules in it
        are still the operator's wishes.
        """
        harness = gate_for([plain("<html>\nUser-agent: *\nDisallow: /private\n</html>")])
        assert not harness.gate.allows("https://cpwd.test/private").allowed

    def test_a_missing_content_type_is_read_as_plain_text(self) -> None:
        """Refusing to read a robots.txt because a header was missing would deny over nothing."""
        harness = gate_for(
            [Step(status=200, body=b"User-agent: *\nDisallow: /private", content_type=None)]
        )
        assert not harness.gate.allows("https://cpwd.test/private").allowed

    def test_an_empty_file_permits_everything(self) -> None:
        harness = gate_for([plain("")])
        decision = harness.gate.allows("https://cpwd.test/a")
        assert decision.allowed
        assert "absent" in decision.reason


class TestNotApplicable:
    def test_a_source_that_declares_robots_not_applicable_makes_no_request(self) -> None:
        """The strongest assertion in this file, and it is a negative one.

        ``not_applicable`` must mean "do not ask", not "ask and ignore the answer". Fetching and
        then discarding the result would pass every other test here while making one pointless
        request per authority to a site it has already decided not to listen to.
        """
        harness = gate_for([], respect=False)
        decision = harness.gate.allows("https://cpwd.test/anything")
        assert decision.allowed
        assert "not_applicable" in decision.reason
        assert harness.transport.urls == []
