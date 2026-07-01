"""governance_policy: framework review-freshness columns

Revision ID: 0006_framework_review
Revises: 0005_policy_per_cloud
Create Date: 2026-06-30

Idempotent: the 0001 baseline is generated from live ORM metadata, so a fresh DB
already has these columns — add them only where missing (existing deployments).
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

from app.models.base import GUID

revision = "0006_framework_review"
down_revision = "0005_policy_per_cloud"
branch_labels = None
depends_on = None

_COLUMNS = [
    ("framework_last_reviewed_at", sa.DateTime(timezone=True), {"nullable": True}),
    ("framework_reviewed_by_id", GUID(), {"nullable": True}),
    ("framework_review_interval_days", sa.Integer(), {"nullable": False, "server_default": "180"}),
    ("framework_review_notes", sa.Text(), {"nullable": True}),
]


def upgrade() -> None:
    have = {c["name"] for c in inspect(op.get_bind()).get_columns("governance_policy")}
    for name, type_, kwargs in _COLUMNS:
        if name not in have:
            op.add_column("governance_policy", sa.Column(name, type_, **kwargs))


def downgrade() -> None:
    for name, _type, _kw in _COLUMNS:
        op.drop_column("governance_policy", name)
