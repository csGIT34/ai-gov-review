"""Dev-auth fallback (M0–M4).

When DEV_AUTH_ENABLED is true the API trusts an `X-Dev-User` header naming the
acting user's email, defaulting to the seeded admin. This is a stand-in for the
OIDC flow built in M10 and MUST be disabled in production.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Role, User

# Seeded dev users (email -> (display_name, roles)).
DEV_USERS: dict[str, tuple[str, list[str]]] = {
    "admin@dev.local": ("Dev Admin", [Role.ADMIN.value]),
    "approver@dev.local": ("Dev Approver", [Role.APPROVER.value]),
    "reviewer@dev.local": ("Dev Reviewer", [Role.REVIEWER.value]),
}

DEFAULT_DEV_USER = "admin@dev.local"


def seed_dev_users(db: Session) -> None:
    for email, (name, roles) in DEV_USERS.items():
        exists = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
        if exists is None:
            db.add(User(email=email, display_name=name, roles=roles, is_active=True))
    db.commit()
