# Data model

Current scope: the acquisition metadata store. Canonical evidence entities (Vendor,
PurchaseOrder, InvoiceLine, …) arrive in Phase 3 and are not modelled yet.

## Tables

### `documents` — one row per unique content

| Column | Type | Notes |
| --- | --- | --- |
| `id` | UUID, PK | UUIDv5 derived from `sha256`. Not random. |
| `sha256` | varchar(64), unique | Lowercase hex, enforced by CHECK. |
| `size_bytes` | bigint | `> 0`; an empty file is never valid evidence. |
| `file_format` | varchar(16) | From the `FileFormat` vocabulary. |
| `media_type` | varchar(128) | As declared by the server, for forensics. |
| `original_filename` | varchar(128) | Descriptive only; never used to build paths. |
| `storage_key` | varchar(512), unique | Object key, derived from the digest. |
| `document_type` | varchar(48) | Classification result; `unknown` until classified. |
| `document_category` | varchar(32) | Business domain. |
| `classification_confidence` | float | `NULL` or within `[0, 1]`, enforced by CHECK. |
| `classifier_version` | varchar(64) | Which model produced the classification. |
| `state` | varchar(32) | Lifecycle state. |
| `first_seen_at` / `updated_at` | timestamptz | |

### `discovered_urls` — the crawl frontier

| Column | Type | Notes |
| --- | --- | --- |
| `id` | UUID, PK | |
| `source_id` | varchar(64) | References the YAML registry, not a table. |
| `url` | text | Full URL as discovered. |
| `url_sha256` | varchar(64) | Unique per source; indexed instead of the URL. |
| `state` | varchar(32) | Per-URL lifecycle state. |
| `document_id` | UUID, FK → `documents`, nullable | `ON DELETE RESTRICT`. |
| `job_id` | UUID, FK → `crawl_jobs`, nullable | `ON DELETE SET NULL`. |
| `discovered_at` / `last_attempted_at` / `downloaded_at` | timestamptz | |
| `attempts`, `http_status`, `error_type`, `error_message` | | Retry bookkeeping. |

Unique on `(source_id, url_sha256)`.

### `crawl_jobs` — one row per crawl run

Holds counters, the JSONB `checkpoint` that makes a run resumable, the failure reason, and
`software_version` for reproducibility.

## Why the frontier is separate from content

This is the design decision worth understanding.

The same PDF is routinely published at several URLs, sometimes across several portals. Two
obvious models both fail:

- **Key on URL.** The same payload is stored many times. Storage and OCR costs multiply, and
  "have we seen this document?" becomes unanswerable.
- **Key on content only.** Deduplication works, but the URLs are lost, so provenance — which
  is the entire point of an audit trail — is destroyed.

So: `discovered_urls` is *where we looked*, `documents` is *what we found*. Many URLs may
reference one document.

```
discovered_urls                        documents
─────────────────────────              ─────────────────────
cpwd  /tender/123.pdf   ──┐
cpwd  /archive/123.pdf  ──┼──────────► sha256 = 9f2a…  (stored once)
nhai  /docs/tender.pdf  ──┘
```

`document_id` is null until the payload has been fetched and hashed, because content identity
cannot be known before download. A CHECK constraint enforces that any URL past `downloading`
names its document.

## Identity and idempotency

```
document_id = uuid5(namespace, sha256_hex)
namespace   = uuid5(NAMESPACE_URL, "https://aedifex.dev/ns/document")
            = 852e666c-780a-5903-85c4-d357129f3878
```

Derived from content alone, so the same bytes always produce the same primary key on any
machine. Re-running a crawler conflicts on the existing row instead of inserting a duplicate.
The namespace is pinned as a literal and asserted against its derivation in
`tests/unit/test_content.py`: changing it would silently break deduplication for the whole
existing corpus.

## Lifecycle states

```
DISCOVERED ──► DOWNLOADING ──► DOWNLOADED ──► VALIDATED ──► PROCESSING ──► PROCESSED
     │              │               │             │              │
     └──────────────┴───────────────┴─────────────┴──────────────┘
                              ▼
                            FAILED ──► (retry: DOWNLOADING | PROCESSING)
                              │
                        QUARANTINED  (terminal; human release only)
```

`FAILED` can re-enter the pipeline, so a retry is a legal state move rather than a manual
database edit. `QUARANTINED` is terminal by design: content that tripped a safety limit is
released only by an explicit human decision. Transitions are declared in
`STATE_TRANSITIONS` and enforced by `assert_transition_allowed`.

## Type choices

**Enums are `VARCHAR`, not native PostgreSQL enums.** This vocabulary will grow as document
types are added, and extending a native enum needs DDL and takes locks. Values are validated
on write by SQLAlchemy; note this is application-layer enforcement, so the database alone
would accept an out-of-vocabulary string written by hand.

**Enum *values* are persisted, not names.** The database holds `invoice`, not `INVOICE`.
SQLAlchemy's default stores names, which would put a second spelling of every term into the
schema and force translation in every hand-written query.

**`url_sha256` is indexed, not `url`.** Procurement portals emit URLs long enough to exceed
btree index limits.

**Constraint names come from a naming convention.** Without one, PostgreSQL invents names,
`alembic check` reports phantom drift, and downgrades cannot reliably drop what upgrades
created.

## Migrations

Alembic, in `migrations/`. The database URL comes from `AEDIFEX_DATABASE_URL` via application
settings, never from `alembic.ini`, so no credential is committed and migrations cannot be
pointed at a different database than the application uses.

The initial migration was hand-written because no PostgreSQL instance was available when it
was authored. Two checks guard against drift:

1. `tests/unit/test_migration_matches_models.py` renders both the migration and the models to
   PostgreSQL DDL offline and compares them. Runs with no database.
2. CI runs `alembic upgrade head`, then `alembic check`, then a full downgrade/upgrade cycle
   against real PostgreSQL. This is authoritative.
