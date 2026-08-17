# Threat models

A lightweight threat model is written **before** implementing a high-risk feature, not after. The
list of features requiring one is in the engineering constitution: file upload, crawlers,
authentication, multi-tenancy, LLM processing, customer documents, external integrations, and
payment recommendations.

| Document | Covers | Status |
| --- | --- | --- |
| [threat-model-http-fetch.md](threat-model-http-fetch.md) | Outbound HTTP: SSRF, DNS rebinding, redirects, resource exhaustion, politeness, credential leakage | Accepted, pre-implementation |

Each model states assets, trust boundaries, numbered threats with mitigations, explicit non-goals,
a fails-closed check, and the verification obligations that discharge it. A threat model whose
verification obligations are unmet is a plan, not a control.

See also [SECURITY.md](../../SECURITY.md) for the implemented controls and known gaps.
