"""Governance policy: the admin-editable inputs the auto-answer engine uses.

Currently the approved data-residency regions, keyed by cloud
({"azure": [...], "gcp": [...]}). Stored as a single GovernancePolicy row
(created with defaults on first access); a DiscoverySource may override its
cloud's list via config["approved_regions"] (a list for that source's cloud, or
a per-cloud dict).
"""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import DiscoverySource, GovernancePolicy, Model, utcnow
from app.services import audit
from app.services.autoanswer import DEFAULT_APPROVED_REGIONS, Policy

KNOWN_CLOUDS = ("azure", "gcp")


def _default_regions() -> dict[str, list[str]]:
    return {cloud: sorted(regions) for cloud, regions in DEFAULT_APPROVED_REGIONS.items()}


def get_policy(db: Session) -> GovernancePolicy:
    """Return the singleton policy row, creating it with defaults if absent."""
    policy = db.execute(select(GovernancePolicy).limit(1)).scalar_one_or_none()
    if policy is None:
        policy = GovernancePolicy(approved_regions=_default_regions())
        db.add(policy)
        db.flush()
    return policy


def _clean_regions(regions) -> list[str]:
    """Strip/dedupe/sort a list of region strings; ignore non-list / non-str."""
    if not isinstance(regions, list):
        return []
    return sorted({r.strip() for r in regions if isinstance(r, str) and r.strip()})


def _clean_provided(approved_regions: dict) -> dict[str, list[str]]:
    """Clean only the known clouds actually present in the payload."""
    return {
        cloud: _clean_regions(approved_regions[cloud])
        for cloud in KNOWN_CLOUDS
        if cloud in approved_regions
    }


def update_policy(
    db: Session, *, approved_regions: dict, actor_id: uuid.UUID, request_ip: str | None = None
) -> GovernancePolicy:
    policy = get_policy(db)
    before = dict(policy.approved_regions)
    # Merge onto the current policy: a cloud omitted from the payload keeps its
    # current value (a partial PUT must not silently wipe the other cloud); a
    # cloud sent with [] explicitly clears it.
    merged = {c: list((policy.approved_regions or {}).get(c) or []) for c in KNOWN_CLOUDS}
    merged.update(_clean_provided(approved_regions))
    policy.approved_regions = merged
    policy.updated_by_id = actor_id
    db.flush()
    audit.record(
        db,
        action="policy_updated",
        entity_type="governance_policy",
        entity_id=policy.id,
        actor_id=actor_id,
        before={"approved_regions": before},
        after={"approved_regions": policy.approved_regions},
        request_ip=request_ip,
    )
    return policy


def mark_framework_reviewed(
    db: Session,
    *,
    actor_id: uuid.UUID,
    notes: str | None = None,
    interval_days: int | None = None,
    request_ip: str | None = None,
) -> GovernancePolicy:
    """Record that an admin has confirmed the questionnaire still matches NIST."""
    policy = get_policy(db)
    before = {
        "last_reviewed_at": policy.framework_last_reviewed_at.isoformat()
        if policy.framework_last_reviewed_at
        else None,
        "interval_days": policy.framework_review_interval_days,
    }
    policy.framework_last_reviewed_at = utcnow()
    policy.framework_reviewed_by_id = actor_id
    if notes is not None:
        policy.framework_review_notes = notes
    if interval_days is not None and interval_days > 0:
        policy.framework_review_interval_days = interval_days
    db.flush()
    audit.record(
        db,
        action="framework_reviewed",
        entity_type="governance_policy",
        entity_id=policy.id,
        actor_id=actor_id,
        before=before,
        after={
            "last_reviewed_at": policy.framework_last_reviewed_at.isoformat(),
            "interval_days": policy.framework_review_interval_days,
            "notes": policy.framework_review_notes,
        },
        request_ip=request_ip,
    )
    return policy


def resolve_policy(db: Session, model: Model) -> Policy:
    """Resolve the effective per-cloud Policy for a model (source override or global)."""
    regions: dict = {c: list((get_policy(db).approved_regions or {}).get(c) or []) for c in KNOWN_CLOUDS}
    if model.discovery_source_id is not None:
        source = db.get(DiscoverySource, model.discovery_source_id)
        override = source.config.get("approved_regions") if (source and source.config) else None
        # A source may only override its OWN cloud, and the values go through the
        # same normalization as the admin PUT (strip/dedupe; ignore bad types).
        if source and source.cloud in KNOWN_CLOUDS and override is not None:
            if isinstance(override, dict):
                override = override.get(source.cloud)
            if isinstance(override, list):
                regions[source.cloud] = _clean_regions(override)
    return Policy({cloud: frozenset(v) for cloud, v in regions.items()})
