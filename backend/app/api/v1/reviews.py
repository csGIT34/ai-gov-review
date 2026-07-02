"""Review lifecycle endpoints: create, answer controls, submit, score."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import client_ip, db_session, get_current_user, require_reviewer
from app.models import ControlResponse, DiscoverySource, Model, Review, ReviewState, User
from app.models.enums import DECISION_STATES
from app.schemas import (
    AdoptResultOut,
    AssignIn,
    ControlAnswerIn,
    ControlOut,
    ModelTermsOut,
    PrecedentOut,
    PrecedentRefOut,
    ReviewCreate,
    ReviewDetailOut,
    ReviewOut,
    RiskScoreOut,
    SubmitResultOut,
)
from app.services import policy as policy_service
from app.services import precedent as precedent_svc
from app.services import review_workflow as wf
from app.services.errors import ConflictError, NotFoundError
from app.services.models import resolve_discovered, upsert_model

router = APIRouter(prefix="/reviews", tags=["reviews"])

_OPEN_STATES = {
    ReviewState.PENDING_REVIEW.value,
    ReviewState.IN_REVIEW.value,
    ReviewState.SCORED.value,
}


@router.post("", response_model=ReviewOut, status_code=201)
def create_review(
    payload: ReviewCreate,
    request: Request,
    db: Session = Depends(db_session),
    user: User = Depends(require_reviewer),
) -> Review:
    ip = client_ip(request)

    if payload.model_id is not None:
        model = db.get(Model, payload.model_id)
        if model is None:
            raise NotFoundError("Model not found")
        trigger = payload.trigger or "rereview"
    else:
        source = db.get(DiscoverySource, payload.source_id)
        if source is None or not source.enabled:
            raise NotFoundError("Discovery source not found or disabled")
        discovered = resolve_discovered(
            source,
            payload.vendor,
            payload.resource_id,
            payload.model_version,
            config=policy_service.driver_config(db, source),
        )
        model, _created = upsert_model(
            db, source=source, discovered=discovered, actor_id=user.id, request_ip=ip
        )
        trigger = payload.trigger or "manual"

    # Prevent duplicate open reviews for the same model.
    existing = db.execute(
        select(Review).where(
            Review.model_id == model.id, Review.state.notin_(list(s.value for s in DECISION_STATES))
        )
    ).scalars().first()
    if existing is not None:
        raise ConflictError(
            "An open review already exists for this model.",
            details={"review_id": str(existing.id)},
        )

    review = wf.open_review(db, model=model, trigger=trigger, actor_id=user.id, request_ip=ip)
    db.commit()
    db.refresh(review)
    return review


@router.get("", response_model=list[ReviewOut])
def list_reviews(
    db: Session = Depends(db_session),
    _: User = Depends(get_current_user),
    state: str | None = Query(default=None),
    assigned_reviewer_id: uuid.UUID | None = Query(default=None),
) -> list[Review]:
    stmt = select(Review)
    if state:
        stmt = stmt.where(Review.state == state)
    if assigned_reviewer_id:
        stmt = stmt.where(Review.assigned_reviewer_id == assigned_reviewer_id)
    stmt = stmt.order_by(Review.opened_at.desc())
    return list(db.execute(stmt).scalars())


@router.get("/{review_id}", response_model=ReviewDetailOut)
def get_review(
    review_id: uuid.UUID,
    db: Session = Depends(db_session),
    _: User = Depends(get_current_user),
) -> ReviewDetailOut:
    review = db.get(Review, review_id)
    if review is None:
        raise NotFoundError("Review not found")
    detail = ReviewDetailOut.model_validate(review)
    score = wf.current_score(db, review)
    detail.current_score = RiskScoreOut.model_validate(score) if score else None
    return detail


@router.patch("/{review_id}/assign", response_model=ReviewOut)
def assign_review(
    review_id: uuid.UUID,
    payload: AssignIn,
    request: Request,
    db: Session = Depends(db_session),
    user: User = Depends(require_reviewer),
) -> Review:
    review = wf.get_review(db, review_id)
    wf.assign(
        db,
        review=review,
        reviewer_id=payload.reviewer_id,
        approver_id=payload.approver_id,
        actor_id=user.id,
        request_ip=client_ip(request),
    )
    db.commit()
    db.refresh(review)
    return review


@router.get("/{review_id}/controls", response_model=list[ControlOut])
def list_controls(
    review_id: uuid.UUID,
    db: Session = Depends(db_session),
    _: User = Depends(get_current_user),
) -> list[ControlResponse]:
    review = wf.get_review(db, review_id)
    return sorted(review.controls, key=lambda c: (c.nist_function, c.control_id))


@router.patch("/{review_id}/controls/{control_response_id}", response_model=ControlOut)
def answer_control(
    review_id: uuid.UUID,
    control_response_id: uuid.UUID,
    payload: ControlAnswerIn,
    request: Request,
    db: Session = Depends(db_session),
    user: User = Depends(require_reviewer),
) -> ControlResponse:
    review = wf.get_review(db, review_id)
    cr = wf.answer_control(
        db,
        review=review,
        control_response_id=control_response_id,
        answer=payload.answer,
        evidence_url=payload.evidence_url,
        evidence_note=payload.evidence_note,
        actor_id=user.id,
        request_ip=client_ip(request),
    )
    db.commit()
    db.refresh(cr)
    return cr


def _precedent_out(db: Session, a: precedent_svc.Assessment) -> PrecedentOut:
    ref = None
    if a.precedent is not None and a.precedent_model is not None:
        score = wf.current_score(db, a.precedent)
        terms = precedent_svc.terms_of(a.precedent_model)
        ref = PrecedentRefOut(
            review_id=a.precedent.id,
            model_id=a.precedent_model.id,
            model_name=a.precedent_model.model_name,
            model_version=a.precedent_model.model_version,
            cloud=a.precedent_model.cloud,
            decision_state=a.precedent.state,
            decided_at=a.precedent.decided_at,
            tier=score.tier if score else None,
            score=score.overall_score if score else None,
            terms=ModelTermsOut(**terms) if terms else None,
        )
    return PrecedentOut(
        available=a.available,
        reasons=a.reasons,
        model_terms=ModelTermsOut(**a.model_terms) if a.model_terms else None,
        precedent=ref,
        carryable_keys=a.carryable_keys,
        carryable_count=len(a.carryable_keys),
    )


@router.get("/{review_id}/precedent", response_model=PrecedentOut)
def get_precedent(
    review_id: uuid.UUID,
    db: Session = Depends(db_session),
    _: User = Depends(get_current_user),
) -> PrecedentOut:
    """Can this review fast-track from an approved precedent (and why/why not)?"""
    review = wf.get_review(db, review_id)
    return _precedent_out(db, precedent_svc.find_precedent(db, review))


@router.post("/{review_id}/adopt-precedent", response_model=AdoptResultOut)
def adopt_precedent(
    review_id: uuid.UUID,
    request: Request,
    db: Session = Depends(db_session),
    user: User = Depends(require_reviewer),
) -> AdoptResultOut:
    """Carry the precedent's judgment answers into this review (auto facts stay fresh)."""
    review = wf.get_review(db, review_id)
    assessment, carried = precedent_svc.adopt(
        db, review=review, actor_id=user.id, request_ip=client_ip(request)
    )
    db.commit()
    return AdoptResultOut(
        precedent_review_id=assessment.precedent.id,
        carried_keys=carried,
        carried_count=len(carried),
    )


@router.post("/{review_id}/submit", response_model=SubmitResultOut)
def submit_review(
    review_id: uuid.UUID,
    request: Request,
    db: Session = Depends(db_session),
    user: User = Depends(require_reviewer),
) -> SubmitResultOut:
    review = wf.get_review(db, review_id)
    score, _result = wf.submit_review(
        db, review=review, actor_id=user.id, request_ip=client_ip(request)
    )
    db.commit()
    db.refresh(review)
    db.refresh(score)
    return SubmitResultOut(
        review=ReviewOut.model_validate(review),
        score=RiskScoreOut.model_validate(score),
    )


@router.get("/{review_id}/score", response_model=RiskScoreOut)
def get_score(
    review_id: uuid.UUID,
    db: Session = Depends(db_session),
    _: User = Depends(get_current_user),
) -> RiskScoreOut:
    review = wf.get_review(db, review_id)
    score = wf.current_score(db, review)
    if score is None:
        raise HTTPException(status_code=404, detail="Review has no score yet")
    return RiskScoreOut.model_validate(score)
