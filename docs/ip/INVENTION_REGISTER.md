# Invention register

Every potentially novel technical idea gets an `AED-IP-NNN` id. An entry here is a record, not a
claim: "potential invention" and "patent review required" only.

**Status: no entries yet — deliberately.**

Nothing built so far is a specific enough technical method to be worth a disclosure. The
foundation (typed configuration, content-addressed storage, a source registry, an SSRF guard) is
sound engineering assembled from well-known techniques. Writing disclosures for it would dilute
the register and waste review attention.

The register begins when one of the watch-list areas below becomes an implemented, specific
mechanism.

## Entries

| ID | Title | First documented | Contributors | Disclosed publicly | Patent review status |
| --- | --- | --- | --- | --- | --- |
| — | — | — | — | — | — |

## Watch list

Areas where a distinctive method may emerge. **These are not inventions and must not be treated as
such** — each is a problem area. A disclosure is created only when a specific implemented
technical mechanism exists.

| Area | Why it might become specific enough | Current state |
| --- | --- | --- |
| Cross-document construction evidence reconciliation | The central problem: deciding sufficiency across PO/invoice/challan/GRN/certificate rather than reading one document | Not built |
| Evidence graph architecture for project assurance | How relationships are inferred and traversed to answer a payment question | Not built |
| Hybrid deterministic + semantic verification | How a rule engine and a language model divide work so arithmetic stays deterministic while terminology mapping does not | Not built |
| Provenance-preserving audit findings | How page/bbox/method/confidence survives every transformation so a finding is reproducible | Partially: content-addressed identity and immutable raw storage exist |
| Material certificate → specification reconciliation | Unit- and grade-aware comparison against a specification | Not built |
| Evidence-sufficiency calculation | How "enough evidence to approve" is computed and explained | Not built |
| Missing-evidence-driven retrieval | Using an absence to decide what to look for next | Not built |
| Safe processing of adversarial construction documents | Isolation and resource-bounding for hostile documents | Partially: content validation and the SSRF guard exist |

## The distinction that matters

Not worth pursuing:

> "Use AI to audit construction documents."

Potentially worth review, once implemented:

> How documents are represented; how relationships are inferred; how conflicting claims are
> reconciled; how provenance survives each transformation; how deterministic and semantic checks
> interact; how audit rules execute and are versioned; how evidence sufficiency is calculated; how
> missing evidence triggers further retrieval; how adversarial documents are isolated.

Specific technical mechanisms, not the idea of applying AI to a domain.
