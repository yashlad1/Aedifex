# IP readiness

**Purpose:** preserve the records that would make a future patent, copyright, trade-secret, or
ownership assessment straightforward — and keep them accurate while the facts are fresh.

**Not:** a substitute for advice from a patent attorney. Nothing here is a legal determination.

## What this directory is for

Good engineering records do not create IP rights, but poor records can make otherwise valuable
work hard to protect: who conceived what, when, and how it works. For AI-assisted development the
recordkeeping matters more, not less, because inventorship centres on the contributions of natural
persons — so the human contribution to a potentially patentable idea has to be legible.

## Confidentiality

**`docs/ip/` is private and must stay private.** Trade-secret protection depends partly on taking
reasonable measures to keep the information confidential, so documenting a secret in a public
repository actively undermines the thing the document is trying to protect.

Before this repository is ever made public, or before any part of it is published:

1. Check [PUBLIC_DISCLOSURES.md](PUBLIC_DISCLOSURES.md) and [INVENTION_REGISTER.md](INVENTION_REGISTER.md).
2. Anything marked `Patent review required` or listed in
   [TRADE_SECRET_REGISTER.md](TRADE_SECRET_REGISTER.md) needs human approval first.
3. Record the disclosure afterwards.

## Contents

| File | Purpose |
| --- | --- |
| [INVENTION_REGISTER.md](INVENTION_REGISTER.md) | Every potentially novel technical idea, with an AED-IP id |
| [AUTHORSHIP.md](AUTHORSHIP.md) | Who contributed what, and how AI assistance was used |
| [IP_DECISIONS.md](IP_DECISIONS.md) | Patent candidate / trade secret / publish / do not pursue |
| [PUBLIC_DISCLOSURES.md](PUBLIC_DISCLOSURES.md) | Every external disclosure, dated |
| [TRADE_SECRET_REGISTER.md](TRADE_SECRET_REGISTER.md) | Confidential assets and the measures protecting them |
| [disclosures/](disclosures/) | Full invention disclosures, one per AED-IP id |
| [prior_art/](prior_art/) | Prior art per invention, including unfavourable references |
| [experiments/](experiments/) | Hypotheses, methods, and results — including failures |
| [diagrams/](diagrams/) | Dated architecture diagrams, never overwritten |

## Vocabulary

Use **"potential invention"** and **"patent review required"**. Never write "patentable" —
patentability is a legal determination that has not been made.

## Rules Claude Code follows here

Claude Code may: draft technical documentation, preserve evidence, organise prior art, and keep
contribution history accurate.

Claude Code must not: declare patentability, draft legal claims, conclusively identify inventors,
file anything, or publish material marked `Patent review required` or as a trade secret.

## When to update

For a substantial architectural or algorithmic change, ask: *does this create potentially valuable
new technical IP?*

- **No** → no update needed. This is the common case.
- **Possibly** → create or update a disclosure, record contributors, link commits, note public
  disclosure status.

Minutes, not bureaucracy.
