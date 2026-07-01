"""Discovery driver interface + registry + a small TTL cache.

A driver enumerates, for one configured cloud scope, the vendors and models a
reviewer can pick from. v1 ships a StubDriver; real Azure/GCP drivers register
here in M5/M6 (same interface, so the API and dropdowns don't change).
"""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from datetime import datetime


@dataclass
class DiscoveredModel:
    """A model surfaced by a discovery driver, ready to seed a Model row."""

    vendor: str
    model_name: str
    resource_id: str  # canonical cloud id — dedup key (with model_version)
    model_version: str | None = None
    model_format: str | None = None
    resource_kind: str | None = None
    subscription_or_project: str | None = None
    resource_group: str | None = None
    region: str | None = None
    sku: str | None = None
    endpoint: str | None = None
    provisioning_state: str | None = None
    cloud_created_at: datetime | None = None
    cloud_last_modified_at: datetime | None = None

    def label(self) -> str:
        v = f":{self.model_version}" if self.model_version else ""
        loc = f" ({self.region})" if self.region else ""
        return f"{self.model_name}{v}{loc}"

    def as_dict(self) -> dict:
        return asdict(self)


class DiscoveryDriver(ABC):
    """Enumerates vendors/models for one cloud. Implementations must be read-only."""

    cloud: str = ""

    @abstractmethod
    def list_vendors(self, scope: str, config: dict | None = None) -> list[str]:
        ...

    @abstractmethod
    def list_models(
        self, scope: str, vendor: str, config: dict | None = None
    ) -> list[DiscoveredModel]:
        ...


# --- registry ------------------------------------------------------------------

_REGISTRY: dict[str, DiscoveryDriver] = {}


def register_driver(driver: DiscoveryDriver) -> None:
    _REGISTRY[driver.cloud] = driver


def get_driver(cloud: str) -> DiscoveryDriver:
    driver = _REGISTRY.get(cloud)
    if driver is None:
        raise KeyError(f"No discovery driver registered for cloud '{cloud}'")
    return driver


def list_supported_clouds() -> list[str]:
    return sorted(_REGISTRY.keys())


# --- tiny TTL cache ------------------------------------------------------------
# Cloud queries can be slow; cache dropdown results briefly so the UI is snappy
# and we don't hammer cloud APIs. Keyed by (cloud, scope, vendor|"").


@dataclass
class _CacheEntry:
    value: list
    expires_at: float


class TTLCache:
    def __init__(self, ttl_seconds: float = 120.0):
        self.ttl = ttl_seconds
        self._store: dict[tuple, _CacheEntry] = {}

    def get(self, key: tuple):
        entry = self._store.get(key)
        if entry is None:
            return None
        if entry.expires_at < time.monotonic():
            self._store.pop(key, None)
            return None
        return entry.value

    def set(self, key: tuple, value: list) -> None:
        self._store[key] = _CacheEntry(value=value, expires_at=time.monotonic() + self.ttl)

    def clear(self) -> None:
        self._store.clear()


discovery_cache = TTLCache(ttl_seconds=120.0)


# Register the built-in stub driver(s). Real drivers replace these in M5/M6.
from app.discovery.stub import StubAzureDriver, StubGcpDriver  # noqa: E402

register_driver(StubAzureDriver())
register_driver(StubGcpDriver())
