# NHAI's public data endpoints, and how to join across them

Date: 2026-08-21
Verified by request against `https://nhai.gov.in` on 2026-08-21. Every endpoint below answered
without authentication, without a session, and without a CAPTCHA unless noted.

## Why this document exists

NHAI's website is an Angular single-page app over Drupal. It serves the same HTML shell for every
route, has no `sitemap.xml`, and its `robots.txt` returns HTTP 404 — so HTML link discovery finds
zero documents and a crawler written against the pages would find nothing. Everything the site
displays comes from a JSON API that its own front end calls, and that API is not documented anywhere.

This is the map. It exists because the discovery cost is real — the endpoint names live only inside a
1.4 MB minified JavaScript bundle — and because two of these endpoints turned out to publish primary
post-award construction evidence that the acquisition strategy had assumed would need an RTI request.

**The boundary respected throughout.** Using the ungated data API that the public front end already
calls is reading what the site publishes. Defeating a CAPTCHA is not, and one endpoint here is
CAPTCHA-gated on its search path: that path is out of scope permanently, while its ungated listing
is used.

---

## 1. How the API is called

Endpoint names are discoverable by fetching the front end's JavaScript bundle and grepping for the
service calls:

```bash
curl -s https://nhai.gov.in/ | grep -oE 'src="main\.[a-f0-9]+\.js"'
curl -s https://nhai.gov.in/main.<hash>.js | grep -oE 'apiService\.(post|get)\("[a-zA-Z0-9_/-]+"'
```

Every endpoint is `POST https://nhai.gov.in/nhai/api/<name>` with a `multipart/form-data` body. The
common parameters are:

| Parameter | Meaning |
| --- | --- |
| `language` | `en` or `hi` |
| `index` | **Page number, not a record offset.** Getting this wrong looks like an empty dataset — `index=1000` with `totalrecord=200` returns zero rows, not records 1000–1199. |
| `totalrecord` | Page size. 200 works; 1000 works on the smaller collections. |
| `sortby`, `sorttype` | Where supported |

A separate set of **static JSON assets** is served over plain `GET` with no parameters at all, and
those turned out to be the most valuable thing here.

---

## 2. The endpoints

### Primary evidence

| Endpoint | Rows | What it returns | Attachments |
| --- | --- | --- | --- |
| **`project-agreements`** | **351** | Executed project agreements. `id`, `title`, `state_id`/`state_name`, `mode_id`/`mode_value`, `upload_file[]`. Modes: HAM 276, BOT TOLL 53, BOT ANNUITY 21. | **Yes** — one PDF per record, 1–125 MB |
| **`agr-memo-of-underst`** | **712** | A nested tree, `{group: {subgroup: [items]}}`. `Contract Agreements` → `Concession Agreement for Private Sector participation` (4 **model** agreements), `Concession Agreement signed by NHAI` (171 **executed**), `Project Name` (6 — this is where the four-part contract agreement and the IPC payment register live). Plus `Memorandum of Understanding` (3). | **Yes**, several per record, each with a `description` |
| `tenderlist` | 183 | *Current* tenders only, not an archive. `id`, `title`, `publish_date`, `tender_no`, bid submission and opening dates. | No |
| `tenderdetail` (`nid=`) | per tender | `basic_information` (Tender No, Section, Department, Procurement Category, Tender Type, Evaluation Type, Application Fee, **EMD Value**), `documents` (slots for **Notice Inviting Tender**, **Tender Document**, **Pre Bid Query Response**, **Result**, **Agreement Rate Contract**), `important_dates`, `other_documents[]` with file URLs. | **Yes** |
| `commercial-operations` | 591 | User-fee/toll collection contracting — RFQs, addenda, year-grouped. | **Yes** |

**The named document slots in `tenderdetail` matter more than they look.** `Result` and
`Agreement Rate Contract` mean NHAI's schema can publish an award result and a signed rate contract
per tender. Both were empty on the tender sampled, but the shape is there, and a tender that fills
them would close the pre-award-to-award link that section 4 says is currently missing.

### Reference and administrative

| Endpoint | Rows | Notes |
| --- | --- | --- |
| `policycirculars` | 9,105 | **Not a policy library, despite the name.** 758 records sampled across four pages spanning 2013–2026: almost entirely right-of-way permissions to lay cables and pipelines across highways. Zero matches on standard bid document, price adjustment, mobilisation advance, retention or measurement. **Search is CAPTCHA-gated** — a `title` parameter returns `{"_resultflag":0,"message":"please enter captcha"}` — and that path is out of scope. The unfiltered listing is not gated. |
| `legalarbitration` | 22 | Chairman's letters and arbitration-policy documents, with PDFs |
| `legalcases` | 50 | Grouped under *Society For Affordable Redressal Of Disputes (SAROD)* |
| `bonds` | 128 | 54EC and taxfree/taxable bond documents |
| `downloadforms` | 8 | Digital-signature application forms |

### Broken or empty

| Endpoint | Result |
| --- | --- |
| `project-information` | **Times out server-side.** Empty reply after ~61 s even at `totalrecord=2`. Requires `phase_type`, `sortby`, `sorttype`; supplying them did not help. The static assets in section 3 appear to carry the same data and work. |
| `status-of-arbitral-award-payment` | **HTTP 500.** A server error, not an access control. Worth re-probing later: the name suggests award-payment status. |
| `rest_api` | HTTP 500 |
| `get_category`, `commontype` | HTTP 200 with a message and no data |

### Unreachable from this environment

`library.nhai.org` (the `CircularTree` circular library), `aipr.nhai.org`, `rpc.nhai.org`,
`datalakeg.nhai.gov.in`, `complaint.nhai.org` — all connection-reset or timeout, consistent with the
geo-restriction pattern already recorded for 14 other Indian domains in
[the acquisition strategy](CORPUS_ACQUISITION_STRATEGY.md). Probably reachable from an Indian network.

---

## 3. The static project register — the most valuable endpoint here

Five plain `GET` JSON files, no parameters, no authentication:

```text
https://nhai.gov.in/assets/json/get_ui_projects.json               647 rows   under implementation
https://nhai.gov.in/assets/json/get_om_projects.json               422 rows   operations & maintenance
https://nhai.gov.in/assets/json/get_dpr_in_progress_projects.json  381 rows   DPR in progress
https://nhai.gov.in/assets/json/get_target_in_cfy_projects.json    290 rows   targeted this financial year
https://nhai.gov.in/assets/json/get_to_be_awarded_projects.json     22 rows   to be awarded
```

1,762 rows, **1,450 distinct projects**. Each row is `{responseCode, data[], responseMessage}` and
every record carries the same 26 fields:

| Field | Example | Why it matters |
| --- | --- | --- |
| **`upc`** | `N/02005/21005/BR` | **The join key.** Unique Project Code. |
| `project_name` | `Aurangabad - Barachatti (TNHP/7; Package - V A) 4L of existing 2L section from km. 180 to km. 240 on NH-2` | Often embeds the **contract number** and **package name** |
| `mode` | `Item Rate`, `EPC`, `HAM`, `BOT Toll`, `BOT Annuity`, `TBD` | Decides whether a priced BOQ and RA bills exist at all |
| `current_project_stage` | `Completed & Agency Demobilised (Civil/O&M)` | Whether a full post-award history exists |
| `ro`, `piu`, `state`, `division` | `RO-Ranchi`, `Dhanbad`, `Bihar` | Administrative locators |
| `nh`, `length`, `lanes` | `2`, `60`, `4L` | Physical scope |
| **`awarded_cost`**, `total_capital_cost` | `284.87`, `858.62` (₹ crore) | **Award value, and the gap to final cost** |
| **`loa_date`**, `agreement_date`, `appointed_date` | `31/07/2001` | **Award and award-acceptance chronology** |
| `scheduled_completiondate`, `likely_completiondate`, `final_completation_date` | `30/10/2007`, `07/01/2010` | **Delay, as a subtraction** |
| `dateof_termination` | `null` | Terminated contracts are visible |

Mode distribution across the 1,450: **EPC 645 · HAM 354 · TBD 188 · BOT Toll 177 · Item Rate 46 ·
BOT Annuity 40.**

---

## 4. Join keys: what joins deterministically and what does not

The requirement was a deterministic answer to *"is this agreement about the same project as this
payment record?"* — no fuzzy matching where an exact identifier exists.

### It joins: UPC ↔ agreement PDF, via the filename

**The agreement PDF filenames are the UPC with the slashes removed.**

```text
register upc   N/02004/27002/AP
PDF            https://nhai.gov.in/nhai/sites/default/files/project_agreement/N0200427002AP_0.pdf
```

Strip `/` from `upc`, strip a trailing `_<n>` from the filename stem, upper-case both. **274 of 352
agreement files join to a register record this way.** NHAI uses the compact form itself — one
agreement title reads *"[Revived of earlier terminated N0200427001AP]"* — so this is the authority's
own convention, not a pattern inferred from coincidence.

The 78 that do not join are mostly older `concession_files/` uploads named after the road rather than
the project.

### It joins: contract number, printed in the document and embedded in the register

The Package V-A contract agreement states *"Contract No. : TNHP/7"* on its signature page, and the
register's `project_name` for `N/02005/21005/BR` reads *"Aurangabad - Barachatti (**TNHP/7**;
Package - V A)"*. Exact substring, no ambiguity. This is what tied a 361-page scan to a project
record.

### It joins: package name

`ABP-III` appears in the document title *"Monthly ipc payment details of package ABP-iii"* and in the
register's `project_name` for `N/02005/06004/UP`: *"4L of Allahabad Bypass - Construction of Road from
km. 198.00 to km. 242.708 (**Construction Package ABP-III**)"*. Case-insensitive exact match.

### It joins, and independently confirms the other joins: the LOA date

The register gives `loa_date = 31/07/2001` for `N/02005/21005/BR`. The performance bank guarantee
bound into the contract agreement recites *"No.11016/7/2000/Tech/GM(WB) dated 31.07.2001"*. Two
independent sources, one date. This is the check that made the UPC join believable rather than
plausible.

### It does not join: tenders

**`tenderlist` carries `tender_no` and no UPC.** A tender number like
`NHAI/PIU-Purulia/Tender/2026/622` shares no identifier with the project register, and the listing
holds only 183 *current* tenders rather than an archive — so a 2001 or 2004 award has no tender record
to join to at all.

The consequence is precise and it is the main structural gap: **a project's pre-award and post-award
records cannot be linked by identifier through NHAI's public data.** Linking them would need PIU plus
chainage plus NH matching, which is inference, not a join. Left undone.

---

## 5. What this makes possible, and what it does not

**Possible now, deterministically:** for a project identified by UPC, the executed agreement PDF, the
awarded cost, the LOA and agreement dates, the appointed date, the scheduled and final completion
dates, the mode, and the administrative chain down to the PIU. That is a real award-and-completion
record for 274 projects.

**Not possible from these endpoints:** measurement books, running account bills, variation orders, and
— except for one legacy upload — interim payment certificates. `project-agreements` publishes only
concession-type agreements (HAM, BOT Toll, BOT Annuity), and a concession has no priced BOQ or RA bill
by construction. **Not one of the 46 `Item Rate` projects in the register has a published agreement.**

The two exceptions are both in the `agr-memo-of-underst` → `Project Name` group, which is a small
legacy list of six entries, and they belong to **two different projects**: the four-part contract
agreement is Package V-A on NH-2 in Bihar, and the monthly IPC payment register is the Allahabad
Bypass package ABP-III. Reading adjacency in that flat list as association is a mistake, and it is one
this project made before checking the document itself.
