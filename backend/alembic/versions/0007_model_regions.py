"""models.region (scalar) -> models.regions (list footprint)

Revision ID: 0007_model_regions
Revises: 0006_framework_review
Create Date: 2026-06-30

A model is deployed across many regions, so its residency footprint is a list.
Idempotent: fresh DBs (0001 baseline from ORM metadata) already have `regions`
and no `region`, so this is a no-op there; existing DBs get `regions` added,
back-filled from the scalar `region`, then `region` dropped.
"""
import sqlalchemy as sa
from alembic import op

revision = "0007_model_regions"
down_revision = "0006_framework_review"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    cols = {c["name"] for c in sa.inspect(bind).get_columns("models")}
    if "regions" not in cols:
        op.add_column("models", sa.Column("regions", sa.JSON(), nullable=True))
    if "region" in cols:
        meta = sa.MetaData()
        m = sa.Table("models", meta, autoload_with=bind)
        for mid, region in bind.execute(sa.select(m.c.id, m.c.region)).fetchall():
            bind.execute(m.update().where(m.c.id == mid).values(regions=[region] if region else []))
        op.drop_column("models", "region")


def downgrade() -> None:
    bind = op.get_bind()
    cols = {c["name"] for c in sa.inspect(bind).get_columns("models")}
    if "region" not in cols:
        op.add_column("models", sa.Column("region", sa.String(length=100), nullable=True))
    if "regions" in cols:
        meta = sa.MetaData()
        m = sa.Table("models", meta, autoload_with=bind)
        for mid, regions in bind.execute(sa.select(m.c.id, m.c.regions)).fetchall():
            first = regions[0] if isinstance(regions, list) and regions else None
            bind.execute(m.update().where(m.c.id == mid).values(region=first))
        op.drop_column("models", "regions")
