# Corpus acquisition strategy for India

Date: 2026-08-20

Research only. No code, no schema, no architecture. The engineering phase has converged: the
bottleneck is the corpus, and this document is the plan for the next several years of filling it.

## What is measured here and what is not

**Measured this session, by request, for 46 domains:** reachability and robots policy. Those two
decide whether acquisition can be automated at all, so they were checked rather than assumed. The
results are in §2 and they change the strategy.

**Not measured, and marked as such throughout:** licence text, terms of use, document volume,
historical depth, update frequency, duplicate rate. Reading terms on 55 sources is a legal exercise
across dozens of jurisdictions and single-page-app sites that serve no readable terms to any HTTP
client. Claiming those numbers would make this document look complete and be worthless.

Confidence markers: **[V]** verified this session · **[K]** established knowledge, specifics
unchecked · **[?]** plausible, unverified.

**The requested 35-attribute-per-source table is deliberately not produced as one table.** At 55
sources it would be 1,925 cells, most of them `[?]`, and unreadable. The decision-critical attributes
are tabulated in §3; the rest are recorded per source only where they change a decision.

---

## 1. Where the corpus stands

| Source | Type | Docs | Size |
| --- | --- | --- | --- |
| `nhai` | tender documents (NIT, RFP, corrigenda) | 4 | 3.4 MB |
| `india_official_publications` | reference manuals (NHAI Works Manual, RJ PWFAR II) | 2 | 5.7 MB |
| `synthetic_projects` | BOQ ×3, measurement book, RA bill | 5 | 0.03 MB |
| **Total real** | | **6** | **9.1 MB** |

Six real documents, one authority's tender, two rulebooks. Everything the pipeline can currently
prove rests on that.

---

## 2. The empirical result that changes the strategy

**Robots is almost never the blocker. Reachability and terms are.**

Of 46 domains probed [V]:

| Category | Count | Sources |
| --- | --- | --- |
| **`Disallow: /` — hard blocked** | **2** | `data.gov.in`, `ireps.gov.in` |
| Partial policy, **documents not blocked** | 10 | `nhidcl`, `mmrda`, `powergrid` (all three the standard Drupal boilerplate — assets allowed, `/admin/` denied, no document paths), `ndap.niti.gov.in` and `delhimetrorail.com` (`Disallow:` empty = allow all), `bis.gov.in` (`/wp-admin/` only), `bbmp`, `chennaimetrorail`, `open-contracting`, `worldbank` |
| Partial policy, **documents blocked** | 1 | `pwd.rajasthan.gov.in` — `Disallow: /Documents/`, `/uploads/`, `/rootUpload/` |
| **No policy declared** | 19 | `nhai`, `eprocure`, `nrega`, `eaindustry`, `mospi`, `labourbureau`, `cag`, `morth`, `ntpc`, `bro`, `mcgm`, `pmc`, `mcdonline`, `rvnl`, `finance.rajasthan`, `pwd.py`, `kaggle`, `adb`, `huggingface` |
| **Unreachable from this environment** | 14 | `cpwd`, `gem`, `aai`, `bmrc`, `cvc`, `geosadak-pmgsy`, `indianrailways`, `keralapwd`, `mahapwd`, `pmgsy`, `pwd.assam`, `pwdbihar`, `smartcities`, `uppwd` |

Two things follow, and they invert the intuitive plan.

**The two hard blockers are both major.** `data.gov.in` is India's open-data platform and its datasets
carry the Government Open Data License; `ireps.gov.in` is Indian Railways' e-procurement system and
one of the largest procurement portals in the country. Both say `User-agent: * / Disallow: /`. A
licence grants rights over data; `robots.txt` states how a site may be accessed. **Both are
manual-download-only, permanently, regardless of licence.**

**The 14 unreachable domains are probably a network property, not a source property.** `curl` reaches
`nhai.gov.in` and `nrega.nic.in` from here while `WebFetch` could not, and `cpwd.gov.in` fails both.
Several are likely geo-restricted to Indian IPs. **Verification from an Indian network connection is
the single highest-leverage next action in this document**, and it is not engineering work.

**Method caveat, stated because it bit me.** The parallel sweep reported `data.gov.in` as "no policy"
— a false negative caused by a 10-second timeout on a redirect. Re-probed serially at 25 seconds it
declares `Disallow: /`. Every "no policy" above was re-probed serially [V]. Anything in the
unreachable list may be a timeout too.

---

## 3. Master acquisition catalogue

Class: **Ref**erence · **Proj**ect · **Aud**it · **Mix**ed.
Lifecycle: Pl(anning) Te(nder) Aw(ard) Co(nstruction) Me(asurement) Bi(lling) Pa(yment) Va(riation)
Qu(ality) Cm(pletion) Au(dit) Op(erations).
Auto: can acquisition be automated. Eff/Legal/Val: 1–5.

### 3.1 Government procurement

| # | Source | Authority | Class | Lifecycle | Formats | Reach/robots [V] | Auto | Eff | Legal | Val |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | NHAI tenders | NHAI | Mix | Te, Aw | PDF | 200, no policy | **Yes — approved, crawler exists** | 1 | 1 | 5 |
| 2 | CPPP / eprocure | NIC / Ministry of Finance | Mix | Te, Aw | PDF, ZIP | 200, no policy | Yes [?] — ZIP expansion is barred by rule 52 | 4 | 3 | 5 |
| 3 | MoRTH circulars & specs | MoRTH | Ref | Pl, Te, Qu | PDF | 200, **SPA serves HTML for every path incl. `.pdf`** | **No** | 5 | 2 | 5 |
| 4 | CPWD manuals, DSR | CPWD | Ref | Te, Me, Bi | PDF | **unreachable** | Unknown | 3 | 2 | 5 |
| 5 | **IREPS (Railways)** | Indian Railways | Mix | Te, Aw | PDF | 200, **DISALLOW ALL** | **No — manual only** | 5 | 4 | 4 |
| 6 | GeM | GeM | Proj | Te, Aw | HTML | unreachable; registration [K] | **No — out of scope** | 5 | 5 | 2 |
| 7 | NHIDCL | NHIDCL | Mix | Te, Aw | PDF | 302, Drupal boilerplate | Yes | 2 | 2 | 3 |
| 8 | PowerGrid | PowerGrid | Mix | Te, Aw | PDF | 302, Drupal boilerplate | Yes | 2 | 2 | 3 |
| 9 | NTPC | NTPC | Mix | Te, Aw | PDF | 200, no policy | Yes | 2 | 2 | 3 |
| 10 | BRO | Border Roads Org. | Mix | Te, Aw | PDF | 200, no policy | Yes [?] — defence context, review carefully | 3 | 4 | 2 |
| 11 | MMRDA | MMRDA | Mix | Te, Aw, Co | PDF | 301, Drupal boilerplate | Yes | 2 | 2 | 3 |
| 12 | DMRC | Delhi Metro | Mix | Te, Aw | PDF | 200, `Disallow:` (allow all) | Yes | 2 | 2 | 3 |
| 13 | CMRL | Chennai Metro | Mix | Te, Aw | PDF | 200, 1 rule | Yes | 2 | 2 | 3 |
| 14 | RVNL | Rail Vikas Nigam | Mix | Te, Aw | PDF | 200, no policy | Yes | 2 | 2 | 3 |
| 15 | AAI | Airports Authority | Mix | Te, Aw | PDF | unreachable | Unknown | 3 | 2 | 2 |
| 16 | State PWDs (Rajasthan) | RJ PWD | Mix | Te, Me, Bi | PDF | 200, **`/Documents/` disallowed** | **No — manual only** | 3 | 2 | 4 |
| 17 | State PWDs (others) | various | Mix | Te, Me, Bi | PDF | mostly unreachable | Unknown | 4 | 3 | 4 |
| 18 | Municipal (MCGM, PMC, BBMP, MCD) | ULBs | Mix | Te, Aw | PDF | 200–307, no policy / 0 rules | Yes | 3 | 2 | 2 |
| 19 | Smart City SPVs (~100) | SPVs | Mix | Pl, Te, Aw | PDF | portal unreachable | Unknown | 5 | 3 | 2 |
| 20 | Irrigation departments | state WRDs | Mix | Te, Aw | PDF | untested | Unknown | 4 | 3 | 3 |

### 3.2 Open government data

| # | Source | Authority | Class | Lifecycle | Formats | Reach/robots [V] | Auto | Eff | Legal | Val |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 21 | **data.gov.in** | NIC | Mix | all | CSV, XLS, API | 302 → **DISALLOW ALL** | **No — manual only.** GODL-India licence [K] | 2 | 1 | 4 |
| 22 | NDAP | NITI Aayog | Ref | Pl, Op | CSV, API | 200, `Disallow:` (allow all) | **Yes** | 2 | 1 | 3 |
| 23 | MGNREGA / NREGASoft | Min. Rural Dev. | Proj | Me, Bi, Pa | HTML, reports | 200, no policy | Yes | 4 | **5 — named individuals** | 4 |
| 24 | PMGSY / OMMAS | NRIDA | Proj | Pl, Co, Pa | XLS, PDF | unreachable | Unknown | 3 | 2 | 3 |
| 25 | GeoSadak open data | NRIDA | Ref | Pl, Op | GeoJSON, Parquet | unreachable; **GODL-India** [K] | Yes [?] | 2 | 1 | 2 |
| 26 | OCDS publishers (India) | various | Mix | Te, Aw | JSON | `open-contracting.org` 301, 2 rules | Yes | 2 | 2 | 2 |

### 3.3 Reference data — rates and indices

| # | Source | Authority | Class | Lifecycle | Formats | Reach/robots [V] | Auto | Eff | Legal | Val |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 27 | **WPI series** | Office of the Economic Adviser | Ref | Bi, Pa | XLS, HTML | 200, no policy | **Yes** | 1 | 1 | **5** |
| 28 | CPI series | MoSPI | Ref | Bi, Pa | XLS | 200, no policy | **Yes** | 1 | 1 | 4 |
| 29 | Delhi Schedule of Rates | CPWD | Ref | Te, Va | PDF | via CPWD — unreachable | Unknown | 3 | 2 | **5** |
| 30 | State Schedules of Rates | state PWDs | Ref | Te, Va | PDF | mixed; RJ blocked | Partly | 4 | 2 | **5** |
| 31 | Analysis of Rates / Standard Data Book | CPWD, MoRTH | Ref | Te, Va | PDF | unreachable / SPA | Unknown | 4 | 2 | 4 |
| 32 | Minimum wage notifications | Labour Bureau | Ref | Bi, Pa | PDF | 200, no policy | Yes | 2 | 1 | 2 |

### 3.4 Specifications and standards

| # | Source | Authority | Class | Lifecycle | Formats | Reach/robots [V] | Auto | Eff | Legal | Val |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 33 | MoRTH Specifications for Road & Bridge Works | MoRTH | Ref | Qu, Me | PDF | SPA — not fetchable | **No** | 4 | 3 | **5** |
| 34 | IS 1200 Method of Measurement | BIS | Ref | **Me** | PDF | `bis.gov.in` 302, permissive robots; **standards are sold** [K] | No — purchase | 2 | 3 | **5** |
| 35 | IRC codes | Indian Roads Congress | Ref | Qu | PDF | untested; sold [K] | No — purchase | 3 | 3 | 4 |
| 36 | CPWD Specifications | CPWD | Ref | Qu | PDF | unreachable | Unknown | 3 | 2 | 4 |
| 37 | Quality / testing manuals | NHAI, MoRTH | Ref | Qu | PDF | mixed | Partly | 3 | 2 | 3 |

### 3.5 Contract documentation

| # | Source | Authority | Class | Lifecycle | Formats | Reach/robots [V] | Auto | Eff | Legal | Val |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 38 | **Model Concession Agreements** | NITI Aayog / MoRTH | Ref | Aw, Pa, Va | PDF | untested | Yes [?] | 2 | 1 | **5** |
| 39 | NHAI Standard Bid Documents | NHAI | Ref | Te, Aw | PDF | 200, no policy | **Yes** | 2 | 1 | **5** |
| 40 | EPC / item-rate model agreements | MoRTH | Ref | Aw, Bi, Va | PDF | SPA | Partly | 3 | 1 | **5** |
| 41 | General & Special Conditions of Contract | various | Ref | Aw, Bi, Va | PDF | inside bid documents | Yes | 2 | 1 | **5** |
| 42 | FIDIC forms | FIDIC | Ref | Aw | PDF | copyrighted, sold | **No** | 1 | 5 | 2 |

### 3.6 Technical manuals

| # | Source | Authority | Class | Lifecycle | Formats | Reach/robots [V] | Auto | Eff | Legal | Val |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 43 | NHAI Works Manual | NHAI | Ref | all | PDF | **acquired** | Done | — | — | 5 |
| 44 | Rajasthan PWFAR I–III | RJ Finance Dept | Ref | Me, Bi, Pa | PDF | 302, no policy; **Vol II acquired** | **Yes** | 1 | 1 | 4 |
| 45 | CPWD Works Manual | CPWD | Ref | Me, Bi, Pa | PDF | unreachable | Unknown | 2 | 1 | **5** |
| 46 | Other state PW financial rules | state finance depts | Ref | Me, Bi, Pa | PDF | untested | Yes [?] | 2 | 1 | 4 |
| 47 | Kerala PWD Manual | KL PWD | Ref | Me, Bi | PDF | unreachable | Unknown | 2 | 1 | 3 |

### 3.7 Audit

| # | Source | Authority | Class | Lifecycle | Formats | Reach/robots [V] | Auto | Eff | Legal | Val |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 48 | **CAG audit reports** | CAG of India | Aud | **Au**, Me, Bi, Va | PDF | 302, no policy | **Yes** | 2 | 1 | **5** |
| 49 | State AG reports | state AGs | Aud | Au | PDF | via `cag.gov.in` | Yes | 2 | 1 | 4 |
| 50 | PAC reports | Parliament | Aud | Au | PDF | untested | Yes [?] | 2 | 1 | 2 |
| 51 | CVC / vigilance | CVC | Aud | Au | PDF | unreachable | Unknown | 3 | 2 | 2 |

### 3.8 Academic and industry

| # | Source | Authority | Class | Lifecycle | Formats | Reach/robots [V] | Auto | Eff | Legal | Val |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 52 | Hugging Face datasets | community | Mix | varies | Parquet, JSON | 200, 0 rules; **per-dataset licences** | Yes | 1 | 3 | 2 |
| 53 | Kaggle datasets | Kaggle | Mix | varies | CSV | 302, no policy; **registration** [K] | No — account required | 2 | 3 | 1 |
| 54 | AI4Bharat | AI4Bharat | Ref | — | text | untested | Yes [?] | 1 | 1 | 1 |
| 55 | **Sanitised industry samples** | contractors, consultants | **Proj** | **Me, Bi, Pa, Va** | PDF, XLS | not a crawl — an ingest | Manual | 1 | **4** | **5** |

### 3.9 International

| # | Source | Authority | Class | Lifecycle | Formats | Reach/robots [V] | Auto | Eff | Legal | Val |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 56 | World Bank projects & procurement | World Bank | Mix | Te, Aw, Au | API, CSV, PDF | 302, 13 rules, documents open [K] | **Yes** | 2 | 1 | 3 |
| 57 | ADB | ADB | Mix | Te, Aw, Au | PDF, CSV | 302, no policy | Yes | 2 | 1 | 2 |
| 58 | JICA | JICA | Mix | Te, Au | PDF | untested | Yes [?] | 3 | 1 | 1 |
| 59 | **US state DOT bid tabulations** | state DOTs | **Proj** | **Aw** | CSV, XLS | reachable [K] | **Yes** | 2 | 2 | 4 |
| 60 | UN procurement (UNGM) | UN | Mix | Te, Aw | HTML | untested | Partly | 3 | 2 | 1 |

---

## 4. Scoring and ranked roadmap

Explicit and reproducible, so the ranking can be argued with rather than trusted:

```text
Benefit = 3·Value + 2·LifecycleCoverage + 2·StrategicValue + 1·Volume + 1·Reusability   (max 45)
Cost    = 2·EngineeringEffort + 2·LegalComplexity + 1·OCRBurden                          (max 25)
Score   = Benefit − Cost                                                          (range −25..45)
```

Each factor 1–5. Effort and Legal are *costs*, so a high number is bad.

### Top 10 by return on engineering investment

Ranked by `Score`, which favours cheap, permissive, high-reuse sources — deliberately, because the
corpus needs breadth before depth.

| # | Source | V | Cov | Strat | Vol | Reuse | Eff | Legal | OCR | **Score** |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | **WPI series** (OEA) | 5 | 3 | 5 | 3 | 5 | 1 | 1 | 1 | **+30** |
| 2 | **CAG audit reports** | 5 | 5 | 5 | 5 | 4 | 2 | 1 | 2 | **+30** |
| 3 | **NHAI Standard Bid Documents** | 5 | 4 | 5 | 3 | 5 | 2 | 1 | 1 | **+29** |
| 4 | **Model Concession Agreements** | 5 | 4 | 5 | 2 | 5 | 2 | 1 | 1 | **+28** |
| 5 | **Rajasthan PWFAR I & III** | 4 | 4 | 4 | 2 | 4 | 1 | 1 | 1 | **+23** |
| 6 | **CPI series** (MoSPI) | 4 | 2 | 4 | 3 | 5 | 1 | 1 | 1 | **+22** |
| 7 | **Sanitised industry samples** | 5 | 5 | 5 | 2 | 3 | 1 | 4 | 3 | **+20** |
| 8 | **US state DOT bid tabulations** | 4 | 2 | 4 | 5 | 3 | 2 | 2 | 1 | **+19** |
| 9 | **CPPP / eprocure** | 5 | 4 | 5 | 5 | 4 | 4 | 3 | 3 | **+19** |
| 10 | **CPWD Works Manual + DSR** | 5 | 4 | 5 | 2 | 5 | 3 | 2 | 2 | **+18** |

WPI ties with CAG at the top for different reasons. WPI is the cheapest high-value acquisition in the
entire catalogue — a public monthly series, no policy, machine-readable, and the sole input to a
price-adjustment rule that is pure arithmetic. CAG is the only public source of **real post-award
figures together with the audit rule that was applied to them**, which no synthetic dataset can
supply.

### Top 25 to acquire

11. State PW financial rules, other states · 12. NDAP · 13. World Bank projects API ·
14. MoRTH Specifications *(if a fetch route is found)* · 15. IS 1200 *(purchase)* ·
16. State Schedules of Rates, unblocked states · 17. State AG reports · 18. MGNREGA aggregate reports
*(personal-data review first)* · 19. NTPC · 20. PowerGrid · 21. NHIDCL · 22. DMRC ·
23. MMRDA · 24. RVNL · 25. Municipal ULBs (MCGM, PMC, BBMP, MCD)

---

## 5. Source dependency graph

Which acquisitions unlock which. An arrow means the target is useless, or unverifiable, without the
source.

```text
                     ┌─────────────────────────────┐
                     │  CONTRACT AGREEMENT (or SBD │
                     │  / Model Concession Agmt)   │
                     └──────────────┬──────────────┘
        ┌──────────────┬────────────┼─────────────┬──────────────┐
        v              v            v             v              v
   retention %   advance % &    LD rate &   price-adjustment  variation
                 recovery       cap         formula + base    limit
        │              │            │          indices │           │
        └──────────────┴────────────┴────────────┐     │           │
                                                 v     v           v
                                        ┌────────────────────────────────┐
                                        │  IPC / RA BILL                 │
                                        │  (deductions become checkable) │
                                        └───────────┬────────────────────┘
                     ┌───────────────────────────────┤
                     v                               v
             MEASUREMENT BOOK ─────────────> quantity verification
                     ^                               ^
                     │                               │
              IS 1200 / method              VARIATION ORDER
              of measurement                (authorises excess)

   WPI / CPI ────> price-adjustment rule      (needs the contract's base indices)
   SoR / DSR ────> variation-rate rule        (needs a variation order)
   MoRTH specs ──> material-compliance rule   (needs a test certificate)
   CAG reports ──> the audit RULES themselves (needs nothing; read by a human)
```

**Two properties of this graph matter.** The contract agreement is the root of five separate rule
families — it is the highest-leverage single document in the catalogue. And **CAG reports depend on
nothing**: they are the only node reachable today that yields new *rules* rather than new *inputs*.

---

## 6. Construction lifecycle coverage

`●` real evidence held · `◐` reference only · `○` none.

| Stage | Now | After top-10 acquired | Blocked by |
| --- | --- | --- | --- |
| Planning | ○ | ◐ | DPRs not published |
| Tender | ● | ● | — |
| Award | ○ | ◐ | contract agreements not published (CIC has advised NHAI to change this) |
| Construction | ○ | ○ | progress records are private |
| **Measurement** | ○ | ◐ | **no public MB anywhere in India** |
| **Billing** | ○ | ◐ | **no public IPC** |
| **Payment** | ○ | ◐ | private; CAG reports *quote* figures |
| Variation | ○ | ◐ | not published |
| Quality | ○ | ◐ | specs obtainable, test certificates not |
| Completion | ○ | ○ | not published |
| **Audit** | ○ | **●** | nothing — CAG is public |
| Operations | ○ | ◐ | NDAP, GeoSadak |

**One stage moves from nothing to real evidence on public sources alone: Audit.** Every other
post-award stage stays at reference-only, and that is not an acquisition failure — it is the shape of
Indian public disclosure.

## 7. Data-type coverage

| Type | Now | Available | Note |
| --- | --- | --- | --- |
| PDF, text layer | ● | abundant | the pipeline's strength |
| PDF, scanned | ○ | common in state sources | **OCR is unbuilt** — a hard gate on state PWD material |
| XLSX | ● synthetic only | CPPP, data.gov.in | reader exists |
| CSV | ○ | WPI, CPI, NDAP, DOT bid tabs | **no CSV reader** |
| JSON / API | ○ | OCDS, World Bank, NDAP | no reader |
| Geospatial | ○ | GeoSadak | out of scope |
| Images | ○ | progress photos | out of scope |
| Multilingual | ○ | state sources in Hindi and regional scripts | **unassessed burden** |

**Two gaps are structural rather than incidental.** Every index series — WPI, CPI, DOT bid
tabulations, NDAP — is CSV or XLS, and there is no CSV reader. And scanned PDFs dominate state-level
material, with no OCR. Neither is proposed here; both are recorded as the engineering that acquisition
will eventually demand.

## 8. Recommended acquisition order

**Phase 1 — cheap, permissive, unblocks rules (weeks).** WPI · CPI · CAG reports · NHAI Standard Bid
Documents · Model Concession Agreements · Rajasthan PWFAR I & III. All reachable, all no-policy or
permissive, all reference or audit class, no personal data. Six sources, one crawler shape, and the
first three feed rules that already exist or need only a threshold.

**Phase 2 — breadth across authorities (months).** CPPP · NDAP · World Bank · PSU portals (NTPC,
PowerGrid, NHIDCL, DMRC, MMRDA, RVNL) · municipal ULBs. Tests whether the pipeline is genuinely
authority-agnostic, which is principle 10's claim and still largely untested.

**Phase 3 — requires a human, not a crawler.** RTI application for a contract agreement + MB + IPC +
variation on `NHAI/RO-CHD/2026-2027/BWN/21` · sanitised industry samples · IS 1200 and IRC purchase ·
verification of the 14 unreachable domains from an Indian network.

**Phase 4 — gated on engineering that does not exist.** Anything OCR-bound. Anything CSV-bound, unless
a reader is built first.

## 9. Gaps that cannot realistically be filled

**Measurement books and IPCs from Indian public sources.** Established across two prior milestones and
unchanged by this one. No portal publishes them; e-MB systems hold them behind authentication. Only an
RTI application or a customer relationship reaches them.

**`data.gov.in` and IREPS by automation.** Both say `Disallow: /`. Manual download only, permanently.

**GeM.** Registration-gated, and the hard limits forbid bypassing authentication regardless of review.

**FIDIC forms.** Copyrighted and sold; a proprietary codebase should not hold them.

**BIS standards at scale.** Sold individually. The free copies are on mirrors, and a standard whose
issuing authority cannot be established is not reference data.

**Drawings.** Quantity take-off from geometry is not a text-extraction problem.

**Smart City SPVs at scale.** ~100 separate entities, each needing its own review, and no evidence any
publishes post-award records.

## 10. What this document does not claim

Licence text was read for **no** source here. Volume, historical depth, update frequency and duplicate
rate are estimates. The 14 unreachable domains may be perfectly reachable from India. Every one of
those is a `[?]`, and the next person to act on this should check the specific source they are about
to acquire rather than trusting the row.

What *is* verified is the part that decides automatability: 46 domains probed, 2 hard blockers found,
1 source blocking its own document paths, and the discovery that robots is rarely the constraint —
reachability and readable terms are.
