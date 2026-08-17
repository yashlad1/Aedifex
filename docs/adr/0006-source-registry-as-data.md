# 6. Source registry as data, with a mandatory review gate

Date: 2026-08-17

## Status

Accepted

## Context

The project collects documents from public procurement portals. This is legally and ethically
constrained: terms of use differ per portal, some content sits behind registration, rate limits
must be respected, and some sources publish personal data.

The default failure mode for scraping projects is a URL and a `sleep()` hardcoded in a script,
with the legal question answered informally or not at all. Once that pattern exists, "did
anyone check whether we're allowed to do this?" has no answer.

Ethical constraints enforced only by convention get violated by accident, usually by someone
new who did not know the convention existed.

## Decision

Every source is a YAML entry in `config/sources/`, validated by a strict schema. Crawlers
receive their target, limits, and constraints from the registry and embed none of them.

The schema encodes collection ethics as validation rules, so an unsafe configuration cannot be
expressed:

| Rule | Prevents |
| --- | --- |
| `enabled` requires `verification_status: approved` | Collecting before anyone read the terms |
| `enabled` requires a registered `crawler` | Enabling a source nothing can handle |
| `access: restricted` can never be `enabled` | Bypassing an access control |
| `http_crawl` requires `robots_policy: respect` | Ignoring `robots.txt` |
| Plain HTTP requires `allow_insecure_transport: true` | Silently trusting tamperable transport |
| `license` and `allowed_use` are required fields | Undocumented provenance |
| Rate limits bounded and checked for consistency | Becoming a load generator |

`UNVERIFIED` is the default, so a new source is presumed off-limits. Approval additionally
requires `reviewed_by` and `reviewed_on`, asserted by a test.

## Alternatives considered

**Crawler classes carrying their own configuration.** Configuration and code change together,
but reviewing "what are we collecting, and are we allowed to?" means reading every crawler.

**Database-backed registry.** Better for runtime edits; loses code review, which is exactly
the control wanted for a legal decision.

**Registry as data, but with the legal fields optional.** Considered and rejected. Optional
provenance metadata is metadata that does not get filled in.

## Consequences

- Enabling a source is a reviewed change touching licence metadata, so the legal question is
  answered in the pull request.
- Adding a source is cheap; enabling one is deliberately not.
- Rate limits and politeness are uniform across crawlers by construction.
- Runtime changes require a deploy. Acceptable — disabling a source in an emergency is a
  one-line change, and the audit trail is worth more than the latency.
- The schema can express sources we may never collect from, which is useful: recording that a
  source exists and is off-limits, with the reason, prevents it being reconsidered from scratch.
