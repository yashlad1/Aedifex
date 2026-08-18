# Requirements: HTTP fetch layer (Slice 3)

Derived from [the threat model](../security/threat-model-http-fetch.md). Every requirement states
a number or a decidable condition, so "done" is testable rather than asserted.

Status: **the guard, the pure policy layer, the transport, and both loops are implemented** — SSRF
validation (FR-100–109), timeout budget, retry classification, redirect policy, the socket-opening
boundary (FR-170–185), the retry controller, and the redirect controller.

The order was deliberate: every decision was pure and exhaustively tested before anything could open
a socket, and the thing that opens sockets owns no policy of its own. The loops came last and add no
rules — they sequence the decisions that were already made and tested elsewhere.

Still Planned: the adversarial integration suite (NFR-111), which exercises these paths against a
local server rather than a scripted transport.

This file was written before any of the code, and the requirements above were not edited to match
what was built.

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
| FR-107 | The connection shall be made to an address that was validated in this request, such that no second DNS resolution can occur between validation and connection. | Implemented **and enforced in the transport** — `TestDnsRebinding` (`resolver.calls == 1`); `test_the_connection_goes_to_the_validated_address` watches `socket.getaddrinfo` during a live request and asserts the hostname is never looked up |
| FR-108 | TLS certificate verification shall be performed against the original hostname and shall never be disabled or relaxed. | Implemented **and proven over a real handshake** — certificate issued for the hostname and not for `127.0.0.1`: verification succeeds over the pinned address, and fails when the address is used as the identity. No parameter can disable it, asserted against both signatures |
| FR-109 | A source with no resolvable, validatable address shall fail closed. | Implemented — `TestResolutionFailure` — unresolvable and empty answers both fail closed |

## Redirects

| ID | Requirement | Status |
| --- | --- | --- |
| FR-110 | Automatic redirect following shall be disabled in the underlying client; redirects shall be followed only by our own loop. | Implemented — `follow_redirects=False`; `TestRedirectsAreNotFollowed` asserts each of 301/302/303/307/308 is returned as a response and that the server received exactly one request |
| FR-111 | Every redirect hop shall re-enter validation from FR-100 step 1, including the hostname allowlist. | Implemented — `RedirectController` calls `validate_url` for every hop **including the first**, so there is one validation path rather than two. Proven by a recording transport and a recording resolver: a redirect to a permitted hostname resolving to `169.254.169.254`, loopback, RFC1918, CGNAT, `::1`, or a mixed answer is refused *after* the lookup and the transport is never asked for it. Off-allowlist and lookalike hosts (`evilcpwd.test`) are refused *before* the lookup |
| FR-112 | Redirect chains shall be limited to 5 hops; exceeding the limit shall fail the request. | Implemented — enforced by the loop, not only decided by the policy: the transport is asked for exactly 6 requests at the default cap and exactly 3 at a cap of 2 |
| FR-113 | A redirect loop shall be detected and shall fail rather than exhaust the hop budget silently. | Implemented — two checks, both rejecting. The policy compares the resolved `Location` against the chain; the controller also compares the **canonical** URL validation produced, which catches a cycle disguised by an explicit default port or a change of host casing that the string comparison lets through |
| FR-114 | On a cross-host redirect, request headers shall be rebuilt rather than carried over. | Implemented — dropped on a host change and kept when only the port or the casing differs. The host is taken with `urlsplit`, so the userinfo in `https://cpwd.test@evil.test/` cannot pose as the recipient; anything unparseable counts as a crossing. Once dropped they stay dropped for the rest of the chain |
| FR-115 | The full redirect chain shall be recorded, so the requested URL and the answering URL are both retained as provenance. | Implemented — `ChainResult` keeps the caller's URL verbatim, the canonical URL that answered, and a `RedirectHop` per request carrying its status, its raw unresolved `Location`, and its attempt records. A rejection carries the chain up to the refusal, so "refused at hop 3" and "refused immediately" are distinguishable |
| FR-116 | A redirect that downgrades transport (`https` → `http`) shall be rejected unless the source has explicitly accepted an insecure channel. | Implemented — refused by default and followed when the source set `allow_insecure_transport`, asserted through the loop as well as in the policy. `http` → `https` needs no permission. Permission comes from the registry, never from an HTTP library default |

## Transport

The layer that opens sockets, and nothing else. See [ADR 0011](../adr/0011-transport-boundary.md).

| ID | Requirement | Status |
| --- | --- | --- |
| FR-170 | The transport shall accept only a `ValidatedTarget`; no overload shall accept a URL, hostname, or address. | Implemented — enforced by type and by an explicit runtime check (not an `assert`, which `-O` strips); `test_open_accepts_no_parameter_that_could_carry_an_unvalidated_url` pins the signature |
| FR-171 | No DNS resolution shall occur inside the transport. | Implemented — the transport holds no resolver; `socket.getaddrinfo` is observed during a live request and only ever receives the address |
| FR-172 | TLS SNI shall carry the original hostname. | Implemented — asserted by a server-side SNI callback recording what it received |
| FR-173 | The `Host` header shall be derived from the validated authority, including a non-default port, and shall not be settable by a caller. | Implemented — a caller-supplied `Host` is refused rather than overwritten |
| FR-174 | Transport failures shall be converted into a closed taxonomy; no library exception shall escape. | Implemented — seven typed errors; every httpx exception class mapped, with an unrecognised exception becoming a non-retryable `UnclassifiedTransportError` |
| FR-175 | Each transport error shall carry the retry classification for its own failure mode. | Implemented — `outcome` is a class attribute, and declaring it is enforced when a subclass is defined (rule 81d) |
| FR-176 | Connection resources shall be released on success, failure, partial consumption, and interruption. | Implemented — context manager with a `finally`; tested for an unread body, an abandoned body, and an exception raised by the caller |
| FR-177 | No response body shall be buffered by default. | Implemented — iteration is the only access path; `RawResponse` deliberately has no `content`, `text`, or `read`, asserted structurally |
| FR-178 | The transport shall not retry, and shall not permit the HTTP library to retry. | Implemented — `retries=0`, asserted by timing: a refused connection returns in ≪ the 0.5 s httpcore would spend on its first backoff |
| FR-179 | Only `GET` and `HEAD` shall be permitted. | Implemented — allowlist; write methods are refused before anything reaches the network |
| FR-180 | The environment shall not be able to reroute or re-trust a validated request. | Implemented — an env proxy cannot reroute (explicit `transport=`), and `SSL_CERT_FILE` cannot inject a CA (explicit `SSLContext`). Both mechanisms measured rather than assumed; see ADR 0011 |
| FR-182 | The transport shall refuse to open a connection when no time remains, and shall enforce the total deadline while reading a body. | Implemented — pre-flight check before any socket (asserted by a server that records zero requests); deadline re-checked between chunks. Bound is the deadline plus at most one read timeout, which is itself clamped to the remaining budget |
| FR-184 | A `Content-Length` that is present but unparseable shall reject, never be treated as absent. | Implemented — `parse_content_length` accepts ASCII digits only, so non-ASCII digits are refused rather than silently accepted as `int()` would. Reachability recorded honestly: h11 rejects every malformed form first, so end-to-end the outcome is a `ProtocolError` and the parser is covered by direct tests |
| FR-185 | The byte ceiling shall be selectable per request, so per-source and per-document-type limits are possible. | Implemented — `max_response_bytes` on `open`, defaulting to the configured `max_download_bytes` as a backstop. A test asserts the two defaults stay equal |
| FR-183 | The transport shall be unable to reset or extend the request budget. | Implemented — it receives a read-only `Deadline` protocol exposing only `remaining_seconds` and `check`, and takes no `TimeoutPolicy`, so it cannot construct a fresh budget either |
| FR-181 | A connection shall be reusable only when scheme, validated hostname, validated address, and port all match. | **Deferred, and reuse is off until it holds** — `max_keepalive_connections=0`, because httpcore keys its pool by `(scheme, address, port)` and would let two hostnames on one address share a TLS identity. Asserted by observing distinct client source ports across requests |

## Timeouts and resource limits

| ID | Requirement | Target | Status |
| --- | --- | --- | --- |
| FR-120 | Separate connect, read, and total-request timeouts shall be enforced. | connect 10 s, read 30 s, total 300 s (configurable) | Implemented — `TimeoutPolicy` decides, `TransportTimeouts.from_budget` clamps each attempt to what remains, and the transport applies all three. Verified with a stalling server (read) and a drip server (total) |
| FR-121 | A total-request timeout shall bound the whole exchange including redirects, so slow-drip responses cannot evade a per-read timeout. | — | Implemented **and enforced during streaming** — the deadline is checked at every chunk boundary, so a server sending one byte every 20 ms inside a 300 ms read timeout is stopped by the total. `TimeoutBudget` still does not reset across attempts, now also asserted through the transport across three sequential requests |
| FR-122 | A response whose declared `Content-Length` exceeds the size cap shall be rejected before the body is read. | — | Implemented — refused before `RawResponse` is yielded, so the caller's block never runs and no body byte can be read. Skipped for `HEAD`, where no body is sent and refusing would break the one request whose purpose is to discover a size |
| FR-123 | Response bodies shall be streamed with the cap enforced during read, never buffered then measured. | default 256 MiB | Implemented — the running total is checked at every chunk and the chunk is refused before being yielded. A 200 KiB body against a 1 KiB cap is asserted to abort holding at most limit + one chunk, so the bound is numeric rather than claimed |
| FR-124 | A request shall be cancellable, and cancellation shall release the connection. | — | Planned |

## Rate limiting and concurrency

| ID | Requirement | Target | Status |
| --- | --- | --- | --- |
| FR-130 | Requests shall be rate-limited per source using that source's registry `rate_limit`. | — | Implemented — `RateLimits.from_source` reads the source's own entry; a test asserts the registry defaults survive the translation unchanged |
| FR-131 | A minimum delay between consecutive requests to one source shall be enforced. | from `min_delay_seconds` | Implemented — plus a **rolling** 60-second window for `requests_per_minute`, deliberately not a fixed minute: a fixed one permits a double-rate burst across its boundary. The longer of the two waits wins |
| FR-132 | Concurrent requests shall be bounded globally and per source. | per source from `max_concurrency`; global from `max_global_concurrency` (default 8) | Implemented — verified with real threads: a second request is observed to block while the ceiling is full and to proceed once it frees, per source and globally |
| FR-133 | There shall be no unbounded concurrency anywhere in the fetch path. | — | Implemented — every acquisition goes through a bounded semaphore, and waiting for one is itself bounded by the request's deadline rather than blocking indefinitely |
| FR-134 | Connections shall be pooled and reused across requests to one host. | — | **Deliberately not met.** This requirement is in direct tension with the SSRF design and the security decision wins: httpcore keys its pool by `(scheme, address, port)`, so two hostnames behind one address could share a TLS session verified for the first. Reuse stays off until pool identity includes the validated hostname (FR-181, [ADR 0011](../adr/0011-transport-boundary.md)). Recorded as unmet rather than reworded to look satisfied |
| FR-135 | Rate limiting shall apply to retries and redirect hops, not only to initial requests. | — | Implemented — a slot per *attempt* and a slot per *hop*, asserted by counting acquisitions across a 3-attempt sequence and across a 3-hop chain. The slot is released before the backoff and before the next hop, so a deliberate pause does not hold capacity; a 3-hop chain completes under a per-source concurrency limit of 1, which it could not if a hop held its slot |

## Retries

| ID | Requirement | Target | Status |
| --- | --- | --- | --- |
| FR-140 | Transient failures shall be retried with exponential backoff and full jitter. | base 1 s, factor 2, cap 60 s, **max 5 attempts** | Implemented — `BackoffPolicy`, base 1s, factor 2, cap 60s, max 5 attempts |
| FR-141 | Retryable conditions shall be exactly: connection errors, timeouts, and HTTP 408, 425, 429, 500, 502, 503, 504. | — | Implemented — `RETRYABLE_STATUSES`, asserted status-by-status |
| FR-142 | Non-retryable conditions shall be exactly: HTTP 400, 401, 403, 404, 405, 410, 451, and any content rejected as unsafe. | — | Implemented — `NON_RETRYABLE_STATUSES`; decisions never retried, `TestDecisionsAreNeverRetried` |
| FR-143 | `Retry-After` shall be honoured when present, as both delay-seconds and HTTP-date, and shall override computed backoff. | — | Implemented — `parse_retry_after` handles both forms; server delay overrides backoff |
| FR-144 | A `Retry-After` beyond a maximum shall abandon the request rather than sleep. | max 300 s | Implemented — over the 300s cap abandons rather than sleeping |
| FR-145 | Only idempotent methods shall be retried; the fetcher shall expose only `GET` and `HEAD`. | — | Implemented — `ALLOWED_METHODS` is an allowlist in the transport, and write methods are refused before anything reaches the network |
| FR-146 | A retry budget shall bound total retries per crawl run, so a broadly failing source cannot amplify load. | ≤ 20% of attempts | Planned |
| FR-147 | Jitter shall be full jitter, so parallel workers do not synchronise into bursts. | — | Implemented — full jitter over `[0, ceiling]`, `test_full_jitter_spans_the_whole_interval` |
| FR-148 | One request's total budget shall span every attempt and every backoff; no attempt shall receive a fresh allowance. | — | Implemented — the controller is handed a budget and never constructs one. Asserted two ways: the same object reaches every attempt, and the per-attempt read timeout tracks the remaining budget down (30 → 29 → 7) rather than staying constant |
| FR-149 | A backoff shall be interruptible by a shutdown signal. | — | Implemented — an injected `Cancellation` (satisfied structurally by `threading.Event`, asserted at import) turns a pending backoff into `FetchCancelledError` rather than finishing the wait |
| FR-150a | The per-attempt history shall be retained, on success and on failure. | — | Implemented — `AttemptRecord` per attempt with outcome, status, error type, duration, and the delay that followed; carried on `FetchResult` and on `FetchFailedError`. Not yet persisted — that is the downloader's job |

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
| NFR-112 | Transport behaviour shall be tested against a controlled local HTTP server, not mocks. | — | Implemented — real sockets and a real TLS handshake against a throwaway CA, with a server-side callback recording the SNI value received. 14 mutations of security-relevant lines each confirmed to fail a test, plus a control confirmed to fail none |
| NFR-113 | DNS rebinding shall be tested with a resolver returning a public address then a private one. | — | Implemented — `RecordingResolver` scripts successive answers; the second is never consulted |
| NFR-114 | Fetch failures shall never lose the reason: every rejection carries a typed error. | — | Implemented — `SsrfRejectionError` carries a `RejectionReason` |
| NFR-115 | Retry and timeout policy shall be testable without sleeping or reading real time. | — | Implemented — `Clock`, `Sleeper`, and `RandomSource` are injected; no test sleeps |
| NFR-116 | A parsing failure inside the fetch boundary shall reject, never silently omit. | — | Implemented — an unparseable DNS answer rejects the whole resolution (constitution rule 81b) |


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


## Implementation notes for the policy layer

**The timeout budget does not reset across attempts.** A per-attempt timeout bounds an attempt, not
an operation: five retries at a 30s read timeout, with backoff, is a 150s operation that every
individual timeout considered acceptable. Attempt timeouts are clamped to what remains, and a
backoff delay that would not fit converts the retry into an abandonment rather than a sleep that
ends with no time left to act.

**Retryable statuses are enumerated, not derived from status class.** Treating all 5xx alike is the
common shortcut and it is wrong: 501 means the server will never implement this. An unfamiliar
status fails closed. 500 *is* retried, deliberately — portals return it for transient overload and
these are idempotent GETs — with the risk bounded by the attempt cap and rate limiting rather than
by refusing to retry.

**A `Retry-After` above the cap abandons rather than clamping.** Clamping down and sleeping would
hold a worker and a connection slot for the full cap while ignoring what the server actually asked.
Duplicate headers take the first value, so a server cannot lengthen its own hold by appending.

**`Retry-After` accepts ASCII digits only.** Python's `\d` matches Unicode decimal digits and
`float()` accepts them, so an Arabic-Indic digit five parsed as a 5-second delay. Found by an
adversarial test case, not by review.

**Redirect policy grants no permission.** It returns a resolved URL and says re-validation is
required. Validating the first hop confers nothing on later hops, because the remote server chooses
the second destination.

**`https` → `http` is refused by default.** Permission reuses the registry's
`allow_insecure_transport`, so a source either accepts a tamperable channel or does not — rather
than accepting it for its entry point and implicitly for redirects too. `http` → `https` is always
allowed; an upgrade needs no permission.
