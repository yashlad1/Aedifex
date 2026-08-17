# Authorship and contribution record

Purpose: keep an accurate record of who contributed what, and how AI assistance was used. This
matters for ownership diligence, and it matters specifically for AI-assisted work because
inventorship centres on the contributions of natural persons.

## Contributors

| Person | Role | Areas | Period |
| --- | --- | --- | --- |
| Yash Lad | Author, architect, direction | Product definition, engineering constitution, architectural direction, requirements, review | 2026-08 – present |

## AI assistance

Claude Code (Anthropic) was used extensively for implementation, test authoring, and
documentation drafting, under human direction.

**How the division of work has actually run, recorded honestly rather than flatteringly:**

| Contribution type | Who | Examples |
| --- | --- | --- |
| Product definition and scope | Human | The payment-auditor wedge; the decision to build the acquisition platform before the auditor; the refusal to start the synthetic generator early |
| Engineering standards | Human | The engineering constitution, including the priority order, verification discipline, and the rule that "not verified" must never be reported as "implemented" |
| Sequencing and roadmap | Human | Slice ordering; requiring deployment-path verification; requiring the SSRF guard before any fetching exists |
| Security requirements | Human | Requiring the type-level SSRF gate; requiring DNS-rebinding/TOCTOU to be addressed explicitly; the mandatory address corpus; DNS-label-aware host matching; separating global network policy from source policy |
| Design decisions within a directed constraint | Shared | Given "make the gate type-level", the `ValidatedTarget`-only-producer design was AI-proposed and human-reviewed |
| Implementation | AI, human-reviewed | Module code, tests, documentation prose |
| Empirical findings | AI | That `is_global` is True for multicast/NAT64/IPv4-mapped; that `203.0.113.0/24` is classified private; the editable-install packaging defect; the native/container PostgreSQL timezone difference |
| Corrections to AI output | Human | Redirecting scope, rejecting premature work, requiring stricter acceptance criteria |

**No AI system is listed as an inventor or author of record.** Where an AI tool proposed an
approach, the record notes that a human selected, directed, or modified it.

For any future disclosure, the "AI assistance used" and "Contributors" sections must state
specifically which technical decisions originated with which person, rather than describing the
work in aggregate.

## External contributors

None to date.

Before accepting a strategically significant contribution from a contractor or external
contributor, ensure the agreement addresses IP ownership and assignment. Payment alone does not
necessarily resolve ownership.

## Third-party code

No code has been copied from Stack Overflow, blogs, papers, vendor SDK samples, or other
repositories. Dependencies are declared in `pyproject.toml`, pinned in `uv.lock`, and inventoried
by the SBOM generated per container build.
