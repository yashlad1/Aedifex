# Indian post-award sources — a ranked catalogue

Date: 2026-08-20

## Verdict

**No Indian public authority proactively publishes primary post-award construction records — Measurement
Books, Running Account Bills, IPCs or Variation Orders — as downloadable documents.**

Searched across all eight priority categories. Every system that *holds* those records falls into one
of three shapes, and none of the three is a public document source:

| Shape | Examples | Why it does not yield evidence |
| --- | --- | --- |
| Internal workflow system | State PWD e-MB, CPWD works systems | Digitises the MB for departmental use; no public view |
| Identifier or login-gated lookup | AP CFMS, state IFMS/treasury, e-Pradan | Returns *status* for a bill you already identify; not a corpus |
| Aggregate progress dashboard | OMMAS, GeoSadak, Smart City dashboards | Block/district totals, not per-item measurement or billing |

This is not a gap in searching. It is the same institutional fact recorded in
[CORPUS_ROADMAP.md](CORPUS_ROADMAP.md): **public procurement transparency is designed to prove a
contract was let fairly, not that it was paid correctly.**

**The milestone's question does have an answer.** Aedifex's first real Indian post-award corpus will
come from one of two routes, and they are not equivalent:

1. **MGNREGA / NREGASoft** — post-award records published *by statutory design* rather than by
   discretion, with no login. Different contracting model, so it validates some chains and not others.
2. **An RTI application** — the legally defined route to a contract agreement and its bills, now with
   an explicit Central Information Commission advisory behind it.

Everything else is a substitute, and §5 says exactly what each substitute cannot prove.

---

## 1. Method, and the limits of this research

Searched by category, then attempted direct verification of the load-bearing portals.

**Direct verification largely failed, and the findings below are weaker for it.** Several `.nic.in`
hosts were unreachable from this environment: `online.omms.nic.in` and `omms.nic.in` did not resolve,
`nregastrep.nic.in` reset the connection, and two `nrega.nic.in` paths returned 404. Whether that is
geo-restriction, TLS configuration or transient outage was not established.

**Consequences, stated plainly:**

- Every determination marked **[doc]** rests on documentation, press releases, manuals or audit
  reports *about* a portal, not on inspecting it.
- **No `robots.txt` was successfully read for any Indian portal in this research.** The one attempt
  that resolved — `nrega.nic.in/robots.txt` — returned 404, which means no policy is declared, not
  that crawling is permitted.
- **No terms of use were read.** Every licence cell below says so.

That last point is not a shortfall to be apologised for; it is the boundary of the work.
[DATA_SOURCES.md](../../DATA_SOURCES.md) puts terms, robots, licence and personal-data review in the
hands of a human reviewer, and this document deliberately stops where that judgement begins. **Nothing
here is an approval, and the "can Aedifex ingest it?" column answers "not determined" wherever the
honest answer is not determined.**

Verification from an Indian network connection is the first thing that would materially improve this
catalogue.

---

## 2. The catalogue

Columns as specified. `MB` Measurement Book · `RAB` Running Account Bill · `IPC` interim payment
certificate · `VO` variation order. `—` means not found; `?` means plausible but unverified.

### Priority 1 — State PWD e-MB systems

| | |
| --- | --- |
| **Public?** | The *systems* are not. Departmental circulars announcing them are |
| **Login?** | Yes — contractor and engineer roles |
| MB / RAB / IPC / VO | **Held internally: yes. Publicly exposed: none found** |
| **Downloadable?** | No |
| **Licence / ToU** | Not read |
| **Robots** | Not read |
| **Ingest?** | **No.** A login-gated system is permanently out of scope — DATA_SOURCES.md hard limits forbid bypassing authentication, regardless of review outcome |

Confirmed to exist in at least Puducherry and Tripura, whose PWDs published circulars mandating
computerised measurement books and online bill generation [doc]. Kerala's e-services dashboard exposes
contractor *registration*, not bills [doc].

**This is the most tantalising and least accessible category.** These systems contain exactly the
missing evidence, in structured form, under public authorities — and they are built for departmental
workflow, so nothing points outward. The route in is not technical: it is a department choosing to
disclose, or an RTI application, or a contractor who is a customer exporting their own bills.

**Genuinely valuable and public in this category:** the rulebooks. Kerala PWD Manual, Rajasthan Public
Works Financial & Accounts Rules Vol. II and III, CPWD Works Manual, NHAI Works Manual 2006 [doc].
These define MB and bill structure, measurement procedure, and the deduction rules — reference data
that tells Aedifex what an RA bill contains before it ever sees one.

### Priority 2 — PMGSY / OMMAS

| | |
| --- | --- |
| **Public?** | Partly. Aggregate progress yes; transaction records no |
| **Login?** | Yes for the accounting modules; public reports without |
| MB / RAB / IPC / VO | **—** · **—** · **—** · **—**. OMMAS holds a maintenance-expenditure module and receipt-and-payment booking [doc], but publishes progress, not vouchers |
| **Downloadable?** | Yes for the open datasets: Excel, PDF, and geospatial formats [doc] |
| **Licence / ToU** | **GeoSadak PMGSY Rural Connectivity Datasets are published under the Government Open Data License – India** [doc] — the only clear licence found in this entire research |
| **Robots** | Not read |
| **Ingest?** | **The GODL-India datasets, very likely yes** — subject to reading the licence. The transactional system, no |

The single most encouraging licence position and the wrong granularity. GeoSadak publishes the rural
road network with attributes; the physical-and-financial progress datasets are block- and
district-level allocation and expenditure [doc]. That supports "how much was spent on rural roads in
this district", not "was this quantity measured before it was paid for".

A CAG audit chapter exists specifically on OMMAS [doc] — worth reading as evidence of what the system
holds internally, and as an audit-class document in its own right.

### Priority 3 — CPWD post-award disclosures

| | |
| --- | --- |
| **Public?** | Manuals and rules yes. Works records no |
| **Login?** | For departmental systems, yes |
| MB / RAB / IPC / VO | **—** across all four |
| **Downloadable?** | The CPWD Works Manual, yes |
| **Licence / ToU** | Not read |
| **Robots** | Not read |
| **Ingest?** | Not determined; the Works Manual is a strong reference-data candidate |

CPWD is bound by RTI s.4 proactive disclosure through the 17-point manual [doc], which mandates
budget and expenditure categories — not per-contract billing records. The **CPWD Works Manual** is the
authoritative public definition of Form 23 (Measurement Book) and Form 47 / PW 410 (Running Account
Bill), including the deduction structure. That is reference data of real value.

### Priority 4 — NHAI project records

| | |
| --- | --- |
| **Public?** | Tenders and bid documents yes — **already in the corpus.** Contracts, no |
| **Login?** | No for tender documents; CAPTCHA on search, already recorded |
| MB / RAB / IPC / VO | **—** across all four |
| **Downloadable?** | Tender documents yes, and nine are already stored |
| **Licence / ToU** | Reviewed and recorded for the tender path (ADR 0006) |
| **Robots** | Reviewed for the tender path |
| **Ingest?** | Already approved for tender documents. Post-award: nothing to ingest |

**The most important finding in this category is a regulatory one.** In July 2026 the Central
Information Commission observed that *"NHAI is not placing contract agreement-related information on
their website in the public domain"* and advised NHAI to disclose contract information proactively,
reasoning that contractual agreements directly affect public safety, transparency and accountability
[doc].

Two consequences. It **confirms** that NHAI contract agreements are not currently public — closing off
the highest-value document by the portal route. And it gives an **RTI application for a specific
contract agreement explicit CIC backing**, which changes that route from a long shot to a documented
position. See §4.

NHAI's own **Works Manual 2006** is public [doc]: reference data defining NHAI's measurement and
billing procedure.

### Priority 5 — Smart City portals

| | |
| --- | --- |
| **Public?** | Project lists, tenders, progress narratives |
| **Login?** | No for public pages |
| MB / RAB / IPC / VO | **—** across all four; none found on any SPV portal examined |
| **Downloadable?** | Tenders and DPRs in places |
| **Licence / ToU** | Not read |
| **Robots** | Not read |
| **Ingest?** | Not determined; low expected value |

Each city is a separate SPV — a company under the Companies Act with 50:50 state and ULB equity
[doc] — and works are frequently executed by other government departments rather than the SPV, so
billing records sit with the executing department and not the visible portal. High effort, ~100
separate reviews, and no evidence any of them publishes a bill.

### Priority 6 — Irrigation department portals

| | |
| --- | --- |
| **Public?** | Tenders; some progress reporting |
| **Login?** | Varies |
| MB / RAB / IPC / VO | **—** across all four; nothing found |
| **Downloadable?** | Tenders |
| **Licence / ToU** | Not read |
| **Robots** | Not read |
| **Ingest?** | Not determined |

Searched and found nothing distinguishing this from the state PWD pattern. Worth noting that
irrigation contracts are large, item-rate, and heavily audited, so they appear *in* CAG reports even
where their records do not appear online — which makes them good audit-class material.

### Priority 7 — Municipal corporation engineering departments

| | |
| --- | --- |
| **Public?** | Citizen services and tenders. Works billing, no |
| **Login?** | For contractor-facing functions |
| MB / RAB / IPC / VO | **—** across all four |
| **Downloadable?** | Tenders |
| **Licence / ToU** | Not read |
| **Robots** | Not read |
| **Ingest?** | Not determined; low expected value |

MCGM/BMC — the largest municipal works spender in India — exposes property tax, payments and citizen
services publicly [doc]. No public works-contract billing disclosure was found.

### Priority 8 — RTI proactive disclosures (s.4)

| | |
| --- | --- |
| **Public?** | **Yes, by statute** |
| **Login?** | No |
| MB / RAB / IPC / VO | Depends entirely on the authority. Mandated categories are budget and expenditure, not per-contract records |
| **Downloadable?** | Usually PDF |
| **Licence / ToU** | Government publication; not read |
| **Robots** | Not read |
| **Ingest?** | Not determined, and likely permissive — this is information published because the law compels it |

s.4(1)(b) mandates disclosure through a 17-point manual [doc], and the CIC has conducted transparency
audits of compliance [doc]. Compliance is uneven, and the mandated categories stop short of
transaction records. Its real value is as the **legal foundation for a targeted request** (§4) rather
than as a corpus to harvest.

### Outside the eight — and the strongest single candidate

**MGNREGA / NREGASoft — `nrega.nic.in`**

| | |
| --- | --- |
| **Public?** | **Yes, and by design.** NREGASoft exists in part to publish records "which are hidden from public otherwise", in compliance with the RTI Act [doc] |
| **Login?** | **No.** MIS reports open without an account [doc] |
| **MB** | **?** — measurement entries are recorded in the MB *and* the muster roll [doc], and an MB verification screen is referenced [doc]. Public exposure of per-item MB detail is **unverified** |
| **RAB / IPC** | **—** as such. MGNREGA pays through muster rolls and material vouchers, not RA bills |
| **VO** | **—** |
| **Downloadable?** | Reports are viewable and exportable; ~8 crore muster rolls and 15 years of MIS data are described as freely available [doc] |
| **Licence / ToU** | **Not read.** Must be, before anything is collected |
| **Robots** | `robots.txt` returned 404 — no policy declared, which is not permission |
| **Ingest?** | **Not determined, and the most promising of any Indian source** — subject to review, and to a personal-data decision that is unusually serious here |

**Why it ranks first among public sources.** It is the only Indian system found where post-award
records are public *because a statute requires it* rather than because an authority chose to. Muster
rolls, material vouchers, work-wise expenditure and asset details are published at transaction level.

**Two reasons it is not a complete answer, and they matter.**

*It is a different contracting model.* MGNREGA work is largely executed departmentally with labour
paid through muster rolls. There is often no contractor, no priced BOQ, no RA bill and no variation
order — contractors are restricted under the Act. So it can populate the **quantity** chain and part of
the **money** chain, and it cannot populate the rate or deduction structure that the existing payment
rules were written for. It validates the pipeline; it does not validate item-rate contract
verification.

*The personal-data exposure is the most serious of any source here.* Muster rolls are named
individuals with wage payments and job-card numbers. `contains_personal_data: true` is not a checkbox
in this case — it is a reason to consider whether aggregate reports suffice and named records are
never stored at all.

**Other systems examined and rejected:** AP CFMS and state IFMS/treasury portals return the status of
a bill whose identifier you already hold, aimed at the employee or contractor concerned [doc], not a
public register. That is a lookup, not a corpus.

---

## 3. Ranked shortlist

Ranked by *evidence obtained per unit of legal and operational effort*, and each is a candidate for
review, not a decision.

| Rank | Source | Class | What it yields | Blocker |
| --- | --- | --- | --- | --- |
| **1** | **MGNREGA / NREGASoft** | Project (primary) | Transaction-level muster rolls, material vouchers, work-wise expenditure; possibly MB detail | Terms unread; **serious personal data**; different contracting model |
| **2** | **RTI application** for one contract agreement + its bills | Project (primary) | **The exact bundle the CIM ranks first** — contract, MB, IPC, variation, for one contract | Time (30-day statutory reply, appealable); needs a specific contract chosen |
| **3** | **CAG / AG audit reports** | Audit (secondary) | Real contracted/measured/paid figures **and the rules auditors apply** | May never be cited as a measurement |
| **4** | **Reference manuals** — CPWD Works Manual, NHAI Works Manual, Kerala PWD Manual, Rajasthan PWFAR | Reference | Authoritative structure of MB and RA bill; measurement and deduction rules | None known. Government publications, terms unread |
| **5** | **State Schedules of Rates** | Reference | Sanctioned rate per standard item with effective dates | Terms unread; some states sell rather than publish |
| **6** | **GeoSadak / PMGSY open datasets** | Project (aggregate) | District and block progress and expenditure, road network | **GODL-India licence — the clearest position found.** Wrong granularity |
| **7** | State PWD e-MB systems | Project (primary) | Everything needed | **Login. Permanently out of scope unless a department or a customer opens it** |

---

## 4. The RTI route, stated concretely

Rank 2 deserves its own section because it is the only route to the document the
[Construction Information Model](CONSTRUCTION_INFORMATION_MODEL.md) ranks first, and because it is now
better founded than it was a month ago.

The CIC's July 2026 advisory to NHAI [doc] establishes that a public authority's contract agreements
are information the Commission considers should be proactively disclosed. An application therefore
asks for something a Commission has already said belongs in the public domain, rather than testing an
open question.

**The natural target is a contract Aedifex already holds the tender for.** Nine NHAI documents are in
immutable storage, two tenders are identified — `NHAI/RO-CHD/2026-2027/BWN/21` and
`NHAI/RO-CHD/2026-2027/JAL/22` — and one of them has a fully read 37-item priced BOQ totalling
₹8,46,49,969.01. A contract agreement, one measurement book, the corresponding IPC and any variation
order **for that same contract** would give a single provenance chain covering four of the six
verification domains, against a BOQ already extracted and reconciled.

That is not an engineering task and cannot be done by writing code. It needs an applicant, a fee, and
a decision about which contract to name. **This is the specific ask that unblocks the roadmap.**

---

## 5. What is missing, precisely

Against the four chains in the [Construction Information Model](CONSTRUCTION_INFORMATION_MODEL.md) §1
— what each candidate can and cannot prove.

| Chain | Link | Obtainable from public Indian sources? |
| --- | --- | --- |
| Quantity | contracted quantity | ✅ Already held — real priced BOQ |
| | **measured quantity** | ⚠️ MGNREGA only, and for departmental rural works. **Not for item-rate contracts** |
| | **certified quantity** | ❌ Nothing public. RTI or customer only |
| | authorisation above contract | ❌ Variation orders are not published anywhere found |
| Rate | agreed rate | ✅ Already held |
| | **applied rate** | ❌ Requires an IPC |
| | sanctioned baseline | ✅ **Schedule of Rates is publishable** — acquirable now |
| | escalation indices | ✅ WPI and CPI are public monthly series |
| Money | gross claim, deductions, net | ❌ **Nothing.** Requires an IPC |
| | retention %, advance %, LD, escalation formula | ❌ **Nothing.** Requires the contract agreement — and CIC has confirmed NHAI does not publish it |
| Time | appointed date, EoT, completion | ❌ Nothing public found |
| Quality | specification thresholds | ✅ MoRTH, IRC, IS codes are published |
| | test values, inspection approvals | ❌ Nothing public |

**The pattern is exact and worth stating as a rule of thumb: every link that is a *standard* is
publicly obtainable, and every link that is a *transaction* is not.** Reference data is public because
it governs everyone; project data is private because it concerns two parties. Which is precisely the
axis the architecture was reorganised around, arrived at independently from the other direction.

**So the immediately actionable acquisition is reference data** — Schedules of Rates, MoRTH
specifications, IS 1200, price indices, and the works manuals. That is real, licence-plausible,
non-blocked work that populates three chain links and creates the first genuine test of ADR 0014's
applicability model. It does not validate a single payment rule, and it should not be mistaken for
progress on that front.

---

## 6. Recommendation

**Two tracks, and only one of them is mine to run.**

**Yours:** file one RTI application for a contract agreement, measurement book, IPC and variation
order on a named NHAI contract — ideally `NHAI/RO-CHD/2026-2027/BWN/21`, whose priced BOQ is already
extracted and reconciled. The CIC advisory is the strongest supporting position available, and a
30-day statutory clock beats an indefinite search.

**Mine, pending your approval of the sources:** review MGNREGA's terms and personal-data position
before touching it; and acquire reference data — a state Schedule of Rates, MoRTH specifications,
IS 1200, and the WPI/CPI series — which unblocks the rate and quality chains without waiting for
anyone.

**Neither track is code.** The milestone's question is answered: the first real Indian post-award
corpus comes from MGNREGA if a different contracting model is acceptable, and from an RTI application
if it is not.

## Sources

- [MGNREGA / NREGASoft portal](https://nrega.nic.in)
- [NREGASoft releases](https://nrega.dord.gov.in/NREGASoft_update.aspx)
- [MGNREGA e-FMS manual](https://mgnrega.cg.nic.in/TrainingMaterials/eFMS_Manual_ritesh_V5_10may2012.pdf)
- [PMGSY / NRIDA](https://pmgsy.nic.in/node/26)
- [OMMAS maintenance-fund receipt and expenditure booking](https://pmgsy.nic.in/booking-receipt-expenditure-incurred-maintenance-fund-ommas-rp-module)
- [OMMAS, DMEO/NITI Aayog description](https://dmeo.gov.in/index.php/node/437)
- [CAG audit chapter on OMMAS](https://cag.gov.in/uploads/download_audit_report/2016/Chapter_8_Online_Management,_Monitoring_and_Accounting_System.pdf)
- [GeoSadak PMGSY open data](https://geosadak-pmgsy.nic.in/OpenData)
- [PMGSY datasets on data.gov.in](https://www.data.gov.in/keywords/pmgsy)
- [CIC advises NHAI to disclose contract information](https://www.business-standard.com/economy/news/cic-advises-nhai-to-proactively-disclose-contracts-info-in-public-domain-126070200875_1.html)
- [NHAI Works Manual 2006](https://nhai.gov.in/nhai/sites/default/files/2023-06/NHAI_Works_Manual_2006.pdf)
- [CPWD Works Manual](https://www.cpwd.gov.in/Publication/manualvolume2.pdf)
- [Kerala PWD Manual](http://keralapwd.gov.in/keralapwd/eknowledge/Upload/manuals/1153.pdf)
- [Rajasthan Public Works Financial & Accounts Rules, Vol. II](https://finance.rajasthan.gov.in/docs/rules/pwfar/vol-II.pdf)
- [Rajasthan Public Works Financial & Accounts Rules, Vol. III](https://finance.rajasthan.gov.in/docs/rules/pwfar/vol-III.pdf)
- [Puducherry PWD computerised measurement book](https://pwd.py.gov.in/computerized-measurement-book-and-bills-be-submitted-contractor)
- [Tripura PWD e-MB implementation](https://pwd.tripura.gov.in/index.php/government/circulars/32-circulars/works/716-implementation-of-e-mb-electronic-measurement-book-and-generation-of-online-bill)
- [CIC transparency audit of s.4 disclosures](https://cic.gov.in/sites/default/files/Transparency%20Audit%20of%20Disclosures%20Under%20Section%204%20of%20the%20RTI%20Act%20by%20the%20Public%20authorities.pdf)
- [Smart Cities Mission implementation and SPV structure](https://smartcities.gov.in/implementation)
- [MCGM / BMC citizen portal](https://portal.mcgm.gov.in/irj/portal/anonymous/qlOnPayment?guest_user=english)
- [AP CFMS](https://cfms.ap.gov.in)
