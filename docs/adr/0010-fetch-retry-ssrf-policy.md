# 10. HTTP fetch policy: SSRF validation, retries, and rate limiting

Date: 2026-08-17

## Status

Accepted (pre-implementation)

## Context

Slice 3 builds the component that makes outbound requests to public procurement portals. It is
the highest-risk component in the acquisition platform: it is the SSRF pivot, the availability
bottleneck, and the thing portal operators judge us by.

The tempting order is a working fetcher first, hardened later. That order is rejected: retrofitted
SSRF protection is the well-trodden path to a bypass, because the abstraction settles around the
naive behaviour and the guard becomes a bolt-on that some code path skips.

Design decisions are recorded here before implementation so they can be challenged while changing
them is still free. See [the threat model](../security/threat-model-http-fetch.md) and
[the requirements](../requirements/fetch.md).

## Decision

### 1. Validation is a mandatory gate, not a helper

A single choke point performs validation in a fixed order, and the fetch API offers **no way to
issue a request that skips it**. Validation returns a value carrying the validated address, and
the connect path consumes only that value — so bypassing the guard is not a discipline question
but a type-level impossibility.

Order (rejecting at first failure): parse → scheme → embedded credentials → hostname allowlist →
DNS resolution → validate every address → connect.

### 2. Connect to a validated IP, assert the original hostname

The DNS-rebinding mitigation, and the least obvious decision here.

Validating a hostname and then passing that *hostname* to an HTTP client lets the client resolve
again; a hostile 0-TTL record can answer differently the second time, and the validation becomes
theatre. So: resolve once, validate every address, connect to a validated address literal, and
carry the original hostname for TLS SNI, certificate verification, and the `Host` header.

Certificate verification is against the hostname and is never relaxed — connecting by address
while asserting the hostname is precisely the point.

### 3. Redirects are followed by us, not by the client

Automatic following is disabled. Each hop re-enters validation from step 1, including the
allowlist, so a redirect off-allowlist fails even to a public address. Capped at 5 hops, loops
detected explicitly, headers rebuilt across hosts, and the whole chain recorded as provenance.

### 4. Retry policy is a per-status decision

Retry: connection errors, timeouts, 408, 425, 429, 500, 502, 503, 504.
Do not retry: 400, 401, 403, 404, 405, 410, 451, or anything rejected as unsafe content.

Exponential backoff with **full** jitter (base 1 s, factor 2, cap 60 s, max 5 attempts).
`Retry-After` overrides the computed delay; a `Retry-After` beyond 300 s abandons rather than
sleeps. A retry budget caps retries at ~20% of attempts per run.

Only `GET` and `HEAD` are exposed, so retry safety is structural rather than conditional.

### 5. Rate limits come from the registry and apply to every request

Including retries and redirect hops. Limits are already bounded and consistency-checked by the
registry schema, so the fetcher enforces policy it cannot invent.

### 6. `httpx` as the client

Chosen for explicit per-phase timeouts, an injectable transport (which is what makes local-server
testing possible without mocks), first-class streaming, HTTP/2, and a connection-pool model that
maps onto bounded concurrency. Already a dev dependency, so this promotes it rather than adding a
new one.

### 7. Synchronous first

Consistent with ADR 0005. Bounded concurrency is provided by a worker pool rather than an event
loop. Revisit if measurement shows the fetcher is the bottleneck; the interface is designed so an
async transport can be introduced without changing callers.

## Alternatives considered

**`requests` + a `urllib3` adapter.** Ubiquitous and familiar. Rejected: one coarse timeout
rather than per-phase, no streaming-cap ergonomics, and redirect handling is harder to fully
disable and re-implement safely.

**`aiohttp`.** Good async story. Rejected for now under ADR 0005; would also make the SSRF guard's
tests async for no security benefit.

**Rely on a network-level egress allowlist instead of application validation.** Genuinely
strong, and worth having *as well* in production. Rejected as the primary control: it does not
exist in development or CI, so the code would be untested against the threat, and it cannot
express per-source host allowlisting.

**Follow redirects with the client, validating afterwards.** Simpler. Rejected: by the time we
see the final URL, the request to the internal address has already been made. The leak is the
request, not the response.

**Resolve and pass the hostname, trusting the OS resolver cache to be stable.** Rejected: cache
behaviour is not a security control, and a 0-TTL hostile record defeats it. This is the specific
mistake the threat model exists to prevent.

**Retry everything with backoff.** Simpler. Rejected: hammering a 403 gets us blocked, and a
block is permanent where a failure is transient.

## Advantages

- SSRF cannot be bypassed by forgetting a call, because the connect path accepts only a validated
  destination.
- The rebinding window is closed at the DNS layer, which is where the practical attack lives.
- Retry behaviour is explainable per status code, and bounded in three independent ways (attempts,
  budget, `Retry-After` ceiling).
- The guard is pure logic, so the highest-risk code is also the cheapest to test exhaustively.

## Disadvantages

- Re-implementing redirect handling means owning correctness the library would otherwise provide
  (303 method rewriting, relative `Location` resolution, fragment retention). Mitigated by tests
  per redirect status code.
- Connecting by address complicates virtual hosting and forgoes DNS round-robin per request.
- Pinning one address per request can mask a partially unhealthy multi-address host.
- More code than `httpx.get(url)`. This is the cost of the property being bought.

## Operational consequences

An SSRF rejection is a loud, warning-level event naming the failing rule — likely a crawler bug or
a hostile redirect, and always worth a look. Fetch failures carry typed errors so the runbook can
route them: rejection (fix the crawler or block the source), transient (retried), or content
(quarantine).

Rate limits become the operator's throttle: lowering a registry value is the immediate response to
an operator complaint, with no code change.

## Security consequences

Closes T1–T8 in the threat model to the extent achievable in application code. Residual, and
documented rather than claimed solved:

- An OS-level TOCTOU window remains between validation and `connect()`, though no second DNS
  lookup occurs.
- A source's own legitimate host could itself be compromised; the allowlist constrains *where* we
  go, not what we receive. Content validation is the next layer.
- No egress network policy is assumed to exist. Adding one in production would be defence in
  depth, not a replacement.

## Migration consequences

New code; nothing to migrate. `httpx` moves from a dev dependency to a runtime dependency, which
requires a lock update and passes through dependency review.
