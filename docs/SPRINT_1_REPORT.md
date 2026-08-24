# Aedifex — Sprint 1 report

**Sprint 1, 24–30 August 2026.** One-week sprint, Monday to Sunday, weekend banded for blockers and
repository hygiene.

**Sprint goal:** get one authentic building bundle in hand, and close the two evidence gaps that need
no bundle.

**Result: PARTIALLY ACHIEVED.** Both evidence gaps are closed and two further defects were found and
fixed on the way. No authentic bundle was obtained, and that is the half that mattered more.

---

## The one-paragraph version

Five of seven sprint items are done. The software now reads 674 priced lines of a real ₹85 crore
building bill instead of 661, and produces the first reviewable finding it has ever produced from a
real building document. Separately, CI turned out to have been failing for ten consecutive commits
while local checks reported clean — found, explained and fixed, and CI is green again. But the
product hypothesis is **no better validated than it was on Monday**, because that depends entirely on
getting one real project's documents, and we did not get one. Four of the ten verification rules have
still never run against a real measurement sheet, because none exists to run against.

---

## 1. Completed

| Ticket | | |
| --- | --- | --- |
| SCRUM-17 | Investigate the unread BOQ rows | **Done** — two defects found and fixed |
| SCRUM-26 | CI red on main since 21 Aug | **Done** — cause found, CI green again |
| SCRUM-20 | GitHub Action major upgrades | **Done** — 8 actions off a 23-day deadline |
| SCRUM-22 | Canonical local object store | **Done** — decided and made hard to get wrong |
| SCRUM-23 | Repository and environment hygiene | **Done** — 5 items, worked individually |

Ten commits, all on `main`, CI green at `bacdbed`.

## 2. Unfinished, and why

| Ticket | | Why |
| --- | --- | --- |
| SCRUM-10 | Acquire an authentic building bundle | **Not an engineering task.** It needs a person to ask a person: a developer, PMC or QS practice willing to share one project's documents. No public source substitutes — see §7 |
| SCRUM-11 | Indian network egress | Investigated and **deliberately not built**. See §6 |

Neither slipped through inattention. SCRUM-10 is the highest-priority item in the whole project and
there was no engineering action available on it; SCRUM-11 was investigated to a conclusion, and the
conclusion was that building anything would be wrong.

## 3. Defects discovered

Six, four of them fixed this sprint.

1. **A bill that states its own total was reported as stating none.** Page 1 of the Hostel 19 priced
   bill reads `Total 854,391,859.40`. The finding said the document states no total — an assertion
   about a document that the document contradicts, which is the worst category of error this system
   can make. Two independent causes.
2. **Four unit spellings were unrecognised** (`RM`, `Pt.`, `pts.`, `sets`), so 13 priced rows worth
   ₹48,56,587.46 were never read.
3. **A unit borrowed a letter from its own description** — `conductorMtr` was read as unit `rMtr`
   instead of `Mtr`. The row was always read; its unit was wrong, which matters because a unit is
   half of what makes two quantities the same claim.
4. **CI had been failing for ten commits while local runs said clean.** `mypy` checks a module that
   imports two packages from an optional extra, and no documented install path includes that extra.
   Anyone who had once installed everything saw green locally.
5. **Rows split across lines are unread** — ₹58,15,059.75 on one bill. Not fixed; see §5.
6. **Rows whose source states no unit at all** — the source document leaves the unit column empty.
   Not fixed; arguably should not be. See §5.

## 4. Defects fixed, and what proves each fix

The proof matters more than the fix, so it is stated for each.

**The bill's own total is now read.** Verified across four real bills: two gained a correct total
(₹85,43,91,859.40 and ₹23,90,10,920.09), a third correctly gained none because it genuinely states
only section subtotals, and the NHAI bill was untouched.

**Thirteen rows recovered, proved by the document's own arithmetic.** The bill's electrical section
states ₹1,19,52,516.44 against 12 rows worth ₹73,34,366.51, and the two rows measured in `RM` are
worth *exactly* the ₹46,18,149.93 difference. Two further sections closed the same way, to the paisa
rather than to a tolerance. That is the difference between a fix and a coverage number.

| Hostel 19 priced bill | Before | After |
| --- | --- | --- |
| Priced rows read | 661 | **674** |
| Value read | ₹84,37,20,212.19 | **₹84,85,76,799.65** |
| Short of the bill's own stated total | −1.2490% | **−0.6806%** |
| Sections reconciling exactly | 31 of 41 | **34 of 41** |

**A test caught the fix trying to invent a row.** Adding `RM` made *"Providing and laying the platform
12 100.00 1200.00"* read as a priced row measured in `rm` — taking the unit from inside the word
"platform" and asserting a quantity and a rate nobody wrote down. The obvious guard then refused 12
*genuine* rows in another bill, where the flattened PDF glues the unit to the description
(`worksKg`, `4885No.`, `conductorMtr`). The final guard refuses the invention and keeps all twelve.
**A missing row is a gap the bill's own total exposes; a fabricated one is money from nothing.**

**CI is green again**, verified in a throwaway environment built exactly as CI builds one:
2,120 tests pass with 10 skipped without the optional extra, 2,130 pass with it. 2,120 + 10 = 2,130.

## 5. New work recorded, not done

Three tickets, each filed with its evidence and left in the backlog rather than added to the sprint.

| | | |
| --- | --- | --- |
| SCRUM-24 | Rows split across lines — ₹58,15,059.75 | The layout exists for this, and is unreachable because these pages head themselves `BOQ` rather than "Bill of Quantities (BOQ)". Making it reachable would run a second parser over pages where 90% of rows are already read correctly, so the real question is how two readers cooperate without counting a row twice. **Over-reading money is worse than under-reading it** |
| SCRUM-25 | Rows with no unit in the source | The document itself leaves the unit column empty. Reading them needs a rule that would fabricate rows elsewhere, and a quantity with no unit is weak evidence anyway |
| SCRUM-26 | The CI failure | Fixed within the sprint |

## 6. Blockers

**SCRUM-10 — one authentic building project bundle.** The only thing standing between this project
and a validated hypothesis. Nothing was substituted for it: no highway document was promoted, no
synthetic bundle generated, no additional public BOQ counted toward it.

**SCRUM-11 — Indian network egress.** Investigated with actual measurements rather than repeating an
earlier claim, and the earlier claim was too broad. DNS resolves for every host tested; what differs
is the TCP connection. Three state portals time out with TLS never negotiated, while
`cpwd.gov.in` and `nhai.gov.in` — both on the central-government network range — answer normally.
So central government is reachable from here and state works and RERA portals are not.

**Recommendation: build nothing.** The smallest solution is to fetch once from a machine already in
India and load the files through the upload path that already exists. A proxy or VPN inside the
software would be permanent infrastructure for one source we have decided we do not currently need.

## 7. Authentic corpus obtained

**None.** The corpus holds exactly the documents it held at the start of the sprint.

The reason is structural rather than a failure of searching, and it is worth stating plainly because
it will not change: **public procurement transparency exists to prove a contract was awarded fairly.
Nothing obliges anyone to publish proof that it was paid correctly.** So bills of quantities are
public and measurement sheets and RA bills essentially never are — three independent research passes
found one public source in the world, in a state portal that is unreachable from here.

A one-page request that can be forwarded to anyone who might help is at
[docs/DATA_REQUEST.md](DATA_REQUEST.md). Its most important line is that the documents must be for
**one project with the same items appearing across them** — four matching documents are worth more
than forty unrelated ones.

## 8. Tests and gates at HEAD (`bacdbed`)

| | |
| --- | --- |
| `ruff`, `black` | clean |
| `mypy --strict` | 148 files, no issues |
| Unit tests | **2,130 passed** |
| Integration tests | **98 passed** |
| Database migrations | no drift; reverse cleanly |
| Traceability audit | passes — every conclusive finding traces to stored bytes |
| Viewer build | `tsc` + `vite build` clean |
| **CI on `main`** | **green** — first green push since 21 August |

## 9. What was learned about the product

**The rules are mostly right and mostly starved.** 254 of 310 findings are `INCONCLUSIVE` and not one
is `FAIL`. That is not a rule quality problem: most of those are the software correctly declining to
judge where the evidence is absent. Six of ten rules cannot be validated at all without post-award
documents.

**A document's own totals are the best available check on our reading of it.** The single most
valuable thing added this sprint was reading the total a bill states for itself. It turned "the
software read some rows" into "the software is 0.68% short of what this document says it contains,
and here is the page" — and it localises the gap to a section, which is what turns a percentage into
a cause. It also means the system detects its own incompleteness, which no accuracy metric does.

**Local green is not green.** Ten commits were reported as passing on the strength of local checks
while CI was red. The lesson is not "run CI" — it is that an environment which is *more* complete
than production hides failures rather than revealing them.

**Honest refusal is a feature and needs to look like one.** `INCONCLUSIVE` means the evidence was
absent, and must never be displayed as a failure. A reviewer facing 254 of them needs to see
"nothing to judge here" and not "254 problems".

## 10. Engineering completed vs product hypothesis validated

These are not the same thing and the distinction is the most important line in this report.

**Engineering completed.** Four defects fixed, two of them in the evidence path and provable against
the documents' own arithmetic. Eight GitHub Actions moved off a 23-day deadline before it hit. CI
restored after ten red commits. Three new tickets filed with evidence. Five sprint items closed.
2,130 + 98 tests green.

**Product hypothesis validated: nothing.** Zero authentic bundles received. The corpus still contains
no measurement sheet, RA bill, variation order, material statement or quality record. Four rules
verify the payment chain — is the claim within what was measured, is the rate the contract rate — and
**none of them has ever seen a real measurement sheet.** The review queue on the only real project
holds one finding.

A productive week of engineering moved the product hypothesis by zero. That is not a criticism of the
week; it is the correct reading of where the constraint is.

## 11. Recommended Sprint 2 scope

Deliberately not pre-populated with engineering work, because the honest input is a bundle.

**If a bundle arrives:** SCRUM-15 (validate the four payment rules against real measurement and RA
bills), then SCRUM-12 and SCRUM-13 together — what a work item's key actually *is* for a composite
bill is a domain question a real bundle answers and one university tender does not.

**If no bundle arrives:** the candidates are SCRUM-24 (₹58 lakh of unread split rows) and SCRUM-14 (a
project-scoped bill-versus-estimate rule, where both figures are already stored ₹4,10,540.99 apart
and nothing compares them). Both are more parser and rule work against public documents — which is
exactly the work that a validated hypothesis would tell us whether to do. **Doing them instead of
getting a bundle would be choosing the available work over the important work.**

The most valuable action in Sprint 2 is not on this list, because it is not engineering: forwarding
[docs/DATA_REQUEST.md](DATA_REQUEST.md) to one person who can say yes.
