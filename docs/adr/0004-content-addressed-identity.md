# 4. SHA-256 content identity with deterministic UUIDs

Date: 2026-08-17

## Status

Accepted

## Context

The pipeline must be safely re-runnable (crawlers will be re-run constantly), and the same
document is routinely published at multiple URLs and across multiple portals. Something must
answer "is this the same document?" without ambiguity.

## Decision

A document's identity is the SHA-256 of its bytes. Its database primary key is a UUIDv5 derived
from that digest:

```
namespace   = uuid5(NAMESPACE_URL, "https://aedifex.dev/ns/document")
            = 852e666c-780a-5903-85c4-d357129f3878
document_id = uuid5(namespace, sha256_hex)
```

The namespace is pinned as a literal, with a test asserting it still equals its derivation.

Digests are computed while streaming, under a size cap, and the format is sniffed from the same
pass.

## Alternatives considered

**Random UUID primary key, unique index on the digest.** Works, but every ingest needs a
read-then-write to find the existing row, which is racy under concurrency. Deriving the key
means an insert simply conflicts.

**Digest as the primary key directly.** Saves a column. Rejected: a 64-character string key
is wider in every foreign key and index, and UUID is better supported by tooling.

**MD5 or SHA-1.** Faster, both collision-broken. Collision resistance is the property being
relied on for identity, so this is not a place to economise.

**URL as identity.** Loses deduplication entirely, and URLs are unstable.

## Consequences

- Ingestion is idempotent without coordination: same bytes, same key, on any machine.
- Deduplication needs no separate index or lookup.
- The namespace can never change. Doing so would produce different IDs for content already
  stored and silently break deduplication for the entire corpus — hence the test.
- Empty payloads must be rejected: they all share one digest, which would collapse unrelated
  documents into one row.
- A document that is re-published with a one-byte change is a different document. Near-duplicate
  detection is a separate, later concern.
