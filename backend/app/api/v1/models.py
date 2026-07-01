"""Model inventory endpoints."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import db_session, get_current_user
from app.models import Model, Review, User
from app.schemas import ModelDetailOut, ModelOut, ReviewOut

router = APIRouter(prefix="/models", tags=["models"])


@router.get("", response_model=list[ModelOut])
def list_models(
    db: Session = Depends(db_session),
    _: User = Depends(get_current_user),
    cloud: str | None = Query(default=None),
    status_: str | None = Query(default=None, alias="status"),
    tier: int | None = Query(default=None),
) -> list[Model]:
    stmt = select(Model)
    if cloud:
        stmt = stmt.where(Model.cloud == cloud)
    if status_:
        stmt = stmt.where(Model.status == status_)
    if tier is not None:
        stmt = stmt.where(Model.latest_tier == tier)
    stmt = stmt.order_by(Model.last_seen_at.desc())
    return list(db.execute(stmt).scalars())


@router.get("/{model_id}", response_model=ModelDetailOut)
def get_model(
    model_id: uuid.UUID,
    db: Session = Depends(db_session),
    _: User = Depends(get_current_user),
) -> Model:
    model = db.get(Model, model_id)
    if model is None:
        raise HTTPException(status_code=404, detail="Model not found")
    return model


@router.get("/{model_id}/reviews", response_model=list[ReviewOut])
def model_reviews(
    model_id: uuid.UUID,
    db: Session = Depends(db_session),
    _: User = Depends(get_current_user),
) -> list[Review]:
    return list(
        db.execute(
            select(Review).where(Review.model_id == model_id).order_by(Review.opened_at.desc())
        ).scalars()
    )
