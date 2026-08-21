# Indian building, real-estate and general civil construction documents: where they actually are

Date: 2026-08-21

Companion to [CORPUS_ROADMAP.md](CORPUS_ROADMAP.md), which surveyed construction evidence in
general, and to [INDIAN_POSTAWARD_SOURCES.md](INDIAN_POSTAWARD_SOURCES.md), which found almost
nothing usable after award in the highway sector. This document asks the same question of
**buildings**, because the product is meant to work across real estate, buildings, roads, metro,
utilities and industrial civil works — and every primary document in the corpus until now described
a road.

Unlike those two, this one ends in acquisition. Fourteen documents were ingested; the source review
is in [`config/sources/india_building_works.yaml`](../../config/sources/india_building_works.yaml).

## The question, stated as the workflow rather than the authority

Searching by authority finds portals. Searching by workflow finds documents. The horizontal chain
is the thing that has to be populated:

```text
Project → Contract → Work Item → Measurement → Claim → Certification → Payment → Variation → Quality
```

Reference documents (schedules of rates, codes, price indices, methods of measurement) govern that
flow without belonging to it.

## Classification

| | Class | Meaning |
| --- | --- | --- |
| **A** | real primary public | the authority's own document, published, complete |
| **B** | real secondary / quoted | real figures quoted inside another document — audit reports, judgments |
| **C** | sanitised | real document with identities or values removed |
| **D** | training / format | authoritative blank forms and worked teaching examples; no project values |
| **E** | synthetic only | generated |
| **F** | private / RTI | exists, not public; obtainable only by request or engagement |

## The availability matrix

| Workflow link | Class | Where | Status |
| --- | --- | --- | --- |
| **Project** | **A** | IIT Bombay tender sets; eProcurement portals | **acquired** |
| **Contract** (conditions) | **A** | IIT Bombay `gcc.pdf`; Puducherry PWD GCC 2023 | **acquired** |
| **Work Item** (priced BOQ) | **A** | IIT Bombay, priced PDF *and* structured `.xlsx` | **acquired, 5 documents** |
| **Work Item** (unpriced BOQ) | **A** | the same sets, bidder return | **acquired** |
| Award / bid opening | **A** | IIT Bombay `fbo.pdf` — qualified firms, opening date | **acquired** |
| **Measurement** | **A** | **Odisha PPMS** `msrmt_doc/*.pdf` | **identified, unreachable** |
| **Measurement** (format) | **D** | CPWA Book of Forms; WB Form 2900 | **acquired** |
| **Claim / RA bill** | **A** | **Odisha PPMS** `merge_bill_msrmt/*.pdf` | **identified, unreachable** |
| **Claim / RA bill** (format) | **D** | CPWA Book of Forms | **acquired** |
| **Claim / RA bill** (quoted) | **B** | CAG reports; Delhi HC / arbitration judgments | reachable, not acquired |
| **Certification** | B / F | audit reports; otherwise private | not acquired |
| **Payment** | **A** | eGramSwaraj public vouchers; MGNREGA MIS | reachable, tabular not documentary |
| **Variation** | B / F | audit reports; otherwise private | not acquired |
| **Quality** | F | private | none |
| *Reference:* schedule of rates | **A** | CPWD DSR; state BSR/SoR | **not acquired — see below** |
| *Reference:* method of measurement | **A** | IS 1200 (archive.org) | not acquired |
| *Reference:* audit checks | **A** | CAG Works Audit Manual | **acquired** |

### The single most valuable unreached target

**Odisha PPMS — `ppms.odisha.gov.in/upload/merge_bill_msrmt/` and `/upload/msrmt_doc/`.**

A Government of Odisha works portal publishing **filled Running Account Bill forms merged with
their measurement sheets**, at unauthenticated public URLs, for real works ("Construction of CC road
from Siva house to Sisir house"). This is the missing half of the workflow — Measurement → Claim,
same work, real values — and it is the only class-A instance of it found anywhere.

**It cannot be reached from outside India.** The host resolves to `117.250.67.28` and refuses TCP on
both 443 and 80 from a US network; there is no Wayback snapshot of any URL on the domain. Every
`*.odisha.gov.in` host tested is blocked the same way, as are `uppwd.gov.in`, `mahapwd.com`,
`mes.gov.in` and `icf.indianrailways.gov.in`. This is now the **highest-value item on the
human-dependent track** — it needs one person on an Indian connection, not more research.

Reachable from here, and verified: `wbpwd.gov.in`, `cpwd.gov.in`, `cag.gov.in`, `egramswaraj.gov.in`,
`nrega.nic.in`, `eprocure.gov.in`, `etenders.gov.in`, `pwd.kerala.gov.in`, `pwd.rajasthan.gov.in`,
`pwd.py.gov.in`, `indiankanoon.org`, `iitb.ac.in`.

### What is *not* worth pursuing, and why

- **BOQ/RA-bill "templates" from construction blogs and SEO sites.** Class D at best, usually E.
  The first search pass returned almost nothing else; they are not evidence and they are not even
  representative, because they are authored to look tidy.
- **Scribd copies of real documents.** Sometimes genuinely class A in content, but the uploader is
  not the authority, so provenance cannot be recorded honestly. Not approvable.
- **MGNREGA / eGramSwaraj as a document source.** Both publish real measurement and payment data at
  national scale, and both publish it as **MIS reports, not documents**. Valuable later for the
  payment link; a poor fit for a pipeline whose unit is an artifact with a page and a digest. Also
  overwhelmingly rural earthwork rather than buildings.

## What was acquired

Fourteen documents, source `iitb_building_works` (twelve) and `india_audit_reports` (two).

**One real project end-to-end as far as it is published** — IIT Bombay Hostel No. 19, a G+9
hostel for 1,052 students, estimate ₹85,39,81,318.41 excluding GST, NIT
`IITB/Dean (IPS)/CACI/H-19/NIT/R1` dated 31.10.2022:

| Document | Link in the chain |
| --- | --- |
| `nit.pdf`, 194 pp | Project |
| `gcc.pdf`, 115 pp | Contract terms (**typed `model_agreement`** — see below) |
| `d1.pdf` | Financial bid, percentage-on-estimate |
| priced BOQ, 75 pp | Work Items with rate and amount |
| `Spe1.pdf` | Specification |
| `fbo.pdf` | Five prequalified firms, bid opening 30-01-2023 |
| `amen.pdf` | CPWD specification amendment (reference) |

Plus four more priced building BOQs (Victor Menezes Convention Centre interior renovation, a
₹67.85 crore civil+MEP package, a P.C. Saxena refurbishment, a CoE unpriced return), the IIT Bombay
Works Manual 2014, the **CPWA Book of Forms** and the **CAG Works Audit Manual**.

### Why this beats the NHAI corpus for building the product

| | NHAI Package V-A (2001) | IIT Bombay (2014–2025) |
| --- | --- | --- |
| Priced BOQ | rotated scan, **handwritten** rates | **text layer**, machine-typed |
| Rows readable | 1 money value of 10, 0 rows of 6 | every row, exactly |
| Structured form | none | **`.xlsx`, cell-level provenance** |
| Documents per project | 5 of 8, across two sources | 7, one directory |
| OCR needed | yes, and it fails | **no** |

The layout survey's closing caveat was that every conclusion came from a 2001 contract with
handwritten rates, and that a modern building bill might dissolve the problem. On this evidence it
does — for the pre-award half.

## Blockers the real documents exposed

Classified as the acquisition discipline requires. Two were repaired because they are correctness
defects; the rest are recorded.

### BLOCKER, repaired — OCR crashed the process

`h19/fbo.pdf`, a 600 DPI scan at 4964 × 7020, **segfaulted** RapidOCR. Not an exception: SIGSEGV,
which no `except` catches and which the page, character and wall-clock budgets cannot bound because
the process dies mid-page.

It is not a size limit. The same page resized to 4959 × 7012 — 0.2% smaller, same dtype, both
C-contiguous, 104 MB either way — read fine, and 22.3, 25.2 and 28.2 MP all passed. The trigger is
the exact dimensions, somewhere in native code. Fixed with `OCR_MAX_PIXELS = 12_000_000`, above
300 DPI A4 and a **no-op for the entire existing corpus** (every stored page is ≤ 3.8 MP), verified
so that no transcription already relied upon changes. Text is identical at every scale from 2.2 to
28 MP. This reduces an unpredictable native crash to a bounded input; it does not make the engine
crash-proof, and process isolation is the escalation if one recurs.

### BLOCKER, repaired — reclassification left false facts live

Ingested as `contract`, the *general* conditions of contract produced
`estimated_cost = Rs. 5 crores` from the clause "shall not be applicable for works with estimated
cost put to tender being less than Rs. 5 crores", and a `document_date` of 31-12-1979 from another.

The classification was mine and the remedy is `model_agreement` — a template stating norms, which is
exactly what a GCC is. But retyping it **did not retract the false facts**: `persist_retractions`
withdrew only *older* extractor versions, and these carried the same version as the run withdrawing
them. Document type is an *input* to extraction, so the same version reading a retyped document is a
corrected reading of corrected input, not a self-contradiction. The version clause is gone; both
facts are now retracted and both rows remain readable.

### BLOCKER, repaired — a wrong estimate that read as a right one

`estimated_cost` for Hostel 19 was ₹73.86 crore, the **civil component** of a two-part estimate
whose stated total is ₹85.39 crore. The derived bid-security share came out at **1.4996%**, which
looks like a 1.5% policy rule, and it was already cited in two findings. `nit_number` truncated to
`IITB/Dean` at the space before `(IPS)`.

Extractor v4 prefers a stated `Total` over the first component **only when the components sum to
it** — arithmetic, not label-guessing — and refuses a total qualified by GST. The identifier pattern
now allows a parenthesised segment.

### BLOCKER, open — the priced BOQ reader does not read building BOQs

**This is the most important finding in this document and it is not fixed.** A 75-page priced BOQ
with `Sr.No | Description | Unit | Qty | Rate | Amount` on every page yields **zero rows**, and
`bill_items_reconcile_to_stated_total` reports "no priced bill of quantities, so there is nothing to
add up."

Three independent causes, each verified:

1. **The heading anchor cannot fire.** `_BOQ_HEADING` requires "Bill of Quantities (BOQ)" or
   "Priced Bill of Quantit". The document contains the string `"Bill of Quantities"` **zero times**.
2. **The unit vocabulary does not cover it.** `_UNIT` knows `Cum|Sqm|Sqmt|Rmt|…`; these documents
   write `m3`, `m2`, `CUMT`, `SQMT`, `Sqm.`, `sqm`, `each`.
3. **The arithmetic guard would reject the rows even so.** `quantity × rate == amount` exactly is
   what makes positional parsing safe on the NHAI bill. In these documents the **displayed rate is
   rounded to 2 dp while the amount is computed from more precision**:

   | Qty | Rate shown | Amount stated | Qty × Rate |
   | --- | --- | --- | --- |
   | 115 | 8,556.65 | 984,014.26 | 984,014.75 |
   | 1300 | 8,835.65 | 11,486,344.53 | 11,486,345.00 |
   | 1125 | 5,528.09 | 6,219,105.75 | 6,219,101.25 |
   | 215 | 654.00 | 1,40,610.00 | 1,40,610.00 ✓ |

   Some rows are exact; most are off by cents to a few rupees. **A tolerance is a money-semantics
   decision and is deliberately not being taken unilaterally.** The options are a relative epsilon,
   reconstructing the unrounded rate from `amount / quantity`, or treating a near-miss as `REVIEW`
   rather than a rejected row.

This is the spine of the horizontal model — Work Item is what Measurement, Claim and Certification
all attach to — and it is the one link where abundant class-A building evidence now exists and
cannot be read.

### NEXT

- **Legacy `.xls`** (BIFF) BOQs: `openpyxl` refuses them, `xlrd` 2.x reads only these. Not a blocker
  — the same content is published as text-layer PDF.
- **Document-type vocabulary** has no "code / manual / conditions of contract" type. The CPWA Book of
  Forms and the CAG Works Audit Manual are typed `technical_specification` because that is the
  reference bucket whose *behaviour* is right; the note on each records what it actually is.
- **CPWD DSR** — the Delhi Schedule of Rates, the rate authority every government building BOQ item
  cites. Acquiring it plus a DSR-referencing BOQ would give an applied-rate-versus-scheduled-rate
  check with **both sides sourced**. `cpwd.gov.in` is reachable but the direct
  `/Publication/manualvolume2.pdf` fetch was reset by the server; the source is registered and
  `unverified`, so it needs a terms review first.

### DEFERRED

Cross-document project reconciliation for this project; `#N/A` and float-noise cells as facts
(`231.00000000000003`, `109.81487999999996` observed in a published BOQ); IS 1200; class-B judgment
mining.

## Separately: the corpus had lost its raw artifacts

Found while checking that the NHAI extractions had not regressed, and unrelated to buildings.

**31 of 45 documents had no raw artifact in object storage.** Only the 14 ingested today were
present; every pre-existing artifact — NHAI tenders, the Package V-A agreement, the IPC payment
register, WPI and CPI reference data, CAG reports, the synthetic project — was gone from the bucket
while the database rows still claimed them. `scripts/audit_traceability.py` failed with 297 findings
unable to reach an artifact and **10** confirmed. Most likely the damage predates `d611eca`, which
stopped the test suite from being able to delete the corpus but did not restore what was already
lost.

All 45 were restored, and content addressing is what made it safe: a candidate file was uploaded
only when its SHA-256 equalled the digest the database recorded, which is proof the bytes are the
original rather than a substitute. 26 came from the acquisition working directories; the 5 synthetic
files regenerate **byte-identically**, so the generator is deterministic and they restore exactly.

One correction to record: the first pass used a plain `put_object` and set neither `ChecksumSHA256`
nor the `sha256` user-metadata that `RawObjectStore.head` reads, so the audit still called them
missing though the bytes were right. Repaired by rewriting the same verified bytes with the metadata
the store records, digest checked before and after.

The audit now passes: **307 raw artifacts confirmed**, every remaining break an `INCONCLUSIVE`
finding that asserts no value to trace.

## Recommendation

**The first non-highway corpus is `iitb_building_works`, and it is already ingested.** It is the only
class-A building source found that publishes complete per-project sets, needs no OCR, and offers the
Work Item table in a structured format with cell-level provenance.

The next unit of work is **not** more acquisition. It is making the priced BOQ readable for these
documents, which needs one decision from the owner — the rounding tolerance above — and then a
narrow extension of `pdf_boq.py`. Everything downstream in the horizontal model attaches to Work
Item, and the evidence to build it is now in the corpus.

Two things stay on the human-dependent track: **Odisha PPMS**, which needs an Indian connection and
would supply the Measurement and Claim links that no reachable source publishes; and the RTI request
for `NHAI/RO-CHD/2026-2027/BWN/21`, now clearly the second priority of the two.
