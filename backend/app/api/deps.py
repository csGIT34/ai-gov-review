"""FastAPI dependencies: current user, role guards, request context.

v1 uses dev-auth (X-Dev-User header). Replaced by OIDC token validation in M10;
the dependency signatures here won't change, so routers are insulated.
"""
from __future__ import annotations

from collections.abc import Iterator

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import has_role
from app.auth.dev import DEFAULT_DEV_USER
from app.config import Settings, get_settings
from app.db import get_db
from app.models import Role, User


def db_session() -> Iterator[Session]:
    yield from get_db()


def client_ip(request: Request) -> str | None:
    if request.client:
        return request.client.host
    return None


def get_current_user(
    x_dev_user: str | None = Header(default=None, alias="X-Dev-User"),
    db: Session = Depends(db_session),
    settings: Settings = Depends(get_settings),
) -> User:
    if not settings.dev_auth_enabled:
        # OIDC bearer-token validation lands in M10.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication not configured (OIDC pending — M10).",
        )
    email = x_dev_user or DEFAULT_DEV_USER
    user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Unknown or inactive dev user '{email}'.",
        )
    return user


def require_role(role: str):
    """Dependency factory: require `role` (respecting admin ⊃ approver ⊃ reviewer)."""

    def _dep(user: User = Depends(get_current_user)) -> User:
        if not has_role(user.roles, role):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires '{role}' role.",
            )
        return user

    return _dep


require_reviewer = require_role(Role.REVIEWER.value)
require_approver = require_role(Role.APPROVER.value)
require_admin = require_role(Role.ADMIN.value)
