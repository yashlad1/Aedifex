# 13. Build the acquisition boundary, borrow the vocabulary

Date: 2026-08-19

## Status

Accepted.

## Context

Before adding more source adapters, the question was put directly: is Aedifex maintaining custom
crawler infrastructure that an established open-source system already solves better? Four candidates
were named — [Kingfisher Collect](https://github.com/open-contracting/kingfisher-collect),
[Kingfisher Process](https://github.com/open-contracting/kingfisher-process), Scrapy, and the
[Open Contracting Data Standard](https://standard.open-contracting.org/) — with an instruction not to
reject anything merely because custom code already exists, and not to weaken verified security
controls in order to adopt anything.

Aedifex is not a crawler product. It is meant to become an evidence-grounded construction
verification platform; the crawler is one ingestion mechanism.

## What the evaluation found

**Kingfisher Collect collects OCDS, not documents.** Every spider guarantees its output is "either a
release package or record package" — structured JSON from publishers who have adopted OCDS. It does
not fetch tender PDFs. Our entire corpus is PDFs from a portal that publishes no OCDS.

**India is covered, but not the portals we need.** Two spiders exist —
`india_assam_civic_data_lab` and `india_himachal_pradesh_civic_data_lab` — both bulk downloads from
CivicDataLab GitHub repositories rather than live portals, and the Himachal dataset was last
published in 2020. CPPP, eprocure, GeM and NHAI have no spiders.

**Kingfisher Process is an OCDS store.** Collections plus collection notes in PostgreSQL, validation
via the OCDS Data Review Tool library, and transforms that produce *new* collections rather than
mutating originals.

**Scrapy can express our TLS invariant.** This corrected an earlier assumption of ours. Twisted
documents `wrapClientTLS(optionsForClientTLS(hostname), HostnameEndpoint(...))` and states that "the
host you are connecting to and the host whose identity you are verifying can differ" — which is
precisely the connect-to-validated-IP, verify-original-hostname split
[`guard.py`](../../src/aedifex/acquisition/fetch/guard.py) enforces. Scrapy also exposes a resolver
hook, and its `RedirectMiddleware` re-issues each hop through the downloader, so per-hop
re-validation would come for free.

## Decision

| Component | Verdict |
|---|---|
| Kingfisher Collect as our crawl engine | **REJECT** |
| Kingfisher's Assam + Himachal OCDS datasets | **ADOPT the data, not the code** |
| Kingfisher Collect's spider taxonomy | **BORROW** |
| Kingfisher Process | **BORROW** |
| Scrapy as fetch/downloader engine | **REJECT** |
| Scrapy's spider-emits-URLs architecture | **BORROW** (already how we are built) |
| OCDS | **ADOPT as vocabulary** |
| Third-party India portal scrapers | **BORROW reconnaissance only** |

Scrapy is rejected **not** on capability. It is rejected because of where enforcement would live.
Our control is *type-level*: `ValidatedTarget` can only be produced by the guard, the transport
accepts nothing else, and so a plain `str` cannot reach a socket. The Scrapy equivalent is a custom
resolver plus a downloader middleware — two interception points that must stay in sync forever. A
control you can forget to apply is weaker than one you cannot bypass, even when both are correct the
day they ship. Secondarily, neither bundled resolver covers both address families safely
(`CachingThreadedResolver` is IPv4-only; `CachingHostnameResolver` ignores `DNS_TIMEOUT`), and
Twisted's reactor cuts against [ADR 0005](0005-synchronous-sqlalchemy.md).

Kingfisher Collect is rejected for a simpler reason: it solves a problem we do not have. A tool that
collects OCDS JSON contributes nothing to acquiring PDFs from a portal that publishes none.

## Consequences

No new dependency is added. Three things are borrowed as design input rather than code: the spider
taxonomy as a vocabulary of discovery shapes (with *incremental* and *sampling* as concepts we lack),
Kingfisher Process's discipline of versioned collections that are transformed rather than mutated —
which independently validates the append-only `extracted_facts` design — and OCDS field names, so
procurement concepts are not reinvented.

Two new candidate sources are identified: the Assam and Himachal OCDS bulk files, fetchable through
our own acquisition boundary with no Scrapy and no Kingfisher.

**Revisit if** source count passes roughly twenty portals and discovery rather than fetching becomes
the bottleneck; at that point Scrapy for *discovery only*, behind the existing acquisition boundary,
deserves another look. One implementation detail was deliberately left uninvestigated: whether a
custom Twisted resolver is invoked for URLs carrying a bare IP literal. It would refine the wording
of the enforcement-point argument, not the verdict.
