"""Review lifecycle: opening reviews, answering controls, submitting, scoring.

State machine:
    PENDING_REVIEW -> IN_REVIEW -> SCORED -> {APPROVED | APPROVED_WITH_CONDITIONS | REJECTED}

Guards:
    * cannot submit until every control is answered
    * answering is only allowed while PENDING_REVIEW or IN_REVIEW
"""
from __future__ import annotations

import uuid

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import (
    Answer,
    ControlResponse,
    Model,
    Review,
    ReviewState,
    RiskScore,
    utcnow,
)
from app.services import audit, autoanswer, policy
from app.services.errors import ConflictError, NotFoundError, ValidationError
from app.services.questionnaire import Questionnaire, get_questionnaire
from app.services.scoring import RiskResult, ScoredControl, score_controls

_ANSWERABLE_STATES = {ReviewState.PENDING_REVIEW.value, ReviewState.IN_REVIEW.value}
_VALID_ANSWERS = {a.value for a in Answer}


def open_review(
    db: Session,
    *,
    model: Model,
    trigger: str,
    actor_id: uuid.UUID | None,
    questionnaire: Questionnaire | None = None,
    request_ip: str | None = None,
) -> Review:
    """Create a PENDING_REVIEW and materialize its control responses."""
    q = questionnaire or get_questionnaire()
    review = Review(
        model_id=model.id,
        framework=q.framework,
        state=ReviewState.PENDING_REVIEW.value,
        trigger=trigger,
        opened_at=utcnow(),
        snapshot=q.as_snapshot(),
    )
    db.add(review)
    db.flush()  # assign review.id

    # Auto-answer machine-answerable controls from the model's cloud facts,
    # against the org's (admin-configured) governance policy.
    auto = autoanswer.collect(
        model.facts, model.vendor, policy.resolve_policy(db, model), model.cloud
    )
    auto_count = 0
    attested_count = 0
    suggested_count = 0
    for c in q.controls:
        cr = ControlResponse(
            review_id=review.id,
            control_key=c.key,
            control_id=c.control_id,
            nist_function=c.nist_function,
            question_text=c.question,
            evidence_needed=c.evidence_needed,
            weight=c.weight,
            gai_categories=list(c.gai_categories),
            is_ko=c.is_ko,
        )
        r = auto.get(c.key)
        if r is not None:
            cr.answer = r.answer
            cr.answer_source = r.source
            cr.auto_answer = r.answer
            cr.auto_rationale = r.rationale
            cr.auto_confidence = r.confidence
            cr.evidence_url = r.evidence_url
            cr.answered_at = utcnow()
            if r.source == "auto":
                auto_count += 1
            elif r.source == "attested":
                attested_count += 1
            else:
                suggested_count += 1
        elif c.key in autoanswer.MANUAL_GUIDANCE:
            # No cloud signal — leave unanswered, but attach guidance for the reviewer.
            cr.auto_rationale = autoanswer.MANUAL_GUIDANCE[c.key]
        db.add(cr)

    model.current_review_id = review.id
    db.flush()
    audit.record(
        db,
        action="review_opened",
        entity_type="review",
        entity_id=review.id,
        actor_id=actor_id,
        actor_type="user" if actor_id else "system",
        after={
            "model_id": str(model.id),
            "trigger": trigger,
            "controls": len(q.controls),
            "auto_answered": auto_count,
            "attested": attested_count,
            "suggested": suggested_count,
        },
        request_ip=request_ip,
    )
    return review


def get_review(db: Session, review_id: uuid.UUID) -> Review:
    review = db.get(Review, review_id)
    if review is None:
        raise NotFoundError("Review not found")
    return review


def answer_control(
    db: Session,
    *,
    review: Review,
    control_response_id: uuid.UUID,
    answer: str,
    evidence_url: str | None,
    evidence_note: str | None,
    actor_id: uuid.UUID,
    request_ip: str | None = None,
) -> ControlResponse:
    if review.state not in _ANSWERABLE_STATES:
        raise ConflictError(
            f"Cannot answer controls while review is '{review.state}'."
        )
    if answer not in _VALID_ANSWERS:
        raise ValidationError(f"Invalid answer '{answer}'. One of {sorted(_VALID_ANSWERS)}.")

    cr = db.get(ControlResponse, control_response_id)
    if cr is None or cr.review_id != review.id:
        raise NotFoundError("Control response not found for this review")

    before = {"answer": cr.answer, "evidence_url": cr.evidence_url, "source": cr.answer_source}
    cr.answer = answer
    cr.evidence_url = evidence_url
    cr.evidence_note = evidence_note
    cr.answered_by_id = actor_id
    cr.answered_at = utcnow()
    # A human touching a control (confirming a suggestion or overriding) makes it human-owned.
    cr.answer_source = "human"

    # First answer moves the review into IN_REVIEW.
    if review.state == ReviewState.PENDING_REVIEW.value:
        review.state = ReviewState.IN_REVIEW.value

    db.flush()
    audit.record(
        db,
        action="control_answered",
        entity_type="control_response",
        entity_id=cr.id,
        actor_id=actor_id,
        before=before,
        after={"answer": answer, "control_key": cr.control_key},
        request_ip=request_ip,
    )
    return cr


def unanswered_controls(review: Review) -> list[ControlResponse]:
    return [c for c in review.controls if c.answer is None]


def unconfirmed_controls(review: Review) -> list[ControlResponse]:
    """Suggested (doc-based) answers awaiting human confirmation."""
    return [c for c in review.controls if c.answer is not None and c.answer_source == "suggested"]


def _scored_controls(review: Review) -> list[ScoredControl]:
    return [
        ScoredControl(
            key=c.control_key,
            control_id=c.control_id,
            nist_function=c.nist_function,
            weight=c.weight,
            is_ko=c.is_ko,
            answer=c.answer,
        )
        for c in review.controls
    ]


def compute_and_store_score(
    db: Session, *, review: Review, actor_id: uuid.UUID | None, request_ip: str | None = None
) -> tuple[RiskScore, RiskResult]:
    """Score the review, persist a new current RiskScore, update denormalized fields."""
    result = score_controls(_scored_controls(review))

    # Supersede any prior current score for this review.
    db.execute(
        update(RiskScore)
        .where(RiskScore.review_id == review.id, RiskScore.is_current.is_(True))
        .values(is_current=False)
    )
    score = RiskScore(
        review_id=review.id,
        overall_score=result.overall_score,
        tier=result.tier,
        function_deficits=result.function_deficits,
        triggered_gates=result.triggered_gates,
        is_current=True,
    )
    db.add(score)

    model = db.get(Model, review.model_id)
    if model is not None:
        model.latest_score = result.overall_score
        model.latest_tier = result.tier

    db.flush()
    audit.record(
        db,
        action="review_scored",
        entity_type="review",
        entity_id=review.id,
        actor_id=actor_id,
        actor_type="user" if actor_id else "system",
        after={
            "overall_score": result.overall_score,
            "tier": result.tier,
            "gates": [g["type"] for g in result.triggered_gates],
        },
        request_ip=request_ip,
    )
    return score, result


def submit_review(
    db: Session, *, review: Review, actor_id: uuid.UUID, request_ip: str | None = None
) -> tuple[RiskScore, RiskResult]:
    if review.state not in _ANSWERABLE_STATES:
        raise ConflictError(f"Cannot submit a review in state '{review.state}'.")

    missing = unanswered_controls(review)
    pending = unconfirmed_controls(review)
    if missing or pending:
        raise ValidationError(
            "All controls must be answered and suggested answers confirmed before submitting.",
            details={
                "unanswered": [c.control_key for c in missing],
                "needs_confirmation": [c.control_key for c in pending],
            },
        )

    review.state = ReviewState.SCORED.value
    review.submitted_at = utcnow()
    db.flush()
    score, result = compute_and_store_score(
        db, review=review, actor_id=actor_id, request_ip=request_ip
    )
    audit.record(
        db,
        action="review_submitted",
        entity_type="review",
        entity_id=review.id,
        actor_id=actor_id,
        after={"tier": result.tier, "overall_score": result.overall_score},
        request_ip=request_ip,
    )
    return score, result


def current_score(db: Session, review: Review) -> RiskScore | None:
    return db.execute(
        select(RiskScore).where(
            RiskScore.review_id == review.id, RiskScore.is_current.is_(True)
        )
    ).scalar_one_or_none()


def assign(
    db: Session,
    *,
    review: Review,
    reviewer_id: uuid.UUID | None,
    approver_id: uuid.UUID | None,
    actor_id: uuid.UUID,
    request_ip: str | None = None,
) -> Review:
    before = {
        "reviewer": str(review.assigned_reviewer_id) if review.assigned_reviewer_id else None,
        "approver": str(review.assigned_approver_id) if review.assigned_approver_id else None,
    }
    if reviewer_id is not None:
        review.assigned_reviewer_id = reviewer_id
    if approver_id is not None:
        review.assigned_approver_id = approver_id
    db.flush()
    audit.record(
        db,
        action="review_assigned",
        entity_type="review",
        entity_id=review.id,
        actor_id=actor_id,
        before=before,
        after={
            "reviewer": str(review.assigned_reviewer_id) if review.assigned_reviewer_id else None,
            "approver": str(review.assigned_approver_id) if review.assigned_approver_id else None,
        },
        request_ip=request_ip,
    )
    return review
