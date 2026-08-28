# Customer discovery

Interview record for construction, civil, and real-estate professionals. Manually maintained.

**The current product hypothesis is UNVALIDATED.** Nothing in this file has been used to justify a
line of code, and the acquisition platform is deliberately built so that it does not need to know
which product will eventually consume the corpus.

## How to use this

One block per interview, appended in chronological order. Copy the template verbatim so the fields
stay comparable — the value of this file comes from being able to count repetitions across thirty
conversations, and a field that is sometimes recorded and sometimes not cannot be counted.

Rules for filling it in:

- **Record what was said, not what it implies.** "They re-key BOQ line items into Excel twice a
  week" is an observation. "They need automated BOQ extraction" is a conclusion, and it belongs in
  *Potential product implication* clearly marked as a guess.
- **No conclusions from a single interview.** One vivid story is an anecdote. Patterns get reviewed
  after roughly 15–30 conversations, using the tally below.
- **Record the boring answers too.** "This is annoying but we live with it" is a genuine finding, and
  omitting it biases the sample towards whatever sounds like a product.
- **Quantify wherever the interviewee will.** Hours per week, people involved, rupees or dollars at
  stake, how often the error actually happens. An unquantified pain point cannot be prioritised
  against another one.
- **Note when a pain point was volunteered rather than prompted.** A problem someone raises before
  you ask about it is much stronger evidence than one they agree with after you describe it.

Confidentiality: do not record personal contact details, and do not paste confidential project
documents into this repository. Summarise. If an interviewee shares something commercially sensitive,
note that it exists rather than what it says, and ask before quoting anyone by name or employer.

---

## The one question that matters most

> **"Show me how you checked the last bill."**

Not *"how do you usually check bills"*. People describe workflows badly in the abstract and
demonstrate them accurately. If confidentiality allows a screen share, better still. Watching someone
say *"first I open this workbook, then I copy this, then I look up the previous RA, then I ask site
engineering because this item number changed"* is worth more than twenty feature questions — and it
is where Aedifex's business-object model is expected to come from, rather than from design.

Ask it every time, and record what was demonstrated separately from what was described.

## Who to talk to

People who **touch payment evidence**, in rough order of usefulness:

quantity surveyors · billing engineers · project controls · PMC / consultant QS · contracts
engineers · developer-side finance and project accounting · internal construction auditors ·
contractor billing teams.

Less useful at this stage, and it is worth being deliberate about it: generic civil engineers,
architects who do not certify bills, senior executives far from the documents, and construction-tech
enthusiasts. The subject is a workflow. Talk to the person who has the Excel file open.

## Getting the conversation at all

Do not open by sending [../DATA_REQUEST.md](../DATA_REQUEST.md). Four pages as a first contact asks
for too much commitment. Stage 1 is fifteen minutes and no documents; stage 2, only if they recognise
the workflow, is asking for a sanitised sample; stage 3 is the data request as supporting material.
See [../plans/2026-08-24-reality-sprint.md](../plans/2026-08-24-reality-sprint.md).

---

## Interview template

```markdown
### Interview NN — YYYY-MM-DD

| Field | Response |
| --- | --- |
| Interview date | |
| Role | |
| Company type | |
| Years of experience | |
| Workflow discussed | |
| Documents involved | |
| Software currently used | |
| Manual steps | |
| Time spent | |
| Recurring errors / problems | |
| Financial / operational impact | |
| Workaround | |
| Exact pain points (their words) | |
| Seen in previous interviews? | |
| Potential product implication (guess, not conclusion) | |

**Demonstrated or described?** Did they actually walk through the last bill they checked — screen
share, or step by step from memory of that specific bill — or did they describe their general
practice? Record which. A described workflow and a demonstrated one are different strengths of
evidence and must not be tallied together.

**The demonstration, step by step:** what they opened, in what order, what they compared against
what, and where they had to ask somebody else. Verbatim where possible.

**Volunteered vs prompted:** which pain points came up unprompted.

**Notes:** anything that does not fit a field, including where the conversation contradicted an
earlier interview.
```

---

## Interviews

<!-- Append interview blocks below this line, newest last. -->

_None recorded yet._

---

## Signals that are not interviews

Kept separate from the interview count on purpose. An interview is a conversation with a named role
where a workflow was described or demonstrated; the count of those is what the 10/15/30 checkpoints
mean, and letting weaker evidence into it would quietly inflate the one number the direction
decision rests on.

These are recorded because they are the only external evidence the project has, not because they
carry the weight of an interview.

### S-01 — 2026-08-27 — anonymous commenter, r/ConstructionMNGT

A recruiting post asking for 15–20 minute conversations with people in construction, civil
engineering, QS, procurement or real estate development. **333 views, 1 substantive reply.**

The reply, unprompted, after being told the poster was building something:

> "If you're targeting that space, automating away the manual Excel and WhatsApp invoice chaos is
> definitely where the real pain point is."

The owner notes having heard the same from a few other people, not recorded individually.

**What this is evidence of.** One anonymous person, role unknown, company type unknown, nothing
quantified, no workflow described and none demonstrated. It cannot support a direction change and is
not counted toward the 10.

**What is worth noticing anyway.** The volunteered pain is **invoice chaos in Excel and WhatsApp** —
adjacent to RA-bill verification but not the same thing. Verification asks *is this claim supported*;
this describes documents arriving in the wrong form, in the wrong place, and being re-keyed. If that
recurs in real interviews it points at intake and reconciliation of messy inbound paperwork rather
than at the payment-chain rules, and [../plans/2026-08-24-reality-sprint.md](../plans/2026-08-24-reality-sprint.md)
already says the interviews must be allowed to kill payment verification.

**What it says about the channel, which is separate.** 333 views to 1 reply is roughly 0.3%. A cold
post asking strangers for a call converts badly; that is a fact about the outreach method, not about
the problem. The three-stage funnel in the Reality Sprint plan exists for this reason, and warm
introductions are the untried half of it.

---

### S-02 — 2026-08-28 — desk research, not people

A full pass over forums, competitor products and academic surveys is written up in
[MARKET_AND_COMPETITOR_SIGNALS.md](MARKET_AND_COMPETITOR_SIGNALS.md). Three things from it belong
here:

- **The practitioner forums are closed to automated access.** Reddit, Eng-Tips and Quora all return
  403, and were not worked around. Desk research therefore cannot reach the one thing it was for.
- **The Indian market is not empty.** SuperWise, Site Setu, Powerplay, RDash, Onsite and several ERPs
  already do RA bills and measurement books — all on the *generation* side, where Aedifex is on the
  *verification* side.
- **A peer-reviewed survey (n=62) ranks the payment pain as finance and variations, not verification.**
  Nobody in it said they could not tell whether a bill was correct.

None of this is an interview and none of it counts toward the 10.

---

## Pattern tally

Filled in as interviews accumulate. A row earns attention by recurring across **different** roles and
company types, not by being mentioned emphatically once.

| Pain point | Times raised | Volunteered unprompted | Roles / company types | Quantified impact | Status |
| --- | --- | --- | --- | --- | --- |
| | | | | | |

Status values: `too early` · `recurring` · `strong signal` · `contradicted` · `not a real problem`.

Review checkpoints: **10 interviews** (start thinking — do not wait for 30 to have a first thought),
**15 interviews** (first look for patterns, no decisions) and **30 interviews** (direction decision).
Recording a review below is required even when the conclusion is "still too early", because a review
that only gets written up when it finds something is not a sample.

### Reviews

_None yet._

---

## What this file must not become

- A place to justify code already written. If a commit needs this file as evidence, that commit was
  speculative.
- A record of only the interesting interviews. Survivorship bias here would be indistinguishable
  from validation.
- A product spec. Direction changes get recorded as decisions in `docs/adr/`, with this file cited as
  the evidence.
