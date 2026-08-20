"""Parsing Indian-convention money and quantities out of tender text.

This is the deterministic floor of the intelligence layer. Everything above it may eventually
involve interpretation; this module may not. It converts a span of text into an exact number or
refuses, and it never guesses — because a silently wrong amount is the one error the rest of the
pipeline cannot detect. "LLMs interpret evidence. Deterministic code verifies evidence."

Two conventions make Indian tender amounts their own problem:

**Digit grouping.** ``8,46,49,969`` is two-then-two-then-three, not thousands. Once the separators
are removed this stops mattering, which is why they are simply removed rather than validated: the
grouping carries no information the digits do not.

**Unit words.** ``Rs. 16.93 Lacs`` means 1,693,000. A lakh is 10^5 and a crore is 10^7, and tender
notices mix the shorthand with absolute figures freely — sometimes in adjacent columns of one table.

A unit word is honoured only when it sits **adjacent to the number**, never when it appears in a
column header. That rule comes from a real document in the corpus: a table headed
``Estimated Cost (Rs. In Crore)`` whose value was ``7,05,49,159/-`` — already absolute rupees, ₹7.05
crore. Applying the header's declared unit would have multiplied a correct figure by ten million and
produced ₹70,54,91,59,00,00,000. Headers in this corpus describe intent; the cell states the fact.

Amounts are :class:`~decimal.Decimal` throughout. Money in binary floating point is a defect
waiting for a total, and these figures reach a percentage comparison.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Final

__all__ = ["Amount", "find_amounts", "parse_amount"]

# 10^5 and 10^7, with the spellings actually observed in Indian government tenders. "lac" and
# "lakh" are the same word transliterated differently and both appear, sometimes in one document.
_UNIT_MULTIPLIERS: Final[dict[str, int]] = {
    "lakh": 10**5,
    "lakhs": 10**5,
    "lac": 10**5,
    "lacs": 10**5,
    "crore": 10**7,
    "crores": 10**7,
    "cr": 10**7,
    "thousand": 10**3,
    "million": 10**6,
    "billion": 10**9,
}

_UNIT_PATTERN: Final[str] = "|".join(sorted(_UNIT_MULTIPLIERS, key=len, reverse=True))

# A currency marker, then digits with optional Indian grouping, then an optional unit word.
#
# The currency marker is required. Without it this pattern matches chainage ("Km 163.468"), highway
# numbers ("NH-1488"), dates and clause numbers — a tender notice is dense with numbers that are not
# money, and a money parser that accepts them is worse than none.
_AMOUNT: Final[re.Pattern[str]] = re.compile(
    r"""
    # The currency marker is required: this is money, not a chainage or a clause number.
    (?P<currency> Rs\.? | INR | ₹ )
    \s*
    (?P<digits> \d{1,3} (?: [,\s] \d{2,3} )* (?: \.\d+ )? )
    \s*
    (?: (?P<unit> """
    + _UNIT_PATTERN
    + r""" ) \b )?
    """,
    re.IGNORECASE | re.VERBOSE,
)


@dataclass(frozen=True, slots=True)
class Amount:
    """One money figure, with enough provenance to defend it.

    ``literal`` is the text exactly as it appeared, so a finding can quote the document rather than
    a number the reader has to take on trust.
    """

    rupees: Decimal
    literal: str
    multiplier: int
    start: int
    end: int

    @property
    def used_unit_word(self) -> bool:
        """Whether a shorthand such as "Lacs" was expanded to reach :attr:`rupees`."""
        return self.multiplier != 1


def parse_amount(text: str) -> Amount | None:
    """Parse a single amount from ``text``, or return ``None`` if there is not exactly one.

    Refuses rather than picking, because a span that contains two amounts is a span whose meaning
    the caller has misjudged, and choosing one of them would hide that.
    """
    found = find_amounts(text)
    return found[0] if len(found) == 1 else None


def find_amounts(text: str) -> tuple[Amount, ...]:
    """Every money figure in ``text``, in order of appearance.

    Total: never raises. A figure whose digits will not parse is skipped rather than reported as
    zero, which is the same rule the acquisition layer applies to a malformed response — a value
    that could not be read must not become a value that looks read.
    """
    amounts: list[Amount] = []
    for match in _AMOUNT.finditer(text):
        digits = re.sub(r"[,\s]", "", match.group("digits"))
        try:
            value = Decimal(digits)
        except InvalidOperation:  # pragma: no cover - the pattern admits only parseable digits
            continue
        unit = (match.group("unit") or "").lower()
        multiplier = _UNIT_MULTIPLIERS.get(unit, 1)
        amounts.append(
            Amount(
                rupees=value * multiplier,
                literal=match.group(0).strip(),
                multiplier=multiplier,
                start=match.start(),
                end=match.end(),
            )
        )
    return tuple(amounts)
