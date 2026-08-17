# Security

## Threat model

This system deliberately downloads files from the public internet and will eventually process
financially consequential enterprise documents. Two premises follow:

1. **Every downloaded byte is hostile until proven otherwise.**
2. **A false negative is more dangerous than a false positive.** Missing a fraudulent invoice
   costs more than flagging a legitimate one.

## Untrusted content

Implemented in [`acquisition/content.py`](src/aedifex/acquisition/content.py) and
[`domain/files.py`](src/aedifex/domain/files.py).

| Threat | Control | Where |
| --- | --- | --- |
| Oversized payload exhausting memory or disk | Size cap enforced *while streaming*, not after buffering | `hash_stream` |
| Empty file corrupting deduplication | Rejected; every empty file shares one digest | `hash_stream` |
| Content spoofing (a ZIP claiming to be a PDF) | Magic bytes compared against the declared type | `resolve_format` |
| HTML error or login page served with HTTP 200 for a `.pdf` request | Contradiction between media type and filename is rejected | `resolve_format` |
| Unsupported or executable formats | Allowlist per source; anything else refused | `resolve_format` |
| Path traversal via filename or `Content-Disposition` | Filenames stripped to a safe basename; storage keys derived only from digests, never from remote names | `safe_filename`, `storage/keys.py` |
| Unicode filename trickery | NFKC normalisation, then a strict `[A-Za-z0-9._-]` allowlist | `safe_filename` |
| Windows reserved device names | Defused (`con.pdf` → `con_file.pdf`) | `safe_filename` |
| Arbitrary object construction from config | `yaml.safe_load` only | `registry/loader.py` |
| Tampering in transit | Plain HTTP requires explicit per-source acknowledgement | `registry/models.py` |

Content that trips a limit moves to `QUARANTINED`, which is a terminal state. Release requires
an explicit human decision, so a bad payload cannot loop back into the pipeline automatically.

### Known gaps

Honest about what is not yet built, because these matter before any crawler is enabled:

- **Decompression bombs.** ZIP archives are recognised but not yet expanded. Bounded
  expansion (entry count, total uncompressed size, nesting depth) must land with the
  downloader in Phase 1.
- **Malicious PDFs.** No PDF sanitisation yet. Parsers must run without network access and
  with resource limits; embedded JavaScript and external references must be ignored.
- **SSRF.** No crawler exists yet. When one does, URLs must be validated against an allowlist
  derived from the source's `base_url`, with redirects re-validated at every hop and requests
  to private address ranges refused.
- **PII detection and redaction.** Sources that publish personal data are flagged
  (`contains_personal_data`), but no screening is implemented. This must exist before the
  corpus is used for training.

## Secrets

- Never hardcoded. Configuration comes from the environment via `Settings`.
- Typed as `SecretStr`, so they do not leak into `repr`, logs, or tracebacks.
- `safe_database_url()` masks passwords for log lines.
- `.env` is gitignored; `.env.example` holds only placeholders.
- Production uses a secret manager (AWS Secrets Manager), not files.
- CI runs `gitleaks` over full history and `pip-audit` for known vulnerabilities.

### Production refuses to boot with development credentials

`docker-compose.yml` and `.env.example` ship well-known passwords. With
`AEDIFEX_ENVIRONMENT=production`, the configuration layer rejects placeholder DSN credentials,
the development bucket name, placeholder storage keys, `debug=true`, and a placeholder
User-Agent contact. Failing to start is strictly better than serving with `postgres:postgres`.

An unrecognised `AEDIFEX_*` environment variable is also a hard error. A typo such as
`AEDIFEX_DATABSE_URL` would otherwise silently leave the default in place.

## Application security

- **No raw SQL string interpolation.** SQLAlchemy parameterises everything.
- **Statement timeouts** are set at connection level; an unbounded query is how a metadata
  store takes down an API.
- **Container runs as a non-root user.** CI asserts this.
- **Readiness endpoint leaks nothing.** Only the exception *type* is reported, never the DSN
  or driver message, since the endpoint is unauthenticated. Tested.
- **Inbound `X-Request-ID` is truncated to 64 characters.** It is attacker-controlled and
  lands in every log line for the request.

### Not yet built

No authentication, authorisation, or RBAC. The API is read-only metadata and is not intended
to be internet-facing yet. This must be in place before any write endpoint or any deployment
beyond a private network — tracked for Phase 10.

## Privacy

Public procurement documents may contain PAN, Aadhaar, bank accounts, phone numbers,
addresses, signatures, and emails. Obligations:

- Sources known to publish personal data must set `contains_personal_data: true`.
- Personal data must not be used for model training without screening.
- Licence and permitted use are recorded per source and exposed via the API, so anyone
  consuming the corpus can see its constraints.

## Reporting a vulnerability

This is a pre-release internal project. Report privately to the maintainers rather than
opening a public issue. Do not include real credentials or real project documents in a report.
