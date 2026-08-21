# Data sources

## Current status

Three of nine sources are collectable; six remain **disabled and unverified**, with no crawler
written and no terms reviewed.

| Source | Status | Acquired so far |
| --- | --- | --- |
| `nhai` | Approved, crawler registered | 4 tender documents with retrieval provenance, including a real 37-item priced BOQ |
| `synthetic_projects` | Approved, generated here | 5 spreadsheets: BOQ revisions, a measurement book, an RA bill |
| `india_official_publications` | **Approved 2026-08-20 under delegated review**, manual download only | NHAI Works Manual 2006 (297pp), the first real Indian reference document |
| `cppp_eprocure`, `cpwd`, `gem_marketplace`, `open_contracting_registry`, `ted_europa`, `world_bank_projects` | Unverified — cannot be collected from | — |

`gem_marketplace` is `registration_required` and is therefore permanently out of scope rather than
pending: the hard limits below forbid bypassing authentication regardless of review outcome.

Run `make validate-registry` for the current position rather than trusting this table.

```
$ make validate-registry

SOURCE                       ENABLED  REVIEW       ACCESS                 RATE
----------------------------------------------------------------------------------------
cppp_eprocure                no       unverified   public                 10/min
cpwd                         no       unverified   public                 10/min
gem_marketplace              no       unverified   registration_required  6/min
nhai                         no       unverified   public                 10/min
open_contracting_registry    no       unverified   public                 30/min
synthetic_projects           yes      approved     public                 600/min
ted_europa                   no       unverified   public                 20/min
world_bank_projects          no       unverified   public                 20/min

Collectable now: 1 of 8
```

This is the honest state, and the schema enforces it: a source cannot be enabled while its
`verification_status` is `unverified`.

The multi-year acquisition plan — 60 India-specific sources catalogued, scored and ordered, with
reachability and robots policy verified for 46 of them — is in
[docs/research/CORPUS_ACQUISITION_STRATEGY.md](docs/research/CORPUS_ACQUISITION_STRATEGY.md). Two
hard blockers found there: **`data.gov.in` and `ireps.gov.in` both declare `Disallow: /`**, so both
are manual-download-only permanently, regardless of licence.

## Reviews performed under delegated authority

On 2026-08-20 the project owner delegated terms-of-use, licence, privacy and robots review, and the
authority to classify a source approved / blocked / unclear. One review was carried out under that
delegation and is recorded here so the delegation itself is auditable.

**`india_official_publications` — APPROVED, manual download only.** Reference documents that Indian
public authorities publish at stable public URLs on their own sites: works manuals, public works
financial and accounts rules, standard specifications, schedules of rates, audit reports. No crawler
is registered; acquisition is one manual download at a time, and each upload records the exact source
URL and download date. `reviewed_by` names the delegate rather than the owner, because an approval
must say who actually made it.

**`data.gov.in` — BLOCKED for automated access, and this is the one that matters.** Its `robots.txt`
is real and reads `User-agent: * / Disallow: /`. That is honoured *despite* its datasets carrying the
Government Open Data License – India, which is the more permissive of the two signals. The two are
answering different questions: a licence grants rights over the data, `robots.txt` states how the
site may be accessed. Anything wanted from there is downloaded by a human and ingested as an upload
naming that origin.

**Robots findings, each checked by request rather than assumed:** `nhai.gov.in`, `cag.gov.in` and
`nrega.nic.in` return HTTP 404 for `/robots.txt` — no policy is declared, which is not the same as
permission. `morth.nic.in` answers every path including `/robots.txt` with its single-page-app shell,
so it has no robots policy any client can read.

**Not reachable at all from the development environment:** `cpwd.gov.in`, `uppwd.gov.in` and
`geosadak-pmgsy.nic.in` refused connections or failed DNS, while the same requests to `nhai.gov.in`
and `nrega.nic.in` succeeded. Any determination about the unreachable hosts rests on documentation
rather than inspection, and is marked as such in
[docs/research/INDIAN_POSTAWARD_SOURCES.md](docs/research/INDIAN_POSTAWARD_SOURCES.md).

**One source rejected on provenance rather than terms.** `tnebes.org` hosts a Tamil Nadu schedule of
rates and is a trade union's website, not the issuing department. A rate schedule whose issuing
authority cannot be established is not reference data; it is an assertion.

## The registry is data, not code

Each source is a YAML entry declaring its target, its rate limits, and its legal constraints.
A crawler receives all of that from the registry; it never embeds a URL or a delay.

Collection ethics are encoded as validation rules, so an unsafe source cannot be expressed:

| Rule | Effect |
| --- | --- |
| `enabled` requires `verification_status: approved` | Cannot collect before a human reviews the terms |
| `enabled` requires a registered `crawler` | Cannot enable a source nothing can handle |
| `access: restricted` can never be `enabled` | Collecting would mean bypassing an access control |
| `retrieval: http_crawl` requires `robots_policy: respect` | HTML crawling always honours `robots.txt` |
| Plain-HTTP `base_url` requires `allow_insecure_transport: true` | Tamperable transport is a recorded decision |
| `license` and `allowed_use` are mandatory fields | Provenance is not optional documentation |
| Rate limits bounded above, and checked for self-consistency | No configuration can become a load generator |

`UNVERIFIED` is the default, so a newly added source is presumed off-limits.

## Review process

Before a source may be enabled:

1. **Read the terms of use** and the privacy policy. Record the URL in `terms_url`.
2. **Fetch and read `robots.txt`.** If it disallows the paths we need, the source is
   `blocked` — record why in `notes`.
3. **Establish what is reachable without authentication.** Anything behind a login, CAPTCHA,
   or paywall is permanently out of scope, not pending.
4. **Record the licence** and what it permits in `allowed_use`, in your own words.
5. **Decide whether the source publishes personal data.** Bid documents usually carry names,
   PAN, addresses, and contact details. Set `contains_personal_data: true`.
6. **Set `reviewed_by` and `reviewed_on`.** An approval with no reviewer is not an approval,
   and `tests/unit/test_registry_data.py` enforces this.
7. **Set `verification_status`** to `approved` or `blocked`.
8. **Write and register a crawler.** Only then set `enabled: true`.

Steps 1–7 are a documentation change reviewed like any other. The relevant expertise is legal,
not technical, and this file is where that judgement is recorded.

## Hard limits

Never, regardless of review outcome:

- Bypass CAPTCHAs, paywalls, authentication, or access controls.
- Ignore `robots.txt` for HTML crawling.
- Exceed the configured rate limit, or crawl without an identifying User-Agent that carries a
  contact address. The configuration layer rejects an anonymous User-Agent.
- Collect personal data beyond what is incidentally present in public documents, or train
  models on it without screening.

The full ecosystem survey — every realistic source worldwide, with the document lifecycle it serves —
is in [docs/research/CORPUS_ROADMAP.md](docs/research/CORPUS_ROADMAP.md). This file remains the record
of what has been *reviewed and decided*; that one is the record of what exists.

## Candidate sources

Grouped below by geography for historical reasons. The axis that actually matters is **reference data
versus project data** — shared across many projects, or specific to one — and it cuts across every
group here:

- **Reference data:** tender notices, BOQs, standard specifications, Schedule of Rates, material
  specifications, government circulars, contract clauses, procurement rules. Every source in the
  India and International tables below is this. Public portals are good at it.
- **Project data:** contract agreement, Measurement Book, RA Bill / IPC, variation orders, site
  instructions, inspection reports, payment certificates, test reports, daily logs. Only the
  post-award table reaches this, and only `industry_samples` reaches it reliably.

Public versus private is the wrong distinction to plan around: a customer export and a portal
download enter the same immutable pipeline and differ only in provenance. What differs is whether a
document informs many projects or records one.

### India

| Source | What it offers | Why it is interesting | Concerns |
| --- | --- | --- | --- |
| `cppp_eprocure` | Central procurement portal: tenders, BOQs, specs, awards | Broadest coverage of Indian public works | ZIP attachments need bomb-safe expansion; bidder documents carry personal data |
| `cpwd` | Tenders, schedules of rates, specifications | Schedule of rates and specs are *reference data* to check BOQ line items and material grades against | Site structure is dated |
| `nhai` | Highway tenders, contracts, specs | Material grades (bitumen, aggregate, steel) are specified explicitly, which suits the material rules | Large documents |
| `gem_marketplace` | Marketplace POs, contracts | Purchase-order structure | Mostly behind registration; only anonymously reachable pages could ever be in scope |

### International

| Source | What it offers | Why it is interesting | Concerns |
| --- | --- | --- | --- |
| `open_contracting_registry` | OCDS-format releases | **Structured relationships** between buyer, tender, supplier, award, contract, and documents — real ground truth for entity matching, not just synthetic | Licence varies per publisher, so it likely needs splitting into one entry per publisher |
| `world_bank_projects` | Development-bank project and procurement records | Infrastructure focus, bidding documents | Many languages; poor first target |
| `ted_europa` | EU contract and award notices | Highly structured and consistently schema'd | Least representative of the messy scanned evidence the audit engine must eventually handle |

### India — post-award records

A systematic search of every Indian public authority holding post-award records — state PWD e-MB
systems, PMGSY/OMMAS, CPWD, NHAI, Smart City SPVs, irrigation departments, municipal corporations and
RTI s.4 disclosures — is in
[docs/research/INDIAN_POSTAWARD_SOURCES.md](docs/research/INDIAN_POSTAWARD_SOURCES.md). Its verdict:
**no Indian public authority proactively publishes primary post-award records.** Two routes outrank
everything in the table below — **MGNREGA/NREGASoft**, which publishes transaction-level records
because the RTI Act requires it, and an **RTI application**, which is the only route to a contract
agreement now that the CIC has confirmed NHAI does not publish them.

**None of the sources above publishes a post-award record.** Every one is a tender, a notice, a bid
document, a schedule of rates or an award notice, which is the pre-award half of a contract's life.
A measurement book, an interim payment certificate, a variation order and an inspection record are
where construction money is actually decided, and no Indian procurement portal is known to publish
them.

The candidates below are therefore a different shape: mostly documents that *report on* post-award
records rather than being them. That distinction is load-bearing and is why the table names it.

| Source | What it offers | Why it is interesting | Concerns |
| --- | --- | --- | --- |
| `cag_audit_reports` | CAG performance and compliance audit reports on highways, irrigation and PWD works | The closest public analogue to Aedifex's own output. Quotes real contracted / measured / billed / paid quantities and rates, **and states the audit rule it applied** — which is what priority 4 needs and what synthetic examples cannot supply | **Reports on records; is not the record.** A fact traces to a page of an audit report, not to a measurement book, so a finding must not claim primary measurement authority from it. Figures are extracts inside a narrative rather than tabulated |
| `court_arbitration_awards` | Judgments and published arbitral awards in construction disputes | Quote measurement, billing, variation and payment figures in unusual detail, because they are what the parties fought over | Adversarial framing: figures are *claims* that the document then adjudicates, so a quantity may appear three times with three values. Heavy personal data. Selection bias toward contracts that went wrong |
| `state_pwd_disclosures` | State PWD and urban-local-body proactive disclosures under RTI s.4 — work orders, completion certificates, running-account summaries | Occasionally the primary record itself, which none of the others are | Wildly variable by state; frequently scanned images, so OCR-gated; personal data common |
| `world_bank_projects` (post-award use) | Implementation Completion Reports, audited project financial statements | Mandatory disclosure, infrastructure focus | Aggregate level — project totals rather than line items. Already listed above for its procurement records |
| `industry_samples` | Sanitised real documents provided directly by a contractor, consultant or client | **Highest fidelity available.** The only candidate that is reliably the primary record | Not a crawl — an ingest, via `manual_upload`. Needs a human relationship, a sanitisation step, and a decision about what may be retained. No technical work unblocks it |

None is approved. None has had its terms read, its `robots.txt` fetched, or a reviewer recorded, and
none may be enabled until steps 1–8 above are complete. They are listed so the legal judgement has
something concrete to act on.

### Synthetic

`synthetic_projects` is enabled. It is registered as a source rather than special-cased so
that generated documents traverse exactly the same hashing, deduplication, storage, and
provenance path as collected ones — a bug that only affects one path is a bug found late.

## Adding a source

1. Add an entry to a file in `config/sources/`, or create a new file.
2. Run `make validate-registry`. The loader reports every problem at once, naming the file and
   the source id.
3. Run `make test`. `tests/unit/test_registry_data.py` asserts the invariants above.
4. Leave it `enabled: false` until review and a crawler are both done.
