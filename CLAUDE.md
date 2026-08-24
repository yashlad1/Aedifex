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
| [docs/research/POLICY_RULE_COVERAGE.md](docs/research/POLICY_RULE_COVERAGE.md) | Every rule derivable from the current corpus, and whether it is blocked by evidence or by architecture |
| [docs/research/CORPUS_ACQUISITION_STRATEGY.md](docs/research/CORPUS_ACQUISITION_STRATEGY.md) | The multi-year acquisition plan: 60 India-specific sources catalogued, scored and ordered, with robots verified for 46 |
| [docs/research/CAG_AUDIT_PATTERNS.md](docs/research/CAG_AUDIT_PATTERNS.md) | Eight real audit patterns read backwards from completed CAG findings to the evidence each needs, and which document is missing |
| [docs/research/NHAI_PUBLIC_DATA_ENDPOINTS.md](docs/research/NHAI_PUBLIC_DATA_ENDPOINTS.md) | Every ungated NHAI data endpoint, the 1,450-project static register, and the four identifiers that join documents to projects |
| [docs/research/DOCUMENT_LAYOUT_SURVEY.md](docs/research/DOCUMENT_LAYOUT_SURVEY.md) | Layout and table-structure engines measured on the real corpus: what the licences allow, why per-cell OCR failed, and why RapidOCR stays |
| [docs/research/BUILDING_CORPUS_AVAILABILITY.md](docs/research/BUILDING_CORPUS_AVAILABILITY.md) | Where Indian **building** construction documents actually are, classified A–F: what was acquired, why the priced-BOQ reader cannot read them yet, and the one link no reachable source publishes |
| [docs/research/PRODUCT_FIRST_CORPUS_DISCOVERY.md](docs/research/PRODUCT_FIRST_CORPUS_DISCOVERY.md) | Product-first corpus discovery: 152 ranked sources, the workflow coverage matrix, the structural gap at Measurement and RA Bill, the three-layer canonical corpus, and the OCR gateway recommendation |
| [docs/research/REAL_CORPUS_RULE_VALIDATION.md](docs/research/REAL_CORPUS_RULE_VALIDATION.md) | Every rule run against a real building bundle: which `INCONCLUSIVE` results are honest and which were defects, the reviewer friction log, and what the next bundle must contain |
| [docs/DATA_REQUEST.md](docs/DATA_REQUEST.md) | The forwardable one-pager for procuring a real project bundle: the ask, what may be redacted, and what the partner gets back |
| **[docs/plans/2026-08-24-reality-sprint.md](docs/plans/2026-08-24-reality-sprint.md)** | **The standing direction. Engineering is frozen; new work needs an evidence ID** |
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

- **Engineering is frozen as of 2026-08-24.** New work needs an evidence ID: a real document or an
  observed reviewer workflow that forced it. A hypothetical is not one. Documentation and defects
  demanded by real evidence are the exceptions. See the Reality Sprint plan and rule 101.
- The crawler is an ingestion mechanism. It is not the product, and it is not where new effort
  belongs by default.
- Build for the pipeline, not for NHAI. One-off features for a single portal are the failure mode the
  SRS names explicitly (principle 10).
- Gates are run **separately and unpiped** — `ruff`, `black`, `mypy`, then the test suites. A
  pipeline's exit status is the last command's, which has already produced one false "clean".
- Aedifex plans belong in [docs/plans/](docs/plans/) inside this repository, not only in a hidden
  home directory where the file tree cannot show them.
