"""Live Azure discovery driver (M5).

Read-only enumeration of Azure OpenAI / AI Foundry model deployments via the
ARM REST API — every call is a GET against management.azure.com; the app never
writes to the cloud. Required RBAC: **Reader** on the subscription (every
endpoint used is covered by */read).

Shape contract: identical to the stub — one DiscoveredModel per LOGICAL model
(vendor, name, version), with the regions[] footprint aggregated across every
account/deployment that serves it. `facts` are merged FAIL-CLOSED: the worst
security posture anywhere in the footprint wins, so one weak regional
deployment can't hide behind a hardened one.

Two inventory layers:
  * DEPLOYED — accounts + deployments actually present in the subscription;
    full resource posture facts.
  * CATALOG — models Azure OFFERS in the org's approved regions
    (locations/{region}/models), so a review can start before any resource is
    created. Catalog entries carry facts.deployment_status="catalog" and NO
    posture facts (there is no resource to read them from); a deployed model
    with the same (vendor, name, version) always wins.

Auth (keyless / least-privilege, tried in order):
  1. AZURE_ACCESS_TOKEN env — a short-lived bearer from
     `az account get-access-token` for containerized dev; expires in ~1h and
     is never persisted.
  2. azure.identity.DefaultAzureCredential — az CLI locally, managed identity
     or workload identity in production.
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

ARM = "https://management.azure.com"
_API_ACCOUNTS = "2024-10-01"      # Microsoft.CognitiveServices accounts + deployments
_API_DIAG = "2021-05-01-preview"  # Microsoft.Insights diagnosticSettings

_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)

# Account kinds that can host model deployments.
_MODEL_KINDS = {"OpenAI", "AIServices"}

# Deployment model `format` -> vendor slug used across the app.
_FORMAT_VENDOR = {
    "OpenAI": "openai",
    "Meta": "meta",
    "Mistral AI": "mistral",
    "Mistral": "mistral",
    "Cohere": "cohere",
    "Microsoft": "microsoft",
    "DeepSeek": "deepseek",
    "xAI": "xai",
    "AI21 Labs": "ai21",
    "Stability AI": "stabilityai",
    "Black Forest Labs": "black-forest-labs",
}

# Governing-terms identity by vendor. Derived from the publisher's standard
# Azure terms — good enough for precedent matching; reading the actual
# marketplace agreement id off each resource is a future refinement. Vendors
# not listed get terms=None, which FAILS CLOSED (no precedent fast-track).
_VENDOR_TERMS: dict[str, dict] = {
    "openai": {
        "id": "azure-openai-service-terms",
        "label": "Azure OpenAI Service Terms",
        "url": "https://learn.microsoft.com/legal/cognitive-services/openai/",
    },
    "microsoft": {
        "id": "microsoft-product-terms",
        "label": "Microsoft Product Terms",
        "url": "https://www.microsoft.com/licensing/terms/",
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
    # Publisher terms are cloud-agnostic: Claude on Azure AI Foundry is governed
    # by the same Anthropic commercial terms as Claude on Vertex, so the SAME
    # terms id lets a precedent minted on one cloud fast-track the other.
    "anthropic": {
        "id": "anthropic-commercial-tos",
        "label": "Anthropic Commercial Terms of Service",
        "url": "https://www.anthropic.com/legal/commercial-terms",
    },
}


def _slug(fmt: str) -> str:
    return _FORMAT_VENDOR.get(fmt, re.sub(r"[^a-z0-9]+", "-", fmt.lower()).strip("-"))


# --- auth ----------------------------------------------------------------------

class _TokenSource:
    """Caches an ARM bearer token; refreshes 5 minutes before expiry."""

    def __init__(self) -> None:
        self._token: str | None = None
        self._expires_on: float = 0.0
        self._credential = None

    def bearer(self) -> str:
        env_token = os.environ.get("AZURE_ACCESS_TOKEN")
        if env_token:
            return env_token
        if self._token and time.time() < self._expires_on - 300:
            return self._token
        if self._credential is None:
            # Imported lazily so stub-mode deployments don't need azure-identity.
            from azure.identity import DefaultAzureCredential

            self._credential = DefaultAzureCredential()
        t = self._credential.get_token(f"{ARM}/.default")
        self._token, self._expires_on = t.token, float(t.expires_on)
        return self._token


# --- driver ----------------------------------------------------------------------

class AzureLiveDriver(DiscoveryDriver):
    cloud = "azure"

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
            hint = (
                " Credential expired or lacks access — refresh AZURE_ACCESS_TOKEN "
                "(az account get-access-token) or check the identity's Reader role."
                if code in (401, 403) else ""
            )
            raise ValidationError(f"Azure ARM query failed with HTTP {code}.{hint}") from e
        except httpx.HTTPError as e:
            raise ValidationError(f"Azure ARM query failed: {e}") from e
        try:
            return resp.json()
        except ValueError as e:  # 2xx but non-JSON body; don't leak the body itself
            raise ValidationError(
                f"Azure ARM returned a non-JSON response (HTTP {resp.status_code}); "
                "check for a proxy or gateway intercepting management.azure.com."
            ) from e

    def _get_paged(self, url: str) -> list[dict]:
        """Follow ARM's nextLink pagination, concatenating `value` arrays."""
        items: list[dict] = []
        while url:
            page = self._fetch(url)
            items.extend(page.get("value", []))
            url = page.get("nextLink")
        return items

    # -- interface --

    def list_vendors(self, scope: str, config: dict | None = None) -> list[str]:
        inv = self._inventory(self._subscription(scope), self._catalog_scope(config))
        return sorted({m.vendor for m in inv})

    def list_models(self, scope: str, vendor: str, config: dict | None = None) -> list[DiscoveredModel]:
        inv = self._inventory(self._subscription(scope), self._catalog_scope(config))
        return [m for m in inv if m.vendor == vendor]

    # -- helpers --

    @staticmethod
    def _catalog_scope(config: dict | None) -> tuple[str, ...]:
        """Regions whose model CATALOG we list (so reviews can start before any
        resource exists). Scoped to the org's approved-regions policy — passed in
        by the API layer as config["catalog_regions"] — because a model only
        matters if it can be deployed somewhere policy allows. Empty when the
        source opts out via config["include_catalog"] = false."""
        cfg = config or {}
        if not cfg.get("include_catalog", True):
            return ()
        regions = cfg.get("catalog_regions") or DEFAULT_APPROVED_REGIONS["azure"]
        return tuple(sorted({r for r in regions if isinstance(r, str) and r}))

    def _subscription(self, scope: str) -> str:
        if _UUID_RE.match(scope or ""):
            return scope
        fallback = get_settings().azure_subscription_id
        if fallback and _UUID_RE.match(fallback):
            return fallback
        raise ValidationError(
            "Azure live discovery needs a subscription id: set the discovery source's "
            "scope to the subscription GUID, or set AZURE_SUBSCRIPTION_ID."
        )

    def _inventory(self, sub: str, catalog_regions: tuple[str, ...]) -> list[DiscoveredModel]:
        key = (sub, catalog_regions)
        cached = self._inv_cache.get(key)
        if cached and time.monotonic() - cached[0] < self._inventory_ttl:
            return cached[1]
        models = self._build_inventory(sub, catalog_regions)
        self._inv_cache[key] = (time.monotonic(), models)
        return models

    def _build_inventory(self, sub: str, catalog_regions: tuple[str, ...]) -> list[DiscoveredModel]:
        accounts = self._get_paged(
            f"{ARM}/subscriptions/{sub}/providers/Microsoft.CognitiveServices/accounts"
            f"?api-version={_API_ACCOUNTS}"
        )
        model_accts = [a for a in accounts if a.get("kind") in _MODEL_KINDS]

        # Per-account details and per-region catalogs are independent ARM GETs —
        # fetch them concurrently. Serially a cold inventory is 7+ round-trips
        # (several seconds) and the review dropdowns feel broken.
        with ThreadPoolExecutor(max_workers=8) as pool:
            diag_futs = {
                a["id"]: pool.submit(
                    self._get_paged,
                    f"{ARM}{a['id']}/providers/Microsoft.Insights/diagnosticSettings"
                    f"?api-version={_API_DIAG}",
                )
                for a in model_accts
            }
            dep_futs = {
                a["id"]: pool.submit(
                    self._get_paged, f"{ARM}{a['id']}/deployments?api-version={_API_ACCOUNTS}"
                )
                for a in model_accts
            }
            cat_futs = {
                r: pool.submit(
                    self._get_paged,
                    f"{ARM}/subscriptions/{sub}/providers/Microsoft.CognitiveServices"
                    f"/locations/{r}/models?api-version={_API_ACCOUNTS}",
                )
                for r in catalog_regions
            }
            deployments_by_acct = {aid: f.result() for aid, f in dep_futs.items()}
            diag_by_acct = {aid: f.result() for aid, f in diag_futs.items()}
            catalog_by_region = {r: f.result() for r, f in cat_futs.items()}

        # (vendor, model_name, model_version) -> observations across the footprint
        groups: dict[tuple, list[dict]] = defaultdict(list)

        for acct in model_accts:
            acct_id = acct["id"]
            props = acct.get("properties") or {}
            has_diag = _has_enabled_log_sink(diag_by_acct[acct_id])
            for dep in deployments_by_acct[acct_id]:
                dprops = dep.get("properties") or {}
                model = dprops.get("model") or {}
                name = model.get("name")
                if not name:
                    continue
                vendor = _slug(model.get("format") or "unknown")
                groups[(vendor, name, model.get("version"))].append({
                    "format": model.get("format"),
                    "region": acct.get("location"),
                    "resource_group": _rg_of(acct_id),
                    "endpoint": props.get("endpoint"),
                    "sku": (dep.get("sku") or {}).get("name"),
                    "provisioning_state": dprops.get("provisioningState"),
                    "content_filter": dprops.get("raiPolicyName"),
                    "public_network_access": props.get("publicNetworkAccess"),
                    "local_auth_disabled": bool(props.get("disableLocalAuth")),
                    "encryption_cmk": (props.get("encryption") or {}).get("keySource")
                    == "Microsoft.KeyVault",
                    "diagnostic_settings": has_diag,
                    "version_upgrade_option": dprops.get("versionUpgradeOption"),
                    "capabilities": dprops.get("capabilities") or {},
                })

        models = [
            self._merge(sub, vendor, name, version, obs)
            for (vendor, name, version), obs in groups.items()
        ]
        models.extend(self._catalog_models(sub, catalog_by_region, deployed=set(groups)))
        return sorted(models, key=lambda m: (m.vendor, m.model_name, m.model_version or ""))

    def _catalog_models(
        self, sub: str, catalog_by_region: dict[str, list[dict]], deployed: set[tuple]
    ) -> list[DiscoveredModel]:
        """Models Azure OFFERS in the given regions but that have no deployment in
        the subscription — reviewable before any resource is created (zero cost,
        Reader role only). A deployed (vendor, name, version) always wins: it has
        real posture facts."""
        catalog: dict[tuple, dict] = {}
        for region in sorted(catalog_by_region):
            for item in catalog_by_region[region]:
                if item.get("kind") not in _MODEL_KINDS:
                    continue
                model = item.get("model") or {}
                name = model.get("name")
                if not name:
                    continue
                vendor = _slug(model.get("format") or "unknown")
                key = (vendor, name, model.get("version"))
                if key in deployed:
                    continue
                entry = catalog.setdefault(key, {
                    "format": model.get("format"),
                    "regions": set(),
                    "sku": item.get("skuName"),
                    "capabilities": {},
                    "lifecycle": model.get("lifecycleStatus"),
                    "deprecation": (model.get("deprecation") or {}).get("inference"),
                })
                entry["regions"].add(region)
                entry["capabilities"].update(model.get("capabilities") or {})
        return [
            self._catalog_model(sub, vendor, name, version, entry)
            for (vendor, name, version), entry in catalog.items()
        ]

    def _catalog_model(
        self, sub: str, vendor: str, name: str, version: str | None, entry: dict
    ) -> DiscoveredModel:
        regions = sorted(entry["regions"])
        caps = {k.lower() for k in entry["capabilities"]}
        # Posture facts (network, CMK, filters, diagnostics) are intentionally
        # ABSENT: there is no resource to read them from. deployment_status tells
        # the auto-answer engine to treat them as a pre-deployment plan to confirm
        # rather than a measured "no".
        facts = {
            "deployment_status": "catalog",
            "regions": regions,
            "lifecycle_status": entry["lifecycle"],
            "deprecation_inference": entry["deprecation"],
            "min_tls": "1.2",
            "min_tls_source": "platform-enforced (Azure AI services require TLS 1.2+)",
            "is_finetuned": False,
            "modality": "multimodal"
            if any(("image" in c or "vision" in c or "audio" in c) for c in caps) else "text",
            "terms": _VENDOR_TERMS.get(vendor),
        }
        return DiscoveredModel(
            vendor=vendor,
            model_name=name,
            model_version=version,
            model_format=entry["format"],
            resource_id=f"azure:{sub}:{vendor}:{name}",
            resource_kind="CognitiveServices/locations/models",
            subscription_or_project=sub,
            regions=regions,
            sku=entry["sku"],
            provisioning_state="NotDeployed",
            facts=facts,
        )

    def _merge(self, sub: str, vendor: str, name: str, version: str | None,
               obs: list[dict]) -> DiscoveredModel:
        """Collapse per-region observations into one logical model, fail-closed."""
        regions = sorted({o["region"] for o in obs if o["region"]})
        filters = {o["content_filter"] for o in obs}
        upgrade_opts = {o["version_upgrade_option"] for o in obs}
        caps = {k.lower() for o in obs for k in o["capabilities"]}
        facts = {
            "deployment_status": "deployed",
            "regions": regions,
            # A missing content filter on ANY regional deployment is a gap.
            "content_filter": next(iter(filters)) if len(filters) == 1 and None not in filters else None,
            # Attached everywhere but DIVERGENT across regions -> still fails
            # closed, but the rationale can say why.
            "content_filter_mixed": sorted(filters) if len(filters) > 1 and None not in filters else None,
            "public_network_access": "Disabled"
            if all(o["public_network_access"] == "Disabled" for o in obs) else "Enabled",
            "local_auth_disabled": all(o["local_auth_disabled"] for o in obs),
            "encryption_cmk": all(o["encryption_cmk"] for o in obs),
            # Azure Cognitive Services enforces TLS >= 1.2 platform-wide; the ARM
            # API exposes no per-account knob, so this is a documented platform fact.
            "min_tls": "1.2",
            "min_tls_source": "platform-enforced (Azure AI services require TLS 1.2+)",
            "diagnostic_settings": all(o["diagnostic_settings"] for o in obs),
            "version_upgrade_option": "NoAutoUpgrade"
            if upgrade_opts <= {"NoAutoUpgrade"}
            else next((u for u in sorted(filter(None, upgrade_opts)) if u != "NoAutoUpgrade"), None),
            "is_finetuned": ".ft-" in name,
            "modality": "multimodal"
            if any(("image" in c or "vision" in c or "audio" in c) for c in caps) else "text",
            "terms": _VENDOR_TERMS.get(vendor),
        }
        states = {o["provisioning_state"] for o in obs}
        return DiscoveredModel(
            vendor=vendor,
            model_name=name,
            model_version=version,
            model_format=obs[0]["format"],
            resource_id=f"azure:{sub}:{vendor}:{name}",
            resource_kind="CognitiveServices/accounts/deployments",
            subscription_or_project=sub,
            resource_group=obs[0]["resource_group"],
            regions=regions,
            sku=obs[0]["sku"],
            endpoint=obs[0]["endpoint"] if len(obs) == 1 else None,
            provisioning_state=states.pop() if len(states) == 1 else "Mixed",
            facts=facts,
        )


def _rg_of(resource_id: str) -> str | None:
    m = re.search(r"/resourceGroups/([^/]+)/", resource_id, re.I)
    return m.group(1) if m else None


def _has_enabled_log_sink(settings: list[dict]) -> bool:
    """True only when at least one diagnostic setting routes at least one ENABLED
    log category to a real destination. A bare diagnosticSettings resource (or a
    metrics-only / all-disabled one) is not evidence of logging — fail closed."""
    for s in settings:
        p = s.get("properties") or {}
        has_destination = any(
            p.get(k)
            for k in (
                "workspaceId",
                "storageAccountId",
                "eventHubAuthorizationRuleId",
                "marketplacePartnerId",
            )
        )
        has_enabled_logs = any(log.get("enabled") for log in (p.get("logs") or []))
        if has_destination and has_enabled_logs:
            return True
    return False
