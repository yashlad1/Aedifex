# 3. Immutable, content-addressed object storage

Date: 2026-08-17

## Status

Accepted

## Context

Collected documents are the evidence base for financial findings. If a stored document can be
modified after the fact, every finding derived from it becomes indefensible — the question
"what exactly did the invoice say?" must have one permanent answer.

Separately, crawlers will be re-run constantly during development, so the write path must
tolerate repetition without accumulating duplicates.

## Decision

Storage is tiered, and the raw tier is write-once:

```
raw/          immutable. Never modified, never deleted.
processed/    parsed text, OCR output. Regenerable.
normalized/   canonical entities. Regenerable.
labeled/      ground truth.
synthetic/    generated data.
```

Keys are derived entirely from content:

```
raw/<source_id>/<aa>/<bb>/<sha256><ext>
<tier>/<stage>/<aa>/<bb>/<sha256>.<ext>
```

`derived_key()` refuses to target the raw tier, so derived output cannot overwrite its own
input. Keys contain no timestamp, and no remote filename ever appears in a key.

## Alternatives considered

**Timestamp-partitioned keys** (`raw/cpwd/2026/08/17/...`). Conventional and good for
lifecycle policies, but breaks idempotency: the same document re-downloaded next month lands on
a different key, producing a duplicate. Time-based questions are better answered by the
metadata database, which has indexes for them.

**Remote filename in the key.** Human-readable, but the filename is attacker-controlled, so
every write becomes a path-traversal risk. Filenames are kept as descriptive metadata instead.

**Mutable "latest" pointers.** Convenient, and incompatible with an audit trail.

**Flat prefix per source.** Millions of objects under one prefix degrades listing. The
two-level digest shard spreads them evenly.

## Consequences

- Re-running a crawl overwrites objects byte-for-byte with identical content. Harmless.
- Deduplication is free: identical content computes an identical key.
- No path-traversal surface, since both key components are pattern-validated.
- Storage only grows. Reclamation comes from the regenerable tiers, not from raw.
- The same document collected from two sources is stored twice, deliberately: each source's
  collection stays independently auditable and independently deletable if a licence changes.
