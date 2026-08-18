"""Outbound HTTP fetching.

Layered so the security boundary is unambiguous:

``addresses``
    Global network safety policy. Which IP addresses may ever be contacted, by anyone.
``urls``
    Parsing and normalisation, so the authority validated is the authority contacted.
``hosts``
    Per-source host policy, kept separate from global network safety.
``resolver``
    DNS behind a protocol, so single-resolution can be proven and rebinding tested.
``guard``
    The gate. Produces :class:`~aedifex.acquisition.fetch.guard.ValidatedTarget`, which is the
    only thing the transport layer will accept.
``timing``
    Injected clock, sleeper, and randomness; the request timeout budget; ``Retry-After`` parsing.
``retry``
    Retry classification. Pure policy: never sleeps, never performs I/O.
``redirects``
    Redirect decisions, including the transport-downgrade rule. Returns a URL that the caller
    must re-validate; it never confers permission.

See ``docs/security/threat-model-http-fetch.md`` and
``docs/adr/0010-fetch-retry-ssrf-policy.md``.
"""

from __future__ import annotations

from aedifex.acquisition.fetch.addresses import (
    AddressRejection,
    classify_address,
    is_publicly_routable,
)
from aedifex.acquisition.fetch.guard import ValidatedTarget, validate_url
from aedifex.acquisition.fetch.hosts import SourceHostPolicy
from aedifex.acquisition.fetch.redirects import (
    REDIRECT_STATUSES,
    RedirectDecision,
    RedirectOutcome,
    RedirectPolicy,
)
from aedifex.acquisition.fetch.resolver import (
    ResolvedAddress,
    Resolver,
    SystemResolver,
    UnparseableDnsAnswerError,
)
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
from aedifex.acquisition.fetch.timing import (
    MAX_SERVER_REQUESTED_DELAY_SECONDS,
    Clock,
    MonotonicClock,
    RandomSource,
    Sleeper,
    SystemRandomSource,
    SystemSleeper,
    TimeoutBudget,
    TimeoutBudgetExhaustedError,
    TimeoutPolicy,
    parse_retry_after,
)
from aedifex.acquisition.fetch.urls import (
    ALLOWED_PORTS,
    ALLOWED_SCHEMES,
    NormalizedUrl,
    RejectionReason,
    SsrfRejectionError,
    normalize_url,
)

__all__ = [
    "ALLOWED_PORTS",
    "ALLOWED_SCHEMES",
    "MAX_SERVER_REQUESTED_DELAY_SECONDS",
    "NON_RETRYABLE_STATUSES",
    "REDIRECT_STATUSES",
    "RETRYABLE_STATUSES",
    "AddressRejection",
    "AttemptOutcome",
    "AttemptResult",
    "BackoffPolicy",
    "Clock",
    "MonotonicClock",
    "NormalizedUrl",
    "RandomSource",
    "RedirectDecision",
    "RedirectOutcome",
    "RedirectPolicy",
    "RejectionReason",
    "ResolvedAddress",
    "Resolver",
    "RetryDecision",
    "RetryPolicy",
    "RetryVerdict",
    "Sleeper",
    "SourceHostPolicy",
    "SsrfRejectionError",
    "SystemRandomSource",
    "SystemResolver",
    "SystemSleeper",
    "TimeoutBudget",
    "TimeoutBudgetExhaustedError",
    "TimeoutPolicy",
    "UnparseableDnsAnswerError",
    "ValidatedTarget",
    "classify_address",
    "is_publicly_routable",
    "normalize_url",
    "parse_retry_after",
    "validate_url",
]
