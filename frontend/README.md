# Aedifex review workspace

The first user interface. It exists to answer one question — **“what did Aedifex find, and can I
verify it myself?”** — and it is not a dashboard: there are no charts, no scores, and nothing that
implies a magnitude it cannot defend.

## Running it

Two processes. The API must be up first, because the viewer holds no data of its own.

```bash
make run-api                 # http://127.0.0.1:8000
make viewer                  # http://127.0.0.1:5173
```

`make viewer` and `make viewer-check` both use `npm ci`, not `npm install`: it installs exactly the
committed graph and fails if `package.json` and `package-lock.json` disagree — the same guarantee
`uv sync --locked` gives the Python side. CI runs the same two commands and nothing else.

`AEDIFEX_API` overrides the API the dev server proxies to:

```bash
AEDIFEX_API=http://127.0.0.1:8032 npm run dev
```

`npm run build` typechecks (`tsc --noEmit`) and bundles. There is no test suite here yet, and that
is a gap rather than a decision — see “What is missing”.

> **EXTERNAL DEPLOYMENT BLOCKED UNTIL AUTHENTICATION AND TENANT ISOLATION EXIST.**
>
> The API this reads has no authentication, no authorization and no tenancy, and project identifiers
> are global UUIDs with nothing scoping them to an owner. The dev server binds to loopback and the
> banner in the header says so on every screen. Both are reminders, not controls.

## The seven surfaces

| Surface | Where | What it is for |
| --- | --- | --- |
| Project list | `/` | Which projects need a person, which links of the chain are missing, and the form that declares a new one |
| Project overview | `/projects/:id` | Coverage, counts, upload, and the one button that runs the pipeline |
| Document inventory | `/projects/:id` | Every document, with the classifier's disagreement visible |
| Document viewer | `/projects/:id/documents/:id` | The original artifact — a PDF at its page, a workbook at its cell — beside what we read from it |
| Findings | `/projects/:id/findings/:id` | What was checked, what was compared, what happened |
| Evidence trace | same | Fact / derived fact / provision, each openable at its page |
| Human review | same | Append-only decisions, with staleness shown |

## Rules this app follows

**The backend owns truth.** Nothing here recomputes an outcome, re-derives a workflow category,
decides whether a finding needs review, or ranks anything. Those are deterministic decisions with
provenance behind them; a second implementation in TypeScript would be a second answer, and the two
would diverge quietly.

That rule was broken once and the fix is worth recording. This app decided which findings were
outstanding, as `outcome !== "pass" && review_state === "unreviewed"` — which listed every
`INCONCLUSIVE` finding as review work. A reviewer cannot resolve one: the rule could not be applied
because the evidence it needed is missing, and the fix is acquiring a document rather than clicking
Accept. The backend now answers it (`needs_human_review` on every finding, `requires_human_review`
per outcome in `/v1/knowledge`) and this app only sorts by it.

**Vocabulary comes from `/v1/knowledge`.** Workflow categories *and their order*, processing
statuses, review decisions and rule descriptions are fetched, not hardcoded. The order matters —
measurement precedes the bill it justifies — and a viewer that sorts the chain itself eventually
disagrees with the domain.

**The artifact is the evidence.** For a PDF the document pane is an `<iframe>` over
`/v1/documents/{id}/content`, which serves the stored bytes with their digest re-verified, and page
navigation uses the `#page=` fragment the browser's own PDF viewer understands. Nothing is
re-rendered as HTML: a reconstruction is our interpretation of the document, and interpreting the
document is exactly what the reader came to check.

**A spreadsheet gets a grid, and that is not the same thing.** An earlier version of this file
refused to render one, on the grounds that rendering is interpretation. That was too strict, and it
had a perverse result: the format the precedence rules call the *strongest* evidence available — a
workbook, which already carries rows, columns and cell positions — was the only one a reviewer could
not open at the cited location. So `/v1/documents/{id}/sheet` now serves a bounded window and the
viewer draws it, with the cited cell outlined, the sheet selectable, and a line on screen saying the
uploaded workbook remains the authoritative artifact.

What keeps that inside the trust boundary is *where the cells are read*. The window comes from the
server, from the same library and the same `data_only` setting the extractor used — so the grid and
the facts cannot disagree about what F43 contains. A spreadsheet parser in the browser could
disagree, and the reviewer would be looking at the disagreement without knowing.

**Absence is information.** A workflow category with no document says *“Aedifex does not hold one”*,
never *“the project has none”*, and the hover text names the check that cannot run without it.

**Three kinds of evidence stay three kinds.** A value a document states, a value we computed, and a
norm a rulebook states are rendered differently, because “the bill claims this” and “the rulebook
permits this” are not the same sentence.

## Deliberately not here

No state library, no data-fetching library, no component library, no CSS framework, no charting, no
Next.js, no GraphQL. `useApi` is thirty lines and every screen fetches what it shows; there is no
cross-screen cache to invalidate, and a stale number in a review workspace is worse than a second
request.

## What is missing

- **No frontend tests.** CI runs `npm ci && npm run build`, which typechecks and bundles — so the
  committed viewer is guaranteed to compile and nothing more. The interactions were verified by
  driving a real browser against the real corpus. A test suite belongs here once the surfaces settle.
- **Formats other than PDF and XLSX are a download.** There is nothing to render them with that
  would not be a re-rendering, so the artifact itself is the answer.
- **A finding list can be long.** One real project reconciles 37 work items against 4 rules, so 150
  findings exist; the ones needing a person sort first and the rest are behind a click. A work-item
  surface (the API already has `/v1/projects/{id}/work-items`) is the obvious next screen.
- **The document-type list at upload is hardcoded.** `/v1/knowledge` publishes fact types, rules,
  workflow categories and outcomes, but not document types. A stale entry fails loudly, because the
  API validates the value.
- **No keyboard navigation, no accessibility pass, no mobile layout.**
