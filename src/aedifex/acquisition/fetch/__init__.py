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
from aedifex.acquisition.fetch.resolver import ResolvedAddress, Resolver, SystemResolver
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
    "AddressRejection",
    "NormalizedUrl",
    "RejectionReason",
    "ResolvedAddress",
    "Resolver",
    "SourceHostPolicy",
    "SsrfRejectionError",
    "SystemResolver",
    "ValidatedTarget",
    "classify_address",
    "is_publicly_routable",
    "normalize_url",
    "validate_url",
]
