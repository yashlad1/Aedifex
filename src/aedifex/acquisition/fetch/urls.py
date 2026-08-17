"""URL parsing and normalisation for the SSRF guard.

The single property this module exists to guarantee:

    **the authority that is validated is exactly the authority that will be contacted.**

Every SSRF bypass in this class of code comes from breaking that equivalence — validating a
string that a later parser interprets differently. So normalisation happens once, here, and the
result is what downstream code uses. Nothing re-parses the original string.

Normalisation is applied to the parts policy decisions are made on: scheme and host casing, the
trailing root-label dot, IDNA/punycode, IPv6 bracket notation, and default ports. Path and query
are carried through untouched — they are not authority, and rewriting them could change which
document a portal serves.
"""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Final
from urllib.parse import urlsplit, urlunsplit

from aedifex.acquisition.fetch.addresses import IpAddress
from aedifex.errors import AcquisitionError

__all__ = [
    "ALLOWED_PORTS",
    "ALLOWED_SCHEMES",
    "NormalizedUrl",
    "RejectionReason",
    "SsrfRejectionError",
    "normalize_url",
]

ALLOWED_SCHEMES: Final[frozenset[str]] = frozenset({"http", "https"})

# Only the standard web ports. A source needing another port is a registry change, not a
# loosening here: an arbitrary port on an allowlisted host is still a service we never intended
# to speak to. Fail closed by default.
ALLOWED_PORTS: Final[frozenset[int]] = frozenset({80, 443})

_DEFAULT_PORTS: Final[dict[str, int]] = {"http": 80, "https": 443}

# One DNS label: alphanumeric, internal hyphens, 1-63 characters. Deliberately excludes
# underscores, which are invalid in hostnames and a known source of parser disagreement.
_LABEL: Final[re.Pattern[str]] = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")

# Suffixes that only ever name something inside a private network.
_FORBIDDEN_SUFFIXES: Final[tuple[str, ...]] = (
    ".local",
    ".internal",
    ".localdomain",
    ".localhost",
    ".home",
    ".lan",
    ".corp",
    ".intranet",
)

_MAX_HOSTNAME_LENGTH: Final[int] = 253
_MAX_URL_LENGTH: Final[int] = 2048


class RejectionReason(StrEnum):
    """Why a URL was refused. Reported on every rejection for metrics and diagnosis."""

    MALFORMED_URL = "malformed_url"
    URL_TOO_LONG = "url_too_long"
    DISALLOWED_SCHEME = "disallowed_scheme"
    EMBEDDED_CREDENTIALS = "embedded_credentials"
    MISSING_HOST = "missing_host"
    MALFORMED_HOST = "malformed_host"
    FORBIDDEN_HOST_SUFFIX = "forbidden_host_suffix"
    SINGLE_LABEL_HOST = "single_label_host"
    DISALLOWED_PORT = "disallowed_port"
    HOST_NOT_ALLOWED_FOR_SOURCE = "host_not_allowed_for_source"
    IP_LITERAL_NOT_ALLOWED = "ip_literal_not_allowed"
    UNRESOLVABLE_HOST = "unresolvable_host"
    NO_ADDRESSES_RETURNED = "no_addresses_returned"
    FORBIDDEN_ADDRESS = "forbidden_address"
    TOO_MANY_REDIRECTS = "too_many_redirects"
    REDIRECT_LOOP = "redirect_loop"


class SsrfRejectionError(AcquisitionError):
    """A URL was refused before any connection was attempted.

    Its own type because these events are security-relevant and counted separately from
    transport failures: a rejection means either a crawler bug or a hostile redirect, and both
    warrant a look rather than a retry.
    """

    def __init__(self, reason: RejectionReason, detail: str) -> None:
        self.reason = reason
        self.detail = detail
        super().__init__(f"{reason.value}: {detail}")


@dataclass(frozen=True, slots=True)
class NormalizedUrl:
    """A URL reduced to a canonical form, with its authority decomposed.

    ``host`` is lowercase, punycode, and carries no trailing dot; ``port`` is always explicit.
    ``ip_literal`` is set when the authority was written as an address rather than a name, which
    the guard must know because such a URL needs no DNS resolution.
    """

    scheme: str
    host: str
    port: int
    path: str
    query: str
    ip_literal: IpAddress | None

    @property
    def is_ip_literal(self) -> bool:
        return self.ip_literal is not None

    @property
    def netloc(self) -> str:
        """Authority as it should appear in a request, omitting a default port."""
        host = f"[{self.host}]" if self.ip_literal and self.host.count(":") else self.host
        if self.port == _DEFAULT_PORTS[self.scheme]:
            return host
        return f"{host}:{self.port}"

    def to_url(self) -> str:
        """Render the canonical absolute URL."""
        return urlunsplit((self.scheme, self.netloc, self.path or "/", self.query, ""))


def normalize_url(raw: str) -> NormalizedUrl:
    """Parse and normalise ``raw``, applying the scheme, credential, and host-shape rules.

    This covers steps 1-3 of the validation order (parse, scheme, credentials) plus host and
    port shape. Source policy and address validation are applied by the guard, which is what
    keeps global network safety separate from per-source configuration.

    Raises:
        SsrfRejectionError: with a specific :class:`RejectionReason`.
    """
    if not raw or not raw.strip():
        raise SsrfRejectionError(RejectionReason.MALFORMED_URL, "empty URL")
    candidate = raw.strip()
    if len(candidate) > _MAX_URL_LENGTH:
        raise SsrfRejectionError(
            RejectionReason.URL_TOO_LONG,
            f"{len(candidate)} characters exceeds the {_MAX_URL_LENGTH} limit",
        )
    # A control character can split a request line or forge a log entry; neither belongs in a
    # URL that reached us from scraped HTML.
    if any(character in candidate for character in ("\n", "\r", "\t", "\x00")):
        raise SsrfRejectionError(RejectionReason.MALFORMED_URL, "URL contains control characters")

    try:
        parts = urlsplit(candidate)
    except ValueError as error:
        raise SsrfRejectionError(RejectionReason.MALFORMED_URL, str(error)) from error

    scheme = parts.scheme.lower()
    if scheme not in ALLOWED_SCHEMES:
        raise SsrfRejectionError(
            RejectionReason.DISALLOWED_SCHEME,
            f"scheme {scheme or '<relative>'!r} is not one of {sorted(ALLOWED_SCHEMES)}",
        )

    # Credentials are rejected, never stripped. Their presence means the input is wrong, and a
    # URL like https://example.com@127.0.0.1/ is a deliberate attempt to mislead a reader about
    # which host will be contacted.
    if parts.username is not None or parts.password is not None or "@" in parts.netloc:
        raise SsrfRejectionError(
            RejectionReason.EMBEDDED_CREDENTIALS,
            "URL contains embedded credentials or an unexpected '@' in its authority",
        )

    try:
        raw_host = parts.hostname
    except ValueError as error:
        # urlsplit defers some authority errors (e.g. a malformed IPv6 literal) to attribute
        # access rather than raising during the split.
        raise SsrfRejectionError(RejectionReason.MALFORMED_HOST, str(error)) from error
    if not raw_host:
        raise SsrfRejectionError(RejectionReason.MISSING_HOST, "URL has no host")

    try:
        port = parts.port
    except ValueError as error:
        raise SsrfRejectionError(RejectionReason.MALFORMED_URL, f"invalid port: {error}") from error
    resolved_port = port if port is not None else _DEFAULT_PORTS[scheme]
    if resolved_port not in ALLOWED_PORTS:
        raise SsrfRejectionError(
            RejectionReason.DISALLOWED_PORT,
            f"port {resolved_port} is not one of {sorted(ALLOWED_PORTS)}",
        )

    host, ip_literal = _normalize_host(raw_host)

    return NormalizedUrl(
        scheme=scheme,
        host=host,
        port=resolved_port,
        path=parts.path,
        query=parts.query,
        ip_literal=ip_literal,
    )


def _normalize_host(raw_host: str) -> tuple[str, IpAddress | None]:
    """Canonicalise a host, returning it plus its parsed address if it is a literal."""
    # urlsplit already lowercases and removes IPv6 brackets; both are re-applied defensively so
    # this function is correct for any caller.
    host = raw_host.strip().lower().strip("[]")

    # A trailing dot is a legitimate way to write a fully-qualified name, and "example.com." and
    # "example.com" must not be treated as different hosts by policy matching.
    host = host.rstrip(".")
    if not host:
        raise SsrfRejectionError(RejectionReason.MISSING_HOST, "host is empty after normalisation")

    address = _parse_ip_literal(host)
    if address is not None:
        return str(address), address

    if len(host) > _MAX_HOSTNAME_LENGTH:
        raise SsrfRejectionError(
            RejectionReason.MALFORMED_HOST,
            f"hostname is {len(host)} characters, over the {_MAX_HOSTNAME_LENGTH} limit",
        )

    # Convert an internationalised name to punycode so policy matching compares one encoding.
    if any(ord(character) > 127 for character in host):
        try:
            host = host.encode("idna").decode("ascii")
        except (UnicodeError, UnicodeDecodeError) as error:
            raise SsrfRejectionError(
                RejectionReason.MALFORMED_HOST, f"hostname is not valid IDNA: {error}"
            ) from error

    labels = host.split(".")
    if len(labels) < 2:
        # Also catches "localhost". A single-label name can only resolve via local search
        # domains, which is never how a public portal is addressed.
        raise SsrfRejectionError(
            RejectionReason.SINGLE_LABEL_HOST,
            f"hostname {host!r} has no dot; only fully-qualified names are accepted",
        )
    for label in labels:
        if not _LABEL.match(label):
            raise SsrfRejectionError(
                RejectionReason.MALFORMED_HOST,
                f"hostname {host!r} contains an invalid DNS label {label!r}",
            )
    # A punycode label must decode, or it is a malformed name dressed up as a valid one.
    for label in labels:
        if label.startswith("xn--"):
            try:
                label.encode("ascii").decode("idna")
            except (UnicodeError, UnicodeDecodeError) as error:
                raise SsrfRejectionError(
                    RejectionReason.MALFORMED_HOST,
                    f"hostname {host!r} has an undecodable punycode label {label!r}",
                ) from error

    if host.endswith(_FORBIDDEN_SUFFIXES):
        raise SsrfRejectionError(
            RejectionReason.FORBIDDEN_HOST_SUFFIX,
            f"hostname {host!r} uses a private-network suffix",
        )

    return host, None


def _parse_ip_literal(host: str) -> IpAddress | None:
    """Return the address if ``host`` is written as an IP literal, else ``None``."""
    try:
        return ipaddress.ip_address(host)
    except ValueError:
        return None
