"""auto-answer columns: models.facts + control_responses provenance

Revision ID: 0003_autoanswer
Revises: 0002_audit_append_only
Create Date: 2026-06-30

Idempotent: the 0001 baseline is generated from live ORM metadata, so a fresh DB
already has these columns — we add them only where missing (existing deployments).
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "0003_autoanswer"
down_revision = "0002_audit_append_only"
branch_labels = None
depends_on = None


def _cols(table: str) -> set[str]:
    return {c["name"] for c in inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    have = _cols("models")
    if "facts" not in have:
        op.add_column("models", sa.Column("facts", sa.JSON(), nullable=True))

    have = _cols("control_responses")
    additions = [
        ("answer_source", sa.String(length=20)),
        ("auto_answer", sa.String(length=10)),
        ("auto_rationale", sa.Text()),
        ("auto_confidence", sa.String(length=10)),
    ]
    for name, type_ in additions:
        if name not in have:
            op.add_column("control_responses", sa.Column(name, type_, nullable=True))


def downgrade() -> None:
    for name in ("answer_source", "auto_answer", "auto_rationale", "auto_confidence"):
        op.drop_column("control_responses", name)
    op.drop_column("models", "facts")
