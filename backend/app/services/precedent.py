"""Precedent fast-track ("rubber stamp") for reviews.

Most models from a vendor are governed by the same terms, so the org-level
judgment answers (procurement vetting, oversight process, incident runbook,
doc-based confirmations) rarely change between them. Once ONE model has been
fully reviewed and approved, a later model under the SAME vendor and the SAME
governing terms may adopt those judgment answers and go straight to scoring.

What adoption deliberately does NOT do:
  * auto controls are never carried — residency, network exposure, encryption,
    filters, version pinning are recomputed fresh from THIS model's cloud
    facts, so a model with a worse footprint still trips its own gates.
  * a different terms id (e.g. a restricted-availability variant with its own
    addendum) blocks the fast-track entirely — different terms are a new
    governance object and get a full review.
  * scoring, tiers and the approval gate are unchanged. Adoption only pre-fills
    answers, with full provenance: answer_source="carried",
    review.precedent_review_id, and an audit entry.

Precedent eligibility (all must hold, evaluated server-side on adopt):
  vendor match · terms identity present and equal · precedent decided
  approve/approve_with_conditions · same questionnaire version.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ControlResponse, Model, Review, ReviewState, utcnow
from app.models.enums import AnswerSource
from app.services import audit
from app.services.errors import ConflictError
from app.services.review_workflow import _ANSWERABLE_STATES

_APPROVED_STATES = (
    ReviewState.APPROVED.value,
    ReviewState.APPROVED_WITH_CONDITIONS.value,
)

# Sources a precedent answer may be carried FROM (reviewer-attested answers).
_CARRYABLE_FROM = {AnswerSource.HUMAN.value, AnswerSource.CARRIED.value}
# Sources a control may be carried ONTO (unanswered manual / unconfirmed suggestion).
_CARRYABLE_ONTO = {None, AnswerSource.SUGGESTED.value}


def terms_of(model: Model) -> dict | None:
    """Governing-terms identity from the model's cloud facts, or None."""
    terms = (model.facts or {}).get("terms")
    if isinstance(terms, dict) and terms.get("id"):
        return terms
    return None


@dataclass
class Assessment:
    """Result of evaluating a review against the best available precedent."""

    available: bool = False
    reasons: list[str] = field(default_factory=list)
    model_terms: dict | None = None
    precedent: Review | None = None  # best candidate examined, even when blocked
    precedent_model: Model | None = None
    carryable_keys: list[str] = field(default_factory=list)


def _approved_reviews_for_vendor(db: Session, vendor: str, exclude_review_id: uuid.UUID) -> list[Review]:
    """Approved reviews for the vendor, most recently decided first."""
    stmt = (
        select(Review)
        .join(Model, Review.model_id == Model.id)
        .where(
            Model.vendor == vendor,
            Review.state.in_(_APPROVED_STATES),
            Review.id != exclude_review_id,
        )
        .order_by(Review.decided_at.desc())
    )
    return list(db.execute(stmt).scalars())


def _carryable_keys(review: Review, precedent: Review) -> list[str]:
    """Control keys whose judgment answer can be carried from the precedent."""
    attested = {
        c.control_key: c
        for c in precedent.controls
        if c.answer is not None and c.answer_source in _CARRYABLE_FROM
    }
    return [
        c.control_key
        for c in review.controls
        if c.answer_source in _CARRYABLE_ONTO and c.control_key in attested
    ]


def find_precedent(db: Session, review: Review) -> Assessment:
    """Evaluate whether this review can fast-track from an approved precedent."""
    a = Assessment()
    model = review.model
    a.model_terms = terms_of(model)

    if review.precedent_review_id is not None:
        a.precedent = db.get(Review, review.precedent_review_id)
        a.precedent_model = a.precedent.model if a.precedent else None
        a.reasons.append("Precedent answers were already adopted into this review.")
        return a

    if review.state not in _ANSWERABLE_STATES:
        a.reasons.append(
            f"Review is '{review.state}' — precedent can only be adopted while a review is open."
        )
        return a

    candidates = _approved_reviews_for_vendor(db, model.vendor, review.id)
    if not candidates:
        a.reasons.append(
            f"No approved review exists yet for vendor '{model.vendor}' — "
            "the first model from a vendor gets the full review."
        )
        return a

    if a.model_terms is None:
        a.reasons.append(
            "This model reports no governing-terms identity, so a precedent cannot be "
            "established — precedent matching fails closed to a full review."
        )
        return a

    # Prefer the most recent approved review under the SAME terms.
    match: Review | None = None
    for cand in candidates:
        cand_terms = terms_of(cand.model)
        if cand_terms and cand_terms["id"] == a.model_terms["id"]:
            match = cand
            break

    if match is None:
        newest = candidates[0]
        newest_terms = terms_of(newest.model)
        a.precedent = newest
        a.precedent_model = newest.model
        a.reasons.append(
            f"Governing terms differ: this model is under "
            f"'{a.model_terms.get('label') or a.model_terms['id']}', but the approved "
            f"precedent ({newest.model.model_name}) is under "
            f"'{(newest_terms or {}).get('label') or (newest_terms or {}).get('id') or 'unknown terms'}'. "
            "Different terms require a full review."
        )
        return a

    a.precedent = match
    a.precedent_model = match.model

    mine = (review.snapshot or {}).get("version")
    theirs = (match.snapshot or {}).get("version")
    if mine != theirs:
        a.reasons.append(
            f"The precedent was reviewed under questionnaire v{theirs}, but this review "
            f"uses v{mine} — answers cannot be carried across questionnaire versions."
        )
        return a

    a.carryable_keys = _carryable_keys(review, match)
    if not a.carryable_keys:
        a.reasons.append("Nothing to carry — every judgment control is already settled.")
        return a

    a.available = True
    return a


def adopt(
    db: Session,
    *,
    review: Review,
    actor_id: uuid.UUID,
    request_ip: str | None = None,
) -> tuple[Assessment, list[str]]:
    """Carry the precedent's judgment answers into this review (server-validated)."""
    a = find_precedent(db, review)
    if not a.available:
        raise ConflictError(
            "Precedent fast-track is not available for this review.",
            details={"reasons": a.reasons},
        )
    precedent = a.precedent
    assert precedent is not None  # available=True guarantees a matched precedent

    attested: dict[str, ControlResponse] = {
        c.control_key: c
        for c in precedent.controls
        if c.answer is not None and c.answer_source in _CARRYABLE_FROM
    }
    carried: list[str] = []
    now = utcnow()
    for c in review.controls:
        src = attested.get(c.control_key)
        if c.answer_source not in _CARRYABLE_ONTO or src is None:
            continue  # auto controls (and anything human-touched) stay fresh
        c.answer = src.answer
        c.evidence_url = src.evidence_url
        c.evidence_note = src.evidence_note
        c.answer_source = AnswerSource.CARRIED.value
        c.answered_by_id = actor_id
        c.answered_at = now
        carried.append(c.control_key)

    review.precedent_review_id = precedent.id
    if review.state == ReviewState.PENDING_REVIEW.value:
        review.state = ReviewState.IN_REVIEW.value

    db.flush()
    audit.record(
        db,
        action="review_precedent_adopted",
        entity_type="review",
        entity_id=review.id,
        actor_id=actor_id,
        after={
            "precedent_review_id": str(precedent.id),
            "precedent_model": a.precedent_model.model_name if a.precedent_model else None,
            "terms_id": (a.model_terms or {}).get("id"),
            "carried": carried,
            "carried_count": len(carried),
        },
        request_ip=request_ip,
    )
    return a, carried
