"""Reading a norm out of a reference document, as distinct from a fact about it.

Written against one real clause and deliberately no wider. Clause 4.14.1 of the NHAI Works Manual
2006, page 79, reads:

    4.14.1 Each bidder shall furnish bid security as a part of his bid at the following rates:
    (a) two percent of the estimated cost for works up to Rs. 20 crore (subject to a maximum of
    Rs. 30 lacs). (b) one and one-half percent of the estimated cost for works between Rs. 20 crore
    to Rs. 50 crore (subject to a maximum of Rs. 50 lacs). (c) one percent of the estimated cost for
    works above Rs. 50 crore.

That single sentence is why this module exists rather than another fact type. It contains three
rates, none of which is a fact about the manual; each is conditional on a band of *someone else's*
estimated cost; and the rate is written in words while the band is written in figures. A fact type
can hold none of that.

**The rates are words on purpose.** "two percent" and "one and one-half percent" are how the
document writes them, and a reader that only understood digits reported this clause as absent — how
the project spent a milestone believing NHAI had no bid-security policy at all, inferred from two
tenders that happened to sit in different bands.

Not a policy language. Three regexes and a word-to-number table sized to one clause. When a second
real reference document arrives it is expected to need its own reader, and that is cheaper than a
grammar nobody can predict the shape of.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Final

from aedifex.extraction.pdftext import DocumentText
from aedifex.extraction.quantities import find_amounts

__all__ = [
    "POLICY_EXTRACTOR",
    "POLICY_EXTRACTOR_VERSION",
    "PROVISION_BID_SECURITY_SHARE",
    "ExtractedProvision",
    "read_bid_security_policy",
]

PROVISION_BID_SECURITY_SHARE: Final[str] = "bid_security_share"

POLICY_EXTRACTOR: Final[str] = "nhai_works_manual_policy"
POLICY_EXTRACTOR_VERSION: Final[str] = "1"

# The clause that introduces a schedule of rates, with its own number captured so the provision can
# cite what the document calls it. Anchored on "bid security" *and* "following rates" together: the
# manual mentions bid security on many pages and tabulates it on one.
_RATES_CLAUSE: Final[re.Pattern[str]] = re.compile(
    r"(?P<clause>\d+(?:\.\d+)+)\s+[^.]{0,200}?bid\s+security[^.]{0,200}?"
    r"at\s+the\s+following\s+rates\s*:",
    re.IGNORECASE,
)

# One lettered sub-clause, up to the next one or the end of the schedule.
_SUB_CLAUSE: Final[re.Pattern[str]] = re.compile(
    r"\((?P<letter>[a-z])\)\s*(?P<body>[^()]*(?:\([^)]*\)[^()]*)*?)(?=\s*\([a-z]\)|$)",
    re.IGNORECASE,
)

# A percentage written in words. Sized to the three forms this clause uses and the halves it is
# plausible to meet beside them; anything else is refused rather than guessed at.
_WORD_NUMBERS: Final[dict[str, Decimal]] = {
    "half": Decimal("0.5"),
    "one": Decimal(1),
    "two": Decimal(2),
    "three": Decimal(3),
    "four": Decimal(4),
    "five": Decimal(5),
    "six": Decimal(6),
    "seven": Decimal(7),
    "eight": Decimal(8),
    "nine": Decimal(9),
    "ten": Decimal(10),
}
_HALF_WORDS: Final[frozenset[str]] = frozenset({"half", "one-half", "a-half", "a half", "one half"})

# A rate, in any of the three notations the two real reference documents use between them: words
# ("two percent", NHAI), decimals ("0.5%"), and vulgar fractions ("1/2%", Rajasthan PWFAR).
#
# The fraction alternative comes first and the leading guard is not decoration. Without them, "1/2%"
# matched the "2%" inside it and returned **two percent for half a percent** — a fourfold
# overstatement of a money threshold, silently. The guard refuses a match that begins immediately
# after a digit or a slash, so a rate can never be read out of the middle of another number.
_PERCENT: Final[re.Pattern[str]] = re.compile(
    r"(?<![\d/])(?:"
    r"(?P<numerator>\d+)\s*/\s*(?P<denominator>\d+)"
    r"|(?P<value>\d+(?:\.\d+)?|[a-z]+(?:[\s\-]and[\s\-][a-z\-]+)?)"
    r")\s*(?:%|per\s?cent)",
    re.IGNORECASE,
)

# What the band is measured on. Only "estimated cost" is recognised, because that is the only
# quantity this clause conditions on and inventing others would be inventing policy.
_APPLIES_TO: Final[re.Pattern[str]] = re.compile(
    r"of\s+the\s+(?P<subject>estimated\s+cost)", re.IGNORECASE
)
_SUBJECT_FIELD: Final[str] = "estimated_cost"

_UP_TO: Final[re.Pattern[str]] = re.compile(
    r"\b(?:up\s+to|upto|not\s+exceeding|below|less\s+than)\b", re.IGNORECASE
)
_ABOVE: Final[re.Pattern[str]] = re.compile(
    r"\b(?:above|exceeding|more\s+than|over)\b", re.IGNORECASE
)
_BETWEEN: Final[re.Pattern[str]] = re.compile(r"\bbetween\b", re.IGNORECASE)
_CAP: Final[re.Pattern[str]] = re.compile(r"subject\s+to\s+a\s+maximum\s+of", re.IGNORECASE)

# Whose rule it is, read from the document rather than asserted by whoever filed it. A provision's
# authority decides which projects it can reach, so it is the one field that must not be operator
# input: "this manual is NHAI's" typed at ingest time is a claim, and a claim cannot govern money.
#
# Recognised authorities only, and NHAI is the only one so far. A document whose issuing authority
# cannot be established yields no provisions at all -- a threshold that binds nobody in particular
# would end up binding everybody.
_AUTHORITIES: Final[tuple[tuple[re.Pattern[str], str, str], ...]] = (
    (
        re.compile(r"National\s+Highways?\s+Authority\s+of\s+India|\bNHAI\b"),
        "nhai",
        "IN",
    ),
)


@dataclass(frozen=True, slots=True)
class ExtractedProvision:
    """One norm read from a reference document, with everything needed to defend applying it."""

    provision_type: str
    clause: str
    authority: str
    jurisdiction: str
    page: int
    span_start: int
    span_end: int
    snippet: str
    applies_to: str
    applies_from: Decimal | None
    applies_to_max: Decimal | None
    share: Decimal | None
    cap_amount: Decimal | None
    currency: str | None


def _issuing_authority(document: DocumentText) -> tuple[str, str] | None:
    """The body whose rule this document states, and its jurisdiction, or ``None`` if unclear."""
    for page in document.pages:
        for pattern, authority, jurisdiction in _AUTHORITIES:
            if pattern.search(page.text):
                return authority, jurisdiction
    return None


def _percent_as_fraction(text: str) -> Decimal | None:
    """``"two percent"`` to ``0.02``, or ``None`` if the wording is not understood.

    Refusing an unrecognised wording is the whole discipline here. A rate this module guessed at
    would become a threshold a rule compared real money against.
    """
    match = _PERCENT.search(text)
    if match is None:
        return None

    if match.group("numerator") is not None:
        numerator = Decimal(match.group("numerator"))
        denominator = Decimal(match.group("denominator"))
        if denominator == 0:
            return None
        return numerator / denominator / 100

    raw = match.group("value").strip().lower()

    try:
        return Decimal(raw) / 100
    except (ArithmeticError, ValueError):
        pass

    # "one and one-half", "two and a half".
    parts = re.split(r"[\s\-]and[\s\-]", raw, maxsplit=1)
    whole = _WORD_NUMBERS.get(parts[0].strip())
    if whole is None:
        return None
    if len(parts) == 1:
        return whole / 100
    tail = parts[1].strip().replace("-", " ")
    if tail in {word.replace("-", " ") for word in _HALF_WORDS}:
        return (whole + Decimal("0.5")) / 100
    return None


def _band(body: str) -> tuple[Decimal | None, Decimal | None] | None:
    """The range of ``applies_to`` this sub-clause governs, as written.

    Boundaries are taken literally and are *not* nudged to make the bands disjoint. As written,
    "up to Rs. 20 crore" and "between Rs. 20 crore to Rs. 50 crore" both contain exactly Rs. 20
    crore, and the document does not say which wins. Selection reports that as a conflict rather
    than choosing, because choosing would be this module legislating.
    """
    # The cap is an amount too, and it is not part of the band. Cut it off first.
    cap = _CAP.search(body)
    condition = body[: cap.start()] if cap else body
    amounts = find_amounts(condition)
    if not amounts:
        return None

    if _BETWEEN.search(condition) and len(amounts) >= 2:
        low, high = amounts[0].rupees, amounts[1].rupees
        return (low, high) if high >= low else (high, low)
    if _ABOVE.search(condition):
        return (amounts[0].rupees, None)
    if _UP_TO.search(condition):
        return (None, amounts[0].rupees)
    return None


def read_bid_security_policy(document: DocumentText) -> tuple[ExtractedProvision, ...]:
    """Read the bid-security rate schedule from a reference document, if it states one.

    Returns empty for the overwhelming majority of documents, which state no such schedule. A
    sub-clause whose rate, subject or band cannot all be read is skipped rather than half-recorded:
    a provision missing its applicability is a threshold that would be applied to everything.
    """
    issuer = _issuing_authority(document)
    if issuer is None:
        return ()
    authority, jurisdiction = issuer

    provisions: list[ExtractedProvision] = []
    for page in document.pages:
        flat = " ".join(page.text.split())
        clause_match = _RATES_CLAUSE.search(flat)
        if clause_match is None:
            continue
        clause = clause_match.group("clause")
        schedule = flat[clause_match.end() :]

        for sub in _SUB_CLAUSE.finditer(schedule):
            body = sub.group("body").strip()
            if not body:
                continue
            subject = _APPLIES_TO.search(body)
            share = _percent_as_fraction(body)
            band = _band(body)
            if subject is None or share is None or band is None:
                continue

            cap_amount: Decimal | None = None
            cap = _CAP.search(body)
            if cap is not None:
                capped = find_amounts(body[cap.end() :])
                cap_amount = capped[0].rupees if capped else None

            start = clause_match.end() + sub.start()
            provisions.append(
                ExtractedProvision(
                    provision_type=PROVISION_BID_SECURITY_SHARE,
                    clause=f"{clause}({sub.group('letter').lower()})",
                    authority=authority,
                    jurisdiction=jurisdiction,
                    page=page.number,
                    span_start=start,
                    span_end=clause_match.end() + sub.end(),
                    snippet=body[:1000],
                    applies_to=_SUBJECT_FIELD,
                    applies_from=band[0],
                    applies_to_max=band[1],
                    share=share,
                    cap_amount=cap_amount,
                    currency="INR",
                )
            )
        if provisions:
            # One schedule per document. A manual that stated two would need a reader that knew
            # which superseded which, and this one does not.
            break
    return tuple(provisions)
