# Aedifex — start here

## Required reading, before any work

**Read [SRS.md](SRS.md) first, at the start of every session, before writing or changing any code.**

It defines what Aedifex is *for*. Every other document in this repository describes how one part
works; the SRS says why the parts exist. Where a design decision and the SRS disagree, the SRS wins
and the design is wrong.

Do not skip it because a task looks small. A one-line change to an extraction rule can quietly
violate "every extracted value must be traceable", and the cost of noticing later is a corpus of
findings nobody can defend.

Then read, as the task requires:

| Document | What it governs |
| --- | --- |
| [SRS.md](SRS.md) | Vision, mission, the evidence pipeline, guiding principles, personas |
| [AEDIFEX-RULES.md](AEDIFEX-RULES.md) | The engineering constitution: security, testing, verification, review |
| [ARCHITECTURE.md](ARCHITECTURE.md) | What exists today, and the deliberate omissions |
| [DATA_SOURCES.md](DATA_SOURCES.md) | Source approval, and the hard limits that hold regardless of review |
| [SECURITY.md](SECURITY.md) | The threat model and the controls that implement it |
| [docs/adr/](docs/adr/) | Decisions already taken, with their reasoning |
| [docs/research/CONSTRUCTION_INFORMATION_MODEL.md](docs/research/CONSTRUCTION_INFORMATION_MODEL.md) | What construction information *is*: the four chains, the deterministic/AI boundary per document, and the minimum evidence for each verification domain |
| [docs/research/CORPUS_ROADMAP.md](docs/research/CORPUS_ROADMAP.md) | Where construction evidence exists worldwide, and what we are missing |
| [docs/research/INDIAN_POSTAWARD_SOURCES.md](docs/research/INDIAN_POSTAWARD_SOURCES.md) | Every Indian post-award source, ranked, and why almost none is usable |
| [docs/research/REFERENCE_PROVISION_SECOND_SOURCE.md](docs/research/REFERENCE_PROVISION_SECOND_SOURCE.md) | Whether the Reference Provision model generalises to a second authority, and exactly where it does not |
| [docs/plans/](docs/plans/) | Implementation plans, newest first |
| [docs/requirements/functional.md](docs/requirements/functional.md) | Numbered requirements and their status |

## The three sentences that matter most

**Evidence is the product, not documents.** A feature that produces a value nobody can trace back to
a page of a stored artifact has produced nothing this project wants.

**LLMs interpret evidence. Deterministic code verifies evidence.** Arithmetic, compliance checks,
security decisions, state transitions and financial calculations are never delegated to a model.

**Provenance is never optional, and raw data is immutable.** Never fabricate a provenance row,
never invent a source approval, never overwrite or delete stored evidence.

## Practical notes

- The crawler is an ingestion mechanism. It is not the product, and it is not where new effort
  belongs by default.
- Build for the pipeline, not for NHAI. One-off features for a single portal are the failure mode the
  SRS names explicitly (principle 10).
- Gates are run **separately and unpiped** — `ruff`, `black`, `mypy`, then the test suites. A
  pipeline's exit status is the last command's, which has already produced one false "clean".
- Aedifex plans belong in [docs/plans/](docs/plans/) inside this repository, not only in a hidden
  home directory where the file tree cannot show them.
