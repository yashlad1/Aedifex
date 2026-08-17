# Requirements: HTTP fetch layer (Slice 3)

Derived from [the threat model](../security/threat-model-http-fetch.md). Every requirement states
a number or a decidable condition, so "done" is testable rather than asserted.

Status: **all Planned** — no fetch code exists yet. This file is written first, deliberately.

## SSRF and destination validation

| ID | Requirement | Status |
| --- | --- | --- |
| FR-100 | Validation shall proceed in this order, rejecting at the first failure: parse → scheme → embedded credentials → hostname allowlist → DNS resolution → per-address validation → connect. | Planned |
| FR-101 | Only `http` and `https` schemes shall be accepted. All others (`file`, `ftp`, `gopher`, `data`, `blob`, scheme-relative) shall be rejected. | Planned |
| FR-102 | A URL containing embedded credentials shall be rejected, not stripped. | Planned |
| FR-103 | A request shall be rejected unless its hostname is permitted for the specific source, derived from that source's registry `base_url`. | Planned |
| FR-104 | **Every** address returned by DNS resolution shall be validated, not merely the first. | Planned |
| FR-105 | Requests shall be rejected when any resolved address is loopback, private (RFC1918), link-local (incl. `169.254.169.254`), CGNAT `100.64/10`, multicast, reserved, unspecified, IPv4-mapped IPv6, or NAT64. | Planned |
| FR-106 | Hostnames ending in `.local`, `.internal`, or `.localdomain`, and bare single-label hostnames, shall be rejected. | Planned |
| FR-107 | The connection shall be made to an address that was validated in this request, such that no second DNS resolution can occur between validation and connection. | Planned |
| FR-108 | TLS certificate verification shall be performed against the original hostname and shall never be disabled or relaxed. | Planned |
| FR-109 | A source with no resolvable, validatable address shall fail closed. | Planned |

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
| NFR-110 | The SSRF guard shall be pure logic, testable with no network. | — | Planned |
| NFR-111 | Failure-path tests shall cover every case listed in the threat model's verification obligations. | 30+ cases | Planned |
| NFR-112 | Transport behaviour shall be tested against a controlled local HTTP server, not mocks. | — | Planned |
| NFR-113 | DNS rebinding shall be tested with a resolver returning a public address then a private one. | — | Planned |
| NFR-114 | Fetch failures shall never lose the reason: every rejection carries a typed error. | — | Planned |
