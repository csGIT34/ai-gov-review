"""Pytest fixtures: an isolated SQLite app instance with seeded dev data."""
from __future__ import annotations

import os

os.environ.setdefault("DEV_AUTH_ENABLED", "true")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps import db_session
from app.bootstrap import seed_dev_data
from app.discovery.base import discovery_cache
from app.main import app
from app.models import Base


@pytest.fixture()
def client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    with TestSession() as db:
        seed_dev_data(db)

    def _override():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[db_session] = _override
    discovery_cache.clear()
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
    discovery_cache.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()


# Convenience auth headers for the seeded dev users.
ADMIN = {"X-Dev-User": "admin@dev.local"}
APPROVER = {"X-Dev-User": "approver@dev.local"}
REVIEWER = {"X-Dev-User": "reviewer@dev.local"}
