"""Standalone precedents table + review facts_snapshot; retire
reviews.precedent_review_id in favour of reviews.precedent_id.

Precedents decouple the fast-track from review records: a precedent is minted
when a review is approved, outlives that review, and is admin-managed. Reviews
gain a point-in-time snapshot of the CSP data their answers came from.

Idempotent: fresh DBs (0001 baseline from ORM metadata) already have the
table/columns. Existing adopted reviews' precedent_review_id values are dropped
(the audit log keeps the full adoption provenance); precedent rows for existing
approved reviews are backfilled at bootstrap, not here.

Revision ID: 0009_precedents_table
Revises: 0008_precedent
Create Date: 2026-07-02
"""
import sqlalchemy as sa
from alembic import op

from app.models.base import GUID

revision = "0009_precedents_table"
down_revision = "0008_precedent"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "precedents" not in inspector.get_table_names():
        op.create_table(
            "precedents",
            sa.Column("id", GUID(), primary_key=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("vendor", sa.String(100), nullable=False, index=True),
            sa.Column("cloud", sa.String(20), nullable=False),
            sa.Column("terms", sa.JSON(), nullable=False),
            sa.Column("questionnaire_version", sa.Integer(), nullable=False),
            sa.Column("model_name", sa.String(200), nullable=False),
            sa.Column("model_version", sa.String(100), nullable=True),
            sa.Column("decision_state", sa.String(40), nullable=False),
            sa.Column("tier", sa.Integer(), nullable=True),
            sa.Column("score", sa.Float(), nullable=True),
            sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("source_review_id", GUID(), nullable=True),
            sa.Column("created_by_id", GUID(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("answers", sa.JSON(), nullable=False),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        )

    cols = {c["name"] for c in inspector.get_columns("reviews")}
    if "precedent_id" not in cols:
        op.add_column("reviews", sa.Column("precedent_id", GUID(), nullable=True))
    if "facts_snapshot" not in cols:
        op.add_column("reviews", sa.Column("facts_snapshot", sa.JSON(), nullable=True))
    if "precedent_review_id" in cols:
        op.drop_column("reviews", "precedent_review_id")


def downgrade() -> None:
    op.add_column(
        "reviews",
        sa.Column("precedent_review_id", GUID(), sa.ForeignKey("reviews.id"), nullable=True),
    )
    op.drop_column("reviews", "facts_snapshot")
    op.drop_column("reviews", "precedent_id")
    op.drop_table("precedents")
