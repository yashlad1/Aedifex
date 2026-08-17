# 1. Record architecture decisions

Date: 2026-08-17

## Status

Accepted

## Context

This project will be built over months, will touch financially consequential documents, and
will outlive the memory of whoever made any given decision. The expensive failure mode is not
a wrong decision — it is an *undocumented* one, where a later maintainer cannot tell whether
something is load-bearing or accidental, and either preserves a mistake or removes a
safeguard.

Several decisions here are deliberately restrictive (deterministic verification, immutable raw
storage, a review gate on data sources). Restrictions without recorded reasons get removed by
the first person they inconvenience.

## Decision

Every architectural decision is recorded as a numbered ADR in `docs/adr/`, containing context,
the decision, alternatives considered, and consequences.

An ADR is required when a change constrains future work, picks between viable technologies,
introduces or removes a boundary, or encodes a policy in code. Routine implementation does not
need one.

ADRs are immutable once accepted. A reversal is a new ADR that supersedes the old one, so the
history of reasoning survives.

## Alternatives considered

**Document in the wiki / commit messages.** Wikis drift and are rarely read; commit messages
are not discoverable months later when the question is "why is this like this?".

**Comment in code.** Good for local reasoning, and used heavily here, but a decision spanning
several modules has no single home.

## Consequences

- Small ongoing cost per significant change.
- A reviewer can challenge reasoning, not just implementation.
- Reversals are explicit and traceable.
