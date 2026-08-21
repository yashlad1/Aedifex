# Does the Reference Provision model generalise? A second authority, tested

Date: 2026-08-20

## Verdict

**Partially, and the boundary is sharp.**

| Layer | Result |
| --- | --- |
| Acquisition, provenance, immutable storage | **Unchanged.** Worked first time |
| The self-vs-normative distinction | **Unchanged, and it earned its keep** — suppressed two would-be false facts on a document it had never seen |
| Provision *value* shape (share, cap) | **Fits** several of the second document's provisions |
| Provision *applicability* shape | **Does not fit.** Rajasthan's conditions are categorical, not numeric bands |
| Provisions with no value — procedures, definitions | **Structurally impossible.** Proven by an `INSERT` the database refused |
| Extraction | **Did not generalise at all.** Zero of ~17 provisions read, by construction |

**Zero false positives. One real defect found, and it was dangerous.** `1/2%` — which the second
document really writes — parsed as **2%**, a fourfold overstatement of a money threshold, silently.
That is the only code change this milestone justified.

---

## 1. The document

**Rajasthan Public Works Financial & Accounts Rules, Part II.** 301 pages, 4,063,231 bytes,
SHA-256 `cc7260832099459f816c947f2ee751897a5f626b0fa96dc07f6d12f0b4df08d8`, full text layer, 784,825
characters.

Manually downloaded on 2026-08-20 from
`https://finance.rajasthan.gov.in/docs/rules/pwfar/vol-II.pdf` (HTTP 200, `application/pdf`) —
the **Finance Department, Government of Rajasthan**, which is the issuing authority rather than a
mirror. Ingested under `india_official_publications` as an upload, with the URL, byte count and
download date recorded in the provenance note. Document id `c286b7de-970b-5e7d-ba78-283d4878c3d6`.

**Why not the preferred candidates.** Tried in the order given:

| Candidate | Outcome |
| --- | --- |
| 1. CPWD Works Manual | `cpwd.gov.in` unreachable from this environment — HTTP 000 with and without `www`, repeatedly |
| 2. MoRTH Specifications | `morth.nic.in` redirects to `morth.gov.in` and serves its Angular shell for **every** path, including `.pdf` URLs and `/robots.txt`. A document request returns 40,262 bytes of HTML with `content_type: text/html`. Not fetchable by any HTTP client |
| 3. IS 1200 | BIS standards are sold, not published. The freely available copies are on `law.resource.org` and `archive.org` — **mirrors, not the issuing authority**, and excluded by the source entry's own rule |
| 4. State Schedule of Rates | `pwd.rajasthan.gov.in` has a **real `robots.txt` disallowing `/Documents/`, `/uploads/` and `/rootUpload/`** — where its rate schedules live. Honoured; excluded from automated acquisition. `uppwd.gov.in` and `keralapwd.gov.in` unreachable |
| 5. WPI/CPI notifications | `eaindustry.nic.in` reachable and untried — held for a later milestone |

So the document used is a state public-works **rulebook** rather than a rate schedule. It satisfies
what the milestone actually tests: a different issuing authority (state Finance Department vs central
Authority) and a different jurisdiction (`IN-RJ` vs `IN`).

## 2. Why it is reference knowledge

It states no facts about itself and nothing about any particular project. It governs *other people's*
contracts: how measurements are recorded, how running bills are prepared, what earnest money and
security deposit are due, how advances are recovered, how deductions are made. `measurement book`
appears 18 times, `running account` 14, `security deposit` 132, `earnest money` 111.

It is the Rajasthan counterpart of the CPWD Works Manual — the authoritative definition of what an
RA bill contains and what may lawfully be deducted from it, for one state.

## 3. What kinds of provision it contains

Every `@ N%` occurrence in the document, by rate and stated base:

| Count | Rate | Base as written |
| --- | --- | --- |
| 3 | @5% | **no base stated in the sentence** |
| 2 | @10% | of the gross amount of the running bill |
| 2 | @20% | **no base stated** |
| 1 | @2% | of estimated cost of consultancy work |
| 1 | @5% | of cost of consultancy work |
| 1 | @1/2% | of estimated cost of work put to tender |
| 1 | @10% | of the work order |
| 1 | @0.5% | of amount of such a bill |
| 1 | @10% | of SD amount after lapse of one year of completion |
| 1 | @50% | of the Outlay approved by the Ministry of Surface Transport |
| 1 | @9%, @50%, @2% | **no base stated** |

Against the eight representation questions the milestone asks:

| Kind | Present? | Can the model hold it? |
| --- | --- | --- |
| **Thresholds** | Yes, many | **Yes** — share plus optional cap, exactly as NHAI |
| **Effective dates** | Yes, as amendment markers (`1[...]`, `2[i]`) referencing later orders | Field exists; **nothing populates it**, and the markers are unparsed |
| **Jurisdictions** | Yes — Rajasthan | **Yes.** `jurisdiction` is `String(8)`, so `IN-RJ` fits |
| **Applicability conditions** | Yes, and **categorical**: "enlisted" appears **63 times**, "within their zone" | **No.** See §5 |
| **Lookup tables** | Not in this volume | Untested |
| **Formulas** | `formula` appears 12 times | **No.** A share-and-cap cannot hold a multi-variable expression |
| **Measurement procedures** | Yes | **No.** See §5 |
| **Definitions** | Yes | **No.** Same reason as procedures |

## 4. What handled it unchanged

Everything except extraction, and one component deserves singling out.

**Acquisition, hashing, immutable storage, upload provenance.** No change. Content-addressed storage
placed it at its digest, and the note carries the source URL and download date.

**Bounded text extraction.** 301 of 301 pages, full text layer, no truncation.

**The self-metadata guard — the notable result.** This is `FR-129`, written a day earlier against the
NHAI manual, meeting a document from a different authority for the first time. It **suppressed two
facts that would otherwise have been false**:

```text
not extracted: estimated_cost: suppressed — this is a reference document and states no tender
               identifier, so a quoted value is a norm about other projects rather than a fact
               about itself
not extracted: document_date: suppressed — [same reason]
```

The document contains the phrase "estimated cost" and plenty of dates; both would have been captured
as document-scoped facts by the pre-guard reader, exactly as happened with the NHAI manual. The guard
generalised because it tests a *positive* property — does this document name the procurement it
concerns — rather than enumerating policy phrasings. **That design choice is the one thing this
milestone validated outright.**

**Every rule.** Three rules ran and all three returned `INCONCLUSIVE` with an accurate reason. No
spurious verdict, no fabricated threshold.

**The traceability audit.** Clean, exit 0.

**Net: zero facts, zero false positives, zero wrong findings.**

## 5. What did not generalise

### 5a. Extraction is authority-specific by construction — the false negatives

**Zero of roughly seventeen percentage provisions were read.** Two independent reasons, both by
design rather than by accident:

**The authority table recognises only NHAI.** `_AUTHORITIES` in `extraction/policy.py` maps document
text to an authority, and it contains one entry. A document that names no recognised authority yields
no provisions at all — deliberately, because a threshold binding nobody in particular would end up
binding everybody. Rajasthan is not in the table, so extraction stopped before it began.

**The clause pattern is one document's phrasing.** `_RATES_CLAUSE` requires
`<number> ... bid security ... at the following rates:`. Rajasthan writes
`Earnest Money @ 2% of estimated cost of consultancy work`. The words *bid security* and *retention*
appear **zero times** in 301 pages; the same concepts are *earnest money* and *security deposit*.

`extraction/policy.py`'s own docstring predicted this — *"when a second real reference document
arrives it is expected to need its own reader"* — and the prediction held. **This is an extractor
limitation, not a bug**, and §7 explains why no second reader was written.

### 5b. Applicability cannot express a categorical condition — the model limitation

The provision model's applicability is `applies_to` plus a numeric range:

```text
applies_from   applies_to   applies_to_max
```

That fits NHAI clause 4.14.1, whose condition is *a band of estimated cost*. It cannot fit
Rajasthan, whose conditions are about **who the contractor is**:

> Enlisted Contractors will be required to pay Earnest Money @ 1/2% of estimated cost of work put to
> tender … for outside their zone, 2% Earnest Money shall be required

`enlisted` appears **63 times**. Two different rates apply to the same estimated cost depending on
enlistment and zone — a categorical predicate with no numeric ordering. There is no column for it and
no honest way to encode it in the three that exist.

**This is a genuine limitation of the model, demonstrated by a real document.**

### 5c. A provision with no value cannot be stored at all

Proven rather than argued. Attempting to store a measurement procedure — a provision that imposes a
method, not an amount:

```text
ERROR:  new row for relation "policy_provisions" violates check constraint
        "ck_policy_provisions_imposes_something"
```

The constraint requires `share IS NOT NULL OR cap_amount IS NOT NULL`. It was written on the
reasoning that *"a provision that imposes nothing cannot be applied to anything"*, which was true of
the only provisions then in view. It is false in general: a measurement procedure, a definition, and
a formula all impose something real and none of them is a share or a cap.

**So the model as built represents *quantified* norms only.** That is a narrower claim than
"reference provisions", and the name currently overstates what the table can hold.

### 5d. The bases have no fact types

Even a perfectly extracted Rajasthan provision would apply to nothing. Its bases include
*cost of consultancy work*, *gross amount of the running bill*, *the work order*, *SD amount after
lapse of one year* — seven distinct bases, none of which is a fact type Aedifex extracts. And
applicability matches a provision's authority against the *acquisition source* of the document being
judged; the corpus contains no Rajasthan-sourced project document, so nothing could match.

## 6. Every defect found by executing the pipeline

| # | Defect | Class | Fixed? |
| --- | --- | --- | --- |
| **D1** | **`1/2%` parsed as `2%`** — the regex matched the `2%` inside the fraction, returning **four times the true rate**, silently, for a notation the second document really uses | **Extractor bug**, money-critical | **Yes** |
| D2 | Zero of ~17 provisions extracted: authority table has one entry | Extractor limitation, by design | No — §7 |
| D3 | Zero of ~17 provisions extracted: clause pattern is NHAI phrasing | Extractor limitation, by design | No — §7 |
| D4 | Categorical applicability conditions cannot be represented | **Evidence-model problem** | No — §8 |
| D5 | Valueless provisions (procedure, definition, formula) rejected by check constraint | **Evidence-model problem** | No — §8 |
| D6 | Provision bases have no corresponding fact types | **Applicability problem** | No — §8 |
| D7 | `effective_from` is never populated; the document's amendment markers (`1[...]`) are unparsed | Extractor gap | No |
| D8 | No `DocumentType` for a rulebook — both reference documents are filed as `technical_specification` | Evidence-model gap, minor | No |
| D9 | The source document contains a typo — *"gross amount of the running **but**"* — which any exact-phrase reader will miss | Not our defect; worth knowing | n/a |

**False positives: none.** Every wrong-value risk in this document was either suppressed by the guard
or never reached, and D1 was latent rather than triggered, because extraction stopped at the authority
check before any rate was parsed.

## 7. Architecture changes justified by real evidence

**One, and it is a bug fix rather than a design change.**

`_percent_as_fraction` now handles vulgar fractions and refuses to match a rate out of the middle of
another number. The pattern gained a `(?<![\d/])` guard and a `numerator/denominator` alternative.
All three notations the two documents use between them are now covered and tested: words
(`two percent`, `one and one-half percent`), decimals (`0.5%`), and fractions (`1/2%`, `3/4 percent`).

Why this one and nothing else: **it produces a wrong number.** A threshold read four times too high
would fail a compliant bid or pass a deficient one, and the notation is real. Every other defect
above produces either nothing or an honest `INCONCLUSIVE`.

## 8. Changes explicitly rejected as speculative

**A second-authority clause reader.** It would have put Rajasthan provisions in the table and made
the milestone look more successful. It was rejected because the rows would be **inert**: their bases
have no fact types (D6), the corpus has no Rajasthan-sourced project document to apply them to, and
the model cannot represent the categorical conditions most of them carry (D4). Building it would have
produced data that could never reach a rule, while making the real limitation harder to see.

**Adding Rajasthan to the authority table.** One line, and it changes nothing observable without the
reader above. Data for a capability that does not exist.

**A categorical applicability column.** D4 is a real limitation, and fixing it now means guessing the
shape from one document. Is a condition a set of tags, a predicate, a join to a contractor registry?
Rajasthan's "enlisted within their zone" suggests two dimensions; a third document would probably
suggest a fourth. **This is exactly the point at which ADR 0014's discipline applies to its own
implementation**: wait for the case that needs it.

**Relaxing `ck_policy_provisions_imposes_something` to admit procedures and definitions.** D5 is
real, but a provision that holds no value needs somewhere to put what it *does* hold — a method, a
definition, a formula — and inventing three representations at once from one document's prose is the
redesign the architecture rule forbids. The constraint stays, and the model's honest scope is
recorded instead.

**A formula representation.** `formula` occurs 12 times and none was read. A price-adjustment formula
is the obvious motivating case and it is not in this document; the WPI/CPI notifications (candidate 5)
would be the evidence for it.

**A `rulebook` document type.** D8 is cosmetic. `technical_specification` is imprecise for a
financial rulebook and has caused no wrong result.

## 9. What the next design decision has to answer

Stated so the choice is between named options rather than open.

1. **Is the table's scope "quantified norms" or "reference provisions"?** If the former, rename it and
   keep the constraint. If the latter, procedures and definitions need a representation, and that is a
   design decision, not a migration.
2. **How is a categorical condition represented?** Needed before any state PWD rulebook becomes
   useful, because enlistment and zone conditions are pervasive there.
3. **Does each authority get its own reader?** Two documents, two phrasings, zero overlap in
   vocabulary — *bid security* and *retention* against *earnest money* and *security deposit*. A reader
   per authority is honest and scales linearly in effort; a general clause grammar is one attempt to
   predict phrasings nobody has seen. The evidence so far favours the former.
4. **Which candidate source next?** WPI/CPI notifications are reachable and would test formulas and
   effective dates — the two capabilities with fields but no evidence. CPWD would test whether a
   central rulebook shares Rajasthan's vocabulary or NHAI's.
