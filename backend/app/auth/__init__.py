"""Auth package. v1 ships a dev-auth fallback; OIDC/SSO lands in M10."""
from app.auth.roles import ROLE_IMPLIES, effective_roles, has_role

__all__ = ["ROLE_IMPLIES", "effective_roles", "has_role"]
