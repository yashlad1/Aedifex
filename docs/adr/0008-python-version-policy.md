# 8. Python version policy: support 3.12 and 3.13

Date: 2026-08-17

## Status

Accepted

## Context

Phase 0 left the Python version implicit and inconsistent:

| Setting | Value |
| --- | --- |
| `requires-python` | `>=3.12` (open-ended upper bound) |
| black `target-version` | `py312` |
| ruff `target-version` | `py312` |
| mypy `python_version` | `3.12` |
| CI | 3.13 only |
| Dockerfile | 3.13 |

Nothing tested 3.12, so the declared floor was an unverified claim. Equally, `>=3.12` with no
upper bound meant a future 3.14 would be silently accepted by the resolver before anyone had
checked whether the dependencies support it.

This matters more than it looks. The codebase uses `StrEnum`, `datetime.UTC`, PEP 604 unions,
and `zip(strict=)` — all fine on 3.12 — but a future contributor adding a 3.13-only construct
would break the declared floor with no failing test to tell them.

## Decision

**Supported: Python 3.12 and 3.13.**

- `requires-python = ">=3.12,<3.14"` — an explicit ceiling, raised deliberately after testing.
- Tooling (black, ruff, mypy) targets **3.12**, the floor, so a 3.13-only construct is a lint
  or type error rather than a runtime surprise.
- CI runs the lint/typecheck/unit matrix on **both** 3.12 and 3.13.
- The container runs **3.13**, so production is a single known version.

Verified rather than asserted: both interpreters run the full suite (343 unit, 22 integration)
and mypy strict cleanly.

## Alternatives considered

**3.13 only.** Simplest, and production would be unambiguous. Rejected for now because it
forces every contributor and any future library consumer onto the newest release for no benefit
— nothing here needs a 3.13 feature. Reconsider when something does.

**`>=3.12` with no ceiling.** Convenient for libraries, wrong for an application: it lets an
untested interpreter into a resolve. An application knows what it deploys.

**Widen to 3.11.** Rejected. `StrEnum` (3.11) is fine but `datetime.UTC` (3.11) and assorted
typing improvements make 3.12 the pragmatic floor, and nothing asks for 3.11.

## Advantages

- The floor is real, because it is tested.
- 3.13-only syntax cannot slip in unnoticed.
- Production runs one version while development tolerates two.

## Disadvantages

- CI matrix doubles the lint/typecheck/unit job count. Cheap: that job takes well under a
  minute and the two entries run in parallel.
- Cannot use 3.13-only features until the floor is raised. Currently no cost.

## Operational consequences

Raising the floor to 3.13 later is: bump `requires-python`, bump the three tooling targets,
drop the matrix entry, re-lock, and confirm CI. Deliberate, not accidental.

## Security consequences

Bounded above, so a Python release that dependencies have not been audited against cannot be
used unnoticed. An end-of-life interpreter cannot linger silently either, since the supported
set is written down.

## Migration consequences

None. `uv.lock` was re-resolved under the narrowed range and produced the same 73 packages.
