"""reviews.precedent_review_id — precedent fast-track provenance

Revision ID: 0008_precedent
Revises: 0007_model_regions
Create Date: 2026-07-01

Idempotent: fresh DBs (0001 baseline from ORM metadata) already have the column.
"""
import sqlalchemy as sa
from alembic import op

from app.models.base import GUID

revision = "0008_precedent"
down_revision = "0007_model_regions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    cols = {c["name"] for c in sa.inspect(bind).get_columns("reviews")}
    if "precedent_review_id" not in cols:
        op.add_column(
            "reviews",
            sa.Column("precedent_review_id", GUID(), sa.ForeignKey("reviews.id"), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    cols = {c["name"] for c in sa.inspect(bind).get_columns("reviews")}
    if "precedent_review_id" in cols:
        op.drop_column("reviews", "precedent_review_id")
