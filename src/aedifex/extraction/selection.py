"""Choosing which fact to reconcile against, explicitly.

This module exists because of one line of code it replaces::

    by_type = {fact.fact_type: fact for fact in facts}

That dict comprehension silently kept whichever fact the database happened to return last. It gave
correct answers for as long as every version of a document agreed, and it was one revised bill of
quantities away from producing a confident finding from a stale source. Row order is not an
authority.

The policy, in order:

0. **Retracted facts are excluded.** A retraction is a later extractor version saying the document
   never stated this value, and a withdrawn value must never be selected as a current one. Added on
   2026-08-21 after the first end-to-end product run cited one: a threshold quoted inside a model
   agreement — "less than Rs. 5 crores", page 48 — had been correctly retracted weeks earlier and
   was still being compared against the project's real estimated cost, producing a confident FAIL
   from evidence the system itself had withdrawn.
1. Facts from documents that are not ``ACTIVE`` are excluded. A superseded revision is still stored
   and still queryable; it just does not feed current-state reconciliation.
2. Within one document **and one row**, the newest extractor version wins. That is not ambiguity —
   it is us having re-read the same document better. Two *different* rows of one document are two
   claims and stay two candidates; see :func:`_newest_per_claim` for the real bill that proved the
   distinction matters.
3. If exactly one active fact remains, it is chosen.
4. If several remain and they **agree**, one is chosen and the agreement is recorded. Three copies
   of the same number are not a conflict.
5. If several remain and they **disagree**, nothing is chosen. The caller reports ``REVIEW`` or
   ``INCONCLUSIVE``, naming the conflicting documents.

Rule 5 is the whole point. Two active documents stating different contracted quantities is a real
situation — an un-superseded revision, a duplicate upload, a corrigendum nobody linked — and the
honest answer is that Aedifex cannot tell which governs. Picking one would be a guess wearing the
clothes of a finding.

There is no policy engine here and no configuration. When a second policy is genuinely needed, this
is a function to add a parameter to.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal

from aedifex.infrastructure.database.models import Document, ExtractedFact

__all__ = ["Selected", "select_facts", "select_one"]


@dataclass(frozen=True, slots=True)
class Selected:
    """The outcome of choosing one fact, and why.

    ``reason`` is stored on findings, so an auditor asking "why this revision?" gets an answer from
    the record rather than from the code.
    """

    fact_type: str
    fact: ExtractedFact | None
    considered: tuple[ExtractedFact, ...]
    excluded: tuple[ExtractedFact, ...]
    reason: str
    conflicting: bool = False

    @property
    def resolved(self) -> bool:
        return self.fact is not None


def _newest_per_claim(facts: list[ExtractedFact]) -> list[ExtractedFact]:
    """One fact per claim, keeping the newest extractor version.

    Two extractions of one document are two readings of the same evidence, not two claims about the
    world, so the better reading wins and no conflict is reported.

    A claim is a **document and a row**, not a document. This used to key on the document alone,
    which was right for a document-scoped fact — a tender states one estimated cost — and wrong for
    every row-scoped one. The IIT Bombay Hostel 19 bill proves it: its hierarchical numbering
    restarts in each of four parts, so 49 different priced rows normalise to item ``1.3``, and all
    49 reached this function as candidates for one work item's contracted quantity. Keyed on the
    document, 48 were discarded because ``4 > 4`` is false, the survivor was whichever row the
    database returned first, and :func:`select_one` then reported "the only active document stating
    contracted_quantity" — a statement about the evidence that is not true.

    That is the failure this module was written to remove, one level further down: row order was
    still an authority. Keyed on the row, the 49 stay 49, disagree, and rule 5 refuses to choose.

    A fact with no row keys on ``(document, None)``, so document-scoped selection is unchanged.
    """
    newest: dict[tuple[uuid.UUID, int | None], ExtractedFact] = {}
    for fact in facts:
        key = (fact.document_id, fact.sheet_row)
        current = newest.get(key)
        if current is None or fact.extractor_version > current.extractor_version:
            newest[key] = fact
    # Sorted by document then row so two runs consider candidates in the same order, and a row
    # without a number sorts before one with, rather than raising on the comparison.
    return [
        newest[key]
        for key in sorted(newest, key=lambda k: (str(k[0]), k[1] is not None, k[1] or 0))
    ]


def _comparable(fact: ExtractedFact) -> tuple[object, ...]:
    """What makes two facts the same claim. Value and unit, not identity.

    A quantity is compared by number *and* unit: 470 m3 and 470 MT are different claims that happen
    to share a numeral.
    """
    value: object = fact.numeric_value
    if isinstance(value, Decimal):
        # Normalised so 500 and 500.00 are one claim rather than two.
        value = value.normalize()
    return (value, fact.unit, fact.currency, None if value is not None else fact.literal)


def select_one(
    fact_type: str, facts: list[ExtractedFact], documents: dict[uuid.UUID, Document]
) -> Selected:
    """Choose the fact of ``fact_type`` that current reconciliation should use.

    Args:
        fact_type: What is being selected, for the reason string.
        facts: Every candidate, from every document and extractor version.
        documents: The documents those facts came from, for their version state. A fact whose
            document is absent from this mapping is excluded — an unknown provenance is not an
            authority.
    """
    superseded: list[ExtractedFact] = []
    active: list[ExtractedFact] = []
    for fact in facts:
        document = documents.get(fact.document_id)
        # Retracted rows join the excluded rather than being dropped: the row is history, and a
        # caller reporting why nothing was selected should be able to say something was withdrawn
        # rather than that nothing was ever stated.
        withdrawn = fact.is_retracted
        stale = document is None or not document.version_state.is_current
        if withdrawn or stale:
            superseded.append(fact)
        else:
            active.append(fact)

    candidates = _newest_per_claim(active)

    if not candidates:
        excluded_states = sorted(
            {
                (
                    "retracted"
                    if fact.is_retracted
                    else (
                        documents[fact.document_id].version_state.value
                        if fact.document_id in documents
                        else "unknown provenance"
                    )
                )
                for fact in superseded
            }
        )
        reason = (
            f"no active document states {fact_type}"
            if not superseded
            else f"{fact_type} is stated only by documents that are "
            f"{', '.join(excluded_states)}"
        )
        return Selected(
            fact_type=fact_type,
            fact=None,
            considered=(),
            excluded=tuple(superseded),
            reason=reason,
        )

    if len(candidates) == 1:
        return Selected(
            fact_type=fact_type,
            fact=candidates[0],
            considered=tuple(candidates),
            excluded=tuple(superseded),
            reason=f"the only active document stating {fact_type}",
        )

    # How the candidates are spread, because the reason is read by a person deciding what to do
    # about it and the two situations need different actions. Counting candidates as documents was
    # accurate only while there was one candidate per document: a composite bill states 49 different
    # quantities for its item "1.3", and calling that "49 active documents" would be a false claim
    # about the evidence inside the very sentence written to explain the evidence.
    sources = {fact.document_id for fact in candidates}
    subject = (
        f"{len(sources)} active documents"
        if len(sources) > 1
        else f"{len(candidates)} rows of one document"
    )

    distinct = {_comparable(fact) for fact in candidates}
    if len(distinct) == 1:
        return Selected(
            fact_type=fact_type,
            fact=candidates[0],
            considered=tuple(candidates),
            excluded=tuple(superseded),
            reason=f"{subject} agree on {fact_type}",
        )

    # The case this module exists for.
    return Selected(
        fact_type=fact_type,
        fact=None,
        considered=tuple(candidates),
        excluded=tuple(superseded),
        reason=(
            f"{subject} state different values for {fact_type} and none supersedes the others, so "
            f"which governs cannot be determined"
            if len(sources) > 1
            # Not a document conflict: the item key is wrong. Said plainly, because the fix is to
            # tell these rows apart, not to reconcile two revisions.
            else f"{subject} state different values for {fact_type}, so which of those rows is "
            f"this item cannot be determined"
        ),
        conflicting=True,
    )


def select_facts(
    facts: list[ExtractedFact], documents: dict[uuid.UUID, Document]
) -> dict[str, Selected]:
    """Apply :func:`select_one` to every fact type present, keyed by type.

    Returns an entry for every type seen, including the unresolved ones — a caller must be able to
    tell "no such fact" from "several conflicting facts", because those warrant different findings.
    """
    grouped: dict[str, list[ExtractedFact]] = {}
    for fact in facts:
        grouped.setdefault(fact.fact_type, []).append(fact)
    return {
        fact_type: select_one(fact_type, candidates, documents)
        for fact_type, candidates in sorted(grouped.items())
    }
