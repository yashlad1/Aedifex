# Aedifex — what we are asking for, and why

A one-page ask for anyone who can help us reach a developer, PMC, contractor or QS practice.
Written to be forwarded as-is.

---

## 1. The project, in short

Construction projects are paid against paperwork. A contractor measures work, claims it in a running
account bill, an engineer certifies it, and finance pays it. The documents that justify each payment —
the bill of quantities, the measurement sheet, the RA bill, the certificate — sit in different files,
in different formats, and nobody checks them against each other line by line. There is rarely time.

**Aedifex reads those documents and checks them against each other automatically.** It answers one
question in many forms: *is this payment supported by the documents?* For example — is the quantity
claimed within the quantity actually measured; is the rate charged the rate in the contract; has a
cumulative claim gone backwards; do the priced items add up to the total the bill states for itself.

Two things make it different from a spreadsheet macro:

- **Every number it reports is traceable.** If it says a claim exceeds the measurement, it will show
  you the page of the RA bill and the page of the measurement sheet that it read, and the arithmetic
  in between. Nothing is asserted without a citation.
- **A person decides, not the software.** Aedifex produces findings and evidence. It never approves
  or rejects a payment. Every finding is reviewed and adjudicated by a human, and that decision is
  recorded.

It works today. It has read a real ₹85 crore building tender — 674 priced BOQ lines — and found that
the priced bill falls ₹58 lakh short of the total the document states for itself, citing the page.
What it has **never seen** is a real measurement sheet or a real RA bill, because those are not
public anywhere in the world. That is the entire reason for this request.

---

## 2. What we are asking for

**One real building project, with documents that match each other.** Residential or commercial —
apartments, offices, a hostel, a hospital, a factory building. Not a highway or a bridge.

The words "match each other" carry the whole request, so section 3 explains them.

### The minimum that is genuinely useful

| # | Document | Why we need it |
| --- | --- | --- |
| 1 | **Bill of Quantities (BOQ)**, priced, as awarded | The baseline: every item, its unit, contracted quantity and rate |
| 2 | **Measurement sheets / JMR / Measurement Book** for one billing period | What was actually measured on site |
| 3 | **RA bill** for that same period | What was claimed against that measurement |
| 4 | **The next RA bill** (the following period) | Lets us check cumulative figures move forward, not backwards |

**Four documents from one project is a complete, useful set.** We would rather have these four,
matching, than forty unrelated documents.

### Helpful, if easy to include

| Document | What it adds |
| --- | --- |
| Agreement / work order | The contract terms and the awarded value |
| Payment or interim certificate | The certification step between claim and payment |
| Architect / engineer / CA certificate | Who certified what, and on what date |
| Variation or change order | Work outside the original BOQ, which is where disputes live |
| Material reconciliation statement | Material issued against material consumed |
| Completion or progress certificate | The closing position |
| Drawings | Optional. Useful context, not required |

### After the first one

If the first project works, **three to five projects** would let us tell a real pattern from a
one-off. But please do not wait to assemble five. One is the thing that unblocks us.

---

## 3. The one requirement that matters most

**The documents must be for the same project, and the same items must appear in more than one of
them.**

This is the part that is easy to get wrong, because it sounds obvious and is not. A BOQ from project
A and an RA bill from project B are two documents; together they are worth nothing to us, because
there is nothing to compare. What we need is:

```
BOQ                 item 4.12   RCC M-25 in slabs      Cum   1,200 @ ₹8,556.65
Measurement sheet   item 4.12   ... measured this month        340 Cum
RA bill  (period 6) item 4.12   ... claimed this month         340 Cum @ ₹8,556.65
RA bill  (period 7) item 4.12   ... cumulative to date         510 Cum
```

The same item number, or the same item description, appearing in all four. That is what makes a check
possible. **If the item numbering differs between the BOQ and the bills, that is fine and normal —
please send it as it is.** Reconciling that is our problem, and knowing how real projects actually
number things is itself valuable to us.

Two smaller preferences, neither of them blocking:

- **Native files beat scans.** An Excel BOQ is the best possible input, because we can cite an exact
  cell. A PDF exported from Excel or Word is nearly as good. A scan of a printout is usable but
  weaker. **Handwritten measurement sheets are welcome** — that is real and we want to know how well
  we cope.
- **Please don't tidy anything up.** Do not re-type, re-format, correct or complete the documents.
  Messy real files are the point. A cleaned-up file tells us nothing about whether this works.

---

## 4. What happens to the documents

```
You send the files
        ↓
Stored unchanged, and never modified afterwards
        the original file is kept byte for byte
        ↓
Read: items, quantities, rates, amounts, dates
        each value keeps the page or cell it came from
        ↓
Checked against each other
        claim vs measurement; rate vs contract;
        cumulative vs previous; items vs stated total
        ↓
Findings, each one citing its evidence
        "this, because of that page and that page"
        ↓
A person reviews each finding and records a decision
        the software never decides
```

Nothing is deleted, overwritten or edited. Nothing is sent to any third party. Nothing is used to
train an external AI model.

---

## 5. What you get back

Within about two weeks of receiving a usable set, a written report on **your own project**:

1. **Every discrepancy found**, in plain terms, each with the document, the page and the two numbers
   that disagree. Typically: a quantity claimed beyond what was measured; a rate that differs from
   the contract rate; a cumulative figure that went down; items that do not add up to a stated total;
   work billed with no variation order behind it.
2. **Every check we ran and found clean** — the absence of a finding is worth as much as a finding,
   and we will say which checks we could not run because a document was missing.
3. **An honest account of what we got wrong.** If we misread a page, that goes in the report. We are
   trying to learn where this breaks, and a report that hides its own errors would be useless to both
   of us.

There is **no charge and no obligation**. We are not selling anything at this stage. If the report is
useful, good; if it shows the software is not ready for your projects, that is the most valuable
result we can get and we would rather find out now.

We will sign an NDA, and we will delete everything on request at any time, no questions asked.

---

## 6. Confidentiality — how to make this easy to say yes to

**Safe to remove entirely.** None of this affects anything we check:

- Company, client, contractor, consultant and individual names
- Site address and project location
- Phone numbers, emails, addresses
- Signatures, stamps, seals, photographs
- Bank details, PAN, GST numbers, tender or contract reference numbers
- Letterheads and logos

**Please keep these, or the documents stop being checkable:**

- Item numbers and item descriptions
- Units (Cum, Sqm, Nos, Rmt, Kg …)
- Quantities — contracted, measured, claimed, previously certified
- Rates and amounts
- Dates and the sequence of billing periods
- Stated totals and section subtotals — these are what let us verify our own reading

**If the money itself is too sensitive:** multiply every rate and amount in every document by the
same factor of your choosing, and don't tell us what it is. Every check we run is internal to the
documents — quantity × rate = amount, items sum to the total, this bill against that measurement — so
a single consistent multiplier leaves all of them working exactly as before. Quantities and units
must stay real.

A practical shortcut many people prefer: **send documents from a completed project that is closed
out**, where commercial sensitivity has largely expired.

---

## 7. Practicalities

- **Format:** whatever you already have. PDF, Excel, Word, scans, photographs of pages. No conversion
  needed.
- **Size:** typically 10–100 MB for one project. If it is larger, that is fine.
- **How to send:** a shared drive link, or a zip. We will provide whatever destination you prefer.
- **Effort on your side:** for someone who knows where the files are, this is a folder copy and, if
  redaction is wanted, an hour or two. It is not a project.

---

## 8. Questions we expect

**"Why not just use public tender documents?"**
We do, and it is not enough. Public procurement exists to prove a contract was **awarded fairly**.
Nothing obliges anyone to publish proof it was **paid correctly**. So bills of quantities are public
and measurement sheets and RA bills essentially never are — anywhere. We have searched three times
over and found one public source in the world, in a state portal we cannot reach. This gap is
structural, not a matter of searching harder.

**"Is this an AI that will make payment decisions?"**
No. Arithmetic and compliance checks are ordinary deterministic code — the same calculation every
time, auditable, no model involved. AI is used only to help read and describe documents, never to
decide whether a payment is correct and never to do the arithmetic. Every finding is reviewed by a
person before it means anything.

**"What if your software finds an error in our billing?"**
That is between you and your project. The report goes to you and to nobody else. We have no interest
in the finding, only in whether we were able to find it and prove it.

**"What if the documents are messy or incomplete?"**
Then send them messy and incomplete. That is the realistic case and it is the one we need to work
against. A set with a gap in it still teaches us where the gap hurts.

**"How is this different from what our QS already does?"**
It is not trying to replace them. A QS checking an RA bill line by line against a measurement book is
doing exactly what this automates — and usually does not have time to do for every line of every
bill. The aim is that the QS reviews forty flagged lines instead of reading four thousand.

---

## 9. The one-sentence version

*We need one real building project's BOQ, measurement sheets and two consecutive RA bills — the same
items appearing across them — and in return we will send a report on that project showing every
discrepancy we can find and prove, with page citations, for free.*
