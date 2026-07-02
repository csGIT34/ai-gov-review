"""Idempotent startup seeding (dev users + demo discovery sources)."""
from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.dev import seed_dev_users
from app.config import get_settings
from app.models import DiscoverySource

log = logging.getLogger("app.bootstrap")

# Demo sources so the dropdowns work out of the box. Real sources are added via
# POST /api/v1/discovery/sources (admin) once cloud drivers land (M5/M6).
_DEFAULT_SOURCES = [
    {"cloud": "azure", "display_name": "Azure (demo)", "scope": "DEMO-TENANT"},
    {"cloud": "gcp", "display_name": "GCP (demo)", "scope": "organizations/000000000000"},
]


def seed_default_sources(db: Session) -> None:
    live_azure = _ensure_live_azure_source(db)
    for spec in _DEFAULT_SOURCES:
        if spec["cloud"] == "azure" and live_azure:
            continue  # the live source replaces the demo row; don't re-seed it
        exists = db.execute(
            select(DiscoverySource).where(
                DiscoverySource.cloud == spec["cloud"],
                DiscoverySource.display_name == spec["display_name"],
            )
        ).scalar_one_or_none()
        if exists is None:
            db.add(DiscoverySource(enabled=True, **spec))
    db.commit()


def _ensure_live_azure_source(db: Session) -> bool:
    """When live Azure discovery is on, convert the seeded demo source into the
    real-subscription source (or create it on a fresh DB). Only rows this app
    seeded/generated are touched — user-created sources are left alone.
    Returns True when live mode manages the azure source."""
    s = get_settings()
    if s.azure_discovery.lower() != "live" or not s.azure_subscription_id:
        return False
    live_name = f"Azure ({s.azure_subscription_id[:8]}…)"
    rows = list(
        db.execute(
            select(DiscoverySource).where(DiscoverySource.cloud == "azure")
        ).scalars()
    )
    converted = False
    for src in rows:
        if src.display_name in ("Azure (demo)", live_name):
            src.scope = s.azure_subscription_id
            src.display_name = live_name
            converted = True
    if not converted and not any(src.scope == s.azure_subscription_id for src in rows):
        db.add(
            DiscoverySource(
                cloud="azure",
                display_name=live_name,
                scope=s.azure_subscription_id,
                enabled=True,
            )
        )
    db.commit()
    return True


def seed_dev_data(db: Session) -> None:
    seed_dev_users(db)
    seed_default_sources(db)
    # Ensure the governance policy row exists (seeded with default regions).
    from app.services.policy import get_policy

    get_policy(db)
    db.commit()
