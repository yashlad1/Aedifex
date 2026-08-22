"""Bind reviews to the conclusion they reviewed, and record uploads as events

Revision ID: 5c7848cd2c71
Revises: 56d2a75f13b1
Created: 2026-08-22 01:37:06.703725+00:00

Four changes, from an independent review of the repository. Each is a correctness fix rather than a
feature, and each has a failure mode that is silent.

``findings.conclusion_fingerprint`` and ``finding_reviews.reviewed_fingerprint``
    A review was bound to the finding's ``outcome`` and ``rule_version`` only, so a re-read that
    changed the values while leaving the verdict alone kept the old acceptance:

        reviewed:  FAIL  claim 520 m3 exceeds the measured 470 m3   accepted
        re-read:   FAIL  claim 900 m3 exceeds the measured 470 m3   still "accepted"

    Both sides now carry a digest of the whole conclusion. **Both default to the empty string, and
    that is the backfill:** an existing review's blank fingerprint equals its finding's blank
    fingerprint, so every stored review keeps exactly the status it had before this migration. The
    first re-analysis of a finding writes a real digest, at which point a review of the older
    conclusion goes stale — which is the intended behaviour, since nobody has read the new one.

    Deliberately no Python here. Computing real digests would mean importing application code into a
    migration, and a migration whose output depends on a function that is still evolving is not
    reproducible. Recomputing them is a data-maintenance step, and this is the recipe — it preserves
    each review's status exactly, because only the reviews that were current under the previous
    comparison are given the finding's new digest:

    .. code-block:: python

        for finding in session.execute(
            select(Finding).options(
                selectinload(Finding.reviews), selectinload(Finding.evidence)
            )
        ).scalars():
            finding.conclusion_fingerprint = finding.compute_fingerprint()
            for review in finding.reviews:
                if (
                    review.reviewed_outcome == finding.outcome
                    and review.reviewed_rule_version == finding.rule_version
                ):
                    review.reviewed_fingerprint = finding.conclusion_fingerprint

    Run against this repository's own database on 2026-08-22: 310 findings fingerprinted, 5 reviews
    kept current, none made stale.

``document_uploads`` unique key widened
    From ``(document_id, source_id)`` to ``(document_id, source_id, uploaded_by, original_path)``.
    An upload is an event, and the narrow key was tolerable only while every source had one
    operator. With a shared ``customer_provided`` source, two customers uploading identical bytes —
    a contractor's bill sent to both the owner and the PMC — collapsed into whichever arrived first,
    discarding the second uploader, filename, timestamp and note. Widening never merges rows; the
    upgrade is safe on any existing data.

``project_documents.filename``
    What *this* project's uploader called the file. ``documents.original_filename`` is
    content-level, so with content-addressed identity a second project uploading the same bytes was
    shown the first project's filename — one customer's naming inside another customer's project.

``finding_reviews.reviewed_at`` default
    ``clock_timestamp()`` rather than ``now()``. ``now()`` is the transaction's start time, so two
    reviews written in one transaction shared a timestamp and their order — which decides *which one
    is current* — was left to the query planner.

Downgrade must be implemented and must be tested. A migration that cannot be reversed is a
migration that cannot be safely deployed.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "5c7848cd2c71"
down_revision: str | None = "56d2a75f13b1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "findings",
        sa.Column(
            "conclusion_fingerprint",
            sa.String(length=64),
            nullable=False,
            server_default=sa.text("''"),
        ),
    )
    op.add_column(
        "finding_reviews",
        sa.Column(
            "reviewed_fingerprint",
            sa.String(length=64),
            nullable=False,
            server_default=sa.text("''"),
        ),
    )
    op.alter_column(
        "finding_reviews",
        "reviewed_at",
        existing_type=sa.TIMESTAMP(timezone=True),
        existing_nullable=False,
        server_default=sa.text("clock_timestamp()"),
    )
    op.add_column("project_documents", sa.Column("filename", sa.String(length=128), nullable=True))
    # Widening a unique key can never fail on existing data: every row that satisfied the narrow
    # constraint satisfies the wider one.
    op.drop_constraint("one_upload_per_document_and_source", "document_uploads", type_="unique")
    op.create_unique_constraint(
        "one_upload_per_document_source_and_uploader",
        "document_uploads",
        ["document_id", "source_id", "uploaded_by", "original_path"],
    )


def downgrade() -> None:
    # Narrowing the key *can* fail, and must not silently discard provenance to succeed. If two
    # upload events exist for one document and source — two customers who supplied the same bytes —
    # there is no honest automatic answer, so this refuses and says which rows are in the way.
    duplicates = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT count(*) FROM ("
                "  SELECT document_id, source_id FROM document_uploads"
                "  GROUP BY document_id, source_id HAVING count(*) > 1"
                ") AS collisions"
            )
        )
        .scalar_one()
    )
    if duplicates:
        raise RuntimeError(
            f"{duplicates} (document, source) pair(s) hold more than one upload event, which the "
            f"narrower constraint cannot represent. Decide which event to keep and remove the "
            f"others deliberately, then downgrade again."
        )
    op.drop_constraint(
        "one_upload_per_document_source_and_uploader", "document_uploads", type_="unique"
    )
    op.create_unique_constraint(
        "one_upload_per_document_and_source",
        "document_uploads",
        ["document_id", "source_id"],
    )
    op.drop_column("project_documents", "filename")
    op.alter_column(
        "finding_reviews",
        "reviewed_at",
        existing_type=sa.TIMESTAMP(timezone=True),
        existing_nullable=False,
        server_default=sa.text("now()"),
    )
    op.drop_column("finding_reviews", "reviewed_fingerprint")
    op.drop_column("findings", "conclusion_fingerprint")
