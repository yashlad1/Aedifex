# Requirements: HTTP fetch layer (Slice 3)

Derived from [the threat model](../security/threat-model-http-fetch.md). Every requirement states
a number or a decidable condition, so "done" is testable rather than asserted.

Status: **FR-100–109 Implemented** (the SSRF guard, `src/aedifex/acquisition/fetch/`), with
226 tests at 96% coverage of the package. Everything else remains Planned — the HTTP client
is the next slice. This file was written before any of the code, deliberately.

## SSRF and destination validation

| ID | Requirement | Status |
| --- | --- | --- |
| FR-100 | Validation shall proceed in this order, rejecting at the first failure: parse → scheme → embedded credentials → hostname allowlist → DNS resolution → per-address validation → connect. | Implemented — `test_fetch_guard.py::TestSchemeAndCredentialOrdering` proves each step precedes DNS |
| FR-101 | Only `http` and `https` schemes shall be accepted. All others (`file`, `ftp`, `gopher`, `data`, `blob`, scheme-relative) shall be rejected. | Implemented — `TestSchemes` — file/ftp/gopher/data/javascript/dict/ldap all rejected |
| FR-102 | A URL containing embedded credentials shall be rejected, not stripped. | Implemented — `TestEmbeddedCredentials` — rejected, not stripped |
| FR-103 | A request shall be rejected unless its hostname is permitted for the specific source, derived from that source's registry `base_url`. | Implemented — `test_fetch_hosts.py` — label-aware; `evilcpwd.gov.in` rejected |
| FR-104 | **Every** address returned by DNS resolution shall be validated, not merely the first. | Implemented — `TestMixedDnsAnswers` — every address checked |
| FR-105 | Requests shall be rejected when any resolved address is loopback, private (RFC1918), link-local (incl. `169.254.169.254`), CGNAT `100.64/10`, multicast, reserved, unspecified, IPv4-mapped IPv6, or NAT64. | Implemented — `test_fetch_addresses.py` — 62 tests, each address asserted with its reason |
| FR-106 | Hostnames ending in `.local`, `.internal`, or `.localdomain`, and bare single-label hostnames, shall be rejected. | Implemented — `test_private_network_suffixes_rejected`, `test_single_label_hosts_rejected` |
| FR-107 | The connection shall be made to an address that was validated in this request, such that no second DNS resolution can occur between validation and connection. | Implemented — `TestDnsRebinding` — `resolver.calls == 1`; target pins an address |
| FR-108 | TLS certificate verification shall be performed against the original hostname and shall never be disabled or relaxed. | Implemented — Invariant documented in `guard.py`; `TestConnectionInvariant` asserts hostname and address are carried separately |
| FR-109 | A source with no resolvable, validatable address shall fail closed. | Implemented — `TestResolutionFailure` — unresolvable and empty answers both fail closed |

## Redirects

| ID | Requirement | Status |
| --- | --- | --- |
| FR-110 | Automatic redirect following shall be disabled in the underlying client; redirects shall be followed only by our own loop. | Planned |
| FR-111 | Every redirect hop shall re-enter validation from FR-100 step 1, including the hostname allowlist. | Planned |
| FR-112 | Redirect chains shall be limited to 5 hops; exceeding the limit shall fail the request. | Planned |
| FR-113 | A redirect loop shall be detected and shall fail rather than exhaust the hop budget silently. | Planned |
| FR-114 | On a cross-host redirect, request headers shall be rebuilt rather than carried over. | Planned |
| FR-115 | The full redirect chain shall be recorded, so the requested URL and the answering URL are both retained as provenance. | Planned |

## Timeouts and resource limits

| ID | Requirement | Target | Status |
| --- | --- | --- | --- |
| FR-120 | Separate connect, read, and total-request timeouts shall be enforced. | connect 10 s, read 30 s, total 300 s (configurable) | Planned |
| FR-121 | A total-request timeout shall bound the whole exchange including redirects, so slow-drip responses cannot evade a per-read timeout. | — | Planned |
| FR-122 | A response whose declared `Content-Length` exceeds the size cap shall be rejected before the body is read. | — | Planned |
| FR-123 | Response bodies shall be streamed with the cap enforced during read, never buffered then measured. | default 256 MiB | Planned |
| FR-124 | A request shall be cancellable, and cancellation shall release the connection. | — | Planned |

## Rate limiting and concurrency

| ID | Requirement | Target | Status |
| --- | --- | --- | --- |
| FR-130 | Requests shall be rate-limited per source using that source's registry `rate_limit`. | — | Planned |
| FR-131 | A minimum delay between consecutive requests to one source shall be enforced. | from `min_delay_seconds` | Planned |
| FR-132 | Concurrent requests shall be bounded globally and per source. | per source from `max_concurrency` | Planned |
| FR-133 | There shall be no unbounded concurrency anywhere in the fetch path. | — | Planned |
| FR-134 | Connections shall be pooled and reused across requests to one host. | — | Planned |
| FR-135 | Rate limiting shall apply to retries and redirect hops, not only to initial requests. | — | Planned |

## Retries

| ID | Requirement | Target | Status |
| --- | --- | --- | --- |
| FR-140 | Transient failures shall be retried with exponential backoff and full jitter. | base 1 s, factor 2, cap 60 s, **max 5 attempts** | Planned |
| FR-141 | Retryable conditions shall be exactly: connection errors, timeouts, and HTTP 408, 425, 429, 500, 502, 503, 504. | — | Planned |
| FR-142 | Non-retryable conditions shall be exactly: HTTP 400, 401, 403, 404, 405, 410, 451, and any content rejected as unsafe. | — | Planned |
| FR-143 | `Retry-After` shall be honoured when present, as both delay-seconds and HTTP-date, and shall override computed backoff. | — | Planned |
| FR-144 | A `Retry-After` beyond a maximum shall abandon the request rather than sleep. | max 300 s | Planned |
| FR-145 | Only idempotent methods shall be retried; the fetcher shall expose only `GET` and `HEAD`. | — | Planned |
| FR-146 | A retry budget shall bound total retries per crawl run, so a broadly failing source cannot amplify load. | ≤ 20% of attempts | Planned |
| FR-147 | Jitter shall be full jitter, so parallel workers do not synchronise into bursts. | — | Planned |

## Politeness

| ID | Requirement | Status |
| --- | --- | --- |
| FR-150 | Every request shall carry the configured contactable User-Agent. | Implemented (config enforces contactability) |
| FR-151 | `robots.txt` shall be fetched, cached, and honoured for sources whose `robots_policy` is `respect`. | Planned |
| FR-152 | A `robots.txt` that cannot be fetched shall be treated as disallowing, not allowing. | Planned |
| FR-153 | `robots.txt` crawl-delay shall be honoured when it is longer than the configured delay. | Planned |

## Observability

| ID | Requirement | Status |
| --- | --- | --- |
| FR-160 | Every request shall be logged with source, URL, status, duration, attempt number, and outcome. | Planned |
| FR-161 | An SSRF rejection shall be logged at warning with the specific rule that rejected it. | Planned |
| FR-162 | Logged URLs shall be length-bounded, and response bodies shall never be logged. | Planned |
| FR-163 | Per-source counters for attempts, successes, retries, and rejections shall be exposed. | Planned |

## Non-functional

| ID | Requirement | Target | Status |
| --- | --- | --- | --- |
| NFR-110 | The SSRF guard shall be pure logic, testable with no network. | — | Implemented — no new dependency; stdlib only |
| NFR-111 | Failure-path tests shall cover every case listed in the threat model's verification obligations. | 30+ cases | Planned |
| NFR-112 | Transport behaviour shall be tested against a controlled local HTTP server, not mocks. | — | Planned |
| NFR-113 | DNS rebinding shall be tested with a resolver returning a public address then a private one. | — | Implemented — `RecordingResolver` scripts successive answers; the second is never consulted |
| NFR-114 | Fetch failures shall never lose the reason: every rejection carries a typed error. | — | Implemented — `SsrfRejectionError` carries a `RejectionReason` |


## Implementation notes for FR-100–109

Decisions taken during implementation that the requirements did not pin down, recorded here so
they are reviewable:

**IP-literal URLs are rejected outright**, including public ones. An address cannot satisfy a
hostname allowlist, and permitting it would abandon the per-source host constraint entirely.

**Only ports 80 and 443 are accepted.** An arbitrary port on an allowlisted host is still a
service we never intended to speak to. A source needing another port is a registry change.

**IPv4-mapped IPv6 is rejected even when the embedded address is public.** The form is a
canonicalisation hazard (`::ffff:127.0.0.1` defeats any IPv4-only check) and no legitimate portal
is reachable only that way. 6to4, Teredo, and NAT64 are refused for the same reason.

**`is_global` alone is not a sufficient check**, which is why the policy applies every test
rather than one. Measured: `is_global` is `True` for multicast, for NAT64, and for IPv4-mapped
public addresses; `is_private` is `False` for CGNAT.

**Documentation ranges are rejected and reported distinctly.** `203.0.113.0/24` and friends are
what a developer actually hits by pasting an example URL, so the reason names that rather than
reporting a generic private-address failure. Consequence worth knowing: `203.0.113.x` cannot be
used as a "public" address in a test.

**Address selection is the first validated address, deterministically.** Because a mixed answer
is rejected wholesale, every returned address is acceptable, so there is nothing for an attacker
to influence and no reason to randomise.

**`additional_hosts` (new registry field) are exact-match only**, while the source's own
`base_url` host permits subdomains. Authorising a shared CDN or object-storage domain by suffix
would authorise every other tenant on it.
