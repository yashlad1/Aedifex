# Desk research: what the market says, and how much of it to believe

Date: 2026-08-28. Method: web search and direct fetch. **No interviews.** Nothing here counts
toward the 10/15/30 checkpoints in [CUSTOMER_DISCOVERY.md](CUSTOMER_DISCOVERY.md), and the reason is
in §1.

---

## 1. The forums are closed, which is itself the finding

The plan was to read practitioners complaining in their own words, because an unprompted complaint
outranks anything said in answer to a leading question. That could not be done.

| Source | Result |
| --- | --- |
| `reddit.com` (JSON API and web) | **HTTP 403** |
| `eng-tips.com` | **HTTP 403** |
| `quora.com` | **HTTP 403** |
| `contractortalk.com` | HTTP 200, but US residential remodelling — wrong workflow |

These are technical access controls and were **not** worked around: no spoofed browser agent, no
proxy, no rotation. That is a hard limit in [DATA_SOURCES.md](../../DATA_SOURCES.md) and it holds
whether or not the content would have been useful.

So everything below comes from **vendor marketing, competitor product pages, and academic surveys**.
None of it is a practitioner talking freely. **Desk research cannot substitute for the interviews,
and this attempt is the evidence for that claim rather than an opinion about it.**

---

## 2. The uncomfortable finding: this market is not empty

A crowded field of Indian products already does RA bills and measurement books.

**SuperWise**, **Site Setu**, **Powerplay**, **RDash**, **Onsite**, **Tactive**, **NWAY**,
**ACG Infotech**, **Realx ERP**, **BuilderX Pro**.

SuperWise's own description of the problem is almost exactly the Aedifex thesis:

> "Billing engineers manage measurement records in spreadsheets (Excel files) and summarize the same
> in ERP software for billing. Scattered information across multiple spreadsheets and summary-level
> bills in ERP do not help in identifying manual errors."

And its product "automatically calculates the billing amount ensuring that only unbilled and
**verified** measurements are considered."

**But every one of them sits on the generation side of the workflow, and Aedifex sits on the
verification side.** They help a contractor *produce* a correct RA bill from measurements captured
in their own app. Aedifex reads bills and measurements that already exist, in whatever form they
arrived, and asks whether the claim is supported.

That distinction is either the whole opportunity or a fatal weakness, and desk research cannot tell
which:

- **For Aedifex:** their approach only works if everyone on the project is inside their app. The
  employer, PMC, auditor or lender checking a contractor's bill has no such luxury — the documents
  arrive as PDFs and spreadsheets from someone else's system.
- **Against Aedifex:** if the market's answer to bad bills is "prepare them properly in our app",
  then verification is a smaller, later, harder-to-sell problem, and the buyer is not the contractor.

**This is the single most important question for the interviews to settle**, and it should be asked
directly: *who checks the bill, and do they trust the system it came out of?*

---

## 3. What the evidence actually supports, ranked by quality

### Strongest — peer-reviewed, real methodology

*Responsible Causes of Payment Delays in Indian Construction Industry* — 37 causes, **62 responses**
from contractors, consultants and employers, Importance Index and Principal Component Analysis, plus
semi-structured interviews.

Its top-ranked causes are **finance-related, not verification-related**:

1. Delay in settlement of claims
2. Contractor's financial difficulties
3. **Delay in payment for extra work / variations by owner**
4. Late payment from contractor to subcontractor or suppliers
5. **Variation orders / changes of scope by owner during construction**
6. Changes in design by owner

**Read this honestly. Nobody in that survey said the problem was being unable to tell whether a bill
was correct.** They said they were not paid, and that variations and claims were where it stuck.
Two of the top six are variations.

### Moderate — competitor and consultant content, useful but selling something

From Indian construction-audit and PMC practices, a genuinely specific list of recurring overbilling
patterns:

- Inflated plaster, painting and tiling **areas, with opening deductions misapplied or omitted**
- **Shuttering and formwork double-counted** between structural items

These are concrete, deterministic, checkable, and they are exactly the shape of an Aedifex rule.
They are the best product lead in this document.

Also, on why disputes surface late:

> "Quantity disputes show up only at bill review because there is no clean trail from site execution
> to bill line items."

> "Most billing disputes, payment delays, and margin leakage trace back to poorly prepared RA bills
> or unclear measurement records."

And corroborating the one Reddit reply already recorded as S-01: documentation scattered across
**WhatsApp, Excel and paper registers**.

### Weakest — treat as marketing, do not cite

"85% of the industry tracks finances in Excel", "88% of construction spreadsheets contain errors",
"$178 billion lost annually to spreadsheet mistakes", "$280B in slow payments". These circulate
between vendor blogs without traceable methodology. **They are the kind of number this project
exists to refuse.** Recorded here only so nobody re-finds them and mistakes them for evidence.

---

## 4. Variations keep appearing, from independent directions

| Source | What it said |
| --- | --- |
| The 2026-08-24 repository review | "our real nightmare is variations" named as a likely pivot |
| S-01, the one Reddit reply | Excel and WhatsApp invoice chaos |
| Peer-reviewed survey, n=62 | variations and claims settlement in the top 6 delay causes |
| Competitor and PMC content | "extra work" claims named as a standing dispute source |

Four sources, none of them strong alone, none prompted by us, all pointing at the same neighbourhood:
**work that was not in the original BOQ.**

Aedifex currently has no variation-order evidence, no variation rule, and no variation document in
any corpus tier. The corpus contains zero change orders.

---

## 5. What this changes

**Nothing yet, deliberately.** No rule, no schema and no ticket comes out of this document, because
desk research is not an evidence ID under rule 101. A vendor's landing page is not a real document
and a survey abstract is not an observed workflow.

What it does is sharpen the interview script. Three questions to add:

1. **"Who checks the bill, and do they trust the system it came out of?"** — settles §2, the
   generation-versus-verification question, which decides whether this product has a buyer.
2. **"What happens when work isn't in the BOQ?"** — tests the variation signal that four independent
   sources now point at.
3. **"When a bill is wrong, how do you find out — and how late?"** — tests the "disputes show up only
   at bill review" claim, which is the one place the market content actively supports the Aedifex
   thesis.

---

## Sources

Competitors and vendor content: [SuperWise — RA Bill Certification and Measurement Book
Software](https://superwise.site/professions/construction-billing-engineer) ·
[SuperWise — Measurement Book glossary](https://superwise.site/glossary/measurement-book) ·
[Site Setu — construction billing software](https://sitesetu.app/construction-billing-software) ·
[Site Setu — top 10 construction management software in India](https://sitesetu.in/blog/top-10-construction-management-software-india-2026) ·
[Site Setu — subcontractor management](https://sitesetu.in/blog/subcontractor-management-india) ·
[RDash vs PowerPlay vs Onsite](https://onsiteteams.com/rdash-vs-powerplay-vs-onsite/) ·
[ACG Infotech — RA bill software](https://www.acgil.com/ra-bill-payment-software.html) ·
[Realx ERP](https://realxerp.com/construction-billing-software.php) ·
[BuilderX Pro — RA bills guide](https://www.builderxpro.com/blog/construction-billing-ra-bills-guide)

Audit and PMC practice: [AMs — construction audit process in India](https://amsindia.co.in/construction-audit-process-in-india-steps-benefits-best-practices-2026-guide/) ·
[KRIE India — construction audit and advisory](https://krieindia.com/Auditing) ·
[Mastt — invoice validation](https://www.mastt.com/blogs/invoice-validation)

Academic: [Responsible Causes of Payment Delays in Indian Construction Industry](https://www.researchgate.net/publication/360283538_Responsible_Causes_of_Payment_Delays_in_Indian_Construction_Industry) ·
[Analysis of causes of delay in Indian construction projects and mitigation measures](https://www.emerald.com/insight/content/doi/10.1108/jfmpc-04-2018-0020/full/html) ·
[Delay Analysis of Infrastructure Construction Projects in India](https://link.springer.com/article/10.1007/s40030-025-00899-5)

Marketing statistics, recorded as unreliable: [Autodesk](https://www.autodesk.com/blogs/construction/excel-construction/) ·
[Lentune](https://www.lentune.com/blog/construction-spreadsheets) ·
[eSUB](https://esub.com/blog/replace-excel-with-construction-software)
