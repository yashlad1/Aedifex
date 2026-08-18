"""add document_retrievals

Append-only provenance: one row per successful retrieval, holding both URLs, the HTTP metadata, the
attempt history, and where the bytes were stored. See the class docstring in
``infrastructure/database/models.py`` for why this is neither a column on ``documents`` nor one on
``discovered_urls``.

Additive only — a new table, no changes to existing ones — so the downgrade is a clean drop and
applying this to a populated database cannot lose anything.

Revision ID: eafcd4f12f6b
Revises: 0001_initial
Created: 2026-08-18 21:01:24.373235+00:00

Downgrade must be implemented and must be tested. A migration that cannot be reversed is a
migration that cannot be safely deployed.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "eafcd4f12f6b"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "document_retrievals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("source_id", sa.String(length=64), nullable=False),
        sa.Column("requested_url", sa.Text(), nullable=False),
        sa.Column("final_url", sa.Text(), nullable=False),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("http_status", sa.Integer(), nullable=False),
        sa.Column("http_version", sa.String(length=16), nullable=False),
        sa.Column("response_headers", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("declared_media_type", sa.String(length=128), nullable=True),
        sa.Column("declared_content_length", sa.BigInteger(), nullable=True),
        sa.Column("attempts", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("storage_bucket", sa.String(length=64), nullable=False),
        sa.Column("storage_key", sa.String(length=512), nullable=False),
        sa.Column("storage_version_id", sa.String(length=128), nullable=True),
        sa.Column("storage_verification", sa.String(length=32), nullable=False),
        sa.Column("software_version", sa.String(length=32), nullable=False),
        sa.CheckConstraint(
            "storage_verification IN ('server_checksum', 'size_and_metadata')",
            name=op.f("ck_document_retrievals_verification_is_known"),
        ),
        sa.CheckConstraint(
            "attempt_count >= 1", name=op.f("ck_document_retrievals_at_least_one_attempt")
        ),
        sa.CheckConstraint(
            "http_status BETWEEN 100 AND 599",
            name=op.f("ck_document_retrievals_http_status_in_range"),
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name=op.f("fk_document_retrievals_document_id_documents"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document_retrievals")),
    )
    op.create_index(
        op.f("ix_document_retrievals_document_id"),
        "document_retrievals",
        ["document_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_document_retrievals_retrieved_at"),
        "document_retrievals",
        ["retrieved_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_document_retrievals_source_id"), "document_retrievals", ["source_id"], unique=False
    )
    op.create_index(
        "ix_document_retrievals_source_retrieved",
        "document_retrievals",
        ["source_id", "retrieved_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_document_retrievals_source_retrieved", table_name="document_retrievals")
    op.drop_index(op.f("ix_document_retrievals_source_id"), table_name="document_retrievals")
    op.drop_index(op.f("ix_document_retrievals_retrieved_at"), table_name="document_retrievals")
    op.drop_index(op.f("ix_document_retrievals_document_id"), table_name="document_retrievals")
    op.drop_table("document_retrievals")
