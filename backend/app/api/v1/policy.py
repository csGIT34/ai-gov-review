"""Governance policy endpoints (admin-editable auto-answer inputs)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.api.deps import client_ip, db_session, get_current_user, require_admin
from app.models import GovernancePolicy, User
from app.schemas import PolicyOut, PolicyUpdate
from app.services import policy as policy_svc

router = APIRouter(prefix="/policy", tags=["policy"])


@router.get("", response_model=PolicyOut)
def get_policy(
    db: Session = Depends(db_session), _: User = Depends(get_current_user)
) -> GovernancePolicy:
    return policy_svc.get_policy(db)


@router.put("", response_model=PolicyOut)
def update_policy(
    payload: PolicyUpdate,
    request: Request,
    db: Session = Depends(db_session),
    user: User = Depends(require_admin),
) -> GovernancePolicy:
    updated = policy_svc.update_policy(
        db,
        approved_regions=payload.approved_regions,
        actor_id=user.id,
        request_ip=client_ip(request),
    )
    db.commit()
    db.refresh(updated)
    return updated
