"""governance_policy table (admin-editable auto-answer policy)

Revision ID: 0004_governance_policy
Revises: 0003_autoanswer
Create Date: 2026-06-30

Idempotent: the 0001 baseline is generated from live ORM metadata, so a fresh DB
already has this table — create it only where missing (existing deployments).
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

from app.models.base import GUID

revision = "0004_governance_policy"
down_revision = "0003_autoanswer"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "governance_policy" in inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "governance_policy",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("approved_regions", sa.JSON(), nullable=False),
        sa.Column("updated_by_id", GUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("governance_policy")
