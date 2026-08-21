"""Field extraction for NHAI notices inviting tenders.

Scope is deliberately one document type from one source. The fields are the three the first
verification rule needs — the NIT number that identifies the tender, and the two amounts whose
relationship the rule checks — and nothing else. A universal tender ontology is a thing to design
after seeing many sources, not before seeing one work.

Every value carries an :class:`Evidence` record: the page it came from, its offset within that
page's normalised text, and a verbatim snippet of the surrounding words. A finding that cannot be
traced back to a span of a real document is an assertion, not evidence, and the whole point of this
pipeline is that it produces the second kind.

**How the two amounts are told apart.** These notices state them in a table, which arrives from the
text layer as a flat run of words: the column headers first, then the row's cells in order. So the
extractor anchors on the headers and reads the amounts that follow them positionally — first
``Estimated Cost``, then ``Bid Security``. This is a real constraint of the format rather than a
shortcut, and it has a failure mode worth naming: a notice whose columns are ordered differently
would silently swap the two. The verification rule is what catches that, because a swapped pair
produces a ratio of 5000% rather than 2%, and the rule reports the ratio it actually computed.

A field that cannot be found is reported as unsupported, never defaulted. An absent value must not
become a value that looks extracted.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Final

from aedifex.domain.evidence import FactKind
from aedifex.extraction.pdftext import DocumentText, PageText
from aedifex.extraction.quantities import Amount, find_amounts

__all__ = [
    "CURRENCY_INR",
    "EXTRACTOR",
    "EXTRACTOR_VERSION",
    "FIELD_BID_SECURITY",
    "FIELD_DOCUMENT_DATE",
    "FIELD_ESTIMATED_COST",
    "FIELD_NIT_NUMBER",
    "FIELD_PRESCRIBED_BID_SECURITY_SHARE",
    "Evidence",
    "ExtractedField",
    "TenderNotice",
    "extract_tender_notice",
]

FIELD_NIT_NUMBER: Final[str] = "nit_number"
FIELD_ESTIMATED_COST: Final[str] = "estimated_cost"
FIELD_BID_SECURITY: Final[str] = "bid_security"
FIELD_PRESCRIBED_BID_SECURITY_SHARE: Final[str] = "prescribed_bid_security_share"
FIELD_DOCUMENT_DATE: Final[str] = "document_date"
CURRENCY_INR: Final[str] = "INR"

# Recorded on every fact. The version is bumped when extraction logic changes in a way that could
# alter a value, because a finding must be readable against the facts that actually produced it --
# and the unique constraint on (document, fact_type, extractor_version) makes a bump a new row
# rather than a silent overwrite of evidence.
EXTRACTOR: Final[str] = "nhai_tender_notice"

# Bumped to "2" on 2026-08-20, when a real reference document showed the reader inventing a fact.
# The NHAI Works Manual states "two percent of the estimated cost for works up to Rs. 20 crore",
# and version 1 recorded `estimated_cost = Rs 20,00,00,000` as a fact about a procedure manual.
#
# The version bump is the point, not housekeeping. Evidence is never deleted here, so the false row
# stays — but selection takes the newest extractor version per document, so a corrected reading
# supersedes a wrong one instead of sitting beside it. A fact the document never stated is not a
# competing reading to be weighed; it is a value that must stop being selectable.
#
# Bumped to "3" on 2026-08-21 for the same reason at larger scale. Version 2 fixed the reader; it
# did not fix the *classification* the reader depends on. Five real documents from two newly
# acquired sources fell outside the reference-document set and produced five more invented facts —
# ₹13,262 crore from a CAG report on Polavaram R&R colonies, ₹140 crore from a metro car park,
# ₹4 crore from a "design ecosystem", and two dates printed inside specimen forms in NHAI's model
# concession agreements. Nothing about the parsing was wrong. What was wrong is that an audit report
# had no document type of its own and a model contract was indistinguishable from a signed one; both
# are fixed in `aedifex.domain.documents`, and this bump makes the corrected reading the selected
# one while the false rows stay on the record where an auditor can still see them.
EXTRACTOR_VERSION: Final[str] = "3"

# How much surrounding text a snippet carries. Enough to read the value in its own sentence, so a
# reviewer can judge it without opening the PDF; short enough to store per fact.
_SNIPPET_RADIUS: Final[int] = 90

# "NIT No. NHAI/RO-CHD/2026-2027/BWN/21", and the "Tender No." spelling the same portal also uses.
# The value is a slash-separated reference, so it stops at whitespace that is not inside the
# reference itself. Trailing "dated ..." is excluded by requiring at least one slash.
_NIT_NUMBER: Final[re.Pattern[str]] = re.compile(
    # The character class carries "&" and both apostrophes because real references do: one notice
    # in the corpus is numbered NHAI/RO/MUM/A<U+2019>Nagar/NH-160/RC/2026/20, and a class lacking
    # the typographic apostrophe truncated it to "NHAI/RO/MUM/A" -- a wrong identifier rather
    # than a missing one, which is the worse of the two failures.
    r"(?:NIT|Tender|IFB)\s*No\.?\s*[:\-]?\s*"
    r"(?P<value>[A-Za-z0-9][A-Za-z0-9/_.\-&'\u2019]*/[A-Za-z0-9/_.\-&'\u2019]+)",
    re.IGNORECASE,
)

_ESTIMATED_COST_HEADER: Final[re.Pattern[str]] = re.compile(r"Estimated\s+Cost", re.IGNORECASE)
_BID_SECURITY_HEADER: Final[re.Pattern[str]] = re.compile(
    r"Bid\s+Security|Earnest\s+Money|\bEMD\b", re.IGNORECASE
)

# Amounts a table row can contain that are not the tender's own figures. "Cost of Bid Documents" is
# the fee to download the tender, typically Rs. 25,000 — reading it as a bid security would produce
# a plausible-looking ratio from the wrong number, which is worse than finding nothing.
_DOCUMENT_FEE: Final[re.Pattern[str]] = re.compile(
    r"Cost\s+of\s+Bid\s+Document|Tender\s+Fee|Document\s+Fee|Non-?Refundable", re.IGNORECASE
)

# "Estimated cost" as the object of a rate rule, not as this document's own figure. The NHAI Works
# Manual states policy rather than a tender: clause 4.14.1 reads "two percent of the estimated cost
# for works up to Rs. 20 crore", and reading the label positionally produced
# `estimated_cost = Rs 20,00,00,000` as a fact about a 297-page procedure manual -- which then went
# on to be cited as evidence in a finding.
#
# The discriminator is what sits *before* the label. A document stating its own cost writes
# "Estimated Cost (in Rs.)" or "Estimated Cost ... Rs. 13,28,04,915/-"; a document stating a rule
# writes "N percent of the estimated cost". Neither real tender layout in the corpus is preceded by
# a percentage, so this refuses the policy sentence without touching them.
_RATE_OF_COST: Final[re.Pattern[str]] = re.compile(
    r"(?:\d+(?:\.\d+)?\s*(?:%|per\s?cent)|"
    r"(?:one|two|three|four|five|half|quarter)(?:[\s\-]and[\s\-]\w+)?[\s\-]*"
    r"(?:%|per\s?cent))\w*\s+of\s+(?:the\s+)?$",
    re.IGNORECASE,
)

# How far back to look for that construction. Long enough for "one and one-half percent of the",
# short enough that an unrelated percentage earlier in a table cannot reach the label.
_RATE_PREFIX_WINDOW: Final[int] = 60


@dataclass(frozen=True, slots=True)
class Evidence:
    """Where a value was found, precisely enough to go back and look."""

    page: int
    start: int
    end: int
    snippet: str


@dataclass(frozen=True, slots=True)
class ExtractedField:
    """One extracted value, its normalised form, and its provenance.

    ``literal`` is what the document said; ``value`` is what it means. Keeping both means a
    disagreement about the parse can be settled without re-reading the PDF.
    """

    name: str
    literal: str
    value: Decimal | None
    currency: str | None
    evidence: Evidence
    method: str
    kind: FactKind = FactKind.TEXT
    """What kind of value this is, independent of the field name (the shared fact model).

    A cross-document rule selects on this rather than on ``name``, which is what lets one comparison
    serve every money fact instead of being rewritten per document type.
    """

    date_value: dt.date | None = None
    """Parsed calendar value for date facts, so chronology is a query rather than a parse."""

    unit: str | None = None
    """Unit of measure for a quantity. Explicit, never inferred — 470 m3 and 470 MT are not
    comparable, and a quantity that has lost its unit invites exactly that comparison."""

    sheet_row: int | None = None
    sheet_column: int | None = None
    """Grid position, for a value read from a spreadsheet cell rather than a page of text."""


@dataclass(frozen=True, slots=True)
class TenderNotice:
    """What was extracted from one notice, and what was not."""

    fields: tuple[ExtractedField, ...]
    unsupported: tuple[str, ...]

    def field(self, name: str) -> ExtractedField | None:
        for candidate in self.fields:
            if candidate.name == name:
                return candidate
        return None

    @property
    def field_names(self) -> tuple[str, ...]:
        return tuple(field.name for field in self.fields)


def _normalise(text: str) -> str:
    """Collapse runs of whitespace, so a table flattened across lines reads as one sequence."""
    return re.sub(r"\s+", " ", text).strip()


def _snippet(text: str, start: int, end: int) -> str:
    left = max(0, start - _SNIPPET_RADIUS)
    right = min(len(text), end + _SNIPPET_RADIUS)
    prefix = "…" if left > 0 else ""
    suffix = "…" if right < len(text) else ""
    return f"{prefix}{text[left:right]}{suffix}"


def _amount_field(
    name: str, amount: Amount, page: PageText, text: str, method: str
) -> ExtractedField:
    return ExtractedField(
        name=name,
        literal=amount.literal,
        value=amount.rupees,
        currency=CURRENCY_INR,
        kind=FactKind.MONEY,
        evidence=Evidence(
            page=page.number,
            start=amount.start,
            end=amount.end,
            snippet=_snippet(text, amount.start, amount.end),
        ),
        method=method,
    )


def _find_nit_number(pages: tuple[tuple[PageText, str], ...]) -> ExtractedField | None:
    for page, text in pages:
        match = _NIT_NUMBER.search(text)
        if match is None:
            continue
        value = match.group("value").rstrip(".,;")
        return ExtractedField(
            name=FIELD_NIT_NUMBER,
            literal=value,
            value=None,
            currency=None,
            kind=FactKind.IDENTIFIER,
            evidence=Evidence(
                page=page.number,
                start=match.start("value"),
                end=match.start("value") + len(value),
                snippet=_snippet(text, match.start(), match.end()),
            ),
            method="label:NIT No",
        )
    return None


# How close two column headers must be to count as one header block rather than two separate
# labelled groups. Measured from the corpus: a genuine block reads "Estimated Cost (Rs. In Crore)
# Bid Security (in Rs.)" with 30 characters between the labels, while a notice carrying two
# independent groups on one page put 566 between them.
_HEADER_BLOCK_GAP: Final[int] = 120

# How far after a label to look for its value before giving up. Long enough to clear a table row's
# work description, which can run to several hundred characters.
_LABEL_WINDOW: Final[int] = 900

# A bid security is a small fraction of the contract value. One that equals or approaches the
# estimated cost is not a bid security -- it is the same figure read twice, which is how positional
# reading fails when a row does not contain the column it promised. Refusing here means the rule
# never receives a pair it would score as a confident 100%.
_MAX_PLAUSIBLE_SECURITY_SHARE: Final[Decimal] = Decimal("0.5")


# The rate a document *prescribes* for its own bid security, as opposed to the amount it states.
# Sourced from a real clause in the corpus (ITB 13.2 of a 145-page bid document):
#
#   "Any BID not accompanied by the EMD/Bid Security @ 1% of estimated cost and BID Securing
#    Declaration shall be summarily rejected by the Authority as non-responsive."
#
# The lead-in must be Bid Security or EMD, because these documents are full of other percentages of
# estimated cost that are emphatically not this one -- Additional Performance Security at 15%,
# retention at 5%, liquidated damages at 10%, mobilisation advance at 5%, and several eligibility
# thresholds. Matching any "N% of estimated cost" would confidently return the wrong policy.
_PRESCRIBED_SHARE: Final[re.Pattern[str]] = re.compile(
    r"(?:Bid\s+Security|EMD)"
    r"(?P<between>[^.]{0,60}?)"
    r"@?\s*(?P<percent>\d+(?:\.\d+)?)\s*%\s*of\s+(?:the\s+)?estimated\s+cost",
    re.IGNORECASE,
)

# Instruments that also take a percentage of estimated cost. If one of these names appears between
# the "Bid Security" lead-in and the percentage, the percentage belongs to it and not to us.
_OTHER_INSTRUMENT: Final[re.Pattern[str]] = re.compile(
    r"Performance\s+Security|Retention|Liquidated|Advance|Turnover|Similar\s+Work", re.IGNORECASE
)


def _find_prescribed_share(
    pages: tuple[tuple[PageText, str], ...],
) -> ExtractedField | None:
    """The bid-security rate the document itself prescribes, if it states one.

    This is evidence, not configuration. A rate read out of a document's own Instructions to Bidders
    can be cited; a rate held in our settings is an assertion about policy that nobody can check.
    Returning ``None`` is the common case -- a three-page notice contains no ITB -- and it must lead
    to an unjudged measurement rather than a guessed threshold.
    """
    for page, text in pages:
        for match in _PRESCRIBED_SHARE.finditer(text):
            if _OTHER_INSTRUMENT.search(match.group("between")):
                continue
            percent = Decimal(match.group("percent"))
            return ExtractedField(
                name=FIELD_PRESCRIBED_BID_SECURITY_SHARE,
                kind=FactKind.PERCENTAGE,
                literal=f"{match.group('percent')}% of estimated cost",
                # Stored as a fraction, the same form the rule compares against.
                value=percent / Decimal(100),
                currency=None,
                evidence=Evidence(
                    page=page.number,
                    start=match.start(),
                    end=match.end(),
                    snippet=_snippet(text, match.start(), match.end()),
                ),
                method="clause:bid security @ N% of estimated cost",
            )
    return None


def _amounts_after(text: str, offset: int, *, window: int) -> list[Amount]:
    """Currency-marked amounts within ``window`` characters after ``offset``, rebased onto ``text``.

    Amounts labelled as a document fee are dropped. "Cost of Bid Documents (Non-Refundable):
    Rs. 25,000/-" sits inside the same table row as the contract value in this corpus, and reading
    it as a tender figure would produce a plausible-looking number from the wrong line.
    """
    region = text[offset : offset + window]
    kept: list[Amount] = []
    for amount in find_amounts(region):
        preceding = region[max(0, amount.start - 130) : amount.start]
        if _DOCUMENT_FEE.search(preceding):
            continue
        kept.append(
            Amount(
                rupees=amount.rupees,
                literal=amount.literal,
                multiplier=amount.multiplier,
                start=amount.start + offset,
                end=amount.end + offset,
            )
        )
    return kept


def _find_table_amounts(
    pages: tuple[tuple[PageText, str], ...],
) -> tuple[ExtractedField | None, ExtractedField | None]:
    """Read the estimated cost and bid security from a notice's invitation table.

    Two real layouts, distinguished by how far apart the labels sit, because the same positional
    rule cannot serve both:

    *Header block.* "Estimated Cost (in Rs.) Bid Security (in Rs.) Completion Period" then the row.
    Both values follow both labels, so they are taken positionally -- first amount is the cost,
    second is the security.

    *Separate groups.* One page carrying "Estimated Cost ... Rs. 13,28,04,915/-" and, hundreds of
    characters later, "Bid Security Time for completion Rs. 13.28 Lacs". Here each label owns the
    amount that follows it, and reading positionally from the later label would return the wrong
    figure for the cost -- which it did, on a real document, before this distinction existed.
    """
    for page, text in pages:
        # Every occurrence, not the first. A page can state a rule and a value, and taking only the
        # first match let one policy sentence hide a genuine figure further down.
        cost_header = next(
            (
                match
                for match in _ESTIMATED_COST_HEADER.finditer(text)
                if not _RATE_OF_COST.search(
                    text[max(0, match.start() - _RATE_PREFIX_WINDOW) : match.start()]
                )
            ),
            None,
        )
        if cost_header is None:
            continue
        security_header = _BID_SECURITY_HEADER.search(text)
        contiguous = (
            security_header is not None
            and abs(security_header.start() - cost_header.end()) <= _HEADER_BLOCK_GAP
        )

        if contiguous and security_header is not None:
            row_start = max(cost_header.end(), security_header.end())
            found = _amounts_after(text, row_start, window=_LABEL_WINDOW)
            cost_amount = found[0] if found else None
            security_amount = found[1] if len(found) > 1 else None
        else:
            cost_candidates = _amounts_after(text, cost_header.end(), window=_LABEL_WINDOW)
            cost_amount = cost_candidates[0] if cost_candidates else None
            security_amount = None
            if security_header is not None:
                security_candidates = _amounts_after(
                    text, security_header.end(), window=_LABEL_WINDOW
                )
                security_amount = security_candidates[0] if security_candidates else None

        if cost_amount is None:
            continue

        # The same span cannot be two different facts, and a security that is not a small fraction
        # of the cost is the same figure read twice.
        if security_amount is not None and (
            security_amount.start == cost_amount.start
            or cost_amount.rupees <= 0
            or security_amount.rupees / cost_amount.rupees >= _MAX_PLAUSIBLE_SECURITY_SHARE
        ):
            security_amount = None

        cost = _amount_field(
            FIELD_ESTIMATED_COST,
            cost_amount,
            page,
            text,
            "table:header-block" if contiguous else "label:Estimated Cost",
        )
        security = (
            _amount_field(
                FIELD_BID_SECURITY,
                security_amount,
                page,
                text,
                "table:header-block" if contiguous else "label:Bid Security",
            )
            if security_amount is not None
            else None
        )
        return cost, security
    return None, None


# "dated 07.08.2026", "Date: 04.08.2026". Day-first, which is the convention in these documents --
# and the reason a date is parsed into a real date rather than kept as text: 07.08.2026 and
# 07.09.2026 sort correctly as dates and incorrectly as strings.
_DOCUMENT_DATE: Final[re.Pattern[str]] = re.compile(
    r"(?:dated|date)\s*:?\s*(?P<day>\d{1,2})[.\-/](?P<month>\d{1,2})[.\-/](?P<year>\d{4})",
    re.IGNORECASE,
)


def _find_document_date(pages: tuple[tuple[PageText, str], ...]) -> ExtractedField | None:
    """The date the document carries next to its own reference, if it states one.

    Only the first match is taken, and only from the earliest page that has one: a tender document
    is full of other dates -- bid submission, opening, pre-bid meeting -- and the one beside the NIT
    number is the document's own. An impossible date is skipped rather than clamped, because a
    document stating 32.13.2026 has told us something is wrong with our reading of it.
    """
    for page, text in pages:
        for match in _DOCUMENT_DATE.finditer(text):
            try:
                value = dt.date(
                    int(match.group("year")), int(match.group("month")), int(match.group("day"))
                )
            except ValueError:
                continue
            return ExtractedField(
                name=FIELD_DOCUMENT_DATE,
                kind=FactKind.DATE,
                literal=match.group(0),
                value=None,
                currency=None,
                date_value=value,
                evidence=Evidence(
                    page=page.number,
                    start=match.start(),
                    end=match.end(),
                    snippet=_snippet(text, match.start(), match.end()),
                ),
                method="label:dated",
            )
    return None


def extract_tender_notice(document: DocumentText) -> TenderNotice:
    """Extract the NIT number, estimated cost, and bid security from a notice.

    Pure: takes text, returns values. No database, no storage, no clock — so the same document
    always yields the same facts, which is what makes a finding reproducible.
    """
    pages = tuple((page, _normalise(page.text)) for page in document.pages if not page.is_empty)
    if not pages:
        return TenderNotice(
            fields=(),
            unsupported=(
                "no text layer: the document is image-only and needs OCR, which this pipeline "
                "does not yet perform",
            ),
        )

    found: list[ExtractedField] = []
    missing: list[str] = []

    nit = _find_nit_number(pages)
    if nit is not None:
        found.append(nit)
    else:
        missing.append(f"{FIELD_NIT_NUMBER}: no 'NIT No.' or 'Tender No.' label found")

    cost, security = _find_table_amounts(pages)
    if cost is not None:
        found.append(cost)
    else:
        missing.append(
            f"{FIELD_ESTIMATED_COST}: no amount carrying a currency marker followed the "
            f"'Estimated Cost' header"
        )
    if security is not None:
        found.append(security)
    else:
        missing.append(
            f"{FIELD_BID_SECURITY}: no 'Bid Security' header with a following amount was found"
        )

    document_date = _find_document_date(pages)
    if document_date is not None:
        found.append(document_date)
    else:
        missing.append(f"{FIELD_DOCUMENT_DATE}: no 'dated'/'Date:' value found")

    prescribed = _find_prescribed_share(pages)
    if prescribed is not None:
        found.append(prescribed)
    else:
        missing.append(
            f"{FIELD_PRESCRIBED_BID_SECURITY_SHARE}: this document states no bid-security rate, so "
            f"any share computed from it cannot be judged"
        )

    return TenderNotice(fields=tuple(found), unsupported=tuple(missing))
