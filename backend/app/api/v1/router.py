"""Aggregate v1 API router."""
from fastapi import APIRouter

from app.api.v1 import approvals, audit, discovery, meta, models, reviews

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(meta.router)
api_router.include_router(discovery.router)
api_router.include_router(models.router)
api_router.include_router(reviews.router)
api_router.include_router(approvals.router)
api_router.include_router(audit.router)
