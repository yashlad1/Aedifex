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

**Volunteered vs prompted:** which pain points came up unprompted.

**Notes:** anything that does not fit a field, including where the conversation contradicted an
earlier interview.
```

---

## Interviews

<!-- Append interview blocks below this line, newest last. -->

_None recorded yet._

---

## Pattern tally

Filled in as interviews accumulate. A row earns attention by recurring across **different** roles and
company types, not by being mentioned emphatically once.

| Pain point | Times raised | Volunteered unprompted | Roles / company types | Quantified impact | Status |
| --- | --- | --- | --- | --- | --- |
| | | | | | |

Status values: `too early` · `recurring` · `strong signal` · `contradicted` · `not a real problem`.

Review checkpoints: **15 interviews** (first look for patterns, no decisions) and **30 interviews**
(direction decision). Recording a review below is required even when the conclusion is "still too
early", because a review that only gets written up when it finds something is not a sample.

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
