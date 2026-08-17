"""Global network safety policy: which IP addresses may ever be contacted.

This is deliberately separate from per-source host policy (see :mod:`.hosts`). A source may
declare which *hostnames* it serves documents from; no source may ever declare that reaching
loopback or a cloud metadata endpoint is acceptable. Keeping them apart means adding a
legitimate CDN host to a source is a configuration change, not a weakening of network safety.

The classification below is written against *measured* ``ipaddress`` behaviour rather than
assumed semantics, because the obvious one-line checks are all wrong in at least one case:

* ``is_global`` is **True** for multicast (``224.0.0.1``, ``ff02::1``), so a
  "reject unless global" rule would permit multicast.
* ``is_global`` is **True** for NAT64 (``64:ff9b::/96``), whose low 32 bits embed an arbitrary
  IPv4 address — ``64:ff9b::7f00:1`` is a spelling of ``127.0.0.1``.
* ``is_global`` is **True** for an IPv4-mapped public address (``::ffff:93.184.216.34``).
* ``is_private`` is **False** for CGNAT (``100.64.0.0/10``).
* ``is_private`` is **True** for the documentation ranges (``203.0.113.0/24``,
  ``192.0.2.0/24``, ``198.51.100.0/24``, ``2001:db8::/32``), which are therefore rejected —
  worth knowing when choosing a "public" address for a test.

Every check is applied. Redundancy is intentional: relying on one stdlib property to imply
another is how a bypass gets introduced by a Python version bump.
"""

from __future__ import annotations

import ipaddress
from enum import StrEnum
from typing import Final

__all__ = [
    "AddressRejection",
    "IpAddress",
    "classify_address",
    "is_publicly_routable",
]

IpAddress = ipaddress.IPv4Address | ipaddress.IPv6Address

# RFC 6052 NAT64 well-known prefix. The low 32 bits carry an embedded IPv4 address, so this
# range is a complete bypass of any IPv4-only policy. Reserved, but `is_global` is True.
_NAT64_PREFIX: Final = ipaddress.ip_network("64:ff9b::/96")

# RFC 6052 also permits NAT64 on a network-specific prefix; we cannot enumerate those, which is
# one reason IPv4-mapped and NAT64 forms are refused outright rather than unwrapped and checked.
_NAT64_LOCAL_USE_PREFIX: Final = ipaddress.ip_network("64:ff9b:1::/48")

_CGNAT_NETWORK: Final = ipaddress.ip_network("100.64.0.0/10")

# Ranges reserved for documentation and benchmarking. Not routable, and a link to one is a
# crawler bug or a fixture leaking into production rather than a network condition.
_DOCUMENTATION_NETWORKS: Final = (
    ipaddress.ip_network("192.0.2.0/24"),  # TEST-NET-1
    ipaddress.ip_network("198.51.100.0/24"),  # TEST-NET-2
    ipaddress.ip_network("203.0.113.0/24"),  # TEST-NET-3
    ipaddress.ip_network("2001:db8::/32"),  # IPv6 documentation
    ipaddress.ip_network("198.18.0.0/15"),  # benchmarking
)
# 240.0.0.0/4 is deliberately NOT listed here. It is reserved for future use rather than
# documentation, and it contains 255.255.255.255 — labelling it "documentation" would report
# the broadcast address as a copy-paste mistake. It falls through to the `reserved` check.

# 6to4 and Teredo embed IPv4 addresses in the same way.
_SIXTOFOUR_PREFIX: Final = ipaddress.ip_network("2002::/16")
_TEREDO_PREFIX: Final = ipaddress.ip_network("2001::/32")


class AddressRejection(StrEnum):
    """Why an address may not be contacted.

    Carried on rejections so operators and metrics can distinguish a crawler bug (a link to a
    documentation range) from an attack (a redirect to the metadata endpoint).
    """

    UNSPECIFIED = "unspecified"
    LOOPBACK = "loopback"
    PRIVATE = "private"
    LINK_LOCAL = "link_local"
    CARRIER_GRADE_NAT = "carrier_grade_nat"
    MULTICAST = "multicast"
    DOCUMENTATION = "documentation"
    RESERVED = "reserved"
    IPV4_MAPPED = "ipv4_mapped"
    EMBEDDED_IPV4 = "embedded_ipv4"
    NOT_GLOBALLY_ROUTABLE = "not_globally_routable"


def classify_address(address: IpAddress) -> AddressRejection | None:
    """Return why ``address`` is forbidden, or ``None`` if it may be contacted.

    Ordered so the reported reason is the most specific and most diagnostic one. A metadata
    endpoint should be reported as ``link_local``, not as a generic routability failure.
    """
    # IPv4-mapped and other IPv4-embedding forms are refused outright, including when the
    # embedded address is public. They are canonicalisation hazards: ::ffff:127.0.0.1 defeats
    # any IPv4-only check, and no legitimate procurement portal is reachable only this way.
    if isinstance(address, ipaddress.IPv6Address):
        if address.ipv4_mapped is not None:
            return AddressRejection.IPV4_MAPPED
        if address in _NAT64_PREFIX or address in _NAT64_LOCAL_USE_PREFIX:
            return AddressRejection.EMBEDDED_IPV4
        if address in _SIXTOFOUR_PREFIX or address in _TEREDO_PREFIX:
            return AddressRejection.EMBEDDED_IPV4

    if address.is_unspecified:
        return AddressRejection.UNSPECIFIED
    if address.is_loopback:
        return AddressRejection.LOOPBACK
    if address.is_link_local:
        return AddressRejection.LINK_LOCAL
    if address.is_multicast:
        # Checked explicitly because `is_global` is True for multicast.
        return AddressRejection.MULTICAST
    if _is_carrier_grade_nat(address):
        # Checked explicitly because `is_private` is False for 100.64.0.0/10.
        return AddressRejection.CARRIER_GRADE_NAT
    if _is_documentation(address):
        # Reported distinctly from `private` because these are what a developer actually hits:
        # a copy-pasted example URL, or a fixture leaking into a real code path. "documentation"
        # points at the mistake; "private" would send someone hunting a network problem.
        return AddressRejection.DOCUMENTATION
    # `reserved` before `private` because several ranges (240.0.0.0/4, 255.255.255.255) are both,
    # and the narrower category is the more useful reason to report.
    if address.is_reserved:
        return AddressRejection.RESERVED
    if address.is_private:
        return AddressRejection.PRIVATE
    if not address.is_global:
        # Catch-all for anything the specific checks above miss, now and in future Python
        # versions. Reaching this line means the address is not routable on the public
        # internet for some reason we did not enumerate, which is still a rejection.
        return AddressRejection.NOT_GLOBALLY_ROUTABLE
    return None


def is_publicly_routable(address: IpAddress) -> bool:
    """Return whether ``address`` may be contacted."""
    return classify_address(address) is None


def _is_carrier_grade_nat(address: IpAddress) -> bool:
    """Return whether ``address`` is in RFC 6598 shared address space."""
    if isinstance(address, ipaddress.IPv4Address):
        return address in _CGNAT_NETWORK
    return False


def _is_documentation(address: IpAddress) -> bool:
    """Return whether ``address`` is in a range reserved for documentation or benchmarking."""
    return any(address in network for network in _DOCUMENTATION_NETWORKS)
