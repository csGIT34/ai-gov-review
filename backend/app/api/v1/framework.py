"""Governance framework status: which NIST version the questions implement, and
whether an admin has recently confirmed it's still current."""
from __future__ import annotations

from datetime import timedelta, timezone

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.api.deps import client_ip, db_session, get_current_user, require_admin
from app.models import GovernancePolicy, User, utcnow
from app.nist import latest_release
from app.schemas import FrameworkReviewIn, FrameworkStatusOut, UpdateCheckOut
from app.services import policy as policy_svc
from app.services.questionnaire import get_questionnaire

router = APIRouter(prefix="/framework", tags=["framework"])


def _status(db: Session, policy: GovernancePolicy) -> FrameworkStatusOut:
    q = get_questionnaire()
    meta = q.meta
    reviewed_by = None
    if policy.framework_reviewed_by_id:
        u = db.get(User, policy.framework_reviewed_by_id)
        reviewed_by = u.display_name if u else None

    next_due = None
    overdue = False
    last = policy.framework_last_reviewed_at
    if last is not None:
        # SQLite returns naive datetimes; treat stored timestamps as UTC.
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        next_due = last + timedelta(days=policy.framework_review_interval_days)
        overdue = utcnow() > next_due

    latest = latest_release()
    return FrameworkStatusOut(
        id=q.framework,
        name=meta.get("name", q.framework),
        rmf_version=meta.get("rmf_version"),
        effective_date=meta.get("effective_date"),
        references=meta.get("references", []),
        questionnaire_version=q.version,
        control_count=q.control_count,
        last_reviewed_at=policy.framework_last_reviewed_at,
        reviewed_by=reviewed_by,
        review_interval_days=policy.framework_review_interval_days,
        next_review_due=next_due,
        overdue=overdue,
        notes=policy.framework_review_notes,
        update_available=meta.get("rmf_version") != latest["version"],
        latest_known_version=latest["version"],
    )


@router.get("", response_model=FrameworkStatusOut)
def get_framework(
    db: Session = Depends(db_session), _: User = Depends(get_current_user)
) -> FrameworkStatusOut:
    return _status(db, policy_svc.get_policy(db))


@router.get("/check-updates", response_model=UpdateCheckOut)
def check_updates(_: User = Depends(get_current_user)) -> UpdateCheckOut:
    """Compare the version the questionnaire implements against the known-latest
    NIST release (a maintained registry — NIST has no version API)."""
    q = get_questionnaire()
    implemented = q.meta.get("rmf_version") or ""
    latest = latest_release()
    return UpdateCheckOut(
        implemented_version=implemented,
        latest_known_version=latest["version"],
        latest_published=latest["published"],
        latest_label=latest["label"],
        latest_url=latest["url"],
        latest_notes=latest["notes"],
        up_to_date=implemented == latest["version"],
        checked_at=utcnow(),
    )


@router.post("/reviewed", response_model=FrameworkStatusOut)
def mark_reviewed(
    payload: FrameworkReviewIn,
    request: Request,
    db: Session = Depends(db_session),
    user: User = Depends(require_admin),
) -> FrameworkStatusOut:
    policy = policy_svc.mark_framework_reviewed(
        db,
        actor_id=user.id,
        notes=payload.notes,
        interval_days=payload.interval_days,
        request_ip=client_ip(request),
    )
    db.commit()
    db.refresh(policy)
    return _status(db, policy)
