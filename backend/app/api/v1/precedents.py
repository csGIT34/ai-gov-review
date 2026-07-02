"""Admin management of stored precedents (the rubber-stamp source records).

Precedents are minted automatically when a review is approved and live
independently of review records. Admins can disable one (kill switch — stops
all future fast-tracks from it, reversible) or delete it outright. Reviews
that already adopted from it keep their carried answers; the audit log keeps
the adoption provenance.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import client_ip, db_session, get_current_user, require_admin
from app.models import Precedent, Review, User
from app.schemas import PrecedentAdminOut, PrecedentToggleIn
from app.services import audit
from app.services.errors import NotFoundError

router = APIRouter(prefix="/precedents", tags=["precedents"])


def _get(db: Session, precedent_id: uuid.UUID) -> Precedent:
    p = db.get(Precedent, precedent_id)
    if p is None:
        raise NotFoundError("Precedent not found")
    return p


@router.get("", response_model=list[PrecedentAdminOut])
def list_precedents(
    db: Session = Depends(db_session), _: User = Depends(get_current_user)
) -> list[Precedent]:
    return list(
        db.execute(select(Precedent).order_by(Precedent.created_at.desc())).scalars()
    )


@router.patch("/{precedent_id}", response_model=PrecedentAdminOut)
def toggle_precedent(
    precedent_id: uuid.UUID,
    payload: PrecedentToggleIn,
    request: Request,
    db: Session = Depends(db_session),
    user: User = Depends(require_admin),
) -> Precedent:
    p = _get(db, precedent_id)
    if p.enabled != payload.enabled:
        p.enabled = payload.enabled
        audit.record(
            db,
            action="precedent_enabled" if payload.enabled else "precedent_disabled",
            entity_type="precedent",
            entity_id=p.id,
            actor_id=user.id,
            after={"vendor": p.vendor, "model_name": p.model_name, "enabled": p.enabled},
            request_ip=client_ip(request),
        )
        db.commit()
        db.refresh(p)
    return p


@router.delete("/{precedent_id}", status_code=204)
def delete_precedent(
    precedent_id: uuid.UUID,
    request: Request,
    db: Session = Depends(db_session),
    user: User = Depends(require_admin),
) -> None:
    p = _get(db, precedent_id)
    # Reviews that adopted from it keep their carried answers; detach the link
    # (the audit log preserves the adoption provenance).
    for r in db.execute(select(Review).where(Review.precedent_id == p.id)).scalars():
        r.precedent_id = None
    audit.record(
        db,
        action="precedent_deleted",
        entity_type="precedent",
        entity_id=p.id,
        actor_id=user.id,
        before={
            "vendor": p.vendor,
            "model_name": p.model_name,
            "terms_id": (p.terms or {}).get("id"),
            "enabled": p.enabled,
            "answer_count": len(p.answers or {}),
        },
        request_ip=client_ip(request),
    )
    db.delete(p)
    db.commit()
