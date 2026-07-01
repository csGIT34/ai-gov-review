"""Role hierarchy: admin ⊃ approver ⊃ reviewer."""
from __future__ import annotations

from collections.abc import Iterable

from app.models.enums import Role

ROLE_IMPLIES: dict[str, set[str]] = {
    Role.ADMIN.value: {Role.ADMIN.value, Role.APPROVER.value, Role.REVIEWER.value},
    Role.APPROVER.value: {Role.APPROVER.value, Role.REVIEWER.value},
    Role.REVIEWER.value: {Role.REVIEWER.value},
}


def effective_roles(roles: Iterable[str]) -> set[str]:
    out: set[str] = set()
    for r in roles:
        out |= ROLE_IMPLIES.get(r, {r})
    return out


def has_role(user_roles: Iterable[str], required: str) -> bool:
    return required in effective_roles(user_roles)
