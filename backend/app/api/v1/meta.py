"""Meta endpoints: current user + questionnaire template."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import get_current_user
from app.models import User
from app.schemas import QuestionnaireOut, UserOut
from app.services.questionnaire import get_questionnaire

router = APIRouter(tags=["meta"])


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)) -> User:
    return user


@router.get("/questionnaire", response_model=QuestionnaireOut)
def questionnaire() -> dict:
    q = get_questionnaire()
    return q.as_snapshot()
