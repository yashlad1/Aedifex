"""finding reviews: the human decision on a finding

Revision ID: 75660b08c086
Revises: 6a234e15dd11
Created: 2026-08-21 22:33:28.425541+00:00

Downgrade must be implemented and must be tested. A migration that cannot be reversed is a
migration that cannot be safely deployed.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "75660b08c086"
down_revision: str | None = "6a234e15dd11"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "finding_reviews",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("finding_id", sa.Uuid(), nullable=False),
        sa.Column("decision", sa.String(length=24), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("reviewer", sa.String(length=128), nullable=False),
        sa.Column("reviewed_outcome", sa.String(length=16), nullable=False),
        sa.Column("reviewed_rule_version", sa.String(length=32), nullable=False),
        sa.Column(
            "reviewed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("software_version", sa.String(length=32), nullable=False),
        sa.CheckConstraint(
            "decision IN ('accepted', 'rejected', 'needs_evidence')",
            name=op.f("ck_finding_reviews_decision_is_known"),
        ),
        sa.CheckConstraint(
            "length(btrim(note)) > 0", name=op.f("ck_finding_reviews_note_is_not_blank")
        ),
        sa.CheckConstraint(
            "length(btrim(reviewer)) > 0", name=op.f("ck_finding_reviews_reviewer_is_not_blank")
        ),
        sa.ForeignKeyConstraint(
            ["finding_id"],
            ["findings.id"],
            name=op.f("fk_finding_reviews_finding_id_findings"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_finding_reviews")),
    )
    op.create_index("ix_finding_reviews_decision", "finding_reviews", ["decision"], unique=False)
    op.create_index(
        op.f("ix_finding_reviews_finding_id"), "finding_reviews", ["finding_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_finding_reviews_finding_id"), table_name="finding_reviews")
    op.drop_index("ix_finding_reviews_decision", table_name="finding_reviews")
    op.drop_table("finding_reviews")
