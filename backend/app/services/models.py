"""Model upsert/dedup from a discovered selection."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.discovery import DiscoveredModel, get_driver
from app.models import DiscoverySource, Model, utcnow
from app.services import audit
from app.services.errors import NotFoundError


def resolve_discovered(
    source: DiscoverySource, vendor: str, resource_id: str, model_version: str | None
) -> DiscoveredModel:
    """Re-query the driver so the server, not the client, is the source of truth."""
    driver = get_driver(source.cloud)
    for dm in driver.list_models(source.scope, vendor, source.config):
        if dm.resource_id == resource_id and (dm.model_version or None) == (model_version or None):
            return dm
    raise NotFoundError(
        "Selected model not found in the discovery source",
        details={"resource_id": resource_id, "model_version": model_version},
    )


def upsert_model(
    db: Session,
    *,
    source: DiscoverySource,
    discovered: DiscoveredModel,
    actor_id=None,
    request_ip: str | None = None,
) -> tuple[Model, bool]:
    """Insert a new Model or refresh an existing one. Dedup on (resource_id, model_version)."""
    existing = db.execute(
        select(Model).where(
            Model.resource_id == discovered.resource_id,
            Model.model_version == discovered.model_version,
        )
    ).scalar_one_or_none()

    now = utcnow()
    if existing is not None:
        existing.last_seen_at = now
        existing.region = discovered.region or existing.region
        existing.provisioning_state = discovered.provisioning_state or existing.provisioning_state
        existing.facts = discovered.facts or existing.facts
        existing.status = "active"
        db.flush()
        return existing, False

    model = Model(
        discovery_source_id=source.id,
        cloud=source.cloud,
        vendor=discovered.vendor,
        model_name=discovered.model_name,
        model_version=discovered.model_version,
        model_format=discovered.model_format,
        resource_id=discovered.resource_id,
        resource_kind=discovered.resource_kind,
        subscription_or_project=discovered.subscription_or_project,
        resource_group=discovered.resource_group,
        region=discovered.region,
        sku=discovered.sku,
        endpoint=discovered.endpoint,
        provisioning_state=discovered.provisioning_state,
        cloud_created_at=discovered.cloud_created_at,
        cloud_last_modified_at=discovered.cloud_last_modified_at,
        facts=discovered.facts,
        first_seen_at=now,
        last_seen_at=now,
        status="active",
    )
    db.add(model)
    db.flush()
    audit.record(
        db,
        action="model_discovered",
        entity_type="model",
        entity_id=model.id,
        actor_id=actor_id,
        after={
            "cloud": model.cloud,
            "vendor": model.vendor,
            "model_name": model.model_name,
            "model_version": model.model_version,
            "resource_id": model.resource_id,
        },
        request_ip=request_ip,
    )
    return model, True
