# Contributing

## Setup

```bash
make install          # venv + dependencies
make check            # lint + typecheck + unit tests. No infrastructure needed.
.venv/bin/pre-commit install
```

`make help` lists every target.

## Definition of done

A change is not done when it works locally. All of these must hold:

- [ ] Implementation complete, with no `TODO` standing in for missing behaviour
- [ ] Tests written **alongside** the code, covering the failure modes as well as the happy path
- [ ] `make check` passes: ruff, black, mypy strict, unit tests
- [ ] Integration tests pass if the change touches persistence
- [ ] Errors handled explicitly; nothing swallowed to make a test pass
- [ ] Logging added for anything operationally interesting, with the canonical context keys
- [ ] Configuration externalised, not hardcoded
- [ ] Documentation updated: docstrings, plus the relevant `.md` if behaviour or design changed
- [ ] Security implications considered — for untrusted input, explicitly
- [ ] An ADR added if an architectural decision was made
- [ ] Migration written and reversible if the schema changed

## Workflow

Short-lived branches off `main`:

```
feature/cpwd-crawler
feature/download-queue
fix/pdf-parser-timeout
```

Small, reviewable commits. One concern per commit; do not bundle unrelated changes. Commit
messages describe what changed and why, not what file was touched.

CI must be green before merge. Do not disable a check to get a merge through — if a rule is
wrong, change the rule deliberately in its own commit.

## Testing

```
tests/unit/          No database, no network. Must stay fast (currently <1s).
tests/integration/   Real PostgreSQL. Marked, and skipped when unavailable.
```

Principles:

**Test behaviour, not implementation.** A test that breaks on every refactor is a liability.

**Name the failure mode the test prevents.** Prefer a docstring explaining *why* a test exists
over a name restating the assertion. Compare:

```python
def test_empty_payload_is_rejected(self) -> None:
    """Every empty file shares one digest, which would corrupt deduplication."""
```

**Write the regression test before the fix.** When fixing a bug, reproduce it first, so you
have evidence the fix works and a guard against its return.

**Never weaken a test to make it pass.** If a test fails, either the code is wrong or the test
encodes a wrong expectation. Decide which, and say so in the commit message.

**Do not suppress exceptions to get green.** A swallowed error in an auditing system is a
silently wrong answer.

## Code style

- Strict typing. Avoid `Any`; if it is genuinely needed, comment why.
- Functions with one responsibility, typed parameters and returns, predictable side effects.
- Docstrings explain *why*, not *what* — the signature already says what.
- Comments earn their place by explaining a non-obvious decision or a rejected alternative.
  Do not narrate the code.
- Line length 100. Enforced.

## Adding a data source

See [DATA_SOURCES.md](DATA_SOURCES.md). In short: add the YAML entry, leave it
`enabled: false`, review the terms of use as a separate documented step, and only then write a
crawler. The registry schema will refuse to enable it out of order.

## Adding a migration

```bash
make migration m="add findings table"   # autogenerate against a running database
make migrate                            # apply
make downgrade                          # verify it reverses
```

Review the generated file — autogenerate misses check constraints, server defaults, and data
migrations. The `downgrade()` function must be real; a test asserts every revision has
operations in it.

## Dependencies

Adding one requires a reason. Prefer the standard library. Pin with a compatible-release range
in `pyproject.toml`, and remove anything that stops being used — `pip-audit` runs in CI and
every dependency is future attack surface.
