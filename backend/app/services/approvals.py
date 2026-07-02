"""Approval gate: server-side enforcement of tier-appropriate decisions.

Gating rules (bound to the review's current RiskScore):
    Tier 1  -> any approver may approve
    Tier 2  -> approve only with compensating conditions (approve_with_conditions)
    Tier 3  -> approve requires a named risk owner + justification
    Tier 4 / KO fail -> approval FORBIDDEN unless an admin overrides with a reason
    reject  -> always allowed for an approver
Separation of duty: the assigned reviewer may not approve their own review
(unless they are an admin).
"""
from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.auth import has_role
from app.models import (
    ApprovalDecision,
    Decision,
    Review,
    ReviewState,
    Role,
    User,
    utcnow,
)
from app.services import audit
from app.services.errors import ConflictError, ForbiddenError, ValidationError
from app.services.review_workflow import current_score

_VALID_DECISIONS = {d.value for d in Decision}

_DECISION_STATE = {
    Decision.APPROVE.value: ReviewState.APPROVED.value,
    Decision.APPROVE_WITH_CONDITIONS.value: ReviewState.APPROVED_WITH_CONDITIONS.value,
    Decision.REJECT.value: ReviewState.REJECTED.value,
}


def decide(
    db: Session,
    *,
    review: Review,
    current_user: User,
    decision: str,
    justification: str,
    conditions: str | None = None,
    risk_owner_id: uuid.UUID | None = None,
    override_reason: str | None = None,
    request_ip: str | None = None,
) -> ApprovalDecision:
    if decision not in _VALID_DECISIONS:
        raise ValidationError(f"Invalid decision '{decision}'. One of {sorted(_VALID_DECISIONS)}.")
    if not (justification and justification.strip()):
        raise ValidationError("A justification is required for every decision.")

    if not has_role(current_user.roles, Role.APPROVER.value):
        raise ForbiddenError("Approver role required to decide a review.")

    if review.state != ReviewState.SCORED.value:
        raise ConflictError(
            f"Review must be in 'scored' state to decide (currently '{review.state}')."
        )

    score = current_score(db, review)
    if score is None:
        raise ConflictError("Review has no current risk score; submit it first.")

    is_admin = has_role(current_user.roles, Role.ADMIN.value)

    # Separation of duty.
    if review.assigned_reviewer_id == current_user.id and not is_admin:
        raise ForbiddenError(
            "Separation of duty: the assigned reviewer cannot approve their own review."
        )

    overridden_tier: int | None = None
    ko_fail = any(g.get("type") == "ko_fail" for g in (score.triggered_gates or []))

    if decision != Decision.REJECT.value:
        # Approval paths are tier-gated.
        if score.tier == 4 or ko_fail:
            if not is_admin:
                raise ForbiddenError(
                    "Tier 4 / knock-out failure cannot be approved. Admin override required."
                )
            if not (override_reason and override_reason.strip()):
                raise ValidationError(
                    "override_reason is required for an admin to approve a Tier 4 / KO review."
                )
            overridden_tier = score.tier
        elif score.tier == 3:
            if risk_owner_id is None:
                raise ValidationError("Tier 3 approval requires a named risk_owner_id.")
        elif score.tier == 2:
            if decision != Decision.APPROVE_WITH_CONDITIONS.value or not (
                conditions and conditions.strip()
            ):
                raise ValidationError(
                    "Tier 2 requires approval with compensating conditions "
                    "(use decision=approve_with_conditions and provide conditions)."
                )

    record = ApprovalDecision(
        review_id=review.id,
        risk_score_id=score.id,
        decision=decision,
        conditions=conditions,
        justification=justification,
        risk_owner_id=risk_owner_id,
        decided_by_id=current_user.id,
        decided_at=utcnow(),
        overridden_tier=overridden_tier,
        override_reason=override_reason,
    )
    db.add(record)

    review.state = _DECISION_STATE[decision]
    review.decided_at = utcnow()
    if review.assigned_approver_id is None:
        review.assigned_approver_id = current_user.id

    db.flush()
    audit.record(
        db,
        action="review_decided",
        entity_type="review",
        entity_id=review.id,
        actor_id=current_user.id,
        after={
            "decision": decision,
            "tier": score.tier,
            "risk_score_id": str(score.id),
            "override": overridden_tier is not None,
            "overridden_tier": overridden_tier,
            "precedent_id": str(review.precedent_id) if review.precedent_id else None,
        },
        request_ip=request_ip,
    )

    # An approval mints a standalone precedent snapshot so later same-terms
    # models can rubber-stamp — even after this review record is deleted.
    if decision in (Decision.APPROVE.value, Decision.APPROVE_WITH_CONDITIONS.value):
        from app.services import precedent as precedent_svc

        precedent_svc.mint_from_review(
            db,
            review=review,
            tier=score.tier,
            score=score.overall_score,
            actor_id=current_user.id,
            request_ip=request_ip,
        )
    return record
