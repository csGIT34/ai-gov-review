"""Approval gate endpoints."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import client_ip, db_session, get_current_user, require_approver
from app.models import ApprovalDecision, User
from app.schemas import DecisionIn, DecisionOut
from app.services import approvals, review_workflow as wf

router = APIRouter(prefix="/reviews", tags=["approvals"])


@router.post("/{review_id}/decision", response_model=DecisionOut, status_code=201)
def decide(
    review_id: uuid.UUID,
    payload: DecisionIn,
    request: Request,
    db: Session = Depends(db_session),
    user: User = Depends(require_approver),
) -> ApprovalDecision:
    review = wf.get_review(db, review_id)
    decision = approvals.decide(
        db,
        review=review,
        current_user=user,
        decision=payload.decision,
        justification=payload.justification,
        conditions=payload.conditions,
        risk_owner_id=payload.risk_owner_id,
        override_reason=payload.override_reason,
        request_ip=client_ip(request),
    )
    db.commit()
    db.refresh(decision)
    return decision


@router.get("/{review_id}/decision", response_model=DecisionOut)
def get_decision(
    review_id: uuid.UUID,
    db: Session = Depends(db_session),
    _: User = Depends(get_current_user),
) -> ApprovalDecision:
    decision = db.execute(
        select(ApprovalDecision)
        .where(ApprovalDecision.review_id == review_id)
        .order_by(ApprovalDecision.decided_at.desc())
    ).scalars().first()
    if decision is None:
        raise HTTPException(status_code=404, detail="No decision recorded for this review")
    return decision
