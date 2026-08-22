"""Spreadsheet cells become navigable evidence

Revision ID: 56d2a75f13b1
Revises: 4a4f930da9cd
Created: 2026-08-22 00:53:00.000000+00:00

Adds ``extracted_facts.sheet_name``, and backfills it from where the value had been all along.

The row and column of a spreadsheet fact were already stored; the sheet name was not, surviving only
inside ``snippet`` (``BOQ!D7``) and ``method`` (``cell:BOQ!D7``). The consequence was product-shaped
rather than cosmetic: a PDF fact could be opened at its page, while a fact from a spreadsheet — the
format the extractor-precedence rules call the *strongest* evidence available, because a spreadsheet
already carries rows, columns and cell positions — could not be opened at its cell without a client
parsing prose written for a human.

Downgrade must be implemented and must be tested. A migration that cannot be reversed is a
migration that cannot be safely deployed.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "56d2a75f13b1"
down_revision: str | None = "4a4f930da9cd"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("extracted_facts", sa.Column("sheet_name", sa.String(length=128), nullable=True))
    # Recover the sheet name from the snippet, which for a cell fact is exactly the reference the
    # extractor built: ``<sheet>!<column><row>``. Restricted to rows that have a grid position, so a
    # prose snippet containing an exclamation mark cannot be mistaken for a cell reference. Excel
    # does not permit ``!`` in a sheet name, so the first one is the separator.
    op.execute(
        sa.text(
            "UPDATE extracted_facts "
            "SET sheet_name = split_part(snippet, '!', 1) "
            "WHERE sheet_row IS NOT NULL AND position('!' in snippet) > 1"
        )
    )


def downgrade() -> None:
    # Nothing is lost that cannot be recovered: the same value remains in every affected row's
    # snippet and method, which is what the backfill above reads.
    op.drop_column("extracted_facts", "sheet_name")
