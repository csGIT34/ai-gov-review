"""Read-only audit log endpoints (approver/admin)."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import db_session, require_approver
from app.models import AuditLog, User
from app.schemas import AuditOut

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("", response_model=list[AuditOut])
def list_audit(
    db: Session = Depends(db_session),
    _: User = Depends(require_approver),
    entity_type: str | None = Query(default=None),
    action: str | None = Query(default=None),
    actor_id: uuid.UUID | None = Query(default=None),
    limit: int = Query(default=100, le=1000),
) -> list[AuditLog]:
    stmt = select(AuditLog)
    if entity_type:
        stmt = stmt.where(AuditLog.entity_type == entity_type)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if actor_id:
        stmt = stmt.where(AuditLog.actor_id == actor_id)
    stmt = stmt.order_by(AuditLog.ts.desc()).limit(limit)
    return list(db.execute(stmt).scalars())


@router.get("/{entity_type}/{entity_id}", response_model=list[AuditOut])
def entity_timeline(
    entity_type: str,
    entity_id: uuid.UUID,
    db: Session = Depends(db_session),
    _: User = Depends(require_approver),
) -> list[AuditLog]:
    stmt = (
        select(AuditLog)
        .where(AuditLog.entity_type == entity_type, AuditLog.entity_id == entity_id)
        .order_by(AuditLog.ts.asc())
    )
    return list(db.execute(stmt).scalars())
