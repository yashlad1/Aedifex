"""Which reference provision governs which project, decided from evidence.

The first concrete instance of the problem ADR 0014 deferred, and deliberately no more general than
that instance needs. See ``docs/adr/0014-reference-data-by-explicit-applicability.md``.

Project facts stay isolated by default. A provision does not become visible to a project by being
marked global; it reaches one only when **two recorded facts match**:

* the provision's **authority**, read from the reference document's own text, equals the authority
  the project's documents were acquired from — which is provenance, not configuration; and
* the project's stated **estimated cost** falls inside the provision's band.

Both sides are evidence, so "why did this rule apply?" has an answer that cites two documents.

**Ambiguity is reported, never resolved.** Clause 4.14.1's bands, as the document writes them, both
contain exactly Rs. 20 crore: one says "up to Rs. 20 crore" and the next "between Rs. 20 crore to
Rs. 50 crore". A cost landing precisely there matches two provisions, and this module returns
neither. Picking the lower rate would favour the bidder, picking the higher would favour the
authority, and picking either would be Aedifex legislating where the document is silent.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select, union_all
from sqlalchemy.orm import Session

from aedifex.infrastructure.database.models import (
    DocumentRetrieval,
    DocumentUpload,
    PolicyProvision,
)

__all__ = ["ApplicableProvision", "select_provision"]


@dataclass(frozen=True, slots=True)
class ApplicableProvision:
    """The provision that governs a value, or why none does."""

    provision: PolicyProvision | None
    considered: tuple[PolicyProvision, ...]
    reason: str

    @property
    def resolved(self) -> bool:
        return self.provision is not None

    @property
    def ambiguous(self) -> bool:
        """Two or more provisions claim the same value. Reported, never resolved."""
        return self.provision is None and len(self.considered) > 1


def _authority_of(session: Session, document_id: uuid.UUID) -> str | None:
    """The source a document was acquired from, whichever way it arrived.

    A retrieval and an upload are different provenance and the same origin fact, so both are
    consulted — the same reason ``_document_origins`` exists in the projects module.
    """
    origins = union_all(
        select(
            DocumentRetrieval.document_id.label("document_id"),
            DocumentRetrieval.source_id.label("source_id"),
        ),
        select(
            DocumentUpload.document_id.label("document_id"),
            DocumentUpload.source_id.label("source_id"),
        ),
    ).subquery()
    return session.execute(
        select(origins.c.source_id).where(origins.c.document_id == document_id)
    ).scalar_one_or_none()


def _in_band(value: Decimal, provision: PolicyProvision) -> bool:
    """Whether ``value`` falls in the provision's band, with both bounds inclusive as written."""
    if provision.applies_from is not None and value < Decimal(provision.applies_from):
        return False
    return not (provision.applies_to_max is not None and value > Decimal(provision.applies_to_max))


def select_provision(
    session: Session,
    *,
    provision_type: str,
    document_id: uuid.UUID,
    value: Decimal,
    applies_to: str,
) -> ApplicableProvision:
    """The provision of ``provision_type`` that governs ``document_id``, given ``value``.

    Args:
        session: Open session.
        provision_type: e.g. ``bid_security_share``.
        document_id: The document being judged. Its acquisition source supplies the authority.
        value: The project's own figure the band is measured against.
        applies_to: The fact type ``value`` came from, matched against the provision's own
            ``applies_to`` so a band on estimated cost is never applied to some other quantity.
    """
    authority = _authority_of(session, document_id)
    if authority is None:
        return ApplicableProvision(
            provision=None,
            considered=(),
            reason="the document has no recorded acquisition source, so no authority governs it",
        )

    candidates = list(
        session.execute(
            select(PolicyProvision).where(
                PolicyProvision.provision_type == provision_type,
                PolicyProvision.authority == authority,
                PolicyProvision.applies_to == applies_to,
            )
        ).scalars()
    )
    if not candidates:
        return ApplicableProvision(
            provision=None,
            considered=(),
            reason=f"no {provision_type} provision of authority {authority!r} has been extracted",
        )

    # Newest extractor version only. Two readings of one clause are two readings, not two rules.
    newest = max(provision.extractor_version for provision in candidates)
    matching = sorted(
        (
            provision
            for provision in candidates
            if provision.extractor_version == newest and _in_band(value, provision)
        ),
        key=lambda provision: provision.clause,
    )

    if not matching:
        return ApplicableProvision(
            provision=None,
            considered=(),
            reason=(
                f"{value} falls outside every band stated by authority {authority!r} "
                f"for {provision_type}"
            ),
        )
    if len(matching) > 1:
        clauses = ", ".join(provision.clause for provision in matching)
        return ApplicableProvision(
            provision=None,
            considered=tuple(matching),
            reason=(
                f"{value} falls inside {len(matching)} bands at once ({clauses}); the document "
                f"does not say which governs, and choosing would invent policy"
            ),
        )

    chosen = matching[0]
    return ApplicableProvision(
        provision=chosen,
        considered=(chosen,),
        reason=(
            f"clause {chosen.clause} of authority {authority!r} covers {value} "
            f"and is the only band that does"
        ),
    )
