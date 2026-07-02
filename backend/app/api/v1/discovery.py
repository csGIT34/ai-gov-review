"""Cascading discovery endpoints that populate the review dropdowns.

Flow: GET /sources -> GET /sources/{id}/vendors -> .../vendors/{vendor}/models.
Pull-based and cached; real Azure/GCP drivers replace the stub in M5/M6.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import db_session, get_current_user, require_admin
from app.discovery import get_driver
from app.discovery.base import discovery_cache
from app.models import DiscoverySource, User
from app.schemas import DiscoveredModelOut, SourceCreate, SourceOut
from app.services.policy import driver_config

router = APIRouter(prefix="/discovery", tags=["discovery"])


def _get_source(db: Session, source_id: uuid.UUID) -> DiscoverySource:
    source = db.get(DiscoverySource, source_id)
    if source is None or not source.enabled:
        raise HTTPException(status_code=404, detail="Discovery source not found or disabled")
    return source


@router.get("/sources", response_model=list[SourceOut])
def list_sources(
    db: Session = Depends(db_session), _: User = Depends(get_current_user)
) -> list[DiscoverySource]:
    return list(
        db.execute(
            select(DiscoverySource).where(DiscoverySource.enabled.is_(True)).order_by(
                DiscoverySource.cloud, DiscoverySource.display_name
            )
        ).scalars()
    )


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


@router.get("/sources/{source_id}/vendors", response_model=list[str])
def list_vendors(
    source_id: uuid.UUID,
    db: Session = Depends(db_session),
    _: User = Depends(get_current_user),
) -> list[str]:
    source = _get_source(db, source_id)
    cache_key = (source.cloud, source.scope, "")
    cached = discovery_cache.get(cache_key)
    if cached is not None:
        return cached
    try:
        vendors = get_driver(source.cloud).list_vendors(source.scope, driver_config(db, source))
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
    cache_key = (source.cloud, source.scope, vendor)
    cached = discovery_cache.get(cache_key)
    if cached is None:
        try:
            discovered = get_driver(source.cloud).list_models(
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
