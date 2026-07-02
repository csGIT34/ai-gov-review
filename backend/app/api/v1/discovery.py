"""Cascading discovery endpoints that populate the review dropdowns.

Flow: GET /sources -> GET /sources/{id}/vendors -> .../vendors/{vendor}/models.
Pull-based and cached; real Azure/GCP drivers replace the stub in M5/M6.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import client_ip, db_session, get_current_user, require_admin
from app.discovery import driver_for, resolve_mode
from app.discovery.base import VALID_MODES, discovery_cache
from app.models import DiscoverySource, User
from app.schemas import DiscoveredModelOut, SourceCreate, SourceOut, SourceUpdate
from app.services import audit
from app.services.errors import ValidationError
from app.services.policy import driver_config

router = APIRouter(prefix="/discovery", tags=["discovery"])


def _get_source(db: Session, source_id: uuid.UUID) -> DiscoverySource:
    source = db.get(DiscoverySource, source_id)
    if source is None or not source.enabled:
        raise HTTPException(status_code=404, detail="Discovery source not found or disabled")
    return source


@router.get("/sources", response_model=list[SourceOut])
def list_sources(
    include_disabled: bool = False,
    db: Session = Depends(db_session),
    _: User = Depends(get_current_user),
) -> list[DiscoverySource]:
    stmt = select(DiscoverySource).order_by(DiscoverySource.cloud, DiscoverySource.display_name)
    if not include_disabled:
        stmt = stmt.where(DiscoverySource.enabled.is_(True))
    return list(db.execute(stmt).scalars())


@router.post("/sources", response_model=SourceOut, status_code=status.HTTP_201_CREATED)
def create_source(
    payload: SourceCreate,
    db: Session = Depends(db_session),
    _: User = Depends(require_admin),
) -> DiscoverySource:
    source = DiscoverySource(
        cloud=payload.cloud,
        display_name=payload.display_name,
        scope=payload.scope,
        credential_ref=payload.credential_ref,
        config=payload.config,
        enabled=True,
    )
    db.add(source)
    db.commit()
    db.refresh(source)
    return source


@router.patch("/sources/{source_id}", response_model=SourceOut)
def update_source(
    source_id: uuid.UUID,
    payload: SourceUpdate,
    request: Request,
    db: Session = Depends(db_session),
    user: User = Depends(require_admin),
) -> DiscoverySource:
    """Admin-edit a discovery source: display name, scope (subscription/project),
    enabled, and config — including config.driver ("stub" | "live"), which flips
    the source between demo data and the real cloud with NO restart. Credentials
    are never stored here: live drivers authenticate ambiently (workload
    identity / managed identity / CLI) — keyless by design."""
    source = db.get(DiscoverySource, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Discovery source not found")

    before = {
        "display_name": source.display_name,
        "scope": source.scope,
        "enabled": source.enabled,
        "config": dict(source.config or {}),
    }
    if payload.display_name is not None:
        source.display_name = payload.display_name.strip() or source.display_name
    if payload.scope is not None:
        source.scope = payload.scope.strip()
    if payload.enabled is not None:
        source.enabled = payload.enabled
    if payload.config is not None:
        mode = (payload.config.get("driver") or "").lower()
        if "driver" in payload.config and mode not in VALID_MODES:
            raise ValidationError(f"config.driver must be one of {list(VALID_MODES)}")
        # Refuse anything that smells like a credential — auth is ambient/WIF only.
        forbidden = {k for k in payload.config if any(
            s in k.lower() for s in ("secret", "key", "token", "password", "credential")
        )}
        if forbidden:
            raise ValidationError(
                f"Config keys {sorted(forbidden)} are not allowed: sources never "
                "store credentials. Live drivers use keyless auth (workload "
                "identity federation / managed identity)."
            )
        source.config = {**(source.config or {}), **payload.config}
    db.flush()
    audit.record(
        db,
        action="discovery_source_updated",
        entity_type="discovery_source",
        entity_id=source.id,
        actor_id=user.id,
        before=before,
        after={
            "display_name": source.display_name,
            "scope": source.scope,
            "enabled": source.enabled,
            "config": dict(source.config or {}),
        },
        request_ip=client_ip(request),
    )
    db.commit()
    db.refresh(source)
    discovery_cache.clear()  # scope/mode changed -> cached dropdowns are stale
    return source


@router.get("/sources/{source_id}/vendors", response_model=list[str])
def list_vendors(
    source_id: uuid.UUID,
    db: Session = Depends(db_session),
    _: User = Depends(get_current_user),
) -> list[str]:
    source = _get_source(db, source_id)
    # Keyed by source id: scope, driver mode and config are all per-source and
    # admin-editable, so the id captures the full identity of a result set.
    cache_key = (str(source.id), "")
    cached = discovery_cache.get(cache_key)
    if cached is not None:
        return cached
    try:
        vendors = driver_for(source.cloud, source.config).list_vendors(
            source.scope, driver_config(db, source)
        )
    except KeyError:
        raise HTTPException(status_code=501, detail=f"No driver for cloud '{source.cloud}'")
    discovery_cache.set(cache_key, vendors)
    return vendors


@router.get(
    "/sources/{source_id}/vendors/{vendor}/models",
    response_model=list[DiscoveredModelOut],
)
def list_models(
    source_id: uuid.UUID,
    vendor: str,
    db: Session = Depends(db_session),
    _: User = Depends(get_current_user),
) -> list[DiscoveredModelOut]:
    source = _get_source(db, source_id)
    cache_key = (str(source.id), vendor)
    cached = discovery_cache.get(cache_key)
    if cached is None:
        try:
            discovered = driver_for(source.cloud, source.config).list_models(
                source.scope, vendor, driver_config(db, source)
            )
        except KeyError:
            raise HTTPException(status_code=501, detail=f"No driver for cloud '{source.cloud}'")
        cached = [
            DiscoveredModelOut(
                vendor=d.vendor,
                model_name=d.model_name,
                model_version=d.model_version,
                model_format=d.model_format,
                resource_id=d.resource_id,
                resource_kind=d.resource_kind,
                regions=d.regions,
                sku=d.sku,
                endpoint=d.endpoint,
                provisioning_state=d.provisioning_state,
                label=d.label(),
            )
            for d in discovered
        ]
        discovery_cache.set(cache_key, cached)
    return cached
