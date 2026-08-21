"""Declare projects, upload into them, and keep a suggestion apart from a decision

Revision ID: 4a4f930da9cd
Revises: 75660b08c086
Created: 2026-08-21 23:21:50.261430+00:00

Four changes, and each one is a consequence of a project becoming something a person *declares*
rather than only something reconciliation derives:

``documents.type_authority``
    Who decided ``document_type``. The type gates whether the extractor treats a quoted amount as a
    fact about this document, so it has to carry its own warrant. Backfilled to ``declared`` by the
    server default, which is the truth: every row that existed before this column was typed by an
    operator at ingest.

``documents.suggested_document_type``
    What a classifier proposes, in its own column, so that a proposal cannot become a decision by
    being written to the same place.

``projects.description``
    What the project is, in the owner's words.

``projects.external_ref`` becomes nullable
    A developer declaring "Hostel 19" before uploading anything may have no reference number, and
    synthesising one would put an invented identifier in the one column whose contract is that it is
    never invented.

Downgrade must be implemented and must be tested. A migration that cannot be reversed is a
migration that cannot be safely deployed.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "4a4f930da9cd"
down_revision: str | None = "75660b08c086"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DOCUMENT_TYPES = (
    "tender_notice",
    "bid_document",
    "award_notice",
    "corrigendum",
    "purchase_order",
    "contract",
    "bill_of_quantities",
    "measurement_book",
    "running_bill",
    "schedule_of_rates",
    "change_order",
    "model_agreement",
    "audit_report",
    "technical_specification",
    "drawing",
    "inspection_report",
    "material_test_certificate",
    "invoice",
    "delivery_challan",
    "goods_receipt_note",
    "payment_certificate",
    "bank_guarantee",
    "unknown",
)


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column(
            "type_authority",
            sa.Enum(
                "declared",
                "human_confirmed",
                "deterministic_classifier",
                "model_suggestion",
                name="classificationauthority",
                native_enum=False,
                length=32,
            ),
            # Not nullable, and defaulted rather than backfilled by an UPDATE: an existing row's
            # type was declared by an operator, so 'declared' is a statement of fact about it rather
            # than a placeholder. The two reserved values below can only ever be written by a future
            # policy that does not exist yet.
            server_default=sa.text("'declared'"),
            nullable=False,
        ),
    )
    op.add_column(
        "documents",
        sa.Column(
            "suggested_document_type",
            sa.Enum(
                *_DOCUMENT_TYPES,
                name="documenttype",
                native_enum=False,
                length=48,
            ),
            nullable=True,
        ),
    )
    op.add_column("projects", sa.Column("description", sa.Text(), nullable=True))
    op.alter_column("projects", "external_ref", existing_type=sa.VARCHAR(length=256), nullable=True)


def downgrade() -> None:
    # A declared project may legitimately have no identifier, and this column becomes NOT NULL
    # again. There is no honest automatic answer: filling it would invent an identifier in the
    # column that exists precisely because identifiers are never invented, and deleting the rows
    # would destroy a project and cascade away its memberships. So the downgrade refuses, and says
    # what to do about it. On an empty or reconciled database it reverses cleanly, which is what the
    # migration test exercises.
    undeclared = (
        op.get_bind()
        .execute(sa.text("SELECT count(*) FROM projects WHERE external_ref IS NULL"))
        .scalar_one()
    )
    if undeclared:
        raise RuntimeError(
            f"{undeclared} project(s) have no external_ref, which this downgrade would have to "
            f"invent or delete. Give each one the identifier its documents state, or remove the "
            f"project deliberately, then downgrade again."
        )
    op.alter_column(
        "projects", "external_ref", existing_type=sa.VARCHAR(length=256), nullable=False
    )
    op.drop_column("projects", "description")
    op.drop_column("documents", "suggested_document_type")
    op.drop_column("documents", "type_authority")
