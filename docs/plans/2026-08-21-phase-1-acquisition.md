# Phase 1 acquisition — executed

Date: 2026-08-21
Scope: the six highest-ROI India-specific sources from
[the corpus acquisition strategy](../research/CORPUS_ACQUISITION_STRATEGY.md), reviewed, acquired,
ingested and run through the pipeline.

## Outcome in one paragraph

**All six sources are approved and sampled. None was blocked; none was left unclear.** Nineteen
artifacts were acquired, eighteen of them by single manual GET and one as an API response body, and
all nineteen are in immutable storage with provenance recording the exact URL, HTTP status, byte
count and retrieval time. The corpus went from 6 real documents and 9.1 MB to **25 real documents and
244 MB**, and — unplanned — gained its first executed contract, its first bill of quantities inside a
contract, its first interim payment record and its first structured reference index series. Running
the pipeline unchanged surfaced **seven issues, two of them BLOCKER**, and produced **six false facts
that had to be retracted**. The most important single finding is that the extractor-versioning
mechanism cannot retract a fact, only correct one.

---

## The discovery that changed Phase 1

The acquisition strategy named the executed contract agreement as the root of five rule families and
assumed it could arrive only by RTI request or from a customer. **It was public the whole time.**

NHAI's own single-page app calls two unauthenticated endpoints that no earlier review had found:

```text
POST /nhai/api/agr-memo-of-underst    712 records, grouped by category
POST /nhai/api/project-agreements     351 records, one project agreement PDF each
```

Between them NHAI publishes its three **model** concession agreements, **171 executed** concession
agreements, a four-part contract agreement whose Part 1 is titled "Condition of contract and Bill of
Quantities", and a record of **monthly IPC payments** for one package. Four of those were acquired.

Two dead ends are recorded so nobody repeats them. NHAI's `policycirculars` endpoint — 9,105 records
— is **not a policy library**: 758 records sampled across four pages spanning 2013 to 2026 are almost
entirely right-of-way permissions to lay cables and pipelines across highways, and *none* matched
standard bid document, price adjustment, mobilisation advance, retention or measurement. And
`morth.gov.in` answers every path, including nonexistent ones, with its SPA shell, so no path there
can be found by probing.

**A CAPTCHA was found and left alone.** `POST /nhai/api/policycirculars` with a `title` parameter
returns `{"_resultflag":0,"message":"please enter captcha"}`. The unfiltered listing is not gated and
was used; search is a technical access control and was not touched.

---

## Phase 1A — source review

Reviewed under authority delegated by the project owner on 2026-08-20. Reviewer recorded as
`Claude (Opus 5)` in each source entry, because an approval must say who actually made it.

| # | Source | Authority | Jurisdiction | Class | Format | Robots (verified today) | Terms | Verdict |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | WPI series | Office of the Economic Adviser, DPIIT, Min. of Commerce & Industry | India (Union) | Reference | XLSX + PDF | **HTTP 200 carrying the site's ASP error page** — no policy | **Not readable** — `disclaimer.asp` returns the site's ERROR page | **Approved** |
| 2 | CAG audit reports | Comptroller and Auditor General of India | India (Union) | Audit | PDF | 404 after redirect to `/en/robots.txt` — no policy | **Read in full.** Explicit reuse grant | **Approved** |
| 3 | NHAI standard bid / contract documents | National Highways Authority of India | India (Union) | Mixed | PDF | 404 — no policy | Not readable — SPA client-side routes only | **Approved** |
| 4 | Model Concession Agreements | NHAI | India (Union) | Reference | PDF | as above | as above | **Approved** |
| 5 | Rajasthan PWFAR I & III | Finance Dept, Govt of Rajasthan | Rajasthan | Reference | PDF | 404 — no policy | Not retrieved | **Approved** |
| 6 | CPI series | National Statistical Office, MoSPI | India (Union) | Reference | JSON (API) | HTML shell at `/robots.txt` on both `mospi.gov.in` and `api.mospi.gov.in` — no readable policy | Not readable — SPA | **Approved** |

Recorded in three new registry entries — [`india_reference_indices`](../../config/sources/india_reference_indices.yaml),
[`india_audit_reports`](../../config/sources/india_audit_reports.yaml),
[`nhai_published_agreements`](../../config/sources/nhai_published_agreements.yaml) — plus two additions
to the existing `india_official_publications`. Each carries authority, jurisdiction, source class,
format, acquisition method, review date, reviewer, personal-data risk, and the commercial /
redistribution / training-use position.

### Three review findings worth stating plainly

**A robots.txt returning HTTP 200 is not a robots policy.** `eaindustry.nic.in/robots.txt` answers
200 — with the site's own ASP error page as the body. A sweep that recorded status codes would have
logged "200, policy present" and been wrong. The body has to be read.

**CAG is the only one of the six whose terms and copyright policy could actually be retrieved**, and
they are the strongest legal position in the set. Quoted verbatim from
`https://cag.gov.in/en/page-copyright`:

> "Material featured on CAG website may be reproduced free of charge. However, the material has to be
> reproduced accurately and not to be used in a derogatory manner or in a misleading context.
> Wherever the material is being published or issued to others, the source must be prominently
> acknowledged. However, the permission to reproduce this material shall not extend to any material
> which is identified as being copyright of a third party."

Its terms page adds only a liability disclaimer and a governing-law clause — no payment obligation,
no account requirement, no restriction on downloading or automated access. **Redistribution is
explicitly permitted with attribution.** Commercial use is not restricted but is not named;
model-training use is not addressed and is therefore not established.

**Four of six sources publish terms that no HTTP client can read**, because they are single-page apps
serving client-side routes. Approval for those rests on the access pattern — a public authority
publishing its own documents at stable public URLs — and that limitation is written into each source
entry rather than glossed over.

**One access control was found and respected.** `www.mospi.gov.in/api/*` returns HTTP 403 to a
non-browser client. It was not circumvented. The separate public data API on `api.mospi.gov.in`
answers without credentials and was used as published.

---

## Phase 1B — the sample

Nineteen artifacts. Every one carries the source URL, HTTP status, transferred byte count,
content type, SHA-256 and retrieval timestamp in its upload note.

| Source | Artifacts | Bytes |
| --- | --- | --- |
| WPI | monthly index (base 2022-23, Jul-26), yearly index, Aug-2026 press release, WPI/PPI Manual | 4,266,690 |
| CPI | one `getCpiIndex` response, 2,000 records | 395,733 |
| CAG | Indo-Nepal Border Road PA ch. 3 and ch. 4, Polavaram Irrigation PA, Bangalore Metro Rail PA, Karnataka Compliance ch. II pt. I | 23,007,321 |
| NHAI contract documents | Contract Agreement Part 1/4 (conditions + BOQ), ABP-III monthly IPC payment details, ABP-III project brief | 196,729,592 |
| Model Concession Agreements | ≥₹100 cr, ≤₹100 cr, annuity-based (Panagarh–Palsit) | 806,902 |
| Executed concession agreement | Tada–Nellore, NH-5, Vols O–X | 2,914,328 |
| Rajasthan PWFAR | Volume I, Volume III | 6,255,036 |

**The WPI workbook is the highest-quality single artifact acquired.** 1,138 rows × 44 columns, months
Apr-23 to Jul-26, a `Level` column running from `ALL` down to `Item`, commodity codes and weights —
and it carries exactly the series Indian road contracts price-adjust against: **Bitumen (1202010007),
High Speed Diesel (1202010005)**, cement and steel.

**A catalogue's stated file size cannot be trusted.** NHAI's API reported Part-1-4_0_0.pdf as
"376 KB". It transferred **196,544,059 bytes — 187 MB, a factor of 500 out**, and sits inside the
configured 256 MiB download ceiling by a much smaller margin than anyone would have guessed. Any
size-based decision must use bytes actually transferred.

---

## Phase 1C — the pipeline, run unchanged, and what it found

Every document was run through `analyse` with no code changed first. Seven issues.

### BLOCKER 1 — six false facts, from two document classes the vocabulary could not name

Three CAG reports each emitted a document-scoped `estimated_cost` scraped from narrative about a
project the *auditor* had examined, and one also emitted a `document_date` it merely cites:

| Document | False fact | Read from |
| --- | --- | --- |
| Polavaram Irrigation PA | `estimated_cost = ₹132,620,000,000` | "213 R&R colonies were contemplated at an estimated cost of ₹13,262 crore" |
| Bangalore Metro Rail PA | `estimated_cost = ₹1,400,000,000` | "metro station and multi-level parking facility at Challaghatta at an estimated cost of ₹140 crore" |
| Karnataka Compliance ch. II | `estimated_cost = ₹40,000,000` | "design ecosystem at an estimated cost of ₹ 4.00 crore" |
| Polavaram Irrigation PA | `document_date = 27.07.1989` | a date the report cites |
| MCA annuity-based | `document_date = 17/7/2000` | a date printed inside a specimen form, page 75 |
| MCA ≤₹100 cr | `document_date = 6/11/2001` | same, page 115 |

The guard added in August for reference documents worked perfectly on the Rajasthan PWFAR volumes,
which correctly suppressed both fields. It missed these six because **it keys on document type**, and
the audit reports were typed `unknown` (no audit type existed) while the model agreements were typed
`contract` (which is what they look like).

**The lesson is not "add more types." It is that reference-versus-project is a property of a
document's role, not of its shape.** The two contract-shaped cases prove it: NHAI's Model Concession
Agreement and its executed Tada–Nellore concession agreement are the same clauses in the same order,
and one is normative while the other is self-describing. Nothing in the text distinguishes them.

**Fixed, minimally.** Two document types added — `MODEL_AGREEMENT` and `AUDIT_REPORT` — both placed in
the reference set, both **declared by the operator at ingest and never inferred**. That is two enum
members stored as `VARCHAR` (no migration), two `frozenset` entries, and two category mappings. The
tender-notice extractor version went to `3`. Re-run: **all six facts suppressed, with a message that
names which case applies.**

### BLOCKER 2 — extractor versioning can correct a fact, but it cannot retract one

This is the most important finding of the milestone and it is **not fixed**.

Supersession works by writing a corrected row at a higher extractor version, because selection takes
the newest version per document and fact type. A *retraction* writes nothing at all. So after the
version-3 re-run:

```sql
select d.original_filename, f.fact_type, f.extractor_version, f.literal
from extracted_facts f join documents d on d.id = f.document_id
where f.sheet_row is null and d.document_type in ('audit_report','model_agreement');
--  Polavaram …  estimated_cost  2  ₹13,262 crore
--  … five more
```

All six false rows are still **the newest and only rows** for their document and fact type. Nothing
records that version 3 deliberately declined to emit them.

**What is safe today.** No finding cites any of them — the re-run rewrote all 32 findings on those
documents, dropped every evidence link, and every outcome is `INCONCLUSIVE`. The traceability audit
passes. No rule reads historical facts from the database.

**What is not safe.** `GET /v1/documents/{id}/facts` selects every fact row for a document with no
version filter, so it will serve `estimated_cost = ₹13,262 crore` as a fact of a CAG audit report.
Filtering to the newest version would not help — the false rows *are* the newest.

**Deliberately not fixed here.** Representing a retraction is a design decision — a tombstone row, a
`retracted_at` column, a selection view — and guessing at it against a six-row sample is how you
choose the wrong one. It is recorded with the reproduction above and is the first thing to decide
before any persona view or search index reads facts from the database.

### BLOCKER 3 (scoped to three documents) — the best evidence acquired is image-only

| Document | Pages | Text layer |
| --- | --- | --- |
| Contract Agreement Part 1/4 — conditions of contract **and bill of quantities** | 361 (260 read) | **none** |
| ABP-III monthly IPC payment details | 2 | **none** |
| ABP-III project brief | 2 | **none** |

The 187 MB is explained: 361 scanned pages. **The single most valuable document in the acquisition —
a contract containing its own BOQ — is unreadable, and so is the only interim payment record in the
corpus.** This is the first time OCR has been demanded by a document that a rule actually needs
rather than by a hypothetical.

**Not built.** Phase 1F says so explicitly, and it is the right call: OCR is a subsystem, and the
decision of whether to add one belongs to the project owner. Recorded as the blocker for the payment
and contract-BOQ lifecycle stages.

### NEXT 4 — CPI could not be ingested at all

`.json` was not in the ingest extension map, so an approved source with a verified public API could
not enter the corpus. Storage is format-blind — bytes and a digest — and `FileFormat.JSON` was already
in the accepted-format allowlist; only the CLI's extension map stood in the way.

**Fixed** by adding `.json` (and its media type). No JSON reader was added, and none is needed yet:
the artifact is held as reference evidence with its request URL as provenance.

**This settles an open question empirically.** WPI is **XLSX** and CPI is **JSON**. The acquisition
strategy flagged "no CSV reader" as a structural gap; the first two approved structured sources
**require no CSV at all**, and their shapes are opposites — WPI a wide matrix with one column per
month, CPI tall and normalised with one object per state × sector × group × month.

### NEXT 5 — a JSON artifact was handed to the PDF reader

`analyse` dispatched on "XLSX, or else PDF", so the stored CPI response produced:

```text
ERROR  PDF could not be opened: PdfStreamError: Stream has ended unexpectedly
```

which sends an operator hunting for a corrupt download that does not exist. **Fixed:** formats with
no reader are now refused by name — `SKIPPED  no reader for json`. Acquiring an artifact and being
able to read it are separate capabilities and the error message now says which one is missing.

### NEXT 6 — a spreadsheet was told it needed OCR

The WPI workbook reported `0 pages, 0 read  (NO TEXT LAYER - needs OCR)`. A spreadsheet has rows, not
pages, and OCR cannot help a workbook whose rows simply did not match the reader. **Fixed:** the
spreadsheet path now prints `0 rows accepted`.

The refusal underneath it was **correct and should not change** — "no header row recognised: none of
the rows carried an item-number column alongside a quantity or rate column". A WPI index is not a
bill of quantities, and the reader declining to parse it is the right behaviour, not a defect.

### NEXT 7 — a corrupt text layer is indistinguishable from a clean one

The executed Tada–Nellore concession agreement reports `126 pages, 126 read`, and its text is partly
garbage: `pypdf` raises `incorrect startxref pointer`, `invalid distance too far back` and returns
fragments like `amenti/9 or abosh9`, with proposal-request text interleaved into concession-agreement
definitions. `extract_text` catches per-page failures and records an empty page — a deliberate and
correct trade, and the reason the pipeline read 99 pages of a model agreement where raw `pypdf`
crashed outright.

But it means a document can be substantially unreadable while the operator is told every page was
read. **Recorded, not fixed** — a garbage-detection heuristic invented against one example is exactly
the speculative work this milestone was told not to do.

### And what went right

Worth stating, because it is the system behaving correctly under out-of-domain input: **across 30
documents and 252 findings, not one PASS or FAIL was invented.** Every rule facing evidence it could
not use returned `INCONCLUSIVE` with `expected = NOT SOURCED`. The Rajasthan PWFAR volumes suppressed
their quoted values unprompted. The traceability audit walks every finding to an immutable artifact
and reports every break as an inconclusive finding that asserts nothing to trace.

---

## Phase 1D — dataset-specific outcomes

**WPI / CPI.** Format determined by measurement, not assumption: XLSX and JSON, no CSV. Both held as
reference evidence with authority, base year, date and provenance. **No price-adjustment calculation
was implemented**, because no document in the corpus states a contract price-adjustment formula — the
instruction was explicit and it is also correct: the formula is the missing half.

A hazard recorded rather than discovered later: WPI now publishes base 2022-23 alongside 2011-12 with
official linking factors, and CPI carries bases 2010, 2012 and 2024. **A price adjustment that mixes
bases is wrong by a large factor.** The base year is part of the fact.

**CAG.** Eight real audit patterns catalogued in
[docs/research/CAG_AUDIT_PATTERNS.md](../research/CAG_AUDIT_PATTERNS.md), each with the rule invoked,
the documents the auditor examined, the arithmetic and the money consequence, and an honest verdict on
whether Aedifex can express it today.

The headline result: **the Karnataka excess-payment finding reproduces to the rupee.** Three
quantities and two rates, exact `Decimal`, `quantity × (rate_paid − rate_admissible)` summed to
**₹16,101,368.99** against the report's stated ₹1,61,01,369 — a figure computed independently by a
state Accountant General. The report's own table prints the total as `1,61,01,36.99`, a mangled
`…368.99`, which is a real instance of a stated total being wrong while remaining reconstructible from
its line items.

**Zero of the eight patterns are executable today. Six are blocked by nothing but a missing document,
and five of those six would be unblocked by the same two documents: one running account bill and the
agreement it was paid against.** One genuinely new architectural requirement appeared — a formula over
named indices, for the price-adjustment pattern — and it stays unbuilt until a real contract states
one.

**NHAI standard bid documents and Model Concession Agreements.** Acquired. The clause families the
milestone asked to look for — performance security, mobilisation advance, retention, liquidated
damages, defect liability, variation limits, measurement, price adjustment, insurance, completion,
payment certification, disputes — are present in the model agreements as text. **No provision was
extracted from any of them**, because extracting one means asserting it applies somewhere, and the
invariant holds: *reference document + explicit applicability → project rule*. The applicability half
does not exist for these documents. The `_AUTHORITIES` table in the policy extractor still recognises
NHAI alone, deliberately.

**Rajasthan PWFAR I and III.** The reference-provision boundary **held**. Both volumes suppressed
their document-scoped facts without any change, which is the result the milestone was testing for.
Categorical applicability, procedures and formulas appear in these documents and are recorded in the
[second-source study](../research/REFERENCE_PROVISION_SECOND_SOURCE.md); none was implemented,
because no executable rule is blocked by them today.

---

## Phase 1E — corpus metrics

**Evidence classes, never merged.**

| Class | Documents | Bytes | PDF | XLSX | JSON |
| --- | --- | --- | --- | --- | --- |
| **PRIMARY PROJECT** | 8 | 203,182,651 | 8 | — | — |
| **REFERENCE** | 12 | 17,723,246 | 9 | 2 | 1 |
| **AUDIT / SECONDARY** | 5 | 23,007,321 | 5 | — | — |
| **SYNTHETIC** | 5 | 26,040 | — | 5 | — |
| **Total** | **30** | **243,939,258** | 22 | 7 | 1 |

Real (non-synthetic): **25 documents, 243,913,218 bytes**. Before this milestone: 6 documents, 9.1 MB.

| Metric | Value |
| --- | --- |
| Audit reports | 5 |
| Structured datasets | 3 (2 XLSX, 1 JSON) |
| Facts, all extractor versions | 521 |
| Facts, document-scoped | 31 |
| Facts, row-scoped (bill / MB / RA-bill lines) | 490 |
| Derived facts | 16 |
| Policy provisions | 3 (NHAI clause 4.14.1 bands a, b, c) |
| Findings | 252 — 198 inconclusive, 50 pass, 4 review, **0 fail** |
| Finding evidence links | 251 |
| Traceable findings | every conclusive finding; all breaks are inconclusive findings citing nothing |
| **False positives discovered** | **6** (3 `estimated_cost`, 3 `document_date`) — all now suppressed, all six rows still selectable via the API |
| **False negatives discovered** | **1** — the bill of quantities inside Contract Agreement Part 1/4, missed because the PDF is image-only |
| Authorities represented | **5** — NHAI · CAG of India · Office of the Economic Adviser (DPIIT) · National Statistical Office (MoSPI) · Finance Dept, Rajasthan |
| Issuing jurisdictions | **2** — India (Union), Rajasthan |
| Subject jurisdictions (audit reports) | Andhra Pradesh, Karnataka, Bihar, Uttar Pradesh, Union |
| Sources approved | **6 of 6** (3 new registry entries, 1 extended) |
| Sources blocked | 0 |
| Sources unclear | 0 |

**Lifecycle coverage.** ● real evidence · ◐ reference or audit only · ○ nothing.

| Stage | Before | After | What changed |
| --- | --- | --- | --- |
| Planning | ○ | ◐ | CAG reports quote DPR sanctions and revised estimates |
| Tender | ● | ● | unchanged — 4 NHAI tender documents |
| Award | ○ | **●** | **executed concession agreement (Tada–Nellore, NH-5)** |
| Construction | ○ | ◐ | CAG performance audits describe execution |
| Measurement | ○ | ◐ | CAG quotes measurement books; no MB held |
| Billing | ○ | ◐ | contract BOQ acquired but **image-only** |
| Payment | ○ | ◐ | IPC payment record acquired but **image-only** |
| Variation | ○ | ◐ | CAG documents variation-order failures; no variation order held |
| Quality | ○ | ○ | unchanged |
| Completion | ○ | ◐ | CAG quotes completion dates and delays |
| **Audit** | ○ | **●** | **5 CAG reports — the one stage now fully covered** |
| Operations | ○ | ◐ | concession agreements cover the O&M period |

Two stages moved to real evidence: **Award** and **Audit**. Billing and Payment reached documents that
exist in the corpus but cannot be read — the honest mark is ◐, not ●, and OCR is what separates them.

---

## Phase 1F — stop condition

**Met.** All six sources approved and sampled; none blocked, none unclear. Work stops here.

Gates, run separately and unpiped: `ruff` clean · `black` clean · `mypy --strict` clean (83 files) ·
**2,049 tests passed** · traceability audit passes.

### What was changed, and why each change was licensed by a real document

| Change | Licensed by |
| --- | --- |
| `DocumentType.MODEL_AGREEMENT`, `DocumentType.AUDIT_REPORT`, both in the reference set | 6 false facts from 5 real documents |
| Tender-notice extractor version 2 → 3 | the same 6 facts needed superseding |
| `.json` in the ingest extension map, plus its media type | CPI, an approved source, could not otherwise be acquired |
| `analyse` refuses unreadable formats by name | a JSON artifact producing a nonsense PDF error |
| Spreadsheet analysis prints rows, not pages-and-OCR | the WPI workbook was told to try OCR |
| `ingest_file` honours a restated document type, and records the change on the upload note | 5 documents were otherwise uncorrectable through the supported path |
| 3 new source registry entries, 1 extended | Phase 1A |

No schema migration. No new rule. No new fact type. No applicability model. No formula
representation. No procedure representation. No OCR. No CSV reader. No API ingestion framework.

### One process note against myself

Eight documents were reclassified before `ingest_file` learned to write the change to the upload
note, so those eight notes were **backfilled by hand**, and each says so in its own text. The
contemporaneous record is the `ingest.reclassified` log event; the durable record is the note. Stated
here because a provenance entry written after the fact should announce that it was.

### Recommended next decisions, in order

1. **Decide how a retraction is represented.** BLOCKER 2 is the only issue that can currently put a
   value the document never stated in front of a user, through the facts API. Everything that reads
   facts from the database is downstream of this decision.
2. **Decide on OCR.** Three acquired documents, including the two most valuable, are image-only, and
   the Billing and Payment lifecycle stages cannot advance without it.
3. **Acquire one running account bill and its agreement.** Five of the eight catalogued audit
   patterns unblock on that single pair — a better return than any other acquisition available.

### Parallel human-dependent track — unchanged, still open

- **RTI request** for `NHAI/RO-CHD/2026-2027/BWN/21`: executed contract agreement, Measurement Book,
  IPC / RA Bill, Variation Order, Letter of Acceptance, completion record. Note that this milestone
  makes the *contract agreement* part of that request less urgent — NHAI publishes 171 of them — and
  the **Measurement Book and RA Bill** correspondingly more urgent, since nothing public supplies them.
- **Sanitised industry sample**: contract, BOQ, MB, IPC/RA bill, variation.
- **Verification of the 14 unreachable domains from an Indian network**, still the highest-leverage
  non-engineering action from the acquisition strategy.
- **The live crawler remains blocked** pending an approved project contact address. Nothing in this
  milestone used it; all nineteen artifacts arrived as manual downloads.
