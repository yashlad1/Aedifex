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
| Project list | `/` | Which projects need a person, and which links of the chain are missing |
| Project overview | `/projects/:id` | Coverage, counts, and the one button that runs the pipeline |
| Document inventory | `/projects/:id` | Every document, with the classifier's disagreement visible |
| Document viewer | `/projects/:id/documents/:id` | The original artifact beside what we read from it |
| Findings | `/projects/:id/findings/:id` | What was checked, what was compared, what happened |
| Evidence trace | same | Fact / derived fact / provision, each openable at its page |
| Human review | same | Append-only decisions, with staleness shown |

## Rules this app follows

**The backend owns truth.** Nothing here recomputes an outcome, re-derives a workflow category,
decides whether a finding needs review, or ranks anything. Those are deterministic decisions with
provenance behind them; a second implementation in TypeScript would be a second answer, and the two
would diverge quietly.

**Vocabulary comes from `/v1/knowledge`.** Workflow categories *and their order*, processing
statuses, review decisions and rule descriptions are fetched, not hardcoded. The order matters —
measurement precedes the bill it justifies — and a viewer that sorts the chain itself eventually
disagrees with the domain.

**The artifact is the evidence.** The document pane is an `<iframe>` over
`/v1/documents/{id}/content`, which serves the stored bytes with their digest re-verified. Nothing is
re-rendered as HTML: a reconstruction is our interpretation of the document, and interpreting the
document is exactly what the reader came to check. Page navigation uses the `#page=` fragment the
browser's own PDF viewer understands.

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

- **No frontend tests.** The interaction that matters — finding → evidence → page — was verified by
  driving a real browser against the real corpus, not by an automated suite. A suite belongs here
  once the surfaces settle.
- **Spreadsheets are not rendered.** An XLSX shows its sheet and cell reference and a download,
  because a table we drew ourselves would be a re-rendering. Facts from spreadsheets carry their
  cell (`BOQ!E8`) and that is what is shown.
- **A finding list can be long.** One real project reconciles 37 work items against 4 rules, so 150
  findings exist; open ones sort first and the rest are behind a click. A work-item surface (the API
  already has `/v1/projects/{id}/work-items`) is the obvious next screen.
- **No keyboard navigation, no accessibility pass, no mobile layout.**
