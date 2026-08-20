# Known limitations — NHAI analysis vertical slice

Date: 2026-08-19

What the first end-to-end analysis path does **not** do. Recorded rather than fixed, deliberately:
the slice exists to prove the architecture survives real construction documents, and each item below
is a decision to revisit with evidence rather than an oversight.

## Corpus coverage

Of nine acquired NHAI PDFs:

| | Count | Note |
|---|---|---|
| Yield a complete estimated cost + bid security pair | 4 | 2 distinct tenders, each appearing as both a short NIT and a full bid document |
| State their own prescribed bid-security rate | 1 | ITB clause 13.2, page 13 of a 145-page document |
| Image-only, no text layer | 1 | Needs OCR |
| Yield no fields at all | 3 | Corrigenda and notices using labels the extractor does not read (`Earnest Money`, `Name of work` without a `NIT No.`) |

**Only four of nine have provenance rows.** Five objects in the bucket are orphaned from an earlier
incident in which test fixtures truncated the live database. The bytes survive — the raw tier is
immutable and content-addressed — but without a `documents` row they are invisible to `analyse --all`.
They self-heal on re-crawl. Re-creating those rows by hand would be fabricating provenance and is not
an option.

Consequence worth naming: the one document that reaches a **document-sourced** `PASS` is among the
orphans. The judged path is therefore demonstrated with a caller-supplied rate
(`--prescribed-share`), which the finding labels as such. A document-sourced pass needs that document
re-acquired, which needs a real crawler contact address.

## Not built

- **OCR.** An image-only PDF reports `has_text_layer=False` and yields no facts. That is a recorded
  limitation, not a failure, and OCR is its own slice.
- **Entities and relationships.** Facts attach to documents, not to a `Tender` or `Contract`. So the
  two documents describing one tender are not linked, and the 1% rate stated in a bid document is not
  applied to its own NIT even though it plainly governs it. Cross-document inference needs entity
  resolution first.
- **Duplicate-tender detection.** Two artifacts of one tender produce two independent fact sets.
- **Parser isolation.** pypdf runs in-process. Bounds exist on pages and characters and every parser
  error is caught, but there is no process or memory sandbox around untrusted document parsing. This
  is the honest next hardening step.
- **User agent in provenance.** `document_retrievals` records status, headers, digest and storage
  location but not the User-Agent that fetched the document, which is arguably part of how the
  evidence was obtained.

## Extraction fragility

- **Positional table reading.** The two amounts are told apart by column order within a header block.
  A notice ordering its columns differently would swap them. Mitigated by a plausibility guard that
  refuses a bid security at or above 50% of the estimated cost, and by the rule reporting the ratio it
  actually computed — a swap yields 5000%, not a plausible-looking pass.
- **Currency marker required.** An amount written without `Rs.`/`INR`/`₹` is not read. One document
  states its estimated cost as a bare grouped number and so yields nothing from that cell. Refusing is
  correct here: the same pattern without a currency marker matches chainage, highway numbers and
  clause numbers, which a tender notice is dense with.
- **One document type, one source.** NHAI notices inviting tenders. Nothing generalises to CPWD, GeM,
  or CPPP yet, and it should not until more real documents say what generalising means.

## Testing debt

Deliberate, under the sprint's testing rules. Not covered by automated tests: the `analyse` CLI
command and both API endpoints (verified by execution only); `pdftext` bounds against a hostile PDF;
the prescribed-share extractor's rejection of the 15%/5%/10% distractors; idempotency of re-analysis
(verified by running it twice and counting rows). The money parser, the two extraction defects found
while building, and the ratio arithmetic are the parts that warrant tests first, because they are where
a silent wrong number could reach a finding.
