# Dependency review: thirteen open Dependabot branches

Date: 2026-08-24

Nothing auto-merges here by design. Each branch is judged on five questions: is it security related,
does it change runtime behaviour, does it require code changes, does it provide measurable benefit,
and does it increase risk *before* product validation. The last question is doing most of the work
right now: a change that alters extracted evidence is far more expensive today than the same change
would be after a design partner has validated the workflow.

## Verdicts

| Branch | Security | Changes runtime | Needs code | Benefit | Verdict |
| --- | --- | --- | --- | --- | --- |
| `uv/python-patch` (boto3 1.43.73 → .77, botocore → .78) | no | no | no | small | **Merge** |
| `uv/rapidocr-onnxruntime-1.4.4` | no | **yes — changes stored evidence** | re-measure everything | none named | **Reject, and stop asking** |
| `uv/dev-tooling` (pytest-cov `<7`→`<8`, mypy `<2`→`<3`) | no | no (dev only) | unknown, later | negative | **Reject** |
| `uv/pillow-12.3.0` (`<12` → `<13`) | **potentially** | possibly, via OCR | one call site | none today | **Defer, with a trigger** |
| `uv/structlog-26.1.0` | no | yes — log shape | likely | none named | **Defer** |
| `github_actions/github/codeql-action/analyze-4.37.7` | yes, eventually | no | no | keeps scanning working | **Defer — cannot merge alone** |
| `github_actions/github/codeql-action/upload-sarif-4.37.7` | yes, eventually | no | no | as above | **Defer — cannot merge alone** |
| `github_actions/gitleaks/gitleaks-action-3.0.0` | no | no | unknown | none named | **Defer** |
| `github_actions/docker/setup-buildx-action-4.3.0` | no | no (build only) | no | none named | **Defer** |
| `github_actions/actions/dependency-review-action-5.0.0` | no | no (PR check) | no | none named | **Defer** |
| `npm_and_yarn/frontend/typescript-7.0.2` | no | build only | probably | none named | **Defer** |
| `npm_and_yarn/frontend/vite-8.2.2` | no | build only | possibly | none named | **Defer** |
| `npm_and_yarn/frontend/vitejs/plugin-react-6.1.0` | no | build only | possibly | none named | **Defer** |

One merge, two rejections, ten deferrals.

## The two that matter

### `rapidocr-onnxruntime` 1.2.3 → 1.4.4 — reject permanently

The pin is exact and deliberate, and `pyproject.toml` records why: 1.2.3 is the version every OCR
measurement in this repository was taken on, and a re-resolve on 2026-08-21 nearly moved it silently
while "the recorded benchmarks, the page-count limits and the SIGSEGV pixel budget all still
described 1.2.3".

Answering the five questions: no security fix is cited; it changes the transcription of scanned pages,
which means it changes **stored evidence**, which is the one category of change this project treats as
requiring its own justification; it requires every OCR measurement to be retaken; no benefit has been
named; and OCR improvement is explicitly outside the current phase. Accepting it would be OCR work
arriving through dependency maintenance rather than through a decision.

A standing weekly PR against a deliberate pin is worse than no PR: it trains a reviewer to dismiss
Dependabot. Added an `ignore` for major and minor bumps of this package to `dependabot.yml`, with the
reason and the condition for removing it. Patch bumps within 1.2.x still surface.

### `pillow` `<12` → `<13` — defer, but this is the one with a real security argument

Pillow is installed and it decodes untrusted bytes: `ocr.py:258` calls
`Image.open(io.BytesIO(image))` on page images extracted from PDFs acquired from public portals. It
is the highest-exposure decoding dependency in the tree, and image decoders are where memory-safety
fixes land.

The reason to defer anyway: **`<12` does not block security patches.** Pillow 11.x patch releases
resolve freely under the current constraint, so the security argument for taking the *major* is weak
today. What the major does bring is API removals and, potentially, decoder output differences that
would feed into OCR — the same evidence-changing risk as rapidocr, one step removed.

**Trigger for revisiting, rather than a vague "later":** merge this when Pillow 11.x stops receiving
security patches, or immediately if a CVE affects 11.x and is fixed only in 12. Until then the
constraint costs nothing.

## Why the codeql pair cannot be merged individually

The workflows pin `github/codeql-action/init`, `.../analyze` and `.../upload-sarif` at the same commit
SHA. Dependabot raised **analyze** and **upload-sarif** but not **init**, so merging either PR alone
would leave `init@v3` driving `analyze@v4` — a mismatched pair inside one job.

GitHub does eventually stop accepting SARIF uploads from deprecated major versions, so this is real
maintenance rather than churn, and the failure mode is a security scan that quietly stops reporting.
It should be done as one change covering all three call sites, with the workflow run verified
afterwards. It is not urgent and it is not three separate merges.

## Why `dev-tooling` is a rejection rather than a deferral

It does not update anything; it **widens** two ranges — `pytest-cov` to `<8` and `mypy` to `<3`.
Widening mypy to allow a future 2.x means the next major mypy release enters the build without a PR,
and `mypy --strict` is a gate the whole codebase is written against. The failure would arrive on an
unrelated commit, at an unpredictable time, looking like that commit's fault.

That is the opposite of what a lockfile plus reviewed PRs is for: it converts a reviewable decision
into a deferred surprise. Majors should stay pinned so that upgrading is an act rather than an
accident.

## The ten deferrals, in one sentence

None of the frontend or CI-action majors has a named benefit, all of them require the viewer or a
workflow to be rebuilt and re-verified, and none of them is on the path to answering the only question
that matters this phase — whether a quantity surveyor can upload a real bundle, understand the
findings, reach the evidence and record a review. They are worth one batched afternoon after that
question has an answer, not thirteen individual merges before it.
