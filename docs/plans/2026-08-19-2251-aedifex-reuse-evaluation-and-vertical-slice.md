<!-- plan-archive metadata -->
> **Plan archived** · created 2026-08-19 22:51 · revised 2026-08-19 23:35 · project: Aedifex
> · status: Approved for execution
> · original working file: `~/.claude/plans/shiny-fluttering-volcano.md`

---

# Reuse evaluation + finish the NHAI vertical slice

## Context

Two things prompted this plan.

First, a directive to stop building crawler infrastructure before evaluating mature open-source
systems (Kingfisher Collect, Kingfisher Process, Scrapy, OCDS) and to produce explicit
ADOPT / WRAP / BORROW / REJECT verdicts. Aedifex is meant to become an evidence-grounded
construction verification platform serving eight personas; the crawler is one ingestion mechanism,
not the product.

Second, the NHAI vertical slice is **~70% built and currently uncommitted**, with one lint error
blocking it. The slice must finish, but shaped as the persona-agnostic
`Artifact → Fact → Evidence → Rule → Finding` pattern rather than around the 2% bid-security rule.

**Outcome wanted:** a defensible reuse decision on the record, and one real NHAI PDF driven all the
way to an evidence-backed finding visible through CLI/API.

---

## Part 1 — Reuse evaluation (research complete)

### Findings

- **Kingfisher Collect** (BSD-3, Scrapy-based) collects **OCDS release/record packages only** —
  every spider guarantees "either a release package or record package". It does **not** collect
  PDFs or arbitrary portal attachments.
- **India *is* covered**, but only two spiders: `india_assam_civic_data_lab` and
  `india_himachal_pradesh_civic_data_lab`. Both are **bulk downloads from CivicDataLab GitHub
  repos**, not live portals; Himachal's data was last published in **2020**. CPPP, eprocure, GeM
  and NHAI have **no** spiders.
- **Kingfisher Process** (BSD-3) stores/pre-processes OCDS in PostgreSQL: `collection` and
  `collection_note` tables, validation via the OCDS Data Review Tool library, and transforms that
  produce **new** collections (version upgrade, compiled releases) rather than mutating originals.
- **Aedifex's fetch guard** ([guard.py](src/aedifex/acquisition/fetch/guard.py)) enforces: TCP
  connects to the **validated IP** while `Host`, TLS SNI and certificate verification all use the
  **original hostname**; a mixed public/private DNS answer rejects the whole resolution; every
  redirect hop is re-validated; and `ValidatedTarget` is a type-level gate so a plain `str` cannot
  reach a socket. The evaluation below establishes that Twisted *can* express the TLS half of this — the
  distinction that matters is the **type gate**, not the TLS handling.

### Verdicts

| Component | Verdict | Reason |
|---|---|---|
| Kingfisher Collect **as our crawl engine** | **REJECT** | Collects OCDS JSON only. NHAI publishes no OCDS; our evidence is PDFs. Zero overlap with the current need. |
| Kingfisher's **Assam + Himachal OCDS datasets** | **ADOPT the data, not the code** | Real structured Indian procurement data. Register as Aedifex sources and fetch the bulk files through our own boundary — no dependency, no Scrapy. |
| Kingfisher Collect **spider taxonomy** | **BORROW** | Base/Simple/Index/Links/Periodic/CompressedFile/BigFile is a validated taxonomy of discovery shapes. Our `DiscoveryStrategy` already matches Links/Index; adopt the vocabulary plus the *incremental* and *sampling* concepts we lack. |
| Kingfisher **Process** | **BORROW** | Its collection model — versioned collections, transform-into-new-collection, never mutate — independently validates our append-only facts design. But it is OCDS-specific; do not run it. |
| **Scrapy** as fetch/downloader engine | **REJECT** — evaluation complete | Not because the TLS invariant is inexpressible (it is expressible), but because enforcement would move from *one type gate* to *two interception points kept in sync*, against Twisted async vs ADR 0005. |
| Scrapy as **discovery-only** engine | **BORROW the architecture** | The user's own suggested shape — spider emits URLs → Aedifex acquisition boundary → secure fetch → immutable store — is what we already have. Keep the boundary; no Scrapy needed to get it. |
| **OCDS** | **ADOPT as vocabulary** | Do not invent procurement concepts. Map fact types to OCDS names where they exist (`tender.id`, `tender.value`, bid guarantee, `tenderPeriod`). Adopt naming only, not the schema. |
| Existing India scrapers (MIT / GPL-3.0) | **BORROW reconnaissance only** | Already decided. GPL-3.0 is incompatible with this proprietary codebase; MIT is vendorable but architecturally the wrong shape. |

**Net:** no new dependency. Three concrete borrowings (spider taxonomy, collection-versioning
discipline, OCDS naming) and two new candidate sources.

Deliverable: **ADR 0013** recording these verdicts, so this is not re-litigated.

### Scrapy evaluation — correcting my earlier reason

I claimed Scrapy/Twisted could not express "connect to the validated IP while verifying the original
hostname". **That was incorrect.** Twisted documents this as a first-class pattern:
`wrapClientTLS(optionsForClientTLS(hostname), HostnameEndpoint(...))`, and states plainly that "the
host you are connecting to and the host whose identity you are verifying can differ." Scrapy also
exposes a resolver hook (`DNS_RESOLVER` / `TWISTED_DNS_RESOLVER`), and because its
`RedirectMiddleware` re-issues each hop as a new Request through the downloader, per-hop
re-validation would come for free.

So the verdict stands, but on a different and narrower basis:

1. **Enforcement point, not capability.** Aedifex's control is *type-level*: `ValidatedTarget` can
   only be produced by the guard, and the transport accepts nothing else, so a raw `str` cannot
   reach a socket. Scrapy's equivalent would be a custom resolver **plus** a downloader middleware
   (to cover hosts that need no DNS lookup at all), i.e. two interception points that must be kept
   in sync forever. A control you can forget to apply is weaker than one you cannot bypass, even
   when both are correct on the day they ship.
2. **Neither bundled resolver covers both address families safely.**
   `CachingThreadedResolver` (the default) is documented as IPv4-only;
   `CachingHostnameResolver` handles IPv4/IPv6 but ignores `DNS_TIMEOUT`. Aedifex validates both
   families *and* bounds resolution. Getting both under Scrapy means a custom resolver regardless.
3. **Async model.** Twisted's reactor cuts against ADR 0005 (synchronous SQLAlchemy) — the whole
   persistence layer would need re-plumbing for a benefit we cannot yet name.

**Evaluation complete.** One implementation detail — whether a custom Twisted resolver is invoked
for URLs carrying a bare IP literal — is explicitly deferred and out of scope for this milestone. It
would only refine the wording of point 1, not the verdict.

**Revisit trigger:** if source count passes ~20 portals and discovery (not fetching) becomes the
bottleneck, re-evaluate Scrapy for *discovery only*, keeping the Aedifex acquisition boundary.

---

## Part 2 — Current state of the slice

Committed: `998e150` (money parser), `36e5409` (rule 18b), `4eba6b8` (per-source timeouts + contact-guard fix).

Uncommitted and working, smoke-tested against 9 real NHAI PDFs:

- `pyproject.toml` + `uv.lock` — pypdf 6.16.1 declared (BSD-3; PyMuPDF rejected as AGPL)
- [pdftext.py](src/aedifex/extraction/pdftext.py) — bounded PDF→text (`MAX_PAGES`, `MAX_CHARS`, all pypdf errors → `ExtractionError`)
- [tender_notice.py](src/aedifex/extraction/tender_notice.py) — NIT number, estimated cost, bid security, each with page + span + snippet
- [models.py](src/aedifex/infrastructure/database/models.py) — `extracted_facts`, `findings`, `finding_evidence`
- Migration `486135f46988` — **already applied**; `alembic check` reports no drift
- [rules.py](src/aedifex/verification/rules.py) — 2% rule, Decimal-only

Extraction results on the real corpus: **2 tenders extract a complete cost+security pair**, at
exactly **2.0000%** and **1.0000%**. 4 of 9 documents yield a full pair (2 distinct tenders,
duplicated across NIT and RFP).

### Immediate blocker

`ruff` S105 false positive: `PASS = "pass"` in `Outcome` reads as a hardcoded password.
Fix with a targeted `# noqa: S105` and a comment naming it as a false positive.

---

## Part 3 — Remaining work

**1. Unblock** — the S105 noqa above.

**2. Rule takes the prescribed rate as an input, sourced from the document itself.**

Research done first, as instructed. An authoritative rate **does** exist, but only per-document:

| Document | Rate in its own Instructions to Bidders | Observed share |
|---|---|---|
| `65ab…` (145pp, `NHAI/RO-CHD/2026-2027/JAL/22`) | **1% of estimated cost** — ITB clause 13.2, page 13 | 1.0000% |
| `eb75…` (247pp, `NHAI/RO-CHD/2026-2027/BWN/21`) | none found | 2.0000% |
| `cc8a…` (232pp) | none found | — |
| `16ad…`, `70001a…` (NIT extracts, 3–4pp) | none — too short to contain an ITB | 1.0000% / 2.0000% |

The exact clause: *"Any BID not accompanied by the EMD/Bid Security @ 1% of estimated cost and BID
Securing Declaration shall be summarily rejected by the Authority as non-responsive."* The other
percentages in these documents are for different instruments — Additional Performance Security 15%,
retention 5%, liquidated damages 10%, mobilisation advance 5% — and must not be mistaken for it.

There is **no single global NHAI rate** to configure, which settles the design:

- Add a fourth fact, **`prescribed_bid_security_share`**, extracted from ITB text with its own page
  and span. It is evidence like any other fact, not configuration.
- The rule takes the prescribed share as an **input**. Document states a rate → compare → `PASS` or
  `FAIL`. No rate in *that document* → `INCONCLUSIVE`, `expected = "NOT SOURCED"`.
- No global policy configuration architecture, per your instruction. The seam is the rule's
  parameter; a caller may pass a rate, and the extractor supplies one when the document does.

**Cross-document inference is deliberately not done.** `16ad` and `65ab` are the same tender, as are
`70001a` and `eb75` — so the 1% clause arguably governs `16ad` too. Applying it would require entity
resolution to establish that two artifacts describe one tender, which is explicitly deferred. Each
document is judged only on what it itself states.

**3. Rule registry** (small, the persona generalization). A `RULES` mapping of `rule_id → callable`
in `src/aedifex/verification/__init__.py`, so rules are registered rather than hardcoded at the
call site. This is the seam future construction checks plug into. No DSL, no engine.

**4. Persistence** — `src/aedifex/extraction/store.py`:
- `persist_facts(session, document_id, notice, extractor, version) -> list[ExtractedFact]`
- `persist_finding(session, document_id, result, facts) -> Finding`
- Idempotent via the existing unique constraints (`one_fact_per_type_per_extractor_version`,
  `one_finding_per_rule_version`); re-running must update-or-skip, never duplicate.

**5. Runner** — `src/aedifex/extraction/runner.py`, one orchestration path:
read bytes from `RawObjectStore` → `extract_text` → `extract_tender_notice` → persist facts →
evaluate rules → persist finding → advance `DocumentState` (`DOWNLOADED → VALIDATED → PROCESSING →
PROCESSED`) using the existing `assert_transition_allowed`.
Must be runnable over documents already in the live corpus.

**6. Interface** — CLI first (fastest path to the milestone):
`apps/crawler/main.py` gains `analyse <document_id|--all>` and extends `status`, printing the
document, both amounts, the computed ratio, `expected`, an outcome of **PASS / FAIL /
INCONCLUSIVE**, and each fact's page + snippet. When the document states no rate, `expected` renders
as **`NOT SOURCED`** and the outcome is `INCONCLUSIVE` — the interface must make an unjudged
measurement visibly different from a passed check.
Then API: `GET /v1/documents/{id}/facts` and `GET /v1/documents/{id}/findings` in
[apps/api/main.py](apps/api/main.py), following the existing `catalog_entry` / `DocumentResponse`
pattern.

**7. Reuse note** — rename nothing yet, but record the borrowed OCDS field names as comments on the
fact-type constants, so the vocabulary decision is visible where it matters.

### Explicitly deferred (recorded, not built)

OCR for the 1 scanned PDF · `Entity` and `Relationship` tables (Persona H does not need them) ·
duplicate-tender detection · Assam/Himachal source onboarding ·
generic rules DSL · confidence framework.

---

## Part 4 — Testing (per sprint override)

Only tests justified by the stated criteria:

1. **Financial correctness** — a few cases pinning `"16.93 Lacs" → Decimal("1693000")`, the
   crore-header trap, and the 2% ratio arithmetic. This is money; silent wrongness is the risk.
2. **Regression** — the two real defects found while building: `max()`-of-both-headers returning
   the wrong estimated cost, and the truncated `NHAI/RO/MUM/A` NIT number.
3. **Resource limits** — one check that `MAX_PAGES`/`MAX_CHARS` actually bound a large PDF.

No new integration matrices, no fuzzing, no mocks of internal functions. Everything else is
recorded as testing debt.

---

## Verification

1. `.venv/bin/ruff check src apps` · `black --check` · `mypy src apps` — each run **separately and
   unpiped** (a piped chain's exit status is `tail`'s, which has already caused one false "clean").
2. `alembic check` — no drift; `alembic downgrade` then `upgrade` to prove reversibility.
3. **End-to-end on real data, the document that can be judged:** the 145-page `65ab…`
   (`NHAI/RO-CHD/2026-2027/JAL/22`). Expect estimated cost ₹132,804,915 and bid security ₹1,328,000
   (both p4), prescribed share **1% from ITB clause 13.2 (p13)**, observed 1.0000%, outcome
   **PASS** — with a page and snippet for all three facts. This is the milestone: a verdict whose
   threshold is itself cited from the evidence.
4. **The documents that cannot be judged** — `eb75…` (`…/BWN/21`, observed 2.0000%), `70001a…`,
   `16ad…`, `cc8a…` — must each return **`INCONCLUSIVE`** with `expected = NOT SOURCED`, because no
   bid-security rate appears in those documents. No `PASS` and no `FAIL` is expected for any of
   them.
5. Re-run the runner twice; assert no duplicate facts or findings.
6. Full existing suite once: `pytest tests/unit tests/integration`.
7. One documentation pass: FR entries, ARCHITECTURE.md, known limitations, ADR 0013.

## Risks

- **The 2% threshold may be wrong.** Real data shows 1% and 2%. The rule as specified will FAIL a
  legitimate 1% tender. Implementing as instructed and surfacing it rather than quietly widening
  the tolerance.
- **Positional table reading** could swap the two amounts on an unseen layout. Mitigated by the
  plausibility guard (refuses a security ≥50% of cost) and by the rule reporting the ratio it
  actually computed.
