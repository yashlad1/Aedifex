"""add the frontier queue lease and run counters

Revision ID: 34a42436bb53
Revises: eafcd4f12f6b
Created: 2026-08-18 22:21:17.359662+00:00

Additive and reversible. Every new column is either nullable or carries a server default, so this
applies to a populated table without a rewrite and without a window where a row is invalid.

Two things autogenerate got wrong and are corrected by hand:

* The non-nullable integers were emitted with no ``server_default``, which fails on any table that
  already has rows. They now default to ``0`` in the database as well as in the model, which also
  means a hand-written ``INSERT`` cannot produce a null counter.
* ``ck_crawl_jobs_counters_non_negative`` was *modified* rather than added, and Alembic compares
  check constraints by name only, so no difference was detected. Left alone, the database would keep
  guarding the four original counters while the model claimed to guard seven — and a negative
  ``bytes_downloaded`` would have been accepted. It is dropped and recreated explicitly.

Constraint names go through ``op.f()``. Without it the metadata naming convention is applied to a
name that already follows the convention, and ``ck_crawl_jobs_counters_non_negative`` is dropped as
``ck_crawl_jobs_ck_crawl_jobs_counters_non_negative``.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "34a42436bb53"
down_revision: str | None = "eafcd4f12f6b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_COUNTERS = (
    "urls_discovered >= 0 AND documents_stored >= 0 "
    "AND documents_duplicate >= 0 AND documents_failed >= 0"
)
_NEW_COUNTERS = (
    "urls_discovered >= 0 AND urls_skipped >= 0 AND documents_stored >= 0 "
    "AND documents_duplicate >= 0 AND documents_failed >= 0 "
    "AND documents_quarantined >= 0 AND bytes_downloaded >= 0"
)


def upgrade() -> None:
    op.add_column(
        "crawl_jobs",
        sa.Column("urls_skipped", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column(
        "crawl_jobs",
        sa.Column(
            "documents_quarantined", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
    )
    op.add_column(
        "crawl_jobs",
        sa.Column("bytes_downloaded", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column("crawl_jobs", sa.Column("stop_reason", sa.String(length=64), nullable=True))

    op.drop_constraint(op.f("ck_crawl_jobs_counters_non_negative"), "crawl_jobs", type_="check")
    op.create_check_constraint(
        op.f("ck_crawl_jobs_counters_non_negative"), "crawl_jobs", _NEW_COUNTERS
    )

    op.add_column("discovered_urls", sa.Column("lease_owner", sa.String(length=64), nullable=True))
    op.add_column(
        "discovered_urls", sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "discovered_urls",
        sa.Column("next_attempt_after", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "discovered_urls", sa.Column("dead_lettered_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "discovered_urls",
        sa.Column("depth", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column("discovered_urls", sa.Column("discovered_via", sa.Text(), nullable=True))

    # Partial: dead-lettered rows are never claimed again, so they do not belong in the index the
    # claim walks. Ordered as the claim orders, so a frontier of millions is walked rather than
    # sorted.
    op.create_index(
        "ix_discovered_urls_claimable",
        "discovered_urls",
        ["source_id", "depth", "discovered_at"],
        unique=False,
        postgresql_where=sa.text("dead_lettered_at IS NULL"),
    )
    op.create_check_constraint(
        op.f("ck_discovered_urls_depth_non_negative"), "discovered_urls", "depth >= 0"
    )
    # A lease is an owner and an expiry together. Half a lease is either a row nobody will ever
    # reclaim or an expiry nobody owns.
    op.create_check_constraint(
        op.f("ck_discovered_urls_lease_is_whole"),
        "discovered_urls",
        "(lease_owner IS NULL) = (lease_expires_at IS NULL)",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_discovered_urls_lease_is_whole"), "discovered_urls", type_="check")
    op.drop_constraint(
        op.f("ck_discovered_urls_depth_non_negative"), "discovered_urls", type_="check"
    )
    op.drop_index(
        "ix_discovered_urls_claimable",
        table_name="discovered_urls",
        postgresql_where=sa.text("dead_lettered_at IS NULL"),
    )
    op.drop_column("discovered_urls", "discovered_via")
    op.drop_column("discovered_urls", "depth")
    op.drop_column("discovered_urls", "dead_lettered_at")
    op.drop_column("discovered_urls", "next_attempt_after")
    op.drop_column("discovered_urls", "lease_expires_at")
    op.drop_column("discovered_urls", "lease_owner")

    op.drop_constraint(op.f("ck_crawl_jobs_counters_non_negative"), "crawl_jobs", type_="check")
    op.create_check_constraint(
        op.f("ck_crawl_jobs_counters_non_negative"), "crawl_jobs", _OLD_COUNTERS
    )

    op.drop_column("crawl_jobs", "stop_reason")
    op.drop_column("crawl_jobs", "bytes_downloaded")
    op.drop_column("crawl_jobs", "documents_quarantined")
    op.drop_column("crawl_jobs", "urls_skipped")
