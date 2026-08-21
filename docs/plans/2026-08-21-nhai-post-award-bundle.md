# The first real post-award bundle from public Indian primary records

Date: 2026-08-21
Scope: exploit the NHAI public-endpoint discovery fully, before broadening to buildings.

## The primary question, answered

> Can we find one NHAI project for which the public records collectively contain tender, priced BOQ,
> executed contract agreement, LOA/award information, IPC/payment record, measurement, variation and
> completion information?

**No single project has all eight, and no single project has both a contract and a payment record.
The best available is five of eight, and the two halves of a complete bundle sit in two different
projects.**

| Objective | Package V-A (`N/02005/21005/BR`) | ABP-III (`N/02005/06004/UP`) |
| --- | --- | --- |
| 1. Tender / NIT | ✗ | ✗ |
| 2. Priced BOQ | **✓** pages ~150–200 of Part 1/4 | ✗ |
| 3. Executed contract agreement | **✓** Parts 1/4 and 2/4 | ✗ |
| 4. LOA / award information | **✓** LOA 31.07.2001, contract price stated in the document | ✓ register only |
| 5. IPC / payment record | ✗ | **✓** 37 interim payment certificates |
| 6. Measurement | ✗ | ✗ |
| 7. Variation | ◐ awarded ₹284.87 cr vs final ₹858.62 cr | ◐ ₹505.27 cr vs ₹742.95 cr |
| 8. Completion / progress | **✓** scheduled 30.10.2007, final 07.01.2010 | ✓ + a project brief |
| **Total** | **5 of 8** | 4 of 8 |

**Selected: Package V-A on NH-2 in Bihar, Contract No. TNHP/7, UPC `N/02005/21005/BR`** — because it
holds the two documents everything else depends on, an executed contract and the priced bill of
quantities inside it.

The wider picture is worse than these two rows suggest, and it is the finding that matters most:
**of 254 projects whose executed agreement joins deterministically to the project register, every
single one tops out at four of eight objectives** — agreement, award, completion, partial variation.
Not one has a BOQ, an IPC, a measurement or a tender. See §4.

---

## 1. The endpoint map

Full detail in [docs/research/NHAI_PUBLIC_DATA_ENDPOINTS.md](../research/NHAI_PUBLIC_DATA_ENDPOINTS.md).
Fourteen API endpoints and five static JSON assets probed; every one answered without
authentication or a session.

The headline is not an endpoint but a file. **Five plain-`GET` static JSON assets carry NHAI's whole
project register — 1,762 rows, 1,450 distinct projects** — with awarded cost, LOA date, agreement
date, appointed date, scheduled and final completion dates, mode, and the administrative chain down
to the PIU. No parameters, no pagination, no authentication.

Two endpoints publish primary evidence: `project-agreements` (351 executed agreement PDFs) and
`agr-memo-of-underst` (712 rows including 171 executed concession agreements, 3 model agreements, and
the six-entry legacy list where the contract-with-BOQ and the IPC register live).

**A CAPTCHA was found and left alone.** `policycirculars` accepts a `title` search and answers
`{"_resultflag":0,"message":"please enter captcha"}` without the front end's verification parameters.
The unfiltered listing is ungated and was used; search is a technical access control and is out of
scope permanently.

**Three dead ends, recorded so they are not re-probed.** `project-information` times out server-side
after ~61 s even at `totalrecord=2`. `status-of-arbitral-award-payment` and `rest_api` return HTTP
500 — server errors, not access controls. And `policycirculars`, despite the name, is a
right-of-way permission register: 758 records sampled across 2013–2026, **zero** matching standard bid
document, price adjustment, mobilisation advance, retention or measurement.

---

## 2. Join keys — what joins by identifier, and what does not

**The agreement PDF filenames are the UPC with the slashes removed.**

```text
register upc   N/02004/27002/AP
PDF            .../project_agreement/N0200427002AP_0.pdf
```

**274 of 352 agreement files join this way.** It is NHAI's own convention, not an inferred pattern —
one agreement title reads *"[Revived of earlier terminated N0200427001AP]"*.

Three more exact joins, all used:

- **Contract number.** The Package V-A agreement states *"Contract No. : TNHP/7"* on its signature
  page; the register's project name reads *"Aurangabad - Barachatti (**TNHP/7**; Package - V A)"*.
  This is what tied a 361-page scan to a project record.
- **Package name.** *"Monthly ipc payment details of package **ABP-iii**"* against
  *"...(Construction Package **ABP-III**)"* in the register.
- **LOA date, as an independent confirmation.** The register gives `loa_date = 31/07/2001`. The
  performance bank guarantee bound into the contract recites *"dated 31.07.2001"*. Two sources, one
  date — this is what made the UPC join believable rather than merely plausible.

**Tenders do not join.** `tenderlist` carries `tender_no` and no UPC, and holds only 183 *current*
tenders rather than an archive, so a 2001 award has no tender record to join to at all. Linking them
would need PIU plus chainage plus NH matching, which is inference and not a join. **Left undone** —
the instruction was to avoid fuzzy matching where exact identifiers exist, and here no exact
identifier exists at all.

---

## 3. What the selected project's documents actually contain

Read by OCR, since all of it is scanned. Page numbers are the PDF's.

**Page 2 — the Agreement.** Between NHAI and *Oriental Structural Engineers Ltd. – Gammon India Ltd.
Joint Venture*, made **27 September 2001**, for *"Four Laning and Strengthening of the Existing Two
Lane Highway Section From Km. 180.00 to Km. 240.00 on NH-2 in Bihar (India) (Construction Package
V-A), Contract No. : TNHP/7"*, at a contract price of **Rs. 2,279,024,320.00 and US $ 12,226,525.32**
calculated at **1 US $ = Rs. 46.60**. Clause 2 lists the contract documents, including *"(g) the
Priced Bill of Quantities"*.

**A deterministic cross-source check, available right now:**

```text
agreement INR portion            2,279,024,320.00
agreement USD portion   12,226,525.32 × 46.60 =   569,756,079.91
agreement contract price         2,848,780,399.91   = 284.8780 crore
register awarded_cost            2,848,700,000.00   = 284.87   crore
difference                              80,399.91   = 0.00282%
```

The contract price in the executed agreement reconciles with the awarded cost NHAI publishes in its
project register, once the dual-currency amount is converted at the rate the agreement itself states.
The residue is the register **truncating** to two decimals of a crore rather than rounding — 284.8780
would round to 284.88. Worth knowing before anyone builds a rule on `awarded_cost`.

**Pages 150–200 — the Bill of Quantities.** *"BILL NO. 6 - ROAD JUNCTION BILL OF QUANTITIES"*,
*"BILL NO. 0 - MISCELLANEOUS"*, with `Unit`, `Rate (INR)`, `Amount`, and amounts in both figures and
words. Rotated on the page, which is why OCR reads fragments of it mirrored.

**Pages 298–305 — the price-adjustment clause, and this is the most consequential page in the
corpus.** Seven components — Labour, Cement, Steel, Bitumen, POL/Fuel, Plant & Machinery, Other
Materials — each of the form:

```text
V_L = 0.85 × P_l/100 × R_l × (L_i − L_o)/L_o        (labour)
V_c = 0.85 × P_c/100 × R_l × (C_i − C_o)/C_o        (cement)
```

where, verbatim from the document:

- `L_o` = *"the average consumer price index for industrial workers for **Gaya** centre on the day 28
  days prior to the closing date of submission of bids as published by **Labour Bureau, Ministry of
  Labour**, Government of India"*
- `L_i` = the same for **Gaya/Aurangabad** centre, 28 days prior to the last day of the period *"to
  which a particular interim payment certificate is related"*
- `C_o`, `C_i` = *"the all India average **wholesale price index for cement**"*, on the same two dates,
  *"as published by the Ministry of Industrial Development"*

Both index families were checked against the WPI workbook acquired in Phase 1, and the cement half is
there: **Ordinary Portland Cement (OPC), code 1313050003**, alongside the whole *Manufacture of
cement, lime and plaster* sub-group (1313050000), PPC, slag cement and cement clinkers. Every steel
series a road contract could name is there too — *Bars and Rods of Mild steel* (1314010014),
*Hot-Rolled Structural Angles, Shapes, Sections, Beams* (1314010019) — as are Bitumen (1202010007) and
High Speed Diesel (1202010005).

**One ambiguity worth recording before anyone computes with this.** The clause says "wholesale price
index for cement" without saying at which level of the WPI hierarchy. The sub-group `e.Manufacture of
cement, lime and plaster` moved 98.2 → 95.4 over Apr-23 to Jul-26; the item `Ordinary Portland Cement
(OPC)` moved 98.2 → 96.1. Different numbers, same words in the contract. That is a question for
whoever eventually implements the rule, and it is not answerable from the contract alone.

**Page 5 — the performance bank guarantee**, reciting the LOA reference and its date, and naming the
project as part of the *Third National Highway World Bank Project (IBRD Loan No. 4559)*.

**Page 341 — the Form of Bid Security**, referring to *"the amount ... as shown in Clause 17.1 of the
Bidding Data"*.

### Two corrections this reading forced on Phase 1

**The contract agreement is not ABP-III's.** Phase 1 recorded Part 1/4 as belonging to the Allahabad
Bypass package ABP-III, because it sits next to the ABP-III entries in NHAI's flat legacy list. Page 2
of the document says Package V-A, NH-2 Bihar, TNHP/7. **I read adjacency as association and did not
open the document.** The upload note now carries the correction in full, and the
[Phase 1 report](2026-08-21-phase-1-acquisition.md) is corrected. Nothing about the stored bytes
changed; only the claim about which project they describe.

**The wrong CPI was acquired.** Phase 1 acquired MoSPI's Consumer Price Index (Rural/Urban/Combined,
base 2012). This contract needs **CPI for Industrial Workers, by centre, published by the Labour
Bureau** — Gaya, in this case. Those are different series from different authorities, and only one of
them can settle a price-adjustment claim on this contract. The Labour Bureau's CPI-IW releases were
found during Phase 1A and not acquired, because MoSPI was the source the plan named. The plan was
wrong, and the contract is what says so.

---

## 4. The candidate matrix, and why it collapses

254 projects have both an executed agreement PDF and a register record. Scored against the eight
objectives, the top ten are indistinguishable:

| UPC | Mode | Objectives | Agreement size | Stage |
| --- | --- | --- | --- | --- |
| `N0400511001TS` | HAM | 4 / 8 | 143.9 MB | Under Construction (AD issued) |
| `N0402704001AP` | HAM | 4 / 8 | 82.7 MB | Under Construction (AD issued) |
| `N0200607001JK` | BOT Annuity | 4 / 8 | 82.3 MB | CC Issued & O&M |
| `N0801802001UP` | BOT Annuity | 4 / 8 | 78.0 MB | CC Issued & O&M |
| `N0400805001AP` | BOT Toll | 4 / 8 | 70.7 MB | PCC Issued, CC Pending |
| `N0403102001KA` | HAM | 4 / 8 | 65.4 MB | Under Construction (AD issued) |
| `N0200603001JK` | BOT Annuity | 4 / 8 | 62.7 MB | PCC Issued, CC Pending |
| `N0806501001UK` | HAM | 4 / 8 | 60.0 MB | PCC Issued, CC Pending |
| `N0800602001AP` | HAM | 4 / 8 | 57.8 MB | PCC Issued, CC Pending |
| `N0300403001RJ` | BOT Toll | 4 / 8 | 56.6 MB | PCC Issued, CC Pending |

Across all 254: agreement 254, award 191, completion 122, variation 189. **BOQ 0, IPC 0, measurement
0, tender 0.**

**The reason is structural, not incidental.** `project-agreements` publishes concession agreements
only — HAM 276, BOT Toll 53, BOT Annuity 21 — and a concession has no priced bill of quantities and no
running account bill by construction: the concessionaire builds at its own cost and is paid annuity or
toll. Item-rate and EPC contracts are the ones with BOQs, measurement books and RA bills, and **not
one of the 46 Item Rate projects in the register has a published agreement.** Four EPC projects do,
and all four are at *"Balance for Award"* with no dates and no cost.

So the two documents that break past four of eight are both in `agr-memo-of-underst` →
`Project Name`, a legacy list of six entries — and this is the honest summary of the discovery:
**NHAI's post-award primary evidence is not a dataset, it is two files somebody uploaded once.**

---

## 5. OCR — built, bounded, and measured

All four documents in the bundle are image-only: 361 pages, 158 pages, and two of two twice. 523
scanned pages, no text layer anywhere. OCR was the blocker and is now implemented in
[src/aedifex/extraction/ocr.py](../../src/aedifex/extraction/ocr.py).

**The engine: `rapidocr-onnxruntime` 1.2.3, Apache-2.0, pip-installable, no system binary.** Chosen
over Tesseract for an operational reason rather than an accuracy one — Tesseract is equally well
licensed but needs a system package on every machine, container and CI runner, and this milestone was
scoped to reading one project. Declared as an optional extra, `pip install 'aedifex[ocr]'`, so a
deployment that never touches a scan carries no ONNX runtime.

**No rasteriser was needed.** Every scanned page in this corpus carries exactly one full-page image
XObject — `DCTDecode` for the contract, `CCITTFaxDecode` for the IPC register — and pypdf with Pillow
hands both over directly. No poppler, no Ghostscript, and no PyMuPDF, which this project rejected for
being AGPL.

**The seven constraints, each satisfied:**

| Requirement | How |
| --- | --- |
| Identify which documents are image-only | All four named above, by page count and text-layer probe |
| Simplest bounded path | One module, ~250 lines, page images in and page text out |
| Page-level provenance | `PageText.number` is the PDF page; facts carry the page they were read from |
| Never overwrite raw evidence | The artifact is read, never rewritten. `ocrmypdf`, which injects a text layer back into the PDF, was rejected for exactly this — the output would be a different file from the one whose digest is the document's identity |
| OCR output is derived evidence | Every fact records `ocr:<engine>/<version> \| <rule>` in its `method` |
| Record engine and version | From package metadata. The first implementation used `getattr(module, "__version__")`, which does not exist on this package, so every fact recorded `.../unknown` — a version nobody can pin is not a reproducibility record |
| Resource and time limits | 40 pages, 4 M characters and 900 s wall clock by default; **off unless `--ocr` is passed** |

### Two defects found by running it rather than reading it

**Every page of the IPC register failed silently.** OpenCV inside RapidOCR rejects 1-bit input —
*"Unsupported depth of input image ... 'depth' is 9 (CV_Bool)"* — and `CCITTFaxDecode` scans arrive as
1-bit TIFFs. The engine returned the empty string for both pages and the pipeline reported "no text
layer" as if OCR had never run. Fixed by normalising every page image to 8-bit RGB PNG before it
reaches the engine, which is lossless with respect to the text.

**The engine version recorded as `unknown`**, as above.

### What OCR delivers, and what it does not

**On prose it is excellent.** Every figure that matters on the agreement page came out exactly right,
including `2,279,024,320.00`, `12,226,525.32` and the `46.60` exchange rate, and the price-adjustment
clause transcribed cleanly enough to read the formulas off it.

**On a table it recovers the values and loses the record.** The IPC register transcribes column by
column, so the 37 months land in one blob, the 37 rupee amounts in another, and the 37 dollar amounts
in a third. **You cannot say "IPC 1 was ₹87,704,866 in June 2005" from the transcription** without
layout analysis, which is out of scope.

**And on money it is not yet safe.** Several figures picked up a spurious trailing digit from the
vertical cell rule — `87704866` came out as `877048661`, `45949602` as `459496021`. That is a **tenfold
error on a payment amount**. It is visible here because the figures could be checked against the image
by eye; in an automated path it would not be. **No money fact was created from OCR output in this
milestone, and none should be until digits can be verified.** Recorded as the first BLOCKER below.

---

## 6. Fact retraction — resolved

Committed separately. Extractor versioning could correct a fact but not retract one: a retraction
writes nothing, so the false row stayed newest, stayed selected, and stayed served by the facts API.

The smallest model that preserves history: **one append-only table**, `fact_retractions`, holding the
fact id, the extractor and version that withdrew it, a mandatory prose reason, and when. The fact row
is never touched and never deleted, so a finding computed from it remains explainable — which is why
deletion was rejected. A retraction is a new assertion *about* a fact, not a property *of* it, which is
why it is a row rather than a column.

The required semantics, as they now behave:

```text
extractor v2   estimated_cost = ₹13,262 crore
extractor v3   suppressed -> retraction row written, reason recorded
current        no estimated_cost is selectable
historical     the v2 row is still there, still readable, and marked retracted
```

Consumers: the CLI prints what was withdrawn with its old literal and page; the API returns retracted
facts with a `retracted` flag and the reason, rather than hiding them; and the traceability audit now
**fails** on a conclusive finding citing a retracted fact — a verdict whose only support has been
withdrawn is worse than an untraceable one, because it looks explainable.

All six real false facts are retracted through the supported path. Re-running produces none.

---

## 7. Step 5 — the pipeline over the real bundle

Run with the existing extraction and verification, plus `--ocr`.

| Document | Pages | Read | Facts | Method |
| --- | --- | --- | --- | --- |
| PkgVA Contract Agreement Part 1/4 | 361 | 8 (probe) / 361 (full) | `document_date = 31.07.2001` p5 | `ocr:rapidocr-onnxruntime/1.2.3 \| label:dated` |
| PkgVA Contract Agreement Part 2/4 | 158 | 40 | none | — |
| ABP-III monthly IPC payment register | 2 | 2 | `document_date = 04.10.2011` p2 | `ocr:rapidocr-onnxruntime/1.2.3 \| label:dated` |
| ABP-III project brief | 2 | 2 | none — **suppressed in error**, see below | — |

**The first facts ever extracted from a scanned document in this corpus**, and the first is worth
dwelling on: `document_date = 31.07.2001`, OCR'd from the performance bank guarantee's recital of the
Letter of Acceptance, **is exactly the `loa_date` NHAI publishes for this project in its register.**
Two independent sources, one date, arrived at through a 361-page scan and a static JSON file.

Every rule returned `INCONCLUSIVE`. None of the nine registered rules can consume a contract price, a
BOQ item or an IPC amount, because no fact type exists for any of them — which is the right outcome
for an unchanged pipeline and is not a defect.

**A third correction to Phase 1, found here.** The ABP-III project brief was ingested as
`technical_specification`, which is in the reference-document set, so its facts were suppressed as
*"about another project"*. It is a brief report about one specific project — primary project evidence
— and the suppression is wrong. The document type was the error, not the guard.

---

## 8. Issues, classified

### BLOCKER 1 — OCR digits are not safe for money facts

A vertical cell rule reads as a trailing `1`: `87704866` → `877048661`. On a payment amount that is a
factor of ten. Until an OCR-derived numeral can be verified — a second pass, a check digit, a
row-total reconciliation, something — **no money fact may be created from a transcription.** This is
what stops the IPC register becoming 37 payment facts today.

### BLOCKER 2 — a transcribed table has no rows

Column-major reading order means the IPC register's months, rupee amounts and dollar amounts are three
separate lists. The values are present; the *records* are not. Any rule over a payment series needs
row identity, and recovering it is layout analysis, which this milestone explicitly excluded.

### NEXT 3 — the ABP-III project brief is misclassified

Typed `technical_specification`, so its facts are suppressed as reference material. It is primary
project evidence. A one-line reclassification through the supported path.

### NEXT 4 — no fact type for a contract price

`Rs. 2,279,024,320.00 and US $ 12,226,525.32 at 1 US $ = Rs. 46.60` is readable, joins to the
register's `awarded_cost` to within a truncation, and cannot be recorded, because the notice reader
looks for an *"Estimated Cost"* header and a contract states a *contract price*. Three fact types are
missing — contract price, its currency split, and the stated exchange rate — and a dual-currency
contract price is a shape the fact model has never seen.

### NEXT 5 — the register truncates money

`awarded_cost = 284.87` against a true `284.8780` crore. Anything comparing a document's figure to
the register must expect truncation to two decimals of a crore, not rounding. Recorded before it
causes a spurious mismatch.

### DEFERRED 6 — pre-award to post-award linking

No identifier joins a tender to a project. Would need PIU plus chainage plus NH inference. Not worth
doing while the tender archive itself is absent.

### DEFERRED 7 — the 78 unjoined agreement files

Older `concession_files/` uploads named after the road rather than the UPC. Fuzzy matching on road
names, for concession agreements that carry no BOQ anyway.

---

## 9. Which audit rules this makes executable

Against the eight patterns in [CAG_AUDIT_PATTERNS.md](../research/CAG_AUDIT_PATTERNS.md):

| Pattern | Before | Now |
| --- | --- | --- |
| 4 — price adjustment from the wrong index | blocked on evidence **and** formula representation | **evidence half is closed.** A real contract states the formula, names WPI-cement and CPI-IW-by-centre, and the WPI series is in the corpus. Still needs: the applied index from a bill, and a formula representation the provision model does not have |
| 5 — below-BOQ percentage not deducted | needs one RA bill + its agreement | agreement acquired; **still needs the RA bill** |
| 2 — mobilisation advance above ceiling | needs a works code + a payment record | unchanged |
| 1, 3, 6, 7, 8 | evidence-blocked | unchanged |

**Zero become executable.** Every one still needs a running account bill or a measurement book, and
neither exists in NHAI's public data. That answers the milestone's sixth success criterion precisely,
and it is a negative result rather than a disappointment: the corpus now contains the *reference* half
of the price-adjustment rule and the *contract* half of two others, and what remains missing is
exactly one document class.

---

## 10. What is still missing, exactly

1. **A running account bill or IPC with its line items.** One document unblocks five of the eight
   audit patterns. Nothing in NHAI's public data has one — the ABP-III register is a summary of 37
   payments, not a bill.
2. **A measurement book.** Nothing public, anywhere, at any authority reviewed so far.
3. **A variation order.** The register's awarded-versus-final cost gap shows variations happened
   (₹284.87 cr → ₹858.62 cr on Package V-A) without documenting any of them.
4. **CPI-IW by centre, from the Labour Bureau** — Gaya and Aurangabad specifically. Found in Phase 1A,
   not acquired, and now demanded by name by a real contract.
5. **A tender archive**, to link pre-award to post-award by identifier rather than by inference.

## 11. Stop condition

Met, with one criterion failed honestly. One real project has a multi-document post-award bundle
(5 of 8 objectives); the documents are linked deterministically by UPC, contract number, package name
and LOA date; OCR was built only where the project required it and is off by default; false facts can
be retracted without destroying history; the pipeline runs across the bundle; **zero audit rules
became executable, and the missing evidence is named precisely.**

**NHAI expansion stops here.** It is a proving ground and must not define the canonical construction
model — 254 of its 254 joinable projects are concessions, which is the least representative contract
form in construction. The next milestone is deliberately not more NHAI: it is discovery and
acquisition of **building, real-estate and general civil** evidence, where BOQs, RA bills, measurement
sheets and variation orders are the ordinary currency rather than a legacy upload nobody cleaned up.
