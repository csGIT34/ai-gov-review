"""Idempotent startup seeding (dev users + demo discovery sources)."""
from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.dev import seed_dev_users
from app.models import DiscoverySource

log = logging.getLogger("app.bootstrap")

# Demo sources so the dropdowns work out of the box. Real sources are added via
# POST /api/v1/discovery/sources (admin) once cloud drivers land (M5/M6).
_DEFAULT_SOURCES = [
    {"cloud": "azure", "display_name": "Azure (demo)", "scope": "DEMO-TENANT"},
    {"cloud": "gcp", "display_name": "GCP (demo)", "scope": "organizations/000000000000"},
]


def seed_default_sources(db: Session) -> None:
    for spec in _DEFAULT_SOURCES:
        exists = db.execute(
            select(DiscoverySource).where(
                DiscoverySource.cloud == spec["cloud"],
                DiscoverySource.display_name == spec["display_name"],
            )
        ).scalar_one_or_none()
        if exists is None:
            db.add(DiscoverySource(enabled=True, **spec))
    db.commit()


def seed_dev_data(db: Session) -> None:
    seed_dev_users(db)
    seed_default_sources(db)
