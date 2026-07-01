"""FastAPI application factory."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api.v1.router import api_router
from app.config import get_settings
from app.db import SessionLocal, engine
from app.services.errors import DomainError

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    if settings.dev_auth_enabled:
        try:
            from app.bootstrap import seed_dev_data

            with SessionLocal() as db:
                seed_dev_data(db)
            log.info("dev data seeded")
        except Exception as exc:  # pragma: no cover
            log.warning("startup seeding skipped (%s); run migrations first", exc)
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="AI Governance Review",
        version="0.1.0",
        description="Discover cloud-hosted AI models, run a NIST AI RMF review, "
        "score risk, and gate approval with an immutable audit trail.",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(DomainError)
    async def _domain_error_handler(_: Request, exc: DomainError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status,
            content={"detail": exc.message, "details": exc.details},
        )

    @app.get("/healthz", tags=["health"])
    def healthz() -> dict:
        return {"status": "ok"}

    @app.get("/readyz", tags=["health"])
    def readyz() -> JSONResponse:
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return JSONResponse({"status": "ready"})
        except Exception as exc:  # pragma: no cover - infra failure path
            log.warning("readiness check failed: %s", exc)
            return JSONResponse({"status": "degraded"}, status_code=503)

    app.include_router(api_router)
    return app


app = create_app()
