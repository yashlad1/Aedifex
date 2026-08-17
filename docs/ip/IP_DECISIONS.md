# IP decision log

One row per decision. Decisions are recorded, not implied — and "do not pursue" is a legitimate
and common outcome.

Permitted decisions: `Patent candidate` · `Trade secret candidate` · `Publish` ·
`Open-source` · `Keep confidential` · `Do not pursue` · `Attorney review pending`

## Decisions

| Date | Subject | Decision | Rationale | Decided by |
| --- | --- | --- | --- | --- |
| 2026-08-17 | Create IP-readiness infrastructure | Keep confidential | Preserve records now so a later assessment is cheap; `docs/ip/` stays private because trade-secret protection depends on actual confidentiality measures | Yash Lad |
| 2026-08-17 | File anything now | Do not pursue (yet) | Nothing built is a specific enough technical method. The acquisition foundation is sound engineering from well-known techniques. Filing on it would be premature and thin. | Yash Lad |
| 2026-08-17 | Repository visibility | Keep confidential | Private GitHub repository. Public release requires the review gate in README.md. | Yash Lad |

## Independent axes

An idea can be commercially valuable and not patentable. Track these separately rather than
collapsing them into one judgement:

| Axis | Question |
| --- | --- |
| Technical novelty | Is the mechanism genuinely different from prior art? |
| Commercial importance | Does it matter to customers? |
| Difficulty to reverse engineer | Could a competitor infer it from observable behaviour? |
| Ease of keeping secret | Is it visible in output, or only internal? |
| Potential patent value | Would exclusivity be worth the disclosure? |

## Patent versus trade secret

```
Would disclosure help competitors reproduce it?
        │
        ├── Yes, easily, and it is hard to detect infringement
        │        → Consider trade secret
        │
        └── No, or exclusivity is worth more than secrecy
                 → Patent review
```

A trade secret must not be publicly documented for the sake of documentation. That trades away the
protection to gain a record.
