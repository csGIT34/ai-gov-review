"""governance_policy.approved_regions: flat list -> per-cloud dict

Revision ID: 0005_policy_per_cloud
Revises: 0004_governance_policy
Create Date: 2026-06-30

Data migration only (the column is JSON). Any existing row whose approved_regions
is a flat list is split into {"azure": [...], "gcp": [...]} by naming convention
(GCP region names are hyphenated, Azure names are not). Idempotent: dict values
are left untouched.
"""
import sqlalchemy as sa
from alembic import op

revision = "0005_policy_per_cloud"
down_revision = "0004_governance_policy"
branch_labels = None
depends_on = None


def _split(regions: list) -> dict:
    # Normalize like policy._clean (strip/dedupe) so migrated legacy values match
    # real region strings; GCP names are hyphenated, Azure names are not.
    azure, gcp = set(), set()
    for r in regions:
        if not isinstance(r, str) or not r.strip():
            continue
        s = r.strip()
        (gcp if "-" in s else azure).add(s)
    return {"azure": sorted(azure), "gcp": sorted(gcp)}


def upgrade() -> None:
    bind = op.get_bind()
    if "governance_policy" not in sa.inspect(bind).get_table_names():
        return
    meta = sa.MetaData()
    gp = sa.Table("governance_policy", meta, autoload_with=bind)
    for row in bind.execute(sa.select(gp.c.id, gp.c.approved_regions)).fetchall():
        pid, regions = row
        if isinstance(regions, list):
            bind.execute(
                gp.update().where(gp.c.id == pid).values(approved_regions=_split(regions))
            )


def downgrade() -> None:
    bind = op.get_bind()
    if "governance_policy" not in sa.inspect(bind).get_table_names():
        return
    meta = sa.MetaData()
    gp = sa.Table("governance_policy", meta, autoload_with=bind)
    for row in bind.execute(sa.select(gp.c.id, gp.c.approved_regions)).fetchall():
        pid, regions = row
        if isinstance(regions, dict):
            flat = sorted({r for lst in regions.values() for r in (lst or [])})
            bind.execute(gp.update().where(gp.c.id == pid).values(approved_regions=flat))
