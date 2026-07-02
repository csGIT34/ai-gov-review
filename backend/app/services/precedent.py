"""Precedent fast-track ("rubber stamp") for reviews.

Most models from a vendor are governed by the same terms, so the org-level
judgment answers (procurement vetting, oversight process, incident runbook,
doc-based confirmations) rarely change between them. Once ONE model has been
fully reviewed and approved, a later model under the SAME vendor and the SAME
governing terms may adopt those judgment answers and go straight to scoring.

Precedents are STANDALONE records (the `precedents` table), minted
automatically when a review is approved. The fast-track matches against those
rows, not against review records — deleting a review never breaks the rubber
stamp, and admins manage precedents (disable / delete) from the Admin page.

What adoption deliberately does NOT do:
  * auto/attested controls are never carried — residency, network exposure,
    encryption, filters, version pinning and platform attestations are
    recomputed fresh from THIS model's cloud facts, so a model with a worse
    footprint still trips its own gates.
  * a different terms id (e.g. a restricted-availability variant with its own
    addendum) blocks the fast-track entirely — different terms are a new
    governance object and get a full review.
  * scoring, tiers and the approval gate are unchanged. Adoption only pre-fills
    answers, with full provenance: answer_source="carried",
    review.precedent_id, and an audit entry.

Precedent eligibility (all must hold, evaluated server-side on adopt):
  precedent enabled · vendor match · terms identity present and equal ·
  same questionnaire version.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Model, Precedent, Review, ReviewState, utcnow
from app.models.enums import AnswerSource
from app.services import audit
from app.services.errors import ConflictError
from app.services.review_workflow import _ANSWERABLE_STATES

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
    precedent: Precedent | None = None  # best candidate examined, even when blocked
    carryable_keys: list[str] = field(default_factory=list)


def mint_from_review(
    db: Session,
    *,
    review: Review,
    tier: int | None,
    score: float | None,
    actor_id: uuid.UUID | None = None,
    request_ip: str | None = None,
) -> Precedent | None:
    """Snapshot an approved review into a standalone Precedent row.

    Called from the approval flow. Fails soft (returns None) when the model has
    no terms identity — such models can never be matched, so there is nothing
    to store — or when this review already minted one (idempotent re-runs)."""
    model = review.model
    terms = terms_of(model)
    if terms is None:
        return None
    existing = db.execute(
        select(Precedent).where(Precedent.source_review_id == review.id)
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    answers = {
        c.control_key: {
            "answer": c.answer,
            "evidence_url": c.evidence_url,
            "evidence_note": c.evidence_note,
        }
        for c in review.controls
        if c.answer is not None and c.answer_source in _CARRYABLE_FROM
    }
    if not answers:
        return None

    p = Precedent(
        vendor=model.vendor,
        cloud=model.cloud,
        terms=terms,
        questionnaire_version=(review.snapshot or {}).get("version"),
        model_name=model.model_name,
        model_version=model.model_version,
        decision_state=review.state,
        tier=tier,
        score=score,
        decided_at=review.decided_at,
        source_review_id=review.id,
        created_by_id=actor_id,
        answers=answers,
        enabled=True,
    )
    db.add(p)
    db.flush()
    audit.record(
        db,
        action="precedent_created",
        entity_type="precedent",
        entity_id=p.id,
        actor_id=actor_id,
        after={
            "vendor": p.vendor,
            "model_name": p.model_name,
            "terms_id": terms.get("id"),
            "questionnaire_version": p.questionnaire_version,
            "answer_count": len(answers),
            "source_review_id": str(review.id),
        },
        request_ip=request_ip,
    )
    return p


def _candidates(db: Session, vendor: str) -> list[Precedent]:
    """Enabled precedents for the vendor, most recently decided first."""
    stmt = (
        select(Precedent)
        .where(Precedent.vendor == vendor, Precedent.enabled.is_(True))
        .order_by(Precedent.decided_at.desc())
    )
    return list(db.execute(stmt).scalars())


def _carryable_keys(review: Review, precedent: Precedent) -> list[str]:
    """Control keys whose judgment answer can be carried from the precedent."""
    return [
        c.control_key
        for c in review.controls
        if c.answer_source in _CARRYABLE_ONTO and c.control_key in (precedent.answers or {})
    ]


def find_precedent(db: Session, review: Review) -> Assessment:
    """Evaluate whether this review can fast-track from a stored precedent."""
    a = Assessment()
    model = review.model
    a.model_terms = terms_of(model)

    if review.precedent_id is not None:
        a.precedent = db.get(Precedent, review.precedent_id)
        a.reasons.append("Precedent answers were already adopted into this review.")
        return a

    if review.state not in _ANSWERABLE_STATES:
        a.reasons.append(
            f"Review is '{review.state}' — precedent can only be adopted while a review is open."
        )
        return a

    candidates = _candidates(db, model.vendor)
    if not candidates:
        a.reasons.append(
            f"No precedent exists yet for vendor '{model.vendor}' — "
            "the first model from a vendor gets the full review."
        )
        return a

    if a.model_terms is None:
        a.reasons.append(
            "This model reports no governing-terms identity, so a precedent cannot be "
            "established — precedent matching fails closed to a full review."
        )
        return a

    # Prefer the most recently decided precedent under the SAME terms.
    match = next(
        (p for p in candidates if (p.terms or {}).get("id") == a.model_terms["id"]), None
    )
    if match is None:
        newest = candidates[0]
        a.precedent = newest
        a.reasons.append(
            f"Governing terms differ: this model is under "
            f"'{a.model_terms.get('label') or a.model_terms['id']}', but the stored "
            f"precedent ({newest.model_name}) is under "
            f"'{(newest.terms or {}).get('label') or (newest.terms or {}).get('id') or 'unknown terms'}'. "
            "Different terms require a full review."
        )
        return a

    a.precedent = match

    mine = (review.snapshot or {}).get("version")
    if mine != match.questionnaire_version:
        a.reasons.append(
            f"The precedent was recorded under questionnaire v{match.questionnaire_version}, "
            f"but this review uses v{mine} — answers cannot be carried across "
            "questionnaire versions."
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

    stored: dict[str, dict] = precedent.answers or {}
    carried: list[str] = []
    now = utcnow()
    for c in review.controls:
        src = stored.get(c.control_key)
        if c.answer_source not in _CARRYABLE_ONTO or src is None:
            continue  # auto/attested controls (and anything human-touched) stay fresh
        c.answer = src["answer"]
        c.evidence_url = src.get("evidence_url")
        c.evidence_note = src.get("evidence_note")
        c.answer_source = AnswerSource.CARRIED.value
        c.answered_by_id = actor_id
        c.answered_at = now
        carried.append(c.control_key)

    review.precedent_id = precedent.id
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
            "precedent_id": str(precedent.id),
            "precedent_model": precedent.model_name,
            "precedent_source_review_id": (
                str(precedent.source_review_id) if precedent.source_review_id else None
            ),
            "terms_id": (a.model_terms or {}).get("id"),
            "carried": carried,
            "carried_count": len(carried),
        },
        request_ip=request_ip,
    )
    return a, carried
