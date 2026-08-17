# Runbook

Operational procedures for the acquisition pipeline.

> **Scope note.** Phase 0 ships the API, the metadata store, and the source registry. Crawler
> and worker procedures are marked *(Phase 1)* and are written as the intended design, not as
> tested procedure.

## Running PostgreSQL without Docker

Docker is not required for the database. This is the path used to verify migrations and the
integration suite:

```bash
brew install postgresql@17
brew services start postgresql@17
export PATH="/opt/homebrew/opt/postgresql@17/bin:$PATH"
createdb aedifex

export AEDIFEX_ENVIRONMENT=test
export AEDIFEX_DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/aedifex
make migrate
make test-integration
```

`brew services stop postgresql@17` to stop it. Note the Homebrew default superuser is your OS
username; the commands above assume a `postgres` role exists — create it with
`createuser -s postgres` if `psql` reports it missing.

## Health checks

| Endpoint | Meaning | On failure |
| --- | --- | --- |
| `GET /health` | Process is up. Checks no dependencies, so it never flaps. | Process is dead or wedged; restart. |
| `GET /health/ready` | Dependencies reachable. Returns 503 with per-check detail. | Read `checks` in the body to see which dependency is down. |

```bash
curl -s localhost:8000/health/ready | jq
{
  "status": "not_ready",
  "checks": { "registry": "ok (8 sources)", "database": "unavailable (OperationalError)" }
}
```

The database check reports only the exception *type*, deliberately: the endpoint is
unauthenticated and the DSN must not leak. For the real error, read the logs — the full
message is logged at `warning` with `event=readiness.database_unavailable`.

## Log queries

Every line is JSON with these keys where applicable: `request_id`, `job_id`, `source_id`,
`document_id`, `project_id`, `stage`, `status`, `duration_ms`, `error_type`, `error`, plus
`service` and `version`.

```bash
# Everything about one request
jq 'select(.request_id == "3f2a…")'

# Everything that happened to one document
jq 'select(.document_id == "…")'

# All failures in one crawl run
jq 'select(.job_id == "…" and .status == "failed")'

# Slowest stages
jq 'select(.duration_ms != null) | {stage, duration_ms}' | sort -k2 -rn
```

Stage events are `<stage>.started`, `<stage>.completed`, `<stage>.failed`.

## Common situations

### The API will not start

1. **Configuration rejected.** The most common cause. `Settings` validation fails loudly with
   the reason. Two frequent ones:
   - `unknown environment variable(s): AEDIFEX_…` — a typo in a deployment manifest. The full
     list of valid names is in the error.
   - `invalid production configuration: …` — a development placeholder credential reached
     production. This is intentional; supply real values.
2. **Registry invalid.** Startup succeeds but `/v1/sources` returns 503 and the logs carry
   `event=registry.unavailable`. Run `make validate-registry` to see every problem at once.

### A document is stuck

Find its state:

```sql
SELECT state, attempts, error_type, error_message, last_attempted_at
FROM discovered_urls WHERE url_sha256 = '…';
```

| State | Meaning | Action |
| --- | --- | --- |
| `discovered` | Queued, never attempted | Check the worker is running *(Phase 1)* |
| `downloading` | In flight, or the worker died mid-download | If `last_attempted_at` is stale, reset to `failed` so the retry path picks it up |
| `failed` | Retryable | Inspect `error_type`; retry is a legal transition |
| `quarantined` | Tripped a safety limit | **Requires human review.** See below. |

### Something is quarantined

`QUARANTINED` is terminal on purpose. It means content violated a safety limit — oversized,
empty, a format mismatch, or a spoof. Do not bulk-release.

```sql
SELECT source_id, url, error_type, error_message
FROM discovered_urls WHERE state = 'quarantined' ORDER BY discovered_at DESC;
```

Diagnose by `error_type`:

- `payload exceeds … limit` — legitimately large document, or a hostile stream. If legitimate,
  raise `AEDIFEX_MAX_DOWNLOAD_BYTES` deliberately rather than per-document.
- `declared media type … contradicts filename` — almost always an HTML error or login page
  returned with HTTP 200. The crawler needs fixing, not the document releasing.
- `content is actually X but was declared as Y` — treat as hostile until proven otherwise.

Releasing is an explicit, reviewed action. There is deliberately no self-service path.

### Crawl rate complaints from a site operator *(Phase 1)*

1. Set `enabled: false` for that source and deploy. This stops collection immediately.
2. Reduce `rate_limit` in the registry entry.
3. Our User-Agent carries a contact address by design — reply, and record the exchange in the
   source's `notes`.
4. If the operator asks us to stop, set `verification_status: blocked` with the reason. The
   schema then makes re-enabling impossible without a deliberate documented change.

### Disk or bucket filling

Raw storage is immutable and append-only, so it only grows. Check per-source volume:

```sql
SELECT d.file_format, count(*), pg_size_pretty(sum(d.size_bytes))
FROM documents d GROUP BY 1 ORDER BY 3 DESC;
```

Do not delete raw objects to reclaim space — they are the evidence base, and
`ON DELETE RESTRICT` on `discovered_urls.document_id` will refuse anyway while provenance
references them. Reclaim from the regenerable tiers (`processed/`, `normalized/`) instead, or
disable the noisiest source.

## Migrations

```bash
make migrate      # apply to head
make downgrade    # reverse one revision
```

Migrations are run explicitly, never on container start: N replicas booting simultaneously
would race to alter the schema.

If a migration fails partway, `transaction_per_migration` is enabled, so the failing revision
rolls back on its own. Fix the revision and re-run; do not hand-edit `alembic_version`.

## Backups

Not yet configured. Before any real data is collected, the metadata store needs
point-in-time recovery, and the raw bucket needs versioning (the compose stack enables MinIO
versioning locally as a reminder of the intent). Tracked for Phase 10.

## Escalation

There is no on-call rotation; this is a pre-release project. Failures that need a human
decision rather than a restart:

- Anything `quarantined` in bulk — suggests a crawler bug producing garbage.
- A site operator contact — legal and relationship judgement, not technical.
- A finding that cannot be reproduced from stored evidence — this breaks the core promise of
  the system and should stop further processing until understood.
