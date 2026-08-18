"""``robots.txt``: reading a site operator's wishes, and obeying them.

The registry has demanded this since the beginning — ``robots_policy: respect`` is mandatory for
every HTML-crawling source, and DATA_SOURCES.md lists ignoring it under "Hard limits" — and until
now nothing implemented it. A declared control that no code enforces is worse than an absent one,
because it makes a reader believe the site is being asked.

Two halves, deliberately separated:

:func:`parse_robots`
    Pure. Text in, rules out. No network, no clock, no cache, so every awkward file shape can be
    tested as a one-liner and fuzzed.

:class:`RobotsGate`
    Fetches ``/robots.txt`` through the frozen fetch stack, caches it per authority for the run, and
    turns HTTP outcomes into permission. The fetch counts against the source's own rate limit,
    because asking for ``robots.txt`` is asking the site for something.

Why not ``urllib.robotparser``
------------------------------

Two disqualifying problems, neither cosmetic. Its ``read()`` fetches with ``urllib``, which would
step straight around the SSRF guard that every other request in this project goes through — the
robots fetch is a request to a remote host chosen from configuration, and it gets the same
treatment as any other. And it cannot report that a file was unparseable: it silently yields
"allow everything", which is the one answer a failure must never produce (rule 81b).

What an HTTP status means
-------------------------

Following RFC 9309 §2.3.1, which is both the standard and the fail-closed reading:

==================  ==========================================================================
2xx                 Parse it. An empty body is a valid file that permits everything.
3xx                 Followed by the redirect controller, re-validated per hop as always.
4xx except 429      No ``robots.txt`` exists. Everything is permitted.
429, 5xx, no answer **Nothing** is permitted. We could not read it, so we do not proceed.
==================  ==========================================================================

The asymmetry is the point. A 404 is an answer — the site is saying there are no rules. A 503 is
the absence of an answer, and treating silence as consent is how a crawler ends up hammering a site
that was trying to tell it to stop.

Two real portals shaped the rules below, and both were measured rather than imagined:

* ``morth.gov.in`` answers **every** path with its single-page-app shell, so ``/robots.txt`` returns
  HTTP 200 with 40 KB of HTML. A body that is not ``text/plain`` is not a robots file. Denying on it
  would make every pushState site permanently uncrawlable; treating it as permission would be
  sloppy. So the media type decides whether a robots file exists at all, and markup that declares no
  directives is a *failure to read*, which denies.
* ``nhai.gov.in`` has no ``robots.txt`` at all — a plain 404, which permits everything and means
  politeness rests entirely on our own configured rate limits.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from enum import StrEnum
from typing import Final
from urllib.parse import SplitResult, urlsplit, urlunsplit

from aedifex.acquisition.fetch.controller import FetchFailedError
from aedifex.acquisition.fetch.hosts import SourceHostPolicy
from aedifex.acquisition.fetch.ratelimit import RateLimits
from aedifex.acquisition.fetch.redirect_controller import (
    RedirectController,
    RedirectRejectedError,
)
from aedifex.acquisition.fetch.timing import MonotonicClock, TimeoutBudget, TimeoutPolicy
from aedifex.acquisition.fetch.transport import RawResponse, TransportError
from aedifex.acquisition.fetch.urls import SsrfRejectionError
from aedifex.acquisition.registry.models import RobotsPolicy, SourceDefinition

__all__ = [
    "MAX_HONOURABLE_CRAWL_DELAY_SECONDS",
    "MAX_ROBOTS_BYTES",
    "CrawlDelayTooLongError",
    "RobotsDecision",
    "RobotsGate",
    "RobotsRules",
    "RobotsVerdict",
    "parse_robots",
    "polite_limits",
]

MAX_ROBOTS_BYTES: Final[int] = 500 * 1024
"""How much of a ``robots.txt`` is parsed. RFC 9309 §2.3.1.1 requires at least 500 KiB.

Content past this is ignored rather than treated as an error, which is what the RFC asks for: a
misconfigured site that serves a gigantic file has not thereby forbidden us anything.
"""

_FETCH_CEILING_BYTES: Final[int] = 4 * 1024 * 1024
"""What the transport is allowed to deliver before it refuses outright.

Larger than the parse limit so that truncation, not rejection, is the normal handling of an
oversized file — the transport refuses on the *declared* length too, and denying a whole source over
a fat ``robots.txt`` would be the wrong outcome. Past this it is unreadable, and unreadable denies.
"""

MAX_HONOURABLE_CRAWL_DELAY_SECONDS: Final[float] = 300.0
"""The longest ``Crawl-delay`` this project will accept, matching the registry's own ceiling.

Beyond it we refuse to crawl rather than quietly crawl faster than asked. A file saying
``Crawl-delay: 86400`` is telling us one request a day; silently capping that at five minutes would
be a decision to disobey, taken by a constant.
"""

_ROBOTS_PATH: Final[str] = "/robots.txt"
_READ_CHUNK: Final[int] = 16 * 1024
_PLAIN_TEXT: Final[str] = "text/plain"
_MARKUP_HINTS: Final[tuple[str, ...]] = ("<html", "<!doctype", "<?xml", "<head", "<body")


class RobotsVerdict(StrEnum):
    ALLOWED = "allowed"
    DISALLOWED = "disallowed"


@dataclass(frozen=True, slots=True)
class RobotsDecision:
    """Whether one URL may be fetched, and which line of which file said so.

    The reason is carried rather than derived later because it ends up in a frontier row and a log
    line: "skipped, disallowed by ``Disallow: /search``" is actionable, and "skipped" is not.
    """

    verdict: RobotsVerdict
    reason: str
    rule: str | None = None

    @property
    def allowed(self) -> bool:
        return self.verdict is RobotsVerdict.ALLOWED

    def describe(self) -> str:
        if self.rule is None:
            return f"{self.verdict.value}: {self.reason}"
        return f"{self.verdict.value}: {self.reason} ({self.rule})"


@dataclass(frozen=True, slots=True)
class _Rule:
    """One ``Allow`` or ``Disallow`` line, compiled."""

    allow: bool
    pattern: str
    expression: re.Pattern[str]

    @property
    def specificity(self) -> int:
        """Longer patterns win, per RFC 9309 §2.2.2. ``$`` does not count towards length."""
        return len(self.pattern.removesuffix("$"))

    def matches(self, target: str) -> bool:
        return self.expression.match(target) is not None

    def describe(self) -> str:
        return f"{'Allow' if self.allow else 'Disallow'}: {self.pattern}"


def _outranks(candidate: _Rule, incumbent: _Rule) -> bool:
    """Whether ``candidate`` wins, per RFC 9309 §2.2.2: longest pattern, ``Allow`` breaking ties."""
    if candidate.specificity != incumbent.specificity:
        return candidate.specificity > incumbent.specificity
    return candidate.allow and not incumbent.allow


@dataclass(frozen=True, slots=True)
class RobotsRules:
    """The rules that apply to *us*, extracted from one ``robots.txt``."""

    rules: tuple[_Rule, ...] = ()
    crawl_delay_seconds: float | None = None
    sitemaps: tuple[str, ...] = ()
    matched_agent: str | None = None
    """Which ``User-agent`` group we obeyed: our own product token, or ``*``, or nothing."""
    saw_any_directive: bool = False
    """Whether the file contained a single line we recognised.

    Distinguishes "an empty file, which permits everything" from "a body we could not read at all",
    which the gate must treat as a refusal rather than as permission.
    """

    def decide(self, path_and_query: str) -> RobotsDecision:
        """Decide one already-normalised path (with query string, if any).

        Precedence is RFC 9309 §2.2.2: the longest matching pattern wins, and ``Allow`` beats
        ``Disallow`` on an exact tie. The tie rule matters — a file with ``Disallow: /docs`` and
        ``Allow: /docs`` means the narrower permission, and resolving it the other way would refuse
        content the operator explicitly offered.
        """
        best: _Rule | None = None
        for rule in self.rules:
            if rule.matches(path_and_query) and (best is None or _outranks(rule, best)):
                best = rule

        if best is None:
            return RobotsDecision(RobotsVerdict.ALLOWED, "no rule matches this path")
        if best.allow:
            return RobotsDecision(RobotsVerdict.ALLOWED, "permitted by robots.txt", best.describe())
        return RobotsDecision(RobotsVerdict.DISALLOWED, "refused by robots.txt", best.describe())


class CrawlDelayTooLongError(Exception):
    """A ``Crawl-delay`` longer than this project is willing to wait for.

    Raised rather than clamped: the alternative is to crawl faster than the operator asked, which is
    exactly the thing reading ``robots.txt`` was supposed to prevent.
    """


def polite_limits(limits: RateLimits, rules: RobotsRules) -> RateLimits:
    """Fold a ``Crawl-delay`` into a source's configured limits, taking the more polite of the two.

    ``Crawl-delay`` is not in RFC 9309 — it is a widely honoured extension — and it is honoured here
    because a site that bothers to state a delay has stated the one number this project most needs.
    Only ever slows us down: a delay shorter than the configured one is ignored, because our own
    configuration is a floor we chose and a site asking us to hurry is not a reason to.

    Raises:
        CrawlDelayTooLongError: if the requested delay exceeds
            :data:`MAX_HONOURABLE_CRAWL_DELAY_SECONDS`.
    """
    requested = rules.crawl_delay_seconds
    if requested is None or requested <= limits.min_delay_seconds:
        return limits
    if requested > MAX_HONOURABLE_CRAWL_DELAY_SECONDS:
        raise CrawlDelayTooLongError(
            f"robots.txt asks for {requested}s between requests, which exceeds the "
            f"{MAX_HONOURABLE_CRAWL_DELAY_SECONDS}s this project will wait. Crawling this source "
            f"would mean disobeying a delay the operator stated explicitly"
        )
    # The rolling-rate cap has to come down with the delay, or the two limits contradict each other
    # and the limiter's arithmetic silently resolves it. One request per `requested` seconds is what
    # was asked for; at least one per minute, since the limiter refuses zero.
    reachable = max(1, int(60.0 // requested))
    return RateLimits(
        requests_per_minute=min(limits.requests_per_minute, reachable),
        max_concurrency=1,
        min_delay_seconds=requested,
    )


def parse_robots(text: str, *, user_agent: str) -> RobotsRules:
    """Parse ``robots.txt`` and keep only the group that applies to ``user_agent``.

    Pure and total: it never raises. Unrecognised lines are ignored, which RFC 9309 §2.2 requires —
    ``robots.txt`` is an extensible format and a ``Sitemap`` or ``Host`` line is not an error. What
    a caller must check is :attr:`RobotsRules.saw_any_directive`, which separates a file that says
    nothing from a body that was not a robots file at all.

    Group selection is the most specific matching ``User-agent``, with ``*`` as the fallback.
    Matching is a case-insensitive substring test against our product token, so ``User-agent: bot``
    binds a crawler identifying as ``AedifexBot/0.1``. That is looser than an equality test and
    deliberately so: every ambiguity here is resolved towards obeying more rules rather than fewer.
    """
    token = _product_token(user_agent)
    groups = _collect_groups(text)

    best_agent: str | None = None
    best_score = -1
    for agent in groups:
        score = _agent_specificity(agent, token)
        if score > best_score:
            best_agent, best_score = agent, score

    saw_any = any(group.saw_directive for group in groups.values())
    if best_agent is None:
        return RobotsRules(saw_any_directive=saw_any)

    chosen = groups[best_agent]
    return RobotsRules(
        rules=tuple(chosen.rules),
        crawl_delay_seconds=chosen.crawl_delay,
        sitemaps=tuple(_sitemaps(text)),
        matched_agent=best_agent,
        saw_any_directive=saw_any,
    )


@dataclass(slots=True)
class _Group:
    rules: list[_Rule]
    crawl_delay: float | None = None
    saw_directive: bool = False


def _collect_groups(text: str) -> dict[str, _Group]:
    """Split the file into ``User-agent`` groups.

    Consecutive ``User-agent`` lines share one group of rules, which is the part of the format most
    often got wrong: a file listing three agents and then one ``Disallow`` has disallowed that path
    for all three, not just the last.
    """
    groups: dict[str, _Group] = {}
    current: list[str] = []
    starting_new_group = True

    for line in _lines(text):
        parsed = _split_directive(line)
        if parsed is None:
            continue
        name, value = parsed

        if name == "user-agent":
            if not starting_new_group:
                current = []
                starting_new_group = True
            agent = value.lower()
            if agent:
                current.append(agent)
                groups.setdefault(agent, _Group(rules=[]))
            continue

        if name in ("allow", "disallow"):
            starting_new_group = False
            for agent in current:
                groups[agent].saw_directive = True
                # An empty Disallow value is an explicit "nothing is forbidden" and adds no rule;
                # an empty Allow adds nothing either. Both still count as directives seen, so the
                # file is not mistaken for unreadable.
                if value:
                    groups[agent].rules.append(_compile_rule(allow=name == "allow", pattern=value))
            continue

        if name == "crawl-delay":
            starting_new_group = False
            delay = _positive_float(value)
            if delay is not None:
                for agent in current:
                    groups[agent].saw_directive = True
                    existing = groups[agent].crawl_delay
                    # The longest delay stated for us wins, for the same reason as everywhere else
                    # in this module: when a file is ambiguous, be more polite, not less.
                    groups[agent].crawl_delay = delay if existing is None else max(existing, delay)
            continue

        # Anything else — Sitemap, Host, a vendor extension, a typo — ends the agent header without
        # contributing a rule. RFC 9309 §2.2: unrecognised lines are ignored, not fatal.
        starting_new_group = False

    return groups


def _lines(text: str) -> list[str]:
    """Split on any line ending, drop comments and the BOM."""
    body = text.lstrip("﻿")
    return [line.split("#", 1)[0].strip() for line in re.split(r"\r\n|\r|\n", body)]


def _split_directive(line: str) -> tuple[str, str] | None:
    if not line or ":" not in line:
        return None
    name, _, value = line.partition(":")
    return name.strip().lower(), value.strip()


def _compile_rule(*, allow: bool, pattern: str) -> _Rule:
    """Compile a path pattern, where ``*`` matches anything and a trailing ``$`` anchors the end."""
    anchored = pattern.endswith("$")
    body = pattern.removesuffix("$") if anchored else pattern
    expression = ".*".join(re.escape(part) for part in body.split("*"))
    return _Rule(
        allow=allow,
        pattern=pattern,
        expression=re.compile(f"^{expression}{'$' if anchored else ''}"),
    )


def _product_token(user_agent: str) -> str:
    """The bare product name from a User-Agent, e.g. ``aedifexbot`` from ``AedifexBot/0.1 (+…)``."""
    return re.split(r"[/\s]", user_agent.strip(), maxsplit=1)[0].lower()


def _agent_specificity(agent: str, token: str) -> int:
    """How well a group header matches us. ``-1`` means it does not."""
    if agent == "*":
        return 0
    return len(agent) if agent in token else -1


def _sitemaps(text: str) -> list[str]:
    """``Sitemap`` is a file-level directive, not part of any group."""
    found: list[str] = []
    for line in _lines(text):
        parsed = _split_directive(line)
        if parsed is not None and parsed[0] == "sitemap" and parsed[1]:
            found.append(parsed[1])
    return found


def _positive_float(value: str) -> float | None:
    try:
        number = float(value)
    except ValueError:
        return None
    return number if number > 0 and number == number and number != float("inf") else None


_ALLOW_ALL: Final[RobotsRules] = RobotsRules(saw_any_directive=False)
_DENY_ALL: Final[RobotsRules] = RobotsRules(
    rules=(_compile_rule(allow=False, pattern="/"),), saw_any_directive=True
)


class _Origin(StrEnum):
    """Where a set of rules came from. A value, never inferred from the reason text.

    Load-bearing rather than cosmetic. An unreadable ``robots.txt`` denies everything, and the
    obvious way to express that — hand back rules containing ``Disallow: /`` — makes the refusal
    indistinguishable from a site that really did forbid everything. The frontier row would then
    record "refused by robots.txt" for a portal that merely failed to answer: a false provenance
    record, and the kind nobody ever discovers.
    """

    PARSED = "parsed"
    ABSENT = "absent"
    UNREADABLE = "unreadable"


@dataclass(frozen=True, slots=True)
class _CachedRobots:
    rules: RobotsRules
    origin: _Origin
    reason: str
    """Why these rules, for the log and for the frontier row."""


class RobotsGate:
    """Decides whether a URL may be fetched, per authority, fetching ``robots.txt`` at most once.

    One instance per source per run. Not global: the rules that apply depend on the User-Agent we
    present and on which hosts the source is permitted to serve from, and a cache shared across
    sources would answer for the wrong crawler.
    """

    def __init__(
        self,
        *,
        redirects: RedirectController,
        user_agent: str,
        host_policy: SourceHostPolicy,
        limits: RateLimits,
        timeouts: TimeoutPolicy | None = None,
        respect: bool = True,
    ) -> None:
        self._redirects = redirects
        self._user_agent = user_agent
        self._host_policy = host_policy
        self._limits = limits
        self._timeouts = timeouts if timeouts is not None else TimeoutPolicy()
        self._respect = respect
        self._cache: dict[str, _CachedRobots] = {}
        # A lock rather than trusting the GIL: two workers starting on the same host must make one
        # request, not two, and "probably one" is not a politeness guarantee.
        self._lock = threading.Lock()

    @classmethod
    def from_source(
        cls,
        source: SourceDefinition,
        *,
        redirects: RedirectController,
        user_agent: str,
        host_policy: SourceHostPolicy,
        limits: RateLimits,
        timeouts: TimeoutPolicy | None = None,
    ) -> RobotsGate:
        """Build the gate a source's registry entry asks for.

        ``robots_policy: not_applicable`` produces a gate that permits everything without fetching.
        The schema only allows that for sources which are not HTML crawls, and it is recorded here
        rather than hidden so that "this source ignores robots.txt" is visible in one place.
        """
        return cls(
            redirects=redirects,
            user_agent=user_agent,
            host_policy=host_policy,
            limits=limits,
            timeouts=timeouts,
            respect=source.robots_policy is RobotsPolicy.RESPECT,
        )

    def allows(self, url: str) -> RobotsDecision:
        """Whether ``url`` may be fetched. Fetches that authority's ``robots.txt`` if not cached."""
        if not self._respect:
            return RobotsDecision(
                RobotsVerdict.ALLOWED, "source declares robots_policy: not_applicable"
            )
        parts = urlsplit(url)
        cached = self._rules_for(parts)
        if cached.origin is _Origin.UNREADABLE:
            # No rule of the site's said this. Say so, rather than inventing one it never wrote.
            return RobotsDecision(RobotsVerdict.DISALLOWED, cached.reason)
        target = parts.path or "/"
        if parts.query:
            target = f"{target}?{parts.query}"
        decision = cached.rules.decide(target)
        if decision.rule is None:
            return RobotsDecision(decision.verdict, cached.reason, None)
        return decision

    def crawl_delay(self, url: str) -> float | None:
        """The ``Crawl-delay`` that applies to us at ``url``'s authority, if any."""
        return self._rules_for(urlsplit(url)).rules.crawl_delay_seconds

    def rules_for(self, url: str) -> RobotsRules:
        """The parsed rules for ``url``'s authority. Exposed for the runner's politeness folding."""
        return self._rules_for(urlsplit(url)).rules

    def _rules_for(self, parts: SplitResult) -> _CachedRobots:
        authority = f"{parts.scheme}://{parts.netloc}"
        with self._lock:
            cached = self._cache.get(authority)
            if cached is None:
                cached = self._fetch(scheme=parts.scheme, netloc=parts.netloc)
                self._cache[authority] = cached
            return cached

    def _fetch(self, *, scheme: str, netloc: str) -> _CachedRobots:
        """Fetch and interpret one authority's ``robots.txt``. Never raises."""
        url = urlunsplit((scheme, netloc, _ROBOTS_PATH, "", ""))
        budget = TimeoutBudget(policy=self._timeouts, clock=MonotonicClock())
        try:
            with self._redirects.fetch(
                url,
                host_policy=self._host_policy,
                limits=self._limits,
                budget=budget,
                max_response_bytes=_FETCH_CEILING_BYTES,
            ) as chain:
                return self._interpret(chain.response, url=url)
        except FetchFailedError as error:
            status = error.attempts[-1].status_code if error.attempts else None
            return self._from_status(status, url=url)
        except (SsrfRejectionError, RedirectRejectedError, TransportError) as error:
            # No answer at all. RFC 9309 §2.3.1.4: assume complete disallow.
            return _CachedRobots(
                _DENY_ALL,
                _Origin.UNREADABLE,
                f"unreadable: {url} could not be fetched ({type(error).__name__}), so nothing is "
                f"permitted",
            )

    def _interpret(self, response: RawResponse, *, url: str) -> _CachedRobots:
        declared = (response.headers.get("content-type") or "").split(";", 1)[0].strip().lower()
        body = _read_text(response)

        # A missing Content-Type is treated as plain text: most servers send one, and refusing to
        # read a robots.txt because a header was absent would deny a site over a triviality.
        if declared and declared != _PLAIN_TEXT:
            return _CachedRobots(
                _ALLOW_ALL,
                _Origin.ABSENT,
                f"absent: {url} answered {declared!r} rather than {_PLAIN_TEXT!r}, so there is no "
                f"robots.txt to obey",
            )

        rules = parse_robots(body, user_agent=self._user_agent)
        if not rules.saw_any_directive and _looks_like_markup(body):
            # text/plain, but the body is a web page. We did not read a robots.txt, and rule 81b
            # says a parse failure rejects rather than being treated as an absence.
            return _CachedRobots(
                _DENY_ALL,
                _Origin.UNREADABLE,
                f"unreadable: {url} answered markup declared as {_PLAIN_TEXT!r} with no directives",
            )
        if not rules.saw_any_directive:
            return _CachedRobots(
                rules, _Origin.ABSENT, f"absent: {url} states no rules, so everything is permitted"
            )
        group = f" group {rules.matched_agent!r}" if rules.matched_agent else ""
        return _CachedRobots(rules, _Origin.PARSED, f"parsed: {url}{group}")

    def _from_status(self, status: int | None, *, url: str) -> _CachedRobots:
        if status is None:
            return _CachedRobots(
                _DENY_ALL,
                _Origin.UNREADABLE,
                f"unreadable: {url} produced no response, so nothing is permitted",
            )
        if status == 429 or status >= 500:
            # RFC 9309 §2.3.1.4. A 429 is rate limiting, not an absence: the site is asking us to
            # slow down, and reading that as "no rules exist" is the worst available reading.
            return _CachedRobots(
                _DENY_ALL,
                _Origin.UNREADABLE,
                f"unreadable: {url} answered HTTP {status}, which is the absence of an answer "
                f"rather than an answer of 'no rules'",
            )
        if 400 <= status < 500:
            # RFC 9309 §2.3.1.3: unavailable means unrestricted.
            return _CachedRobots(
                _ALLOW_ALL,
                _Origin.ABSENT,
                f"absent: {url} answered HTTP {status}, so no robots.txt exists",
            )
        return _CachedRobots(
            _DENY_ALL, _Origin.UNREADABLE, f"unreadable: {url} answered an unexpected HTTP {status}"
        )


def _read_text(response: RawResponse) -> str:
    """Read at most :data:`MAX_ROBOTS_BYTES` and decode leniently.

    Truncation rather than refusal, per RFC 9309 §2.3.1.1, and lossy decoding for the same reason:
    a stray invalid byte in a comment must not turn a readable file into a refusal, and the RFC
    requires invalid UTF-8 to be ignored rather than to be fatal.
    """
    chunks: list[bytes] = []
    total = 0
    for chunk in response.iter_bytes(_READ_CHUNK):
        chunks.append(chunk)
        total += len(chunk)
        if total >= MAX_ROBOTS_BYTES:
            break
    return b"".join(chunks)[:MAX_ROBOTS_BYTES].decode("utf-8", errors="replace")


def _looks_like_markup(body: str) -> bool:
    head = body[:2048].lstrip().lower()
    return any(hint in head for hint in _MARKUP_HINTS)
