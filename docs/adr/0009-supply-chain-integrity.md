# 9. Supply-chain integrity: lockfile, digest pins, and layered scanning

Date: 2026-08-17

## Status

Accepted

## Context

Phase 0 shipped `pip-audit` and `gitleaks` but had three reproducibility holes:

1. **No lockfile.** `pyproject.toml` declared ranges (`fastapi>=0.115,<1`), so the same commit
   resolved to different dependency graphs on different days. For a system whose central
   promise is *a finding must be reproducible*, that is a contradiction at the foundation: the
   software that produced a finding could not be reconstructed.
2. **Mutable image tags.** `minio/minio:latest` and `minio/mc:latest` in particular. Two
   developers could run materially different stacks while both believed they ran the same one.
3. **Mutable action tags.** `actions/checkout@v4` resolves to whatever that tag currently
   points at. A compromised or retagged action executes with repository credentials.

Scanning was also single-layered: `pip-audit` runs against installed packages after the fact,
which finds nothing about a vulnerable dependency *being introduced*, and nothing at all about
the container base image or data-flow bugs in our own code.

## Decision

**Reproducibility.**

- Commit `uv.lock` (73 packages). Local, CI, and container installs all use
  `uv sync --locked`, which *fails* if the lock has drifted from `pyproject.toml`.
- Pin base images by digest: `python:3.13-slim@sha256:ffb752e1…`,
  `postgres:17-alpine@sha256:18cfe3ef…`, and both MinIO images.
- Pin every third-party GitHub Action to a commit SHA, with the version in a trailing comment.

All digests and SHAs were resolved from the Docker Hub registry API and the GitHub API. None
were guessed.

**Freshness, kept separate from reproducibility (rule 32).** Dependabot raises weekly PRs for
Python dependencies, Actions, and Docker images. Nothing auto-merges; every update passes the
same CI as hand-written code.

**Layered scanning**, because each layer sees something the others cannot:

| Layer | Tool | Catches |
| --- | --- | --- |
| Dependency introduction | `dependency-review-action` on PRs | A new dependency with a known high CVE or a denied licence, *before* merge |
| Installed dependencies | `pip-audit --strict` | Advisories against what is actually installed |
| Our own code, data flow | CodeQL `security-and-quality` | Attacker-controlled input reaching a dangerous sink — ruff's bandit rules do not follow data flow |
| Container image | Trivy | OS and library CVEs in the base image, which no Python tool sees |
| Repository | Trivy `fs` | Secrets and misconfiguration |
| Git history | gitleaks, `fetch-depth: 0` | A secret removed from HEAD but still in history |
| Time | Scheduled weekly workflow | Advisories published *after* the code merged |

**Blocking policy.** PR-time container scanning reports but does not block: a base-image CVE
with no available fix must not halt unrelated work. The scheduled scan uses `exit-code: 1` and
is allowed to fail loudly, since it blocks nobody. Dependency review blocks on high severity,
because that is a decision being made at the moment it can still be reversed cheaply.

An SBOM (SPDX) is generated for each built image.

## Alternatives considered

**`pip freeze` requirements.txt.** Works, but loses the platform-independent resolution and
hash verification `uv.lock` provides, and needs manual regeneration.

**Poetry or pip-tools.** Equivalent capability. uv was already the project's tool; adding a
second resolver would be gratuitous.

**Block PR merges on any image CVE.** Rejected. Base images routinely carry unfixed
low-relevance CVEs; blocking would train people to bypass the gate, which is worse than
reporting.

**Renovate instead of Dependabot.** More configurable, particularly for grouping. Dependabot
is native, needs no third-party app, and supports the `uv` ecosystem. Revisit if grouping
becomes painful.

**Skip SHA-pinning actions and rely on major tags.** The common practice, and the reason
supply-chain attacks via retagged actions work. The cost is Dependabot noise, which is
acceptable.

## Advantages

- A commit now resolves to exactly one dependency graph, one interpreter, and one set of base
  images — a precondition for reproducible findings.
- An upstream retag cannot change what we run.
- Vulnerabilities are caught at introduction, at install, in the image, and on a schedule.

## Disadvantages

- `uv.lock` is a large file that appears in many diffs. Reviewers should read
  `pyproject.toml` for intent and treat the lock as generated output.
- Digest pins are unreadable, hence the version comments.
- SHA-pinned actions require Dependabot to stay current; if Dependabot is ever disabled, the
  pins silently rot. Accepted knowingly.

## Operational consequences

Changing a dependency is now two steps: edit `pyproject.toml`, then `make lock`. CI fails
loudly if the second is forgotten — `make install` also uses `--locked`, so the mistake is
caught locally first.

## Security consequences

Reduces the blast radius of a compromised upstream package, image, or action. Does **not**
address a compromise of the upstream source itself before publication; SLSA build provenance
(rule 38) is the eventual answer and is not yet implemented.

## Migration consequences

Existing developers must run `make install` once to move onto the locked set. `uv.lock` was
generated from the ranges already in `pyproject.toml`, so no version changed.
