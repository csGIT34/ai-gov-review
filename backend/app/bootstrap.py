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
    s = get_settings()
    live = {
        "azure": _ensure_live_source(
            db, cloud="azure",
            is_live=s.azure_discovery.lower() == "live",
            scope=s.azure_subscription_id,
            live_name=f"Azure ({(s.azure_subscription_id or '')[:8]}…)",
            demo_name="Azure (demo)",
        ),
        "gcp": _ensure_live_source(
            db, cloud="gcp",
            is_live=s.gcp_discovery.lower() == "live",
            scope=s.gcp_project_id,
            live_name=f"GCP ({s.gcp_project_id})",
            demo_name="GCP (demo)",
        ),
    }
    for spec in _DEFAULT_SOURCES:
        if live.get(spec["cloud"]):
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


def _ensure_live_source(
    db: Session, *, cloud: str, is_live: bool, scope: str | None,
    live_name: str, demo_name: str
) -> bool:
    """When live discovery is on for a cloud, convert the seeded demo source
    into the real-scope source (or create it on a fresh DB). Only rows this app
    seeded/generated are touched — user-created sources are left alone.
    Returns True when live mode manages that cloud's source."""
    if not is_live or not scope:
        return False
    rows = list(
        db.execute(
            select(DiscoverySource).where(DiscoverySource.cloud == cloud)
        ).scalars()
    )
    converted = False
    for src in rows:
        if src.display_name in (demo_name, live_name):
            src.scope = scope
            src.display_name = live_name
            converted = True
    if not converted and not any(src.scope == scope for src in rows):
        db.add(
            DiscoverySource(cloud=cloud, display_name=live_name, scope=scope, enabled=True)
        )
    db.commit()
    return True


def seed_dev_data(db: Session) -> None:
    seed_dev_users(db)
    seed_default_sources(db)
    # Ensure the governance policy row exists (seeded with default regions).
    from app.services.policy import get_policy

    get_policy(db)
    _backfill_precedents(db)
    db.commit()


def _backfill_precedents(db: Session) -> None:
    """Mint precedent rows for reviews approved before the standalone
    precedents table existed. Idempotent (mint_from_review dedups on
    source_review_id and skips terms-less models)."""
    from app.models import Review, ReviewState
    from app.services import precedent as precedent_svc
    from app.services.review_workflow import current_score

    approved = db.execute(
        select(Review).where(
            Review.state.in_(
                (ReviewState.APPROVED.value, ReviewState.APPROVED_WITH_CONDITIONS.value)
            )
        )
    ).scalars()
    for review in approved:
        score = current_score(db, review)
        precedent_svc.mint_from_review(
            db,
            review=review,
            tier=score.tier if score else None,
            score=score.overall_score if score else None,
        )
