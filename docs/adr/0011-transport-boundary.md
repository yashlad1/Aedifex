# 11. The transport boundary: IP-pinned connections with hostname TLS identity

Date: 2026-08-17

## Status

Accepted (implemented)

## Context

[ADR 0010](0010-fetch-retry-ssrf-policy.md) decided that validation is a type-level gate producing a
`ValidatedTarget`, and that the connect path consumes only that value. This ADR records how the code
that actually opens a socket honours it, and the one question that turned out to have no cheap
answer: connection reuse.

The requirement from the guard is a split that ordinary HTTP clients do not make. A normal client is
handed a hostname, resolves it internally, and connects to whatever comes back — which is exactly
the behaviour that makes DNS rebinding possible, because the resolution that the security check ran
against is not the resolution the socket uses. We need:

| Concern | Value |
| --- | --- |
| TCP destination | the already-validated IP address |
| TLS SNI | the original hostname |
| TLS certificate identity | the original hostname |
| HTTP `Host` header | the original authority, including a non-default port |

Verifying the certificate against the IP address would be the obvious shortcut and is wrong: pinning
the address exists to keep talking to the host that was validated, and only the *name* can establish
that we are. `verify=False` is not a fallback under any circumstances.

## Decision

### 1. httpx, driven through httpcore's `sni_hostname` extension

`httpcore` connects to the URL's host and performs the handshake against `server_hostname`, taken
from the `sni_hostname` request extension when present. So the request URL carries the validated
address, the extension carries the hostname, and the `Host` header is built from the validated
authority. That yields all four rows above with no patched sockets and no forked library.

Alternatives considered:

- **A custom SSL/socket layer.** Full control, but it means owning TLS setup, timeouts, and HTTP/1.1
  framing — a large amount of security-critical code to replace behaviour that already exists.
- **`requests` plus an adapter.** The usual recipe (a custom `HTTPAdapter`) reaches into urllib3
  internals, and urllib3's own hostname/SNI handling would have to be overridden in more than one
  place.
- **Resolve inside the client and validate afterwards.** Rejected outright: it inverts the ordering
  the threat model requires and reintroduces the rebinding window.

### 2. The transport does one thing

It opens a connection, sends one request, and returns status, headers, and an unread body stream. It
owns no retry, redirect, backoff, rate-limit, or size policy. Redirects are returned as ordinary
responses; `follow_redirects` is off, because a redirect the library follows is a request that never
passed the guard. `retries=0` for the same reason in the other direction: a hidden retry loop below
ours would silently multiply every attempt budget decided above it.

### 3. Library exceptions are converted, not propagated

Every failure becomes one of seven typed errors, and each error class declares the `AttemptOutcome`
it classifies as. Retry policy therefore reads the error's own classification rather than
re-deriving one, which is what keeps a TLS verification failure non-retryable no matter who catches
it (rule 81d). Declaring `outcome` is enforced at class-definition time, so a subclass added later
cannot silently inherit a retryable classification it was never assessed for.

An exception the mapping does not recognise becomes `UnclassifiedTransportError`, which is **not**
retryable. Being unable to classify a failure is not evidence that it was transient (rule 81b).

### 4. Connection reuse is disabled, pending a pool identity

This is the unresolved part, recorded rather than papered over.

`httpcore` keys its connection pool by origin — `(scheme, host, port)`. Our host is the *IP address*
and SNI is a per-request extension, so two different hostnames resolving to the same address are
eligible to share one connection, and the second request would travel over a TLS session negotiated
and verified for the first hostname. On shared hosting and behind CDNs, many names per address is
the normal case, not a corner case.

The correct pool identity for this design is:

```
(scheme, validated hostname, validated IP, port)
```

Reusing a connection is safe only when all four match. Implementing that means either a custom pool
key or one pool per destination, and neither is in scope for the transport slice. Until then
`max_keepalive_connections=0`: a connection per request. That costs a handshake per document, which
is real but acceptable — the crawl is rate-limited to be polite long before TLS setup becomes the
bottleneck, and no correctness or security property depends on reuse.

**This must be revisited before high-volume crawling, and the pool key is the entire decision.** A
pool keyed by hostname alone would defeat address pinning; a pool keyed by address alone would
confuse TLS identities.

### 5. The total deadline is enforced while the body is read

Per-attempt timeouts alone are escapable, and this is the reason the transport is given a deadline at
all rather than only two numbers. Every chunk received restarts the read timeout, so a server sending
one byte just inside that window never trips it and holds the connection indefinitely. The deadline is
therefore checked at each chunk boundary, and before the connection is opened at all.

Stated precisely, because "enforces a 300 s total" and "returns within 300 s" are different claims:
the bound is the deadline **plus at most one read timeout**, since a read already in flight runs to
its own limit. That limit was clamped to the remaining budget when the attempt began, so the overrun
is bounded rather than open-ended.

The transport receives the budget through a read-only `Deadline` protocol — `remaining_seconds` and
`check`, nothing else — and takes no `TimeoutPolicy`. It therefore cannot extend, reset, or rebuild
the budget. A budget that resets per attempt is the defect the whole timing layer exists to prevent,
so the layer most tempted to do it is given no means.

### 6. `GET` and `HEAD` only

An allowlist. Aedifex reads published documents and never submits anything, so a crawler that can
issue a state-changing request is only a liability. `POST` is refused rather than unimplemented.

## Consequences

**Operational.** One TCP connection and one TLS handshake per request until pool identity is solved.
Per-host connection pressure is bounded by `max_connections`, which is a resource guard, not the
politeness policy — that arrives with the rate limiter.

**Security.** The rebinding window is closed by construction: the transport has no resolver, is given
none, and cannot obtain one. Verified by watching `socket.getaddrinfo` during a request and asserting
the hostname is never looked up. Certificate verification cannot be disabled through any parameter of
either the constructor or `open`, asserted against the signatures so that a future `verify=False`
escape hatch fails the build.

Two protections turned out to come from somewhere other than the obvious setting, which is recorded
because the obvious reading is wrong:

- Environment proxies are excluded because an explicit `transport=` is supplied
  (`allow_env_proxies = trust_env and transport is None`), not because `trust_env=False`.
- `SSL_CERT_FILE` cannot inject a certificate authority because an explicit `SSLContext` is passed;
  httpx consults that variable only when `verify is True`.

`trust_env=False` is kept anyway, so that reopening the environment takes two mistakes rather than
one. A mutation test confirmed it currently changes nothing on its own.

**Supply chain.** `httpx` moves from a dev dependency to a runtime one, and `certifi` is declared
explicitly because the transport imports it directly rather than relying on it arriving through
httpx. The container image was rebuilt and the transport constructed inside it, with the CA bundle
present.

**Testing.** Behaviour is verified against local servers over real sockets and a real TLS handshake
using a throwaway CA, including a server that records the SNI value it received. The certificate is
issued for the hostname and *not* for `127.0.0.1`, which is what makes the central pair of assertions
decisive: a handshake that succeeds proves the verified identity is the name, and the same handshake
failing when the name is replaced by the address proves the address is not an acceptable identity.

Fourteen mutations of the security-relevant lines were each confirmed to fail at least one test,
alongside a control mutation confirmed *not* to fail any — because a mutation suite that reports
everything as caught is as uninformative as one that catches nothing (rule 81e).

**Migration.** None. Nothing called the transport before it existed, and no source is enabled, so
nothing makes outbound requests yet.
