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
``controller``
    The retry loop. Orchestrates the limiter, the budget, the policy, and the transport; decides
    nothing itself. Takes a rate-limit slot per attempt and keeps the attempt history.
``ratelimit``
    Per-source politeness and the global concurrency ceiling, from each source's registry entry.
``redirects``
    Redirect decisions, including the transport-downgrade rule. Returns a URL that the caller
    must re-validate; it never confers permission.
``transport``
    The boundary that opens sockets, and the error taxonomy every failure is converted into. It
    accepts only a ``ValidatedTarget`` and owns no retry, redirect, or rate-limit policy.
``httpx_transport``
    The one implementation. Isolated so the library it uses is replaceable and so the boundary
    above stays free of any HTTP client's types.

See ``docs/security/threat-model-http-fetch.md`` and
``docs/adr/0010-fetch-retry-ssrf-policy.md``.
"""

from __future__ import annotations

from aedifex.acquisition.fetch.addresses import (
    AddressRejection,
    classify_address,
    is_publicly_routable,
)
from aedifex.acquisition.fetch.controller import (
    AttemptRecord,
    Cancellation,
    FetchCancelledError,
    FetchFailedError,
    FetchResult,
    RetryController,
)
from aedifex.acquisition.fetch.guard import ValidatedTarget, validate_url
from aedifex.acquisition.fetch.hosts import SourceHostPolicy
from aedifex.acquisition.fetch.httpx_transport import HttpxTransport
from aedifex.acquisition.fetch.ratelimit import RateLimiter, RateLimits
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
    Deadline,
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
from aedifex.acquisition.fetch.transport import (
    ALLOWED_METHODS,
    DEFAULT_CHUNK_SIZE,
    DEFAULT_MAX_RESPONSE_BYTES,
    BudgetExhaustedError,
    ConnectionFailedError,
    ConnectTimeoutError,
    ProtocolError,
    RawResponse,
    ReadTimeoutError,
    ResponseHeaders,
    ResponseStreamError,
    ResponseTooLargeError,
    TlsVerificationError,
    Transport,
    TransportError,
    TransportTimeouts,
    UnclassifiedTransportError,
    parse_content_length,
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
    "ALLOWED_METHODS",
    "ALLOWED_PORTS",
    "ALLOWED_SCHEMES",
    "DEFAULT_CHUNK_SIZE",
    "DEFAULT_MAX_RESPONSE_BYTES",
    "MAX_SERVER_REQUESTED_DELAY_SECONDS",
    "NON_RETRYABLE_STATUSES",
    "REDIRECT_STATUSES",
    "RETRYABLE_STATUSES",
    "AddressRejection",
    "AttemptOutcome",
    "AttemptRecord",
    "AttemptResult",
    "BackoffPolicy",
    "BudgetExhaustedError",
    "Cancellation",
    "Clock",
    "ConnectTimeoutError",
    "ConnectionFailedError",
    "Deadline",
    "FetchCancelledError",
    "FetchFailedError",
    "FetchResult",
    "HttpxTransport",
    "MonotonicClock",
    "NormalizedUrl",
    "ProtocolError",
    "RandomSource",
    "RateLimiter",
    "RateLimits",
    "RawResponse",
    "ReadTimeoutError",
    "RedirectDecision",
    "RedirectOutcome",
    "RedirectPolicy",
    "RejectionReason",
    "ResolvedAddress",
    "Resolver",
    "ResponseHeaders",
    "ResponseStreamError",
    "ResponseTooLargeError",
    "RetryController",
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
    "TlsVerificationError",
    "Transport",
    "TransportError",
    "TransportTimeouts",
    "UnclassifiedTransportError",
    "UnparseableDnsAnswerError",
    "ValidatedTarget",
    "classify_address",
    "is_publicly_routable",
    "normalize_url",
    "parse_content_length",
    "parse_retry_after",
    "validate_url",
]
