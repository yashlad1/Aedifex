# 19. A synthetic benchmark corpus, quarantined as Tier 5, and the lifting of the engineering freeze

Date: 2026-08-30

## Status

Accepted. **Amends [rule 101](../../AEDIFEX-RULES.md) and supersedes the freeze clause of
[the Reality Sprint](../plans/2026-08-24-reality-sprint.md)**, whose targets it keeps. Nothing in the
SRS changes, and §18a gains a fifth tier rather than losing any of the four.

## Context: the freeze was correct, and it stopped working

On 2026-08-24 engineering was frozen behind an evidence ID. The premise was explicit and it was
right:

> The platform is sufficiently complete for the next experiment. Writing more code is now likely to
> **reduce** learning efficiency.

That premise carries a hidden condition. Writing code reduces learning *only if the learning
activity is actually happening in its place*. Six days on, the record is:

| | 2026-08-24 | 2026-08-30 |
| --- | --- | --- |
| Interviews in [CUSTOMER_DISCOVERY.md](../research/CUSTOMER_DISCOVERY.md) | 0 | **0** |
| Authentic RA bills in any tier | 0 | **0** |
| Authentic measurement books in any tier | 0 | **0** |
| External signals | 0 | 2, neither an interview |

The outreach was tried and the conversion is measured, not assumed: **333 views, 1 substantive
reply — 0.3%** (S-01). The practitioner forums that were to supply unprompted complaints return 403
and were not worked around. Reddit's official API route was tested and is shut.

So the freeze has not been trading engineering for market evidence. It has been trading engineering
for nothing, and the only work its exceptions permit is defect repair. That is a worse position than
either alternative, and it is the position that prompted the owner's instruction to lift it.

**The freeze is not being repudiated. Its condition failed.** If interviews start converting, the
argument for re-imposing it returns intact.

## The second reason, which is the stronger one

A cold request for fifteen minutes asks a stranger to spend their time establishing whether you are
worth talking to. A working demonstration inverts that: it shows the workflow first and asks whether
it is recognisable. The question `CUSTOMER_DISCOVERY.md` already names as the one that matters —
**"show me how you checked the last bill"** — is far easier to reach from *"here is a bill with a
₹4 lakh unsupported claim in it, does this look like yours?"* than from *"can I have fifteen
minutes?"*.

The product cannot currently do that demonstration. On the strongest real Tier 1 material available,
[REAL_CORPUS_RULE_VALIDATION.md](../research/REAL_CORPUS_RULE_VALIDATION.md) measured **82%
`INCONCLUSIVE`, 0 `FAIL`, and four of ten rules that have never executed at all**. Not because the
rules are wrong — because verification compares two adjacent links of a chain and the corpus has
never contained both ends of any link.

So the corpus gap is simultaneously blocking the engineering *and* blocking the outreach that was
supposed to close the corpus gap. Something has to break the cycle, and only one end of it is under
our control.

## Decision

**1. The freeze is lifted, and replaced by a narrower rule** — see rule 101 as amended and the new
rule 102. Evidence IDs still gate work on the *real* corpus. What is now additionally admissible is
work whose evidence ID is a **Tier 5 synthetic document**, under the quarantine below.

**2. A fifth corpus tier is created: the Synthetic Benchmark Corpus.** SRS §18a gains:

| Tier | Name | Contents | Purpose |
| --- | --- | --- | --- |
| **5** | **Synthetic benchmark** | Generated building-project bundles with planted, documented defects | **Executability and regression only.** It proves a rule *runs* and *is specific*. It never proves a rule is *right about real documents* |

**3. The bundle is generated, not authored.** A generator with a written specification, reproducible
byte-for-byte, so the corpus is a function of its spec rather than a pile of files somebody edited
until the tests passed.

## The quarantine, which is the whole of the safety argument

Synthetic evidence is the most dangerous material this project has ever created, because it is
indistinguishable from progress. Five constraints, each of which exists to stop a specific failure:

1. **Tier 5 never mixes with Tiers 1–4.** Separate directory, `SYNTHETIC` in every filename, a
   banner row in every sheet and a banner on every rendered page. A reader who encounters one of
   these files out of context must be unable to mistake it for a real document.
2. **A Tier 5 document may make a rule *executable*. It may never make a rule *correct*.** The
   distinction is the point of the tier. That `claim_within_measured_quantity` produces a `REVIEW`
   on planted row 6.2.3 proves the rule runs and cites the right cells. It proves nothing whatsoever
   about whether real billing engineers over-claim that way.
3. **Ground truth is written before generation and the pipeline never reads it.** The defect
   specification is the input to the generator and the *comparison* for the run, never an input to
   extraction, classification, calculation or verification. Scoring is a separate pass over stored
   findings.
4. **Clean rows are mandatory and are the real test.** A benchmark of nothing but defects measures
   recall and hides false positives. The majority of items carry no defect, and **the false-positive
   count is reported with equal prominence to the detection count.** A run that finds all twelve
   planted defects and also flags forty clean rows has failed.
5. **No synthetic finding leaves this repository without the word synthetic attached.** Not in a
   demo, not in a deck, not in an outreach message. Stating a detection rate from Tier 5 as though
   it were a product accuracy figure would be the exact species of unsourced number
   [MARKET_AND_COMPETITOR_SIGNALS.md §3](../research/MARKET_AND_COMPETITOR_SIGNALS.md) records as
   the kind this project exists to refuse.

## What the bundle must contain, and why those things

Two classes of defect, deliberately mixed.

**Mechanical**, to make the four dead rules execute: over-claim against measured quantity, claimed
rate departing from contract rate, a cumulative claim regressing below what was previously
certified, and two documents making conflicting statements about one item.

**Real audit patterns**, taken from the overbilling behaviours named independently in
[MARKET_AND_COMPETITOR_SIGNALS.md §3](../research/MARKET_AND_COMPETITOR_SIGNALS.md) and
[CAG_AUDIT_PATTERNS.md](../research/CAG_AUDIT_PATTERNS.md): plaster and paint areas billed without
deducting door and window openings, shuttering double-counted across two structural items, and
**work billed with no parent BOQ item and no approved variation**.

The third of those is the one that matters most, and it is worth stating why it is not an arbitrary
choice. Four independent sources — a peer-reviewed survey with n=62, PMC practice content, the one
external signal this project has, and the 2026-08-24 repository review — point at variations.
Independently, the codebase itself already says variations are the reason it cannot produce a
`FAIL`: [`reconciliation.py`](../../src/aedifex/verification/reconciliation.py) downgrades every
discrepancy to `REVIEW` because *"an approved variation is exactly the thing that would make a
differing rate correct, and we cannot see one."*

The document the market says it cares about and the document the engine says it is missing are the
same document, and there are zero of them in any tier. Tier 5 is where that stops being true.

## What this does not authorise

The **Do not build** list in the Reality Sprint plan stands unchanged: no graph database, no
microservices, no Celery, no Redis, no Kafka, no agent framework, no rules DSL, no vector database,
no RAG, no LLM document reasoning, no multi-tenancy, no authentication, no Kubernetes, no
dashboards. **External deployment remains blocked** until authentication and tenant isolation exist,
and the production guard in the write API is untouched.

The frontend is still not to be beautified. A synthetic bundle is a reason to have something to
show, not a reason to add a risk gauge to it.

## What would falsify this

When a real bundle finally arrives, it gets run through HEAD unchanged — rule 101's second corollary
still holds, and it now matters more, because there will be a temptation to fix things against Tier 5
first. If the rules behave materially differently on the real bundle than on Tier 5, **the synthetic
corpus was mis-shaped and gets rebuilt from what the real document showed.** It does not get
defended, and the real bundle wins every disagreement.

That is the same relationship Tier 2 has to Tier 1, and it is recorded here because the failure mode
is identical: a corpus that is easy to obtain quietly starts defining the product. Tier 5 is the
easiest corpus to obtain that has ever existed, since we write it ourselves.
