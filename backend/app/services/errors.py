"""Domain errors raised by services, mapped to HTTP responses in the API layer."""
from __future__ import annotations


class DomainError(Exception):
    """Base for domain/validation errors. `status` maps to an HTTP code."""

    status = 400

    def __init__(self, message: str, *, details: dict | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class NotFoundError(DomainError):
    status = 404


class ConflictError(DomainError):
    status = 409


class ValidationError(DomainError):
    status = 422


class ForbiddenError(DomainError):
    status = 403
