# Product-first corpus discovery: where building and real-estate work leaves digital evidence

Date: 2026-08-21
Research only. **No documents were acquired.** Two listing pages and one 400-byte probe were fetched
to settle questions that change the recommendation; nothing entered the corpus.

## Why this document exists

Every previous corpus document in this repository asked *what can we get?* This one asks *what will a
paying customer upload?* The two answers are not the same, and the gap has been quietly steering the
project: highways publish more, so the corpus became highways.

That drift is now named and reversed. NHAI is a **validation corpus**. The product is residential
real estate, commercial real estate and building construction, serving developers, PMCs, quantity
surveyors, billing engineers, contracts engineers, finance and internal audit.

Companion to [CORPUS_ROADMAP.md](CORPUS_ROADMAP.md) (where construction evidence exists at all),
[BUILDING_CORPUS_AVAILABILITY.md](BUILDING_CORPUS_AVAILABILITY.md) (the first building acquisition)
and [DOCUMENT_LAYOUT_SURVEY.md](DOCUMENT_LAYOUT_SURVEY.md) (the layout engines).

## How to read this

Confidence is marked because a roadmap collapses if a guess reads like a fact:

- **[V]** verified during this research — a request was made, a licence field was read
- **[K]** established domain knowledge, specifics not re-checked
- **[?]** plausible and unverified — check before relying on it

Reachability was measured from a **US network**, and that is a property of this machine, not of the
source. 70 hosts were tested [V]; results are in §4.1 and they matter, because roughly a third of
Indian public hosts refuse connections from outside India.

Column codes for the catalogue:

| Code | Meaning |
| --- | --- |
| **Bld / Inf / Both** | building vs infrastructure |
| **Stage** | workflow stages covered, numbered per §2 |
| **Pub** | public availability: Y / part / N |
| **Auto** | automation feasibility: High / Med / Low / None |
| **Qual** | expected quality: struct (spreadsheet/API), text (PDF text layer), scan, mixed |
| **Prim** | primary evidence: Y / quoted / N |
| **Cust** | resembles what a real customer would upload: High / Med / Low |
| **Use** | overall usefulness to Aedifex, 0–5 |

---

## 1. The finding that reframes everything

**The document class Aedifex is built for is not published by *any* public procurement portal,
because it is created after the public interest ends — but it *is* published, statutorily, by a
regulator, for private residential projects.**

India's Real Estate (Regulation and Development) Act requires every registered residential project
to file **quarterly** certificates signed by named professionals [V]:

| Form (MahaRERA naming) | Signed by | Certifies | Workflow stage |
| --- | --- | --- | --- |
| **Form 1** | Architect | percentage of work completed, discipline by discipline | **Certification** |
| **Form 2** | Structural engineer | cost incurred on the project to date | **Certification** |
| **Form 2A** | — | quality assurance | **Quality Evidence** |
| **Form 3** | Chartered accountant | cost incurred, and withdrawal permitted from the designated account | **Payment** |
| **Form 4** | Architect | project completion | **Completion** |
| **Form 5** | Chartered accountant | annual audit of the designated account | Payment |

This is a professional certifying, under personal liability, that a percentage of work is complete
and that a sum may be withdrawn. It is **exactly** the `Measurement → Claim → Certification →
Payment` chain the product verifies — and it concerns **real private residential projects built by
real developers**, not a government road.

The 70% designated-account rule is what makes it exist: a promoter may only withdraw construction
money in proportion to certified completion, so the certificate *is* the payment control. Internal
audit and finance personas have a statutory artifact to audit against, and it is public.

**This is the single most product-relevant document class discovered in any research pass so far.**

The catch is acquisition, not content — see §4.3. Its content is class A; its automation feasibility
is Low.

## 2. The canonical workflow, and what the documents are actually called

The product's workflow, with the vocabulary a real Indian building project uses [V for JMR/RA bill
naming, K for the rest]. Naming matters because a customer will upload a file called `JMR-14.pdf`,
not `measurement.pdf`.

```text
 1 Project        registration, approvals, layout, sanctioned plan
 2 Contract       Work Order / LOI / LOA, agreement, GCC + SCC, correspondence
 3 BOQ            priced BOQ, Schedule of Quantities, Schedule of Values, rate analysis
 4 Measurement    JMR (Joint Measurement Record), Measurement Book, measurement sheet, DPR
 5 RA Bill        Running Account Bill + Abstract + Deviation Statement + Extra Item statement
 6 Certification  Architect's Certificate, IPC, Engineer's certificate, RERA Form 1/2
 7 Payment        payment advice, retention, mobilisation advance recovery, RERA Form 3
 8 Variation      Variation Order, Change Order, Deviation Order, extra-item rate analysis, EOT
 9 Quality        cube test reports, MTC, third-party inspection, NCR, snag list, RERA Form 2A
10 Completion     WCC, virtual/final completion, OC, defect liability, final bill, RERA Form 4
    supporting    PO, indent, GRN / delivery challan, Material Reconciliation Statement (MRS),
                  tax invoice, e-way bill, debit note / recovery statement, hindrance register
```

Two vocabulary facts worth recording because they are load-bearing:

**"The JMR is the bedrock of contractor billing in India," and the subcontractor attaches it to the
RA Bill as proof of work** [V]. So stage 4 → 5 is a *document attachment* relationship in real
practice, not an inference Aedifex must reconstruct. If a customer uploads an RA bill, the JMR is
very likely in the same bundle.

**The US equivalent is a single standardised pair: AIA G702 / G703** [K]. G702 is the Application
and Certificate for Payment; **G703 is the continuation sheet — a line-item schedule of values with
"work completed to date" per item**. That is structurally an RA bill against a BOQ. Anyone building a
document model for building payment should read G702/G703 as the canonical shape, because it is the
most standardised instance of it in the world. FIDIC's IPC is the international-contract equivalent.

---

## 3. Deliverable 1 — ranked catalogue

152 sources across 12 categories. Ranked within each category by **Use**.

### 3.1 Indian institutional building owners (universities, institutes, hospitals)

The best public analogue of a commercial building project: a single owner, a campus of buildings,
per-project document sets, no highways. All 20 hosts tested were reachable [V].

| # | Source | Owner | Bld/Inf | Stage | Pub | Licence | Auto | Qual | Prim | Cust | Use |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | **IIT Kanpur IWD "Tender Hall"** | IIT Kanpur | Bld | 1,2,3,8 | Y | none published | **High** | struct+text | Y | High | **5** |
| 2 | **IIT Bombay Dean (IPS)** | IIT Bombay | Bld | 1,2,3,8 | Y | none published | **High** | text+struct | Y | High | **5** |
| 3 | IIT Madras tenders | IIT Madras | Bld | 1,2,3 | Y | none published | Med | text | Y | High | 4 |
| 4 | IIT Kharagpur tenders | IIT KGP | Bld | 1,2,3 | Y | none published | Med | text | Y | High | 4 |
| 5 | IISc tenders | IISc | Bld | 1,2,3 | Y | none published | Med | text | Y | High | 4 |
| 6 | IIT Delhi tenders | IIT Delhi | Bld | 1,2,3 | Y | none published | Med | text | Y | High | 4 |
| 7 | IIT Hyderabad tenders | IIT-H | Bld | 1,2,3 | Y | none published | Med | text | Y | High | 4 |
| 8 | IIT Roorkee | IIT-R | Bld | 1,2,3 | Y | none published | Med | mixed | Y | High | 3 |
| 9 | IIT Guwahati | IIT-G | Bld | 1,2,3 | Y | none published | Med | mixed | Y | High | 3 |
| 10 | IIT BHU | IIT BHU | Bld | 1,2,3 | Y | none published | Med | mixed | Y | High | 3 |
| 11 | IIT Gandhinagar | IIT-GN | Bld | 1,2,3 | part | none published | Low (403) | text | Y | High | 3 |
| 12 | IIT Ropar / Patna / Mandi / Jammu | new IITs | Bld | 1,2,3 | Y | none published | Med | mixed | Y | High | 3 |
| 13 | IISER Pune (and other IISERs) | IISERs | Bld | 1,2,3 | Y | none published | Med | mixed | Y | High | 3 |
| 14 | AIIMS New Delhi + new AIIMS | MoHFW | Bld | 1,2,3 | Y | GoI | Med | mixed | Y | **High** | 4 |
| 15 | JNU / DU / BHU / AMU works | central univs | Bld | 1,2,3 | Y | GoI | Med | mixed | Y | Med | 3 |
| 16 | NIT tenders (31 institutes) | NITs | Bld | 1,2,3 | Y | GoI | Med | mixed | Y | High | 3 |
| 17 | IIM tenders (20 institutes) | IIMs | Bld | 1,2,3 | Y | none published | Med | text | Y | High | 3 |
| 18 | Central/Navodaya school building works | KVS/NVS | Bld | 1,2,3 | Y | GoI | Low | mixed | Y | Med | 2 |
| 19 | ICAR / agricultural universities | ICAR | Bld | 1,2,3 | Y | GoI | Low | mixed | Y | Med | 2 |
| 20 | State technical universities | states | Bld | 1,2,3 | part | varies | Low | scan | Y | Med | 2 |
| 21 | ISRO / DRDO / BARC civil works | DoS/DRDO/DAE | Bld | 1,2,3 | part | GoI | Low | mixed | Y | Med | 2 |
| 22 | Railway building divisions | Indian Railways | Both | 1,2,3 | Y | GoI | Low | scan | Y | Low | 2 |
| 23 | Airport terminal works (AAI) | AAI | Bld | 1,2,3 | Y | GoI | Low | mixed | Y | Med | 2 |
| 24 | Public bank premises divisions | SBI etc. | Bld | 1,2,3 | part | — | Low | scan | Y | Med | 1 |

**IIT Kanpur is the find of this pass** [V]. Its `iwd/tenderhall.htm` lists **9,959 unique documents
across 3,033 tender folders, 2019–2026**, at stable paths `file/<year>/<division>-<no>/<doc>`:

| Document family | Count |
| --- | --- |
| BOQ spreadsheets (`boq.xls`, `boqnit*.xls`, `schedulequantity.xls`, `pschedule.xls`) | **~1,028** |
| `tenderdocument.pdf` / `.doc` | 715 |
| `nit.pdf` / `nit*.pdf` | 976 |
| **`contractdocument*.pdf`** | **475** |
| `financialbid.xls` | 278 |
| `corrigendum*.pdf` | 153 |
| Total by type | 6,785 pdf · 1,943 xls · 882 xlsx · 216 doc · 159 docx |

Civil divisions are `IWD-Div-I/II/III` and `IWD-CO`; `ED-EE`/`ED-SE` are electrical and services.
**475 contract documents is the largest public source of building Contract-stage evidence found
anywhere in this research**, and 2,825 spreadsheets means structured BOQ with cell-level provenance
rather than PDF table reconstruction.

### 3.2 Indian government building agencies

| # | Source | Owner | Bld/Inf | Stage | Pub | Licence | Auto | Qual | Prim | Cust | Use |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 25 | **CPWD** (works + DSR + manuals) | MoHUA | Bld | 1,2,3,+refs | Y | GoI | Med | text+scan | Y | **High** | **5** |
| 26 | NBCC India | NBCC | Bld | 1,2,3 | Y | — | Med | mixed | Y | High | 4 |
| 27 | HSCC (hospitals) | HSCC/NBCC | Bld | 1,2,3 | part | — | Low | mixed | Y | High | 3 |
| 28 | Engineers India Ltd (EPIL) | EPIL | Both | 1,2,3 | part | — | Low | mixed | Y | Med | 2 |
| 29 | NPCC | NPCC | Bld | 1,2,3 | part | — | Low | mixed | Y | Med | 2 |
| 30 | WAPCOS | WAPCOS | Inf | 1,2,3 | part | — | Low | mixed | Y | Low | 1 |
| 31 | MES (Military Engineer Services) | MoD | Bld | 1,2,3 | part | GoI | **None (blocked)** | scan | Y | Med | 1 |
| 32 | State PWD building wings — Kerala | Kerala PWD | Bld | 1,2,3 | Y | state | Med | mixed | Y | Med | 3 |
| 33 | State PWD — Rajasthan (+ BSR) | Rajasthan PWD | Bld | 1,2,3,refs | Y | state | Med | mixed | Y | Med | 3 |
| 34 | State PWD — West Bengal | WB PWD | Bld | 1,2,3,4* | Y | state | Med | scan | Y | Med | 3 |
| 35 | State PWD — Puducherry (GCC 2023, CMB) | Pud. PWD | Bld | 2,4 | Y | state | Med | text | Y | Med | 3 |
| 36 | State PWD — UP | UP PWD | Both | 1,2,3 | Y | state | **None (blocked)** | scan | Y | Low | 1 |
| 37 | State PWD — Maharashtra | Maha PWD | Both | 1,2,3 | Y | state | **None (blocked)** | mixed | Y | Med | 1 |
| 38 | State PWD — MP / Assam | states | Both | 1,2,3 | Y | state | None (no DNS) | mixed | Y | Low | 1 |
| 39 | **Odisha WAMIS / PPMS (e-MB + RA bill)** | Odisha Works | Both | **4,5,7** | Y | state | **None (blocked)** | text | **Y** | **High** | **5*** |
| 40 | HUDCO (housing finance + technical) | HUDCO | Bld | refs | Y | — | Low | text | N | Low | 1 |

`*` Odisha PPMS is scored 5 on content and None on feasibility from here. It is the only public
source found that publishes **filled RA bills merged with their measurement sheets** — see §4.3.

### 3.3 Municipal & development authorities

| # | Source | Owner | Bld/Inf | Stage | Pub | Licence | Auto | Qual | Prim | Cust | Use |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 41 | **DDA** (housing + commercial) | DDA | Bld | 1,2,3 | Y | GoI | Med | mixed | Y | **High** | 4 |
| 42 | **CIDCO** (new-town buildings) | CIDCO | Bld | 1,2,3 | Y | state | Med | mixed | Y | **High** | 4 |
| 43 | MCGM / BMC building works | MCGM | Bld | 1,2,3 | Y | state | Med | mixed | Y | High | 4 |
| 44 | Pune Municipal Corporation | PMC | Bld | 1,2,3 | Y | state | Med | mixed | Y | High | 3 |
| 45 | GHMC Hyderabad | GHMC | Bld | 1,2,3 | Y | state | Med | mixed | Y | High | 3 |
| 46 | Greater Chennai Corporation | GCC | Bld | 1,2,3 | Y | state | Med | mixed | Y | Med | 3 |
| 47 | Noida Authority | NOIDA | Bld | 1,2,3 | Y | state | Med | mixed | Y | High | 3 |
| 48 | BBMP Bengaluru | BBMP | Bld | 1,2,3 | Y | state | **None (blocked)** | mixed | Y | High | 2 |
| 49 | YEIDA | YEIDA | Bld | 1,2,3 | Y | state | None (**DNS→127.0.0.1**) | mixed | Y | Med | 1 |
| 50 | GMDA Gurugram | GMDA | Both | 1,2,3 | Y | state | None (blocked) | mixed | Y | Med | 1 |
| 51 | HSVP (ex-HUDA) | Haryana | Bld | 1,2,3 | Y | state | Low | mixed | Y | Med | 2 |
| 52 | MMRDA | MMRDA | Both | 1,2,3 | Y | state | Low | mixed | Y | Med | 2 |
| 53 | Ahmedabad / Surat municipal | AMC/SMC | Bld | 1,2,3 | Y | state | Low | mixed | Y | Med | 2 |
| 54 | Kolkata Municipal Corporation | KMC | Bld | 1,2,3 | Y | state | Low | scan | Y | Med | 2 |
| 55 | Smart Cities Mission SPVs (100) | MoHUA/SPVs | Bld | 1,2,3 | Y | GoI | Low | mixed | Y | Med | 3 |
| 56 | Cantonment boards | MoD | Bld | 1,2,3 | part | GoI | Low | scan | Y | Low | 1 |

### 3.4 Public housing and RERA — the private-project regulator

| # | Source | Owner | Bld/Inf | Stage | Pub | Licence | Auto | Qual | Prim | Cust | Use |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 57 | **RERA QPR + Form 1/2/2A/3/4/5 (all states)** | state RERAs | **Bld (residential, private)** | **1,6,7,9,10** | Y | statutory filing | **Low** | scan+text | **Y** | **Highest** | **5** |
| 58 | MahaRERA | Maharashtra | Bld | 1,6,7,9,10 | Y | statutory | None (blocked) | mixed | Y | Highest | 5* |
| 59 | HP RERA (QPR PDFs visible) | HP | Bld | 1,6,7,10 | Y | statutory | Low (tokenised) | scan | Y | Highest | 4 |
| 60 | Haryana RERA | Haryana | Bld | 1,6,7,10 | Y | statutory | Low | mixed | Y | Highest | 4 |
| 61 | K-RERA Kerala (+ QPR manual) | Kerala | Bld | 1,6,7,10 | Y | statutory | Low (503/WAF) | mixed | Y | Highest | 4 |
| 62 | UP RERA | UP | Bld | 1,6,7,10 | Y | statutory | Low | mixed | Y | Highest | 4 |
| 63 | Rajasthan / Goa / Jharkhand RERA | states | Bld | 1,6,7,10 | Y | statutory | Low | mixed | Y | Highest | 3 |
| 64 | Karnataka / Telangana / Gujarat / AP / MP RERA | states | Bld | 1,6,7,10 | Y | statutory | None (blocked) | mixed | Y | Highest | 3* |
| 65 | **MHADA** | Maharashtra | Bld | 1,2,3 | Y | state | Med | mixed | Y | High | 4 |
| 66 | PMAY-U MIS / pmaymis | MoHUA | Bld | 1,7 | Y | GoI | Med | struct | part | Med | 3 |
| 67 | State housing boards (TN, KA, AP, WB…) | states | Bld | 1,2,3 | part | state | Low | mixed | Y | High | 3 |
| 68 | Slum Rehabilitation Authority (SRA) | Maharashtra | Bld | 1,6,10 | part | state | Low | scan | Y | High | 2 |
| 69 | Delhi Urban Shelter Improvement Board | Delhi | Bld | 1,2,3 | Y | state | Low | mixed | Y | Med | 2 |
| 70 | eGramSwaraj public vouchers | MoPR | Bld (small) | 7 | Y | GoI | Med | struct | Y | Low | 2 |

### 3.5 Indian e-procurement and transparency infrastructure

| # | Source | Owner | Bld/Inf | Stage | Pub | Licence | Auto | Qual | Prim | Cust | Use |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 71 | **CPPP eprocure.gov.in** | NIC/GoI | Both | 1,2,3 | Y | GoI, **terms unreviewed** | Med (CAPTCHA) | mixed | Y | High | 4 |
| 72 | NIC etenders.gov.in | NIC | Both | 1,2,3 | Y | GoI | Med (CAPTCHA) | mixed | Y | High | 3 |
| 73 | GeM | GoI | Both | 1,2 | part | **registration required** | None | struct | Y | Med | 1 |
| 74 | MSTC e-commerce | MSTC | Both | 1,2 | Y | — | Low | mixed | Y | Low | 1 |
| 75 | State e-procurement portals (~30) | states | Both | 1,2,3 | Y | state | Low | mixed | Y | High | 3 |
| 76 | data.gov.in | GoI | Both | 1,7 | Y | GODL-India | High | struct | part | Low | 2 |
| 77 | PFMS / treasury payment data | MoF | Both | 7 | part | GoI | Low | struct | Y | Low | 2 |
| 78 | CAG audit reports | CAG | Both | all (quoted) | Y | **explicit reuse policy** | High | text | **quoted** | Low | 3 |

### 3.6 International public procurement

| # | Source | Owner | Bld/Inf | Stage | Pub | Licence | Auto | Qual | Prim | Cust | Use |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 79 | **UK Contracts Finder** (+ OCDS API) | UK Cabinet Office | Both | 1,2 | Y | **OGL v3** | **High (API)** | struct+text | Y | Med | 4 |
| 80 | UK Find a Tender Service | UK Cabinet Office | Both | 1,2 | Y | OGL v3 | High | struct | Y | Med | 3 |
| 81 | Singapore GeBIZ | GovTech SG | Both | 1,2 | Y | SG OGL | Med | text | Y | Med | 3 |
| 82 | AusTender | Australia | Both | 1,2 | Y | CC-BY (typical) | Med | text | Y | Med | 3 |
| 83 | SAM.gov (US federal) | GSA | Both | 1,2,3 | Y | **US public domain** | **High (API)** | text | Y | Med | 4 |
| 84 | CanadaBuys | PSPC | Both | 1,2 | Y | Canada OGL | Med | text | Y | Med | 3 |
| 85 | TED (EU) | EU | Both | 1,2 | Y | EU reuse | High (API) | struct | Y | Low | 3 |
| 86 | World Bank projects & procurement | World Bank | Both | 1,2,10 | Y | CC-BY 4.0 | High | text | Y | Low | 3 |
| 87 | ADB projects | ADB | Both | 1,2,10 | Y | CC-BY | Med | text | Y | Low | 2 |
| 88 | UNGM | UN | Both | 1,2 | Y | — | Low | text | Y | Low | 1 |
| 89 | US state/city capital projects (e.g. NYC SCA, TX) | states | Bld | 1,2,3,6,7 | Y | public record | Med | mixed | Y | **High** | 4 |
| 90 | US school district bond programmes | districts | Bld | 1,2,3,6,7 | Y | public record | Med | mixed | Y | **High** | 4 |
| 91 | data.gov / data.gov.uk / data.gov.sg / open.canada.ca | govts | Both | 1,7 | Y | open | High | struct | part | Low | 2 |
| 92 | OCDS registry (100+ countries) | OCP | Both | 1,2,7 | Y | mostly open | High | struct | part | Low | 3 |

**US state and municipal capital projects are underrated** and worth a dedicated pass. Unlike Indian
portals, US public-record law frequently puts **pay applications (AIA G702/G703), change orders and
certificates of substantial completion** into published board packets — stages 5–8, in the exact
standardised form §2 describes. This is the strongest lead for post-award *building* evidence outside
India. [?] — inferred from how board packets work, not verified against a specific district.

### 3.7 International institutional capital projects

| # | Source | Owner | Bld/Inf | Stage | Pub | Licence | Auto | Qual | Prim | Cust | Use |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 93 | US public university capital projects | universities | Bld | 1,2,3,6,7 | Y | public record | Med | mixed | Y | High | 4 |
| 94 | UK university estates tenders | universities | Bld | 1,2,3 | Y | OGL-ish | Med | text | Y | High | 3 |
| 95 | Australian university capital works | universities | Bld | 1,2,3 | Y | varies | Low | text | Y | High | 2 |
| 96 | Singapore BCA / JTC / HDB projects | SG govt | Bld | 1,2,3 | Y | SG OGL | Med | text | Y | High | 3 |
| 97 | Canadian university/provincial buildings | provinces | Bld | 1,2,3 | Y | OGL | Low | text | Y | High | 2 |
| 98 | NZ GETS | NZ | Both | 1,2 | Y | CC-BY | Low | text | Y | Low | 1 |
| 99 | Hong Kong ArchSD | HK govt | Bld | 1,2,3 | Y | — | Low | text | Y | Med | 2 |
| 100 | Gulf (Dubai/Abu Dhabi) public buildings | govts | Bld | 1,2 | part | — | Low | scan | Y | Med | 1 |

### 3.8 Standard-form contracts and document taxonomies — not corpora, but the schema

These do not supply project evidence. They define what the fields *are*, which is worth more than
another portal for building the domain model.

| # | Source | Owner | Stage | Pub | Licence | Use |
| --- | --- | --- | --- | --- | --- | --- |
| 101 | **AIA G702 / G703** (payment application + continuation sheet) | AIA | 5,6,7 | **N (restricted)** | commercial | **5 (schema)** |
| 102 | **CPWA Book of Forms** (MB, RA bill forms) | CAG/GoI | 4,5 | Y | GoI | **5 (schema)** — acquired |
| 103 | **IS 1200** method of measurement (25 parts) | BIS | 4 | Y | BIS terms | **5 (schema)** |
| 104 | FIDIC Red/Yellow/Silver Book (IPC clauses) | FIDIC | 5,6,7 | N | commercial | 4 (schema) |
| 105 | NEC4 | NEC/ICE | 5,6,7 | N | commercial | 3 |
| 106 | JCT suite | JCT | 5,6,7 | N | commercial | 3 |
| 107 | CPWD Form 7/8 + Works Manual | CPWD | 2,4,5 | Y | GoI | **5 (schema)** |
| 108 | CPWA Code / OPWD Code / state PW codes | govts | 4,5,7 | Y | GoI/state | 4 (schema) |
| 109 | CAG Works Audit Manual | CAG | audit rules | Y | reuse policy | **5 (rules)** — acquired |
| 110 | RICS NRM 1/2/3 (new rules of measurement) | RICS | 3,4 | N | commercial | 4 (schema) |
| 111 | CSI MasterFormat / UniFormat | CSI | 3 | part | commercial | 3 |
| 112 | RERA model agreement for sale + Form formats | state RERAs | 2,6 | Y | statutory | 4 (schema) |

### 3.9 Cost and rate databases (reference evidence)

| # | Source | Owner | Pub | Licence | Auto | Use |
| --- | --- | --- | --- | --- | --- | --- |
| 113 | **CPWD DSR (Civil + E&M)** | CPWD | Y | GoI | Med | **5** |
| 114 | CPWD Plinth Area Rates | CPWD | Y | GoI | Med | 4 |
| 115 | Rajasthan BSR | Rajasthan PWD | Y | state | Med | 4 |
| 116 | Maharashtra DSR | Maha PWD | Y | state | None (blocked) | 3 |
| 117 | Karnataka / Kerala / TN / AP / Telangana SoR | states | Y | state | Low | 3 |
| 118 | Delhi / MES / Railway schedules of rates | agencies | part | GoI | Low | 3 |
| 119 | WPI (Office of the Economic Adviser) | DPIIT | Y | GoI | Med | 4 — acquired |
| 120 | **CPI-IW by centre (Labour Bureau)** | Labour Bureau | Y | GoI | Med | **4 — still missing** |
| 121 | RSMeans | Gordian | N | commercial | None | 2 |
| 122 | Spon's Price Books | Taylor & Francis | N | commercial | None | 2 |
| 123 | BCIS (RICS) | RICS | N | commercial | None | 2 |
| 124 | Singapore BCA cost data / tender price indices | BCA | part | SG | Low | 2 |

### 3.10 Datasets, BIM and ML corpora

| # | Source | Content | Pub | Licence | Use |
| --- | --- | --- | --- | --- | --- |
| 125 | DataDrivenAEC dataset directory (129 datasets) | meta-catalogue | Y | unstated | 3 |
| 126 | Global Procurement Dataset (72M contracts, 42 countries) | award metadata | Y | unstated | 2 |
| 127 | AECBench (4,800 Q&A, 23 tasks) | LLM eval | Y | unstated | 2 |
| 128 | CODE-ACCORD (regulation NLP) | 862 sentences | Y | unstated | 1 |
| 129 | IFCNet / BIMNet / IFC-Bench / ifc-bim-qa | BIM geometry, scan-to-BIM, Q&A | Y | mixed | **1** |
| 130 | PubTables-1M / FinTabNet / PubTabNet | table structure | Y | mixed (CDLA/NC) | 3 (OCR eval) |
| 131 | DocLayNet | layout, 80k pages | Y | CDLA-Permissive | 3 (OCR eval) |
| 132 | SROIE / CORD / FUNSD | receipts, forms | Y | mixed/NC | 2 (OCR eval) |
| 133 | IAM / RIMES handwriting | handwriting | part | research-only | 2 (OCR eval) |
| 134 | Synthetic BOQ/RA-bill generation (in-repo) | E-class | — | own | 2 |

**BIM is a negative finding.** Every open BIM/IFC dataset located is geometry, point clouds or
schema Q&A. **None links cost, measurement or payment to a document with a page and a digest**, so
none feeds an evidence pipeline whose unit is a citable artifact. Cost-linked BIM (5D) exists
commercially and is not published. Priority 6 should be closed unless a customer arrives with IFC.

### 3.11 Dispute, audit and litigation records

| # | Source | Content | Stage | Pub | Auto | Prim | Use |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 135 | Indian Kanoon (construction arbitration) | judgments quoting RA bills, MB, certificates | 4,5,6,8 | Y | High | **quoted** | 3 |
| 136 | Delhi/Bombay HC arbitration judgments | s.34/s.37 challenges with claim tables | 5,6,8 | Y | Med | quoted | 3 |
| 137 | NCLT/NCLAT orders (developer insolvency) | project cost, receivables | 7 | Y | Med | quoted | 2 |
| 138 | CAG state building-works audits | measured vs paid, excess payment | 4,5,7 | Y | High | quoted | 3 |
| 139 | Arbitral award exhibits (rarely published) | actual bills | 4,5 | N | None | Y | 1 |
| 140 | Consumer/RERA adjudication orders | delay, completion disputes | 6,10 | Y | Med | quoted | 2 |

### 3.12 Private-sector systems — understanding, not scraping

Not sources. This is the answer to *what will a customer actually upload, and out of what system?*

| # | System | Class | Who uses it [K/?] | Export shape a customer would upload |
| --- | --- | --- | --- | --- |
| 141 | SAP (ECC/S4, PS + MM) | Tier-1 ERP | L&T, Tata Projects, SP [K] | PDF bill prints, XLSX extracts, GRN/PO reports |
| 142 | Oracle Primavera P6 / Unifier | schedule + PM | large EPC [K] | schedule PDF, payment-application workflow exports |
| 143 | In4Suite (In4Velocity) | India real-estate ERP | residential developers [V] | RA bill, MRS, PO, invoice PDFs; investor reports |
| 144 | Farvision (Gamut) | India real-estate ERP | mid-size developers [K] | billing + inventory PDFs |
| 145 | Nway ERP | India construction ERP | contractors [V] | RA bill, material reconciliation |
| 146 | Inniti / Bsquare / Highrise / Powerplay | India SME construction | 43+ builders across 12 states [V] | bill, DPR, JMR photos |
| 147 | Procore | international PM | Indian arms of MNC PMCs [?] | pay applications, RFIs, submittals |
| 148 | Autodesk Construction Cloud / BIM 360 | doc control | design-led projects [K] | drawing sets, RFI, submittal logs |
| 149 | RIB Candy / CCS | QS/estimating | QS firms, EPC [K] | BOQ, valuations, cost reports |
| 150 | Zoho / Tally + Excel | SME reality | most small contractors [K] | **Excel RA bills, scanned JMRs, WhatsApp photos** |
| 151 | Aconex / Oracle Textura | payment management | large commercial [K] | payment applications with lien waivers |
| 152 | MS Excel + email + WhatsApp | the true baseline | everyone below Tier-1 [K] | **the actual upload: XLSX + phone photos of signed JMRs** |

**The most important row is the last one.** Below the Tier-1 contractors, the real artifact set is
Excel workbooks, PDF prints of Excel, and **phone photographs of hand-signed JMRs and measurement
sheets**. That is the input Aedifex must survive — not a clean ERP export. It has three consequences:

1. **XLSX is the primary format, not PDF.** The existing spreadsheet path with cell-level provenance
   is more valuable than any PDF table work.
2. **Handwriting appears at the signature and measurement layer**, not usually in the priced BOQ. A
   modern RA bill is typed; the JMR behind it is often handwritten and photographed.
3. **Photographs, not scans.** Skew, shadow, perspective and phone-camera EXIF — a different
   pre-processing problem from a flatbed scan, and one no current Aedifex code addresses.

---

## 4. Deliverable 2 — workflow coverage matrix

Best realistically obtainable class per stage. `A` = real primary public, `B` = real quoted,
`D` = authoritative blank format, `F` = private.

| Stage | Best public class | Best source | Feasible now? |
| --- | --- | --- | --- |
| 1 Project | **A** | IITK/IITB, CPWD, RERA registration | **Yes** |
| 2 Contract | **A** | **IITK `contractdocument*.pdf` (475)**, GCC/SCC sets | **Yes** |
| 3 BOQ | **A** | **IITK ~1,028 BOQ spreadsheets**, IITB priced PDFs | **Yes** |
| 4 Measurement | A (blocked) / **D** | Odisha PPMS `msrmt_doc`; CPWA forms; WB PWD | **No** |
| 5 RA Bill | A (blocked) / **D** | Odisha PPMS `merge_bill_msrmt`; CPWA Form 26 | **No** |
| 6 Certification | **A** | **RERA Form 1/2**; US pay applications (G702) | **Partly** |
| 7 Payment | **A** | **RERA Form 3**; eGramSwaraj; PFMS | **Partly** |
| 8 Variation | **A** | IITK/IITB corrigenda (pre-award only); CAG (quoted) | Weakly |
| 9 Quality | **A** | RERA Form 2A; MTC in tender annexures | Weakly |
| 10 Completion | **A** | RERA Form 4 + OC; IITK completed-projects list | **Partly** |

### 4.1 Reachability, measured [V]

70 hosts tested from a US network. This is a hard constraint on automation feasibility and it is not
uniform.

**Reachable (selected):** all 20 institutional hosts (IITB, IITD, IITM, IITK, IITKGP, IISc, IISER-P,
IIT-R/G/H/GN/RPR/P/Mandi/Jammu, JNU, DU, BHU, AMU) · cpwd.gov.in · nbccindia.in · dda.gov.in ·
mhada.gov.in · cidco.maharashtra.gov.in · hudco.org.in · pwd.rajasthan/kerala/py · wbpwd ·
portal.mcgm · pmc · ghmc · chennaicorporation · noidaauthorityonline · eprocure · etenders ·
mstcecommerce · pmaymis · pmay-urban · up-rera · hprera.nic.in · rera.kerala · haryanarera ·
rera.goa · jharera · rera.rajasthan · **every international portal tested**.

**Blocked / unusable:** mes.gov.in · uppwd · mahapwd · pwd.mp · pwd.assam · nbccindia.com ·
site.bbmp · gmda · tenders.gov.in (no DNS) · buyandsell.gc.ca (no DNS) · **maharera** ·
rera.karnataka · gujrera · rera.mp · rera.assam · rerabihar · orera · rera.cg · tgrera · rera.ap ·
punjabrera · **all `*.odisha.gov.in`** · `www.yeida.in` (**resolves to 127.0.0.1** — a broken public
DNS record, not a block).

**The pattern that matters:** the highest-value RERA states — Maharashtra, Karnataka, Telangana,
Gujarat — are precisely the ones blocked. Residential real-estate volume is concentrated there.

### 4.2 Deliverable 3 — gap analysis

**Stages 4 and 5 (Measurement, RA Bill) have no realistic public source reachable from outside
India, and this is now a structural conclusion rather than a search failure.** Three independent
research passes have found exactly one class-A instance worldwide (Odisha PPMS), and it is
geo-blocked.

Why the gap is structural, not incidental:

- Public procurement transparency is designed to prove a contract was **let fairly**. Nothing
  requires proving it was **paid correctly**. Payment happens between two parties after the public
  interest has been institutionally satisfied.
- Where post-award records are digitised (state WAMIS/e-MB systems), they are *internal accounting
  systems* that occasionally leak public URLs, not publication channels.
- RERA is the exception precisely because a *regulator* inserted itself into the payment control —
  but it regulates the **developer's** withdrawals, not the **contractor's** bills. So RERA gives
  stages 6, 7, 9, 10 and skips 4 and 5.

**Also missing, and worth naming:**

- **Variation orders** (stage 8) post-award: none, anywhere, publicly.
- **Contractor invoices, POs, GRNs, material reconciliation** (the supporting set): none. These are
  purely commercial and never published.
- **Photographed handwritten JMRs** — the actual customer input per §3.12 — exist in no dataset.
- **CPI-IW by centre (Gaya/Aurangabad)** — still not acquired, and the price-adjustment clause in
  the corpus names it.

**Three ways to close stages 4–5, in order of realism:**

1. **An Indian network egress** (VPN/VPS or a person). Immediately unlocks Odisha PPMS, MahaRERA,
   Karnataka/Telangana/Gujarat RERA, MES, UP/Maharashtra PWD. This is one operational decision worth
   more than any further research.
2. **US public-record building projects** (§3.6 #89/#90): school-district and university board
   packets that publish AIA G702/G703 pay applications and change orders. Different jurisdiction,
   right document class, and the most standardised form of it in existence.
3. **One design partner** — a developer, PMC or QS firm supplying a sanitised real project. Nothing
   public will ever match it, and stages 4, 5, 8 and the supporting set are only obtainable this way.

---

## 5. Deliverable 4 — the canonical corpus recommendation

**Aedifex should adopt a three-layer corpus, and stop looking for one corpus that does everything.**

### Layer 1 — Development corpus: **IIT Kanpur IWD + IIT Bombay Dean (IPS)**

The canonical corpus for building the product. Not because it is easy to crawl, but because it is
the closest public analogue of a commercial building project, and it is the only source that supplies
**Contract + BOQ at scale in structured form**:

- **3,033 tender folders, ~1,028 BOQ spreadsheets, 475 contract documents** — real buildings
  (hostels, labs, hospitals, campuses), real money, an owner behaving like a developer.
- **Structured spreadsheets**, so Work Item facts get cell-level provenance and the whole PDF
  table-reconstruction problem is bypassed for the stage that matters most.
- Stable paths, text layers, no OCR, no CAPTCHA, reachable, robots-permitted.
- Governs stages 1–3 and 8 (pre-award), which is where the deterministic rules with **both sides
  sourced** live: BOQ item ↔ DSR scheduled rate, priced bill ↔ advertised estimate, bill total ↔
  stated total.

### Layer 2 — Product-truth corpus: **RERA quarterly filings**

The corpus that proves Aedifex works on the *target market's own documents*. Private residential
projects, real developers, statutory professional certificates, stages 6/7/9/10. Nothing else public
is this close to the paying customer. Acquisition is manual-first and needs Indian egress for the
big states.

### Layer 3 — Validation corpora: **NHAI, CPWA/IS 1200/CPWD schemas, Odisha PPMS when reachable**

NHAI stays, doing exactly one job: proving the pipeline survives a 2001 handwritten scan. It defines
nothing. The schema documents (CPWA Book of Forms, IS 1200, CPWD Form 7/8, AIA G702/G703) define the
field vocabulary for stages 4–5 that no public instance supplies.

### What this is *not*

Not CPPP/eprocure, despite being the largest Indian tender source: CAPTCHA-gated, terms unreviewed,
and it duplicates what IITK/IITB give in a cleaner form. Not BIM. Not MGNREGA/eGramSwaraj (rural,
tabular, not documents). Not court judgments as a primary corpus — class B only.

---

## 6. Deliverable 5 — OCR and document-understanding architecture

**Recommendation: stop building an OCR pipeline. Build an OCR gateway.** The owner's instinct is
right, and the evidence in this repository already supports it.

### 6.1 Why the current shape is wrong

`aedifex.extraction.ocr` is a *RapidOCR module with bounds*, not a gateway. Its bounds, provenance
and parallelism are genuinely good work and should survive; its coupling to one engine should not.
The tell: adding a handwriting model today would mean editing that module rather than registering an
implementation.

There is already a `OcrEngine` Protocol with `name`, `version` and `read()`. That is the seed of the
gateway and it is nearly sufficient — it needs routing, a confidence contract, and per-engine
provenance, not a rewrite.

### 6.2 Verified licence matrix

Read from Hugging Face model-card licence fields on 2026-08-21 [V], not from PyPI, because PyPI
reports code licences and silently omits weights.

| Model | Licence | Handwriting | Tables | Determinism | Verdict |
| --- | --- | --- | --- | --- | --- |
| **RapidOCR / PP-OCRv5** | **Apache-2.0** | **no** | no | **deterministic** | **keep as baseline** |
| **TrOCR base handwritten** | **MIT** | **yes** | no (line-level) | deterministic | **adopt for the handwriting lane** |
| TrOCR large handwritten | **card states none** | yes | no | deterministic | resolve licence first |
| **Table Transformer (TATR)** | **MIT** | n/a | **structure only** | deterministic | adopt for the table lane |
| **Docling / granite-docling-258M** | **Apache-2.0** | partial | **yes** | mostly | **benchmark next** |
| **PP-StructureV3** | Apache-2.0 (v5 rec verified) | no | **yes** | deterministic | benchmark next |
| **GOT-OCR2** | **Apache-2.0** | **yes (7/10 measured)** | destroys | greedy-deterministic | candidate, hallucinates |
| **Florence-2-large** | **MIT** | limited | limited | deterministic | benchmark |
| **Qwen2.5-VL-7B / Qwen3-VL-8B** | **Apache-2.0** | **yes** | **yes** | sampling → pin seed | **strongest VLM candidate** |
| **InternVL3-8B** | **Apache-2.0** | yes | yes | sampling | candidate |
| **olmOCR-7B** | **Apache-2.0** | yes | yes | sampling | candidate |
| **DeepSeek-OCR** | **MIT** | yes | yes | sampling | candidate |
| Donut | MIT | limited | weak | deterministic | low priority (no OCR-free gain here) |
| Nougat | **CC-BY-NC-4.0** | — | yes | — | **blocked** |
| Surya rec2 | **CC-BY-NC-SA-4.0** | yes | **yes (best measured)** | **non-deterministic** | **blocked** |
| Marker | modified RAIL-M | yes | yes | non-det | blocked |
| LayoutLMv3 | weights **CC-BY-NC-SA** | — | yes | det | **blocked** |
| DocLayout-YOLO | code **AGPL-3.0** | — | yes | det | **blocked** |
| MinerU | **AGPL-3.0** | yes | yes | — | **blocked** |
| Nanonets-OCR-s / MonkeyOCR / dots.ocr | **card states none** | ? | ? | ? | unresolved |
| Azure DI / Google Doc AI / AWS Textract / Mistral OCR | commercial API | **yes** | **yes** | versioned | **viable, data-residency question** |

**One correction to the earlier survey.** [DOCUMENT_LAYOUT_SURVEY.md](DOCUMENT_LAYOUT_SURVEY.md)
recorded Surya's weights as "modified AI Pubs Open RAIL-M" from the repository `LICENSE`. The
`vikp/surya_rec2` model card states **CC-BY-NC-SA-4.0**. Both are non-commercial and the practical
verdict is unchanged, but the two sources disagree, and a licence that cannot be pinned is itself a
reason to stay away.

**The material new fact: `microsoft/trocr-base-handwritten` is MIT.** The layout survey concluded
that the real blocker was "a handwriting-capable recogniser under a permissive licence" — the gap
between TATR's correct cell boundaries and a value nobody could read. That model exists, is MIT, and
is 210k downloads/month. It should be the first thing benchmarked when a handwritten corpus exists.

### 6.3 The gateway

```text
                    ┌──────────────── document class router (deterministic) ────────────────┐
 XLSX / CSV ────────┤ native cell read                → cell provenance                    │
 PDF w/ text layer ─┤ pdftext / pdf_boq               → span provenance                     │
 Printed scan ──────┤ RapidOCR (Apache-2.0)           → page provenance                     │
 Typed table ───────┤ TATR / Docling / PP-Structure   → row+cell provenance                 │
 Handwritten table ─┤ TrOCR / VLM lane                → cell provenance + LOW confidence    │
 Photograph ────────┤ deskew/dewarp, then as above    → page provenance                     │
                    └──────────────────────────────────┬───────────────────────────────────┘
                                                       ▼
                              deterministic validation (row_arithmetic, bill_total)
                                                       ▼
                              EXACT / CONSISTENT / REVIEW  +  engine, version, bounds
                                                       ▼
                                   human review when uncertain
```

Four invariants the gateway must enforce, and they are the actual product:

1. **Routing is deterministic.** Document class decides the engine. A model never decides which
   model runs.
2. **Every engine records `name`, `version`, page and bounds** on every fact derived from it. Facts
   from different engines must be distinguishable forever.
3. **No engine's output becomes a money fact on the engine's own confidence.** It becomes a money
   fact only when deterministic validation closes (`row_arithmetic`) or a human accepts it.
   Otherwise `REVIEW` / `INCONCLUSIVE`. This is the requirement: *never turn uncertain document
   reading into a confident financial finding.*
4. **Swapping an engine changes no verification code.** The test is a one-line registration.

Non-goals, explicitly: no in-house OCR model, no fine-tuning, no OCR research. Aedifex owns the
**trust boundary**, not the recogniser.

### 6.4 Fine-tuning gate

Per the owner's four conditions, all four must hold. Today **zero** hold: there is no labelled
representative set, no repeated observed failure on target documents, no demonstration that
off-the-shelf permissive models fail, and no user workflow measurably affected. Revisit only after
Layer 2 acquisition, and then evaluate **specialised models per document class** rather than one
universal OCR.

### 6.5 The question that must be answered before any OCR work

**Is handwriting actually common in the target workflow?** Every handwriting conclusion in this
repository comes from *one* 2001 highway contract. §3.12 predicts the answer is: **priced BOQs and RA
bills are typed; the JMR behind them is often handwritten and photographed.** If that holds, the
handwriting lane matters at stage 4 and nowhere else — a much narrower problem than "OCR for
construction". **Do not build the handwriting lane until a real building corpus settles this.**

---

## 7. Deliverable 6 — acquisition roadmap, product-driven

Ordered by product value, not by ease. Each step names the user problem it unblocks.

| # | Step | Unblocks | Effort | Depends on |
| --- | --- | --- | --- | --- |
| **1** | **Indian network egress** (VPS/VPN or a person) | MahaRERA, Karnataka/Telangana/Gujarat RERA, Odisha PPMS, MES, UP/Maha PWD — i.e. stages 4,5,6,7 | one decision | **owner** |
| **2** | Harvest IIT Kanpur IWD: BOQ spreadsheets + contract documents | Contract + Work Item at scale, structured. Rules with both sides sourced | days | source review |
| **3** | Acquire **CPWD DSR** (Civil + E&M) | applied-rate vs scheduled-rate rule — the first rule a QS persona cares about | hours | CPWD terms review (source is `unverified`) |
| **4** | RERA pilot: one state, 10 projects, Form 1/2/3 + QPR | Certification + Payment on **private residential** projects; audit & finance personas | days | step 1 for big states |
| **5** | Define the workflow-B product surfaces against Layer 1 | project workspace → findings → evidence → review | weeks | steps 2–3 |
| **6** | US public-record building project (1 district, full packet) | G702/G703 pay applications, change orders — stages 5,6,8 | days | none |
| **7** | Benchmark Docling + PP-Structure + TrOCR on the **real building** corpus | settles §6.5 and the table question | days | steps 2,4 |
| **8** | Design-partner conversation for one sanitised real project | stages 4,5,8 + PO/GRN/MRS — the only route | ongoing | **owner** |
| **9** | Labour Bureau CPI-IW by centre | completes the price-adjustment clause already in the corpus | hours | — |
| **10** | Photograph pre-processing (deskew/dewarp) | the real customer input per §3.12 | later | step 8 |

**Steps 1 and 8 are owner decisions and they gate more value than all the engineering combined.**

---

## 8. What was not done, and what would change these conclusions

- **No documents were acquired.** Two HTML listing pages (IITK tender hall, IITB tender list) and one
  400-byte probe were fetched.
- **Reachability is from one US network on one day.** Re-measure from India before concluding a source
  is unusable.
- **US public-record building projects (#89/#90) are the weakest-evidenced high-value claim** here,
  marked [?]. One district's board packet would confirm or kill it, and it is the cheapest way to
  reach stages 5–8 without Indian egress.
- **The licence field of a model card is not a licence review.** Four models state no licence at all
  and must not be adopted on download counts.
- If a design partner appears, **most of this document stops mattering** — a single real project
  bundle beats every public source listed, and the roadmap should collapse to steps 5 and 10.
