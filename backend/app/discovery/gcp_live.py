"""Live GCP discovery driver (M6).

Read-only enumeration of Vertex AI models via the regional
aiplatform.googleapis.com REST API — every call is a GET; the app never writes
to the cloud. Required IAM: **roles/aiplatform.viewer** on the project (or any
role covering aiplatform.*.list / publishers.models.list).

Two inventory layers, mirroring the Azure driver:
  * CATALOG — publisher models Google OFFERS in the org's approved regions
    (Vertex AI Model Garden, `publishers/{publisher}/models`), so a review can
    start before any resource exists. facts.deployment_status="catalog", no
    fabricated posture facts.
  * DEPLOYED — Vertex AI endpoints + uploaded/tuned models actually present in
    the project; per-resource posture (CMEK, private networking) merged
    FAIL-CLOSED across the footprint. A deployed (vendor, name, version)
    always wins over its catalog twin.

Auth (keyless / least-privilege, tried in order):
  1. GCP_ACCESS_TOKEN env — a short-lived bearer from
     `gcloud auth print-access-token` for containerized dev; expires in ~1h
     and is never persisted.
  2. google.auth.default() — Application Default Credentials: gcloud locally,
     attached service account / workload identity in production.
"""
from __future__ import annotations

import os
import re
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

import httpx

from app.config import get_settings
from app.discovery.base import DiscoveredModel, DiscoveryDriver
from app.services.autoanswer import DEFAULT_APPROVED_REGIONS
from app.services.errors import ValidationError

_API_V1 = "v1"
_API_BETA = "v1beta1"  # publisher model catalog

_PROJECT_RE = re.compile(r"^[a-z][a-z0-9-]{4,28}[a-z0-9]$")

# Model Garden publishers we enumerate (there is no list-publishers API).
_PUBLISHERS = ("google", "anthropic", "meta", "mistralai", "ai21", "cohere")

# Publisher -> vendor slug used across the app.
_PUBLISHER_VENDOR = {"mistralai": "mistral"}

# Governing-terms identity by vendor. Same ids as the Azure driver and the stub
# where the publisher's terms are cloud-agnostic (anthropic, meta, mistral), so
# a precedent minted on one cloud fast-tracks the other. Vendors not listed get
# terms=None, which FAILS CLOSED (no precedent fast-track).
_VENDOR_TERMS: dict[str, dict] = {
    "google": {
        "id": "gcp-service-terms",
        "label": "Google Cloud Service Terms (Vertex AI)",
        "url": "https://cloud.google.com/terms",
    },
    "anthropic": {
        "id": "anthropic-commercial-tos",
        "label": "Anthropic Commercial Terms of Service",
        "url": "https://www.anthropic.com/legal/commercial-terms",
    },
    "meta": {
        "id": "llama-3.3-community-license",
        "label": "Llama 3.3 Community License",
        "url": "https://www.llama.com/llama3_3/license/",
    },
    "mistral": {
        "id": "mistral-ai-terms",
        "label": "Mistral AI Terms of Service",
        "url": "https://mistral.ai/terms/",
    },
}

# Name fragments that indicate a non-text-only model.
_MULTIMODAL_HINTS = ("gemini", "imagen", "veo", "claude", "vision", "multimodal")


def _vendor_of(publisher: str) -> str:
    return _PUBLISHER_VENDOR.get(publisher, publisher)


def _modality(name: str) -> str:
    n = name.lower()
    return "multimodal" if any(h in n for h in _MULTIMODAL_HINTS) else "text"


# --- auth ----------------------------------------------------------------------

class _TokenSource:
    """Caches a bearer token; refreshes 5 minutes before expiry."""

    def __init__(self) -> None:
        self._credentials = None
        self._token: str | None = None
        self._expires_at: float = 0.0

    def bearer(self) -> str:
        env_token = os.environ.get("GCP_ACCESS_TOKEN")
        if env_token:
            return env_token
        if self._token and time.time() < self._expires_at - 300:
            return self._token
        # Imported lazily so stub-mode deployments don't need google-auth.
        import google.auth
        import google.auth.transport.requests

        if self._credentials is None:
            self._credentials, _ = google.auth.default(
                scopes=["https://www.googleapis.com/auth/cloud-platform.read-only"]
            )
        self._credentials.refresh(google.auth.transport.requests.Request())
        self._token = self._credentials.token
        expiry = getattr(self._credentials, "expiry", None)
        self._expires_at = expiry.timestamp() if expiry else time.time() + 600
        return self._token


# --- driver ----------------------------------------------------------------------

class GcpLiveDriver(DiscoveryDriver):
    cloud = "gcp"

    def __init__(self, fetch: Callable[[str], dict] | None = None, inventory_ttl: float = 60.0):
        # `fetch` is injectable for tests; the default does authenticated GETs.
        self._fetch = fetch or self._default_fetch
        self._tokens = _TokenSource()
        self._inventory_ttl = inventory_ttl
        self._inv_cache: dict[tuple, tuple[float, list[DiscoveredModel]]] = {}

    # -- transport --

    def _default_fetch(self, url: str) -> dict:
        try:
            resp = httpx.get(
                url, headers={"Authorization": f"Bearer {self._tokens.bearer()}"}, timeout=30.0
            )
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            code = e.response.status_code
            if code == 404:
                # A publisher/location combination Vertex doesn't serve — not an
                # error, just nothing offered there.
                return {}
            hint = (
                " Credential expired or lacks access — refresh GCP_ACCESS_TOKEN "
                "(gcloud auth print-access-token) or check the identity's "
                "aiplatform.viewer role."
                if code in (401, 403) else ""
            )
            raise ValidationError(f"GCP Vertex AI query failed with HTTP {code}.{hint}") from e
        except httpx.HTTPError as e:
            raise ValidationError(f"GCP Vertex AI query failed: {e}") from e
        try:
            return resp.json()
        except ValueError as e:  # 2xx but non-JSON body; don't leak the body itself
            raise ValidationError(
                f"GCP Vertex AI returned a non-JSON response (HTTP {resp.status_code}); "
                "check for a proxy or gateway intercepting aiplatform.googleapis.com."
            ) from e

    def _get_paged(self, url: str, items_key: str) -> list[dict]:
        """Follow pageToken pagination, concatenating the named item array."""
        items: list[dict] = []
        token = None
        while True:
            page = self._fetch(f"{url}&pageToken={token}" if token else url)
            items.extend(page.get(items_key, []))
            token = page.get("nextPageToken")
            if not token:
                return items

    # -- interface --

    def list_vendors(self, scope: str, config: dict | None = None) -> list[str]:
        inv = self._inventory(self._project(scope), self._catalog_scope(config))
        return sorted({m.vendor for m in inv})

    def list_models(self, scope: str, vendor: str, config: dict | None = None) -> list[DiscoveredModel]:
        inv = self._inventory(self._project(scope), self._catalog_scope(config))
        return [m for m in inv if m.vendor == vendor]

    # -- helpers --

    @staticmethod
    def _catalog_scope(config: dict | None) -> tuple[str, ...]:
        """Regions whose Model Garden catalog we list — scoped to the org's
        approved-regions policy (passed by the API layer as
        config["catalog_regions"])."""
        cfg = config or {}
        if not cfg.get("include_catalog", True):
            return ()
        regions = cfg.get("catalog_regions") or DEFAULT_APPROVED_REGIONS["gcp"]
        return tuple(sorted({r for r in regions if isinstance(r, str) and r}))

    def _project(self, scope: str) -> str:
        if _PROJECT_RE.match(scope or ""):
            return scope
        fallback = get_settings().gcp_project_id
        if fallback and _PROJECT_RE.match(fallback):
            return fallback
        raise ValidationError(
            "GCP live discovery needs a project id: set the discovery source's "
            "scope to the project id, or set GCP_PROJECT_ID."
        )

    def _inventory(self, project: str, catalog_regions: tuple[str, ...]) -> list[DiscoveredModel]:
        key = (project, catalog_regions)
        cached = self._inv_cache.get(key)
        if cached and time.monotonic() - cached[0] < self._inventory_ttl:
            return cached[1]
        models = self._build_inventory(project, catalog_regions)
        self._inv_cache[key] = (time.monotonic(), models)
        return models

    def _build_inventory(self, project: str, regions: tuple[str, ...]) -> list[DiscoveredModel]:
        # All regional queries are independent GETs — fetch concurrently
        # (catalog: regions × publishers; deployed: endpoints + models per region).
        with ThreadPoolExecutor(max_workers=8) as pool:
            cat_futs = {
                (r, pub): pool.submit(
                    self._get_paged,
                    f"https://{r}-aiplatform.googleapis.com/{_API_BETA}"
                    f"/publishers/{pub}/models?pageSize=200",
                    "publisherModels",
                )
                for r in regions
                for pub in _PUBLISHERS
            }
            ep_futs = {
                r: pool.submit(
                    self._get_paged,
                    f"https://{r}-aiplatform.googleapis.com/{_API_V1}"
                    f"/projects/{project}/locations/{r}/endpoints?pageSize=100",
                    "endpoints",
                )
                for r in regions
            }
            model_futs = {
                r: pool.submit(
                    self._get_paged,
                    f"https://{r}-aiplatform.googleapis.com/{_API_V1}"
                    f"/projects/{project}/locations/{r}/models?pageSize=100",
                    "models",
                )
                for r in regions
            }
            catalog_items = {k: f.result() for k, f in cat_futs.items()}
            endpoints_by_region = {r: f.result() for r, f in ep_futs.items()}
            models_by_region = {r: f.result() for r, f in model_futs.items()}

        deployed = self._deployed_models(project, endpoints_by_region, models_by_region)
        deployed_keys = {(m.vendor, m.model_name, m.model_version) for m in deployed}
        out = deployed + self._catalog_models(project, catalog_items, deployed_keys)
        return sorted(out, key=lambda m: (m.vendor, m.model_name, m.model_version or ""))

    # -- deployed (endpoints + uploaded/tuned models) --

    def _deployed_models(
        self,
        project: str,
        endpoints_by_region: dict[str, list[dict]],
        models_by_region: dict[str, list[dict]],
    ) -> list[DiscoveredModel]:
        # Model resource name -> its metadata (uploaded/tuned Vertex models).
        model_meta: dict[str, dict] = {}
        for region, models in models_by_region.items():
            for m in models:
                model_meta[m.get("name", "")] = {**m, "_region": region}

        # (vendor, name, version) -> per-endpoint observations, fail-closed merge.
        groups: dict[tuple, list[dict]] = defaultdict(list)
        for region, endpoints in endpoints_by_region.items():
            for ep in endpoints:
                private = bool(ep.get("network") or ep.get("privateServiceConnectConfig"))
                ep_cmk = bool((ep.get("encryptionSpec") or {}).get("kmsKeyName"))
                for dm in ep.get("deployedModels", []):
                    meta = model_meta.get(dm.get("model", ""), {})
                    name = meta.get("displayName") or dm.get("displayName")
                    if not name:
                        continue
                    vendor = self._deployed_vendor(name)
                    version = meta.get("versionId") or dm.get("modelVersionId")
                    groups[(vendor, name, version)].append({
                        "region": region,
                        "private": private,
                        "cmk": ep_cmk or bool((meta.get("encryptionSpec") or {}).get("kmsKeyName")),
                        "finetuned": bool(meta.get("baseModelSource")),
                        "endpoint": ep.get("name"),
                    })

        out = []
        for (vendor, name, version), obs in groups.items():
            regions = sorted({o["region"] for o in obs})
            facts = {
                "deployment_status": "deployed",
                "regions": regions,
                # Worst posture anywhere in the footprint wins.
                "public_network_access": "Disabled" if all(o["private"] for o in obs) else "Enabled",
                "encryption_cmk": all(o["cmk"] for o in obs),
                # googleapis endpoints enforce TLS 1.2+; no per-resource knob.
                "min_tls": "1.2",
                "min_tls_source": "platform-enforced (Google APIs require TLS 1.2+)",
                # A Vertex deployment pins the model version it serves.
                "version_upgrade_option": "NoAutoUpgrade",
                "is_finetuned": any(o["finetuned"] for o in obs),
                "modality": _modality(name),
                "terms": _VENDOR_TERMS.get(vendor),
            }
            out.append(DiscoveredModel(
                vendor=vendor,
                model_name=name,
                model_version=version,
                model_format="Vertex AI",
                resource_id=f"gcp:{project}:{vendor}:{name}",
                resource_kind="aiplatform.googleapis.com/Endpoint",
                subscription_or_project=project,
                regions=regions,
                endpoint=obs[0]["endpoint"] if len(obs) == 1 else None,
                provisioning_state="Deployed",
                facts=facts,
            ))
        return out

    @staticmethod
    def _deployed_vendor(display_name: str) -> str:
        n = display_name.lower()
        for hint, vendor in (
            ("gemini", "google"), ("imagen", "google"), ("veo", "google"),
            ("claude", "anthropic"), ("llama", "meta"), ("mistral", "mistral"),
        ):
            if hint in n:
                return vendor
        return "custom"

    # -- catalog (Model Garden publisher models) --

    def _catalog_models(
        self,
        project: str,
        catalog_items: dict[tuple, list[dict]],
        deployed: set[tuple],
    ) -> list[DiscoveredModel]:
        """Publisher models offered in the approved regions but not deployed in
        the project — reviewable before any resource is created (zero cost,
        aiplatform.viewer only)."""
        catalog: dict[tuple, dict] = {}
        for (region, publisher), items in sorted(catalog_items.items()):
            vendor = _vendor_of(publisher)
            for item in items:
                # name: "publishers/google/models/gemini-2.5-pro"
                name = (item.get("name") or "").rsplit("/", 1)[-1]
                if not name:
                    continue
                key = (vendor, name, item.get("versionId"))
                if key in deployed:
                    continue  # actually-deployed model (with real posture) wins
                entry = catalog.setdefault(key, {
                    "regions": set(),
                    "lifecycle": item.get("launchStage"),
                    "open_source": item.get("openSourceCategory"),
                })
                entry["regions"].add(region)

        out = []
        for (vendor, name, version), entry in catalog.items():
            regions = sorted(entry["regions"])
            facts = {
                "deployment_status": "catalog",
                "regions": regions,
                "lifecycle_status": entry["lifecycle"],
                "open_source_category": entry["open_source"],
                "min_tls": "1.2",
                "min_tls_source": "platform-enforced (Google APIs require TLS 1.2+)",
                "is_finetuned": False,
                "modality": _modality(name),
                "terms": _VENDOR_TERMS.get(vendor),
            }
            out.append(DiscoveredModel(
                vendor=vendor,
                model_name=name,
                model_version=version,
                model_format="Vertex AI Model Garden",
                resource_id=f"gcp:{project}:{vendor}:{name}",
                resource_kind="aiplatform.googleapis.com/PublisherModel",
                subscription_or_project=project,
                regions=regions,
                provisioning_state="NotDeployed",
                facts=facts,
            ))
        return out
