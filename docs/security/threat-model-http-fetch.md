# Threat model: HTTP fetch layer

Status: **accepted, pre-implementation.** Written before Slice 3 code exists, per the rule that
threat modelling precedes high-risk features.

Scope: the component that performs outbound HTTP requests to public procurement portals. Not in
scope: crawler-specific HTML parsing (Slice 7), archive expansion (Slice 5), or object storage
(Slice 4).

## Assets

| Asset | Why an attacker wants it |
| --- | --- |
| Internal network reachability | The fetcher makes outbound requests on our behalf. It is the most valuable SSRF pivot in the system. |
| Cloud instance metadata (IMDS) | Credentials. `169.254.169.254` is the canonical target. |
| The corpus's integrity | Poisoned or substituted documents corrupt every downstream finding. Evidence is the product. |
| Availability | The fetcher runs in a loop, so an attacker who makes it hang or allocate without bound gets a durable outage cheaply. |
| Our reputation with portal operators | Traffic that looks abusive gets us blocked, and blocked sources cannot be collected — a permanent loss, not a transient one. |

## Trust boundaries

```
  our code (trusted)
        │
        │  URL from a crawler, seeded by a registry base_url  ◄── semi-trusted
        ▼
┌──────────────────────┐
│  SSRF guard          │  ◄── THE boundary. Everything past it is attacker-influenced.
└──────────────────────┘
        │  validated host + validated IP
        ▼
   network ──────────────► remote server (fully untrusted, possibly hostile)
        │
        │  status, headers, redirect targets, body bytes  ◄── all untrusted
        ▼
   content validation (already implemented: acquisition/content.py)
```

The URL is *semi*-trusted: its origin is our registry, but path and query components come from
scraped HTML, and redirect targets come entirely from the remote server.

## Threats and mitigations

### T1 — SSRF to internal services
An attacker who controls any link we follow points us at `http://localhost:5432`,
`http://10.0.0.5/admin`, or a Kubernetes service DNS name. Our request carries whatever network
position the worker has.

**Mitigation.** Validation ordered exactly as specified, with rejection at the first failure:

```
Requested URL
  → parse (reject unparseable)
  → scheme in {http, https}?            NO → REJECT
  → credentials embedded in URL?       YES → REJECT
  → hostname allowed for this source?   NO → REJECT
  → resolve DNS
  → validate EVERY resolved address     any not public routable → REJECT
  → connect to a validated address
  → redirect received?                 YES → START AGAIN from parse
```

Rejected address space: loopback, `127.0.0.0/8`, `::1`, RFC1918 (`10/8`, `172.16/12`,
`192.168/16`), link-local (`169.254/16`, `fe80::/10`) which covers IMDS, CGNAT `100.64/10`,
multicast, reserved, unspecified, IPv4-mapped IPv6 (`::ffff:0:0/96` — otherwise `::ffff:127.0.0.1`
bypasses an IPv4-only check), and NAT64 `64:ff9b::/96`.

Hostname allowlisting is per source and derived from its registry `base_url`, so a source cannot
reach hosts it never declared. `.local`/`.internal` suffixes are refused regardless.

### T2 — Redirect-based bypass
Validation on the initial URL is worthless if redirects are followed blindly. A portal returns
`302 Location: http://169.254.169.254/latest/meta-data/`.

**Mitigation.** Automatic redirect following is **disabled** in the client. Redirects are handled
by our own loop, and each hop re-enters validation from the top — including the allowlist check,
so a redirect off-allowlist is refused even to an otherwise public address. Hops are capped
(5). The chain is recorded for provenance: the URL we asked for and the URL that answered are
different facts and both matter to an auditor.

### T3 — DNS rebinding / TOCTOU
**The subtle one, and the reason this section exists.** Validating a hostname's addresses and
then handing the *hostname* to an HTTP client means the client resolves again. Between our check
and its connection, a hostile authoritative DNS server with a 0-second TTL can return
`127.0.0.1`. Everything in T1 is then decoration: we validated one answer and connected to
another.

**Mitigation.** Bind the validated resolution to the connection. Concretely: resolve once,
validate every returned address, then **connect to a validated IP literal** while preserving the
original hostname for TLS SNI, certificate verification, and the `Host` header. The connection
therefore cannot use an address we did not check, because no second resolution occurs.

Consequences accepted deliberately:
- TLS must still verify against the *hostname*, not the IP. Certificate validation is never
  relaxed; connecting by IP while asserting the hostname is the whole point.
- A server relying on DNS round-robin for load balancing sees us pinned to one address per
  request. Acceptable, and we pick among validated addresses rather than always the first.
- If a redirect changes host, the new host is resolved and validated independently.

Residual risk: a TOCTOU window remains between validation and `connect()` at the OS level, but it
no longer involves a second *DNS* lookup, which is the practical attack. Documented rather than
claimed solved.

### T4 — Resource exhaustion by a hostile or broken server
Infinite bodies, `Content-Length` that lies, byte-per-second trickling, gzip bombs, redirect
loops, connections that accept and never respond.

**Mitigation.** Streaming with the cap enforced *during* read (already implemented and tested in
`acquisition/content.py`); a declared `Content-Length` over the cap is rejected before the body
is read at all; separate connect, read, and **total** timeouts so slow-drip cannot evade a
per-read timeout; bounded redirect hops; bounded concurrency globally and per source; explicit
decompression limits deferred to Slice 5 with archives, but transport-level compression bounded
here.

### T5 — Looking like an attacker to a portal operator
Unbounded concurrency and retry storms are indistinguishable from a DoS attempt, and the outcome
is a permanent block.

**Mitigation.** Per-source rate limiting and concurrency caps from the registry (already
schema-enforced and bounded); a contactable User-Agent (already enforced by config); `Retry-After`
honoured; retry budget so a broadly failing source cannot amplify; exponential backoff with full
jitter so parallel workers do not synchronise into bursts; `robots.txt` respected for crawling
sources.

### T6 — Retrying what must not be retried
Blind retry turns a `403` into a hammering loop and can duplicate non-idempotent effects.

**Mitigation.** Status-class policy, not a blanket rule. Retry `408`, `425`, `429`, `500`, `502`,
`503`, `504`, connection errors, and timeouts. Do **not** retry `400`, `401`, `403`, `404`, `405`,
`410`, `451`. Never retry a payload rejected as unsafe — a quarantined document is a decision, not
a transient failure. Only idempotent methods (`GET`, `HEAD`) are retried; the fetcher exposes
nothing else.

### T7 — Credential and token leakage
Credentials embedded in a URL (`https://user:pass@host/`) leak into logs, the metadata database,
and provenance records. Headers can leak across a cross-origin redirect.

**Mitigation.** URLs carrying credentials are rejected outright (T1, step 2), not stripped —
their presence means the input is wrong. Authorization headers are never set by this layer; there
is no authenticated source, by policy. On a cross-host redirect, request headers are rebuilt from
scratch rather than carried over.

### T8 — Log injection and unbounded log growth
URLs and headers are attacker-controlled and land in every log line. CRLF in a value can forge
log entries.

**Mitigation.** Structured JSON logging (already implemented) escapes control characters as a
property of the encoding, not by sanitising. Logged URLs are length-bounded. Response bodies are
never logged.

## Explicit non-goals

- **Proxy support.** Not implemented. A proxy would relocate the SSRF boundary and needs its own
  model.
- **Authenticated sources.** Out of scope permanently for anonymous public collection.
- **Bypassing anti-bot measures.** A source that blocks us is a source we stop collecting, not one
  we defeat.
- **Sandboxing the fetch process.** Least-privilege for parser workers is Slice 5+; the fetcher
  needs only outbound HTTP and raw-tier write.

## Fails-closed check

Every decision point above denies by default: an unresolvable host, an unparseable URL, an
address of indeterminate class, a missing rate-limit policy, or a source not in the allowlist all
result in rejection. Nothing proceeds because a check was inconclusive.

## Verification obligations

Not optional, and not satisfied by mocks (see rule 22). Failure paths to be exercised against a
controlled local server: 200, 301/302/303/307/308, redirect off-allowlist, redirect to private
IP, redirect loop, redirect chain over the hop cap, 404, 408, 429 with and without `Retry-After`,
500, 502, 503, connection refused, DNS failure, TLS failure, connect timeout, read timeout, total
timeout, slow-drip body, oversized body, `Content-Length` lie, wrong MIME type, empty response,
truncated stream, malicious filename, retry exhaustion, cancellation.

DNS rebinding specifically: a resolver stub returning a public address on first lookup and a
private one on the second must not produce a connection to the private address.
