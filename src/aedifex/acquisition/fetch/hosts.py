"""Per-source host policy: which hostnames a given source may be fetched from.

Deliberately separate from global network safety (:mod:`.addresses`). A source declares the
hostnames it serves documents from; it can never declare that an unroutable address is
acceptable. So adding a legitimate CDN hostname to a source is a configuration change, and
never a weakening of SSRF protection.

Matching is DNS-label-aware, which is the point of this module existing at all:

    ``host.endswith("cpwd.gov.in")``      also matches ``evilcpwd.gov.in``
    ``host == base or host.endswith("." + base)``   does not

The asymmetry between the two allowlists is intentional:

* The source's **own** domain, taken from its registry ``base_url``, permits subdomains.
  Portals routinely serve documents from ``documents.``/``static.`` hosts, and the operator of
  ``cpwd.gov.in`` controls everything beneath it.
* **Additional** hosts, declared explicitly in the registry, are exact matches only. A CDN
  entry must not silently authorise every other tenant of that CDN — allowing subdomains of a
  shared object-storage domain would authorise every bucket on it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Self

from aedifex.acquisition.registry.models import SourceDefinition

__all__ = ["SourceHostPolicy"]


@dataclass(frozen=True, slots=True)
class SourceHostPolicy:
    """The hostnames one source may be fetched from."""

    source_id: str
    base_hosts: frozenset[str]
    """Hosts whose subdomains are also permitted, from the source's own ``base_url``."""
    exact_hosts: frozenset[str]
    """Hosts permitted only as an exact match, from the source's ``additional_hosts``."""

    @classmethod
    def from_source(cls, source: SourceDefinition) -> Self:
        """Derive the policy from a registry definition.

        Raises:
            ValueError: if the source declares no ``base_url``, so no host could be permitted.
                A source with no target cannot be fetched from, and returning an empty policy
                would silently reject everything at a confusing point instead.
        """
        if source.base_url is None or not source.base_url.host:
            raise ValueError(
                f"source {source.id!r} has no base_url host, so no fetch policy can be derived"
            )
        return cls(
            source_id=source.id,
            base_hosts=frozenset({_canonical(source.base_url.host)}),
            exact_hosts=frozenset(_canonical(host) for host in source.additional_hosts),
        )

    def permits(self, host: str) -> bool:
        """Return whether ``host`` may be contacted for this source.

        ``host`` is expected to be already normalised by
        :func:`~aedifex.acquisition.fetch.urls.normalize_url` — lowercase, punycode, no trailing
        dot. It is canonicalised again here so this method is safe for any caller.
        """
        candidate = _canonical(host)
        if not candidate:
            return False
        if candidate in self.exact_hosts:
            return True
        return any(candidate == base or candidate.endswith(f".{base}") for base in self.base_hosts)

    def describe(self) -> str:
        """Render the policy for an error message or log line."""
        parts: list[str] = []
        if self.base_hosts:
            parts.extend(f"{host} (+subdomains)" for host in sorted(self.base_hosts))
        parts.extend(f"{host} (exact)" for host in sorted(self.exact_hosts))
        return ", ".join(parts) or "<no hosts permitted>"


def _canonical(host: str) -> str:
    """Lowercase, strip brackets, and drop the trailing root-label dot."""
    return host.strip().lower().strip("[]").rstrip(".")
