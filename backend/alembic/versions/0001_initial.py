"""initial schema (baseline from ORM metadata)

Revision ID: 0001_initial
Revises:
Create Date: 2026-06-30

Baseline created directly from the ORM metadata so the models are the single
source of truth (no hand-maintained DDL to drift). Subsequent revisions use
normal Alembic operations.
"""
from alembic import op

# Registers all tables on Base.metadata.
import app.models  # noqa: F401
from app.models import Base

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.create_all(op.get_bind())


def downgrade() -> None:
    Base.metadata.drop_all(op.get_bind())
