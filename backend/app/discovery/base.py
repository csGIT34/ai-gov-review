"""Discovery driver interface + registry + a small TTL cache.

A driver enumerates, for one configured cloud scope, the vendors and models a
reviewer can pick from. v1 ships a StubDriver; real Azure/GCP drivers register
here in M5/M6 (same interface, so the API and dropdowns don't change).
"""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
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
    # The regions this model is deployed to (its residency footprint) — a model is
    # typically deployed to many regions for quota.
    regions: list = field(default_factory=list)
    sku: str | None = None
    endpoint: str | None = None
    provisioning_state: str | None = None
    cloud_created_at: datetime | None = None
    cloud_last_modified_at: datetime | None = None
    # Cloud resource properties the auto-answer engine reads (regions, content
    # filter, network exposure, encryption, versioning, etc.).
    facts: dict = field(default_factory=dict)

    def label(self) -> str:
        v = f":{self.model_version}" if self.model_version else ""
        n = len(self.regions)
        loc = f" ({n} region{'s' if n != 1 else ''})" if n else ""
        tag = " — not deployed" if self.provisioning_state == "NotDeployed" else ""
        return f"{self.model_name}{v}{loc}{tag}"

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
# Both a "stub" and a "live" driver are registered per cloud; WHICH one a
# discovery source uses is admin-configurable per source
# (source.config["driver"]), with the AZURE_DISCOVERY / GCP_DISCOVERY env vars
# as the default. No restart needed to flip a source between stub and live.

VALID_MODES = ("stub", "live")

_REGISTRY: dict[tuple[str, str], DiscoveryDriver] = {}


def register_driver(driver: DiscoveryDriver, mode: str = "stub") -> None:
    _REGISTRY[(driver.cloud, mode)] = driver


def get_driver(cloud: str, mode: str = "stub") -> DiscoveryDriver:
    driver = _REGISTRY.get((cloud, mode))
    if driver is None:
        raise KeyError(f"No '{mode}' discovery driver registered for cloud '{cloud}'")
    return driver


def resolve_mode(cloud: str, config: dict | None) -> str:
    """Driver mode for a source: its own config wins, else the env default."""
    from app.config import get_settings

    cfg_mode = ((config or {}).get("driver") or "").lower()
    if cfg_mode in VALID_MODES:
        return cfg_mode
    env_default = {
        "azure": get_settings().azure_discovery,
        "gcp": get_settings().gcp_discovery,
    }.get(cloud, "stub").lower()
    return env_default if env_default in VALID_MODES else "stub"


def driver_for(cloud: str, config: dict | None) -> DiscoveryDriver:
    return get_driver(cloud, resolve_mode(cloud, config))


def list_supported_clouds() -> list[str]:
    return sorted({cloud for cloud, _ in _REGISTRY})


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


# Register drivers: stub AND live for each cloud, always. Which one a source
# uses is decided per request via resolve_mode() — admin-editable, no restart.
# Live drivers are cheap to construct; credentials resolve lazily on first use.
from app.discovery.azure_live import AzureLiveDriver  # noqa: E402
from app.discovery.gcp_live import GcpLiveDriver  # noqa: E402
from app.discovery.stub import StubAzureDriver, StubGcpDriver  # noqa: E402

register_driver(StubAzureDriver(), "stub")
register_driver(StubGcpDriver(), "stub")
register_driver(AzureLiveDriver(), "live")
register_driver(GcpLiveDriver(), "live")
