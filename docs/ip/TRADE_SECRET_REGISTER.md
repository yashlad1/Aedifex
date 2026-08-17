# Trade secret register

**Confidential.** Do not publish this file or its contents.

Trade-secret protection depends on the information genuinely remaining confidential *and* on
reasonable measures being taken to protect it. A "trade secret" that has been published is simply
published.

## Current assets

**None yet.** Nothing built so far is confidential in substance: the acquisition foundation uses
well-known techniques, and the source registry deliberately documents its own collection policy.

## Candidates as the system matures

Recorded as *candidates* so the decision is deliberate when each comes to exist. Listing something
here does not by itself protect it — the protective measures column is the substance.

| Candidate | Why it may qualify | Protective measures required |
| --- | --- | --- |
| Deterministic audit rule set | The specific rules, thresholds, and severities encode domain expertise; hard to infer from outputs | Private repository; rules versioned but not published; access limited |
| Evidence-matching heuristics | How ambiguous entities are resolved across documents | Private; not described in public documentation |
| Material ontology and specification mapping | Grade/unit/specification equivalences; expensive to assemble | Private; separate from any published schema |
| Risk scoring model | Weights and calibration | Private; explanations shown to users need not reveal weights |
| Evaluation corpora and benchmarks | Costly to build; determines competitive quality measurement | Private storage; never in public CI artifacts |
| Fraud and anomaly patterns | Derived from real audit experience | Private; never in public fixtures |
| Customer-derived tuning | Confidential by obligation as well as by value | Contractual confidentiality; tenant isolation; no cross-tenant leakage |
| Internal prompts and prompt versions | Encode extraction and reasoning approach | Private; versioned in-repo while the repo is private |
| Entity-resolution logic | Determines matching accuracy | Private |

## Required measures as the project grows

- Least-privilege repository access; private repositories.
- Role-based permissions and access logs where practical.
- Confidentiality agreements for employees and contractors; access removal on departure.
- Secrets separated from code (already: environment-based configuration, no committed credentials).
- **No proprietary datasets in public CI artifacts.** The SBOM and test fixtures must never carry
  confidential data.
- A record of who has access to what.

## Conflict rule

If something appears both here and in a public disclosure, that is a defect requiring immediate
attention — not a documentation inconsistency to reconcile later.
