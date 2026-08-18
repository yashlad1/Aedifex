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
| SSRF to internal services, IMDS, loopback | Ordered validation; every resolved address checked; mixed answers rejected entirely | `fetch/guard.py`, `fetch/addresses.py` |
| DNS rebinding / TOCTOU | Resolved once, then the validated address is pinned to the connection; no second lookup exists | `fetch/guard.py` |
| Redirect used to escape validation | Every hop re-validated from the start; loops and hop overruns rejected | `fetch/redirects.py` |
| Transport downgrade via redirect (`https` → `http`) | Refused unless the source explicitly accepted an insecure channel | `fetch/redirects.py` |
| Hostile `Retry-After` parking a worker | Server-requested delays above 300s abandon rather than sleep | `fetch/retry.py` |

Content that trips a limit moves to `QUARANTINED`, which is a terminal state. Release requires
an explicit human decision, so a bad payload cannot loop back into the pipeline automatically.

### Known gaps

Honest about what is not yet built, because these matter before any crawler is enabled:

- **Decompression bombs.** ZIP archives are recognised but not yet expanded. Bounded
  expansion (entry count, total uncompressed size, nesting depth) must land with the
  downloader in Phase 1.
- **Malicious PDFs.** No PDF sanitisation yet. Parsers must run without network access and
  with resource limits; embedded JavaScript and external references must be ignored.
- **SSRF.** ~~Not built.~~ **Implemented** in
  [`acquisition/fetch/`](src/aedifex/acquisition/fetch/): a type-level gate where the transport
  accepts only a `ValidatedTarget`, host allowlisting per source, every resolved address
  validated, mixed answers rejected wholesale, and the validated address pinned to the
  connection so no second DNS lookup can occur. See
  [the threat model](docs/security/threat-model-http-fetch.md) and
  [ADR 0010](docs/adr/0010-fetch-retry-ssrf-policy.md). The transport that consumes it is not
  built yet, so nothing makes outbound requests today.
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

### Known gaps: controls that need GitHub Advanced Security

Three authored controls cannot run on a private repository without Advanced Security. They
are recorded here as gaps rather than presented as passing checks.

| Control | Status | What is lost | What still covers it |
| --- | --- | --- | --- |
| CodeQL | Not running | Taint tracking specifically — following an attacker-controlled value to a dangerous sink | **Semgrep CE** as the mandatory SAST gate, plus ruff's bandit rules as a first pass |
| Dependency review | Not running | Blocking a vulnerable or copyleft dependency *at introduction*, pre-merge | `pip-audit --strict` on the locked set every run — catches vulnerable deps, but not licences and not pre-merge |
| SARIF in code scanning | Not uploading | Findings in the Security tab, with history | Trivy output printed in the log and SARIF retained as a build artifact |

Each is gated so that enabling Advanced Security turns them on via a repository variable
rather than a workflow change. Nothing is left as a permanently red check.

**The repository will not be made public to obtain free CodeQL.** That would publish
[docs/ip/](docs/ip/), including the trade-secret register, and trade-secret protection depends on
actually maintaining confidentiality. The IP direction outranks the convenience.

### Static analysis: Semgrep CE is the gate

| Tool | Role | Blocking |
| --- | --- | --- |
| ruff (bandit-derived rules) | Fast first pass on every commit; patterns only | Yes |
| **Semgrep CE** | Broader code-security analysis, runs standalone on private code | **Yes** |
| pip-audit | Advisories against the locked dependency set | Yes |
| gitleaks | Secrets across full git history | Yes |
| Trivy | Container and filesystem CVEs, secrets, misconfiguration | Weekly run blocks; PR run reports |
| SBOM (SPDX) | Inventory per image | Produced, not a gate |
| CodeQL | Taint tracking | Optional capability, off — needs Advanced Security |

Bandit itself is deliberately **not** added: it overlaps almost entirely with the bandit-derived
`S` rules already enforced by ruff, and a second tool covering the same ground is maintenance
without coverage.

Semgrep runs five rulesets — `p/python`, `p/security-audit`, `p/secrets`, `p/dockerfile`,
`p/github-actions` — the last two chosen because the mistakes this project has actually made were
in a Dockerfile and in workflow permissions, not in application code.

**The scan is self-testing.** A clean Semgrep run is only meaningful if the engine analysed the
code: a wrong path, a failed ruleset fetch, a directory dropped by a default ignore list, or a parse
error the tool downgrades to a warning all produce "0 findings" too, and look identical to success.
So CI additionally runs [`.semgrep/selftest.yaml`](.semgrep/selftest.yaml) and requires it to
produce results — verified by counting matches, files scanned, and scanner errors in the JSON
report, not by reading an exit code. Same discipline as `REQUIRE_INTEGRATION_TESTS`: a check that
cannot fail is not a check.

That instrumentation immediately earned its place. Building it surfaced three defects in the gate it
was meant to validate, none of which were visible in a green log:

| Defect | Effect | Fix |
| --- | --- | --- |
| The Dockerfile carried a comment between two `ENV` line continuations. BuildKit accepts this; Semgrep's Dockerfile parser does not — it abandoned lines 19–104. | `p/dockerfile` analysed essentially none of the Dockerfile, the ruleset chosen *because* our real mistakes are in Dockerfiles. The run still reported 0 findings and exit 0. | Comments moved above the instruction; CI now runs `--strict`, which turns a partial parse into a build failure |
| `tests/` was passed as a scan target but is excluded by Semgrep's default ignore list. | Zero test files were scanned while the command implied otherwise. | Dead target removed; the exclusion is documented below rather than implied away |
| The self-test asserted only that the exit code was non-zero. `--error` makes findings exit 1, but a malformed config exits 7 and a fatal error exits 3. | A broken `selftest.yaml` would have been reported as "matched as expected" — the anti-false-green check had its own false green. | Requires exit code exactly 1, then verifies match count, scanned-file count, and an empty error list from the JSON |

Measured after the fix, in CI: 255 rules over 90 targets, 0 findings, **parsed lines ~100.0%**
(previously ~99.4%, where the missing fraction *was* the Dockerfile). The self-test reported 119
function definitions across 18 of 28 scanned files in `src/aedifex/` with 0 scanner errors, matching
the local run exactly. CI enforces floors well below those numbers, so ordinary churn never trips
them while a real breakage collapses them to zero.

**What the gate does not reach.** Test code is outside the scan, because Semgrep's default ignore
list excludes test directories. That is acceptable — test code does not ship, and fixtures containing
deliberately fake credentials would generate constant noise from `p/secrets` — but it is a stated
limitation rather than an assumed one. Covered: `src/`, `apps/`, `scripts/`, `migrations/`, the
Dockerfile, the workflows, and repository configuration.

**Pinning the tool does not pin the rules.** `semgrep==1.173.0` is pinned, but `p/*` rulesets are
fetched from the registry at run time and change without notice — the rule count moved 255 → 256
between two consecutive local runs. A build can therefore start failing with no change to our code.
That is new coverage, and the response is to fix the finding, never to suppress the rule to restore
green.

#### Detail: no data-flow SAST

**CodeQL is not running.** It reports through GitHub code scanning, which on a private
repository requires GitHub Advanced Security. This repository does not have it — the API returns
`Code scanning is not enabled for this repository` (HTTP 403), and the first real CI run failed
for that reason.

What this means concretely: ruff's bandit-derived rules run on every commit and catch common
patterns, but **nothing currently follows data flow**, so an attacker-controlled value reaching a
dangerous sink would not be detected automatically. That is the bug class that matters most for a
system built to ingest hostile documents, so this gap is real rather than cosmetic.

The workflow is kept but triggered manually only. A check that can only fail is worse than an
acknowledged gap, because it trains people to ignore red.

Three ways to close it, none chosen unilaterally:

| Option | Cost | Note |
| --- | --- | --- |
| Enable Advanced Security | Paid add-on | One setting, then restore the workflow triggers |
| Make the repository public | Free CodeQL | **Read [docs/ip/](docs/ip/) first** — the trade-secret register and invention records must not be published |
| Adopt a SAST tool that gates the build directly | Free | Does not need code scanning; a new tool dependency |

Container and filesystem scanning (Trivy) **do** run, and their SARIF is retained as a build
artifact rather than uploaded to code scanning.

## Base-image vulnerability remediation

Pinning the base image by digest buys reproducibility but freezes its package versions, so
security updates must be applied explicitly rather than arriving with a moving tag. That tradeoff
is deliberate, and this is the other half of it.

The first real CI Trivy scan found **11 fixable HIGH findings, all in the base image and none in
our locked dependencies** (every venv package reported zero):

| Advisory | Count | Component | Remediation |
| --- | --- | --- | --- |
| CVE-2026-53615 | 9 | util-linux family — integer overflow in libblkid partition parsing | `apt-get --only-upgrade` to `2.41.5-0+deb13u1` |
| CVE-2025-47273 | 1 | setuptools path traversal, vendored in pip as `pkg_resources` | pip removed from the runtime image |
| GHSA-6v7p-g79w-8964 | 1 | msgpack out-of-bounds read, vendored in pip | pip removed from the runtime image |

Upstream `python:3.13-slim` had not been rebuilt — the pinned digest was still the current one —
so waiting for a newer digest was not available.

Removing pip is a fix rather than a workaround: the venv is installed non-editable and
self-contained, so nothing at runtime needs pip, setuptools, or `pkg_resources`, and an image that
parses hostile documents has no business carrying a package installer. Verified after removal: the
package still imports, production hardening still rejects placeholder credentials, `alembic`
still runs, and the API still serves `/health` and `/health/ready`.

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
