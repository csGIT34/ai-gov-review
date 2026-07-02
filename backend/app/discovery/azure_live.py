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
from typing import Callable

import httpx

from app.config import get_settings
from app.discovery.base import DiscoveredModel, DiscoveryDriver
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
        self._inv_cache: dict[str, tuple[float, list[DiscoveredModel]]] = {}

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
        return sorted({m.vendor for m in self._inventory(self._subscription(scope))})

    def list_models(self, scope: str, vendor: str, config: dict | None = None) -> list[DiscoveredModel]:
        return [m for m in self._inventory(self._subscription(scope)) if m.vendor == vendor]

    # -- helpers --

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

    def _inventory(self, sub: str) -> list[DiscoveredModel]:
        cached = self._inv_cache.get(sub)
        if cached and time.monotonic() - cached[0] < self._inventory_ttl:
            return cached[1]
        models = self._build_inventory(sub)
        self._inv_cache[sub] = (time.monotonic(), models)
        return models

    def _build_inventory(self, sub: str) -> list[DiscoveredModel]:
        accounts = self._get_paged(
            f"{ARM}/subscriptions/{sub}/providers/Microsoft.CognitiveServices/accounts"
            f"?api-version={_API_ACCOUNTS}"
        )
        # (vendor, model_name, model_version) -> observations across the footprint
        groups: dict[tuple, list[dict]] = defaultdict(list)

        for acct in accounts:
            if acct.get("kind") not in _MODEL_KINDS:
                continue
            acct_id = acct["id"]
            props = acct.get("properties") or {}
            has_diag = _has_enabled_log_sink(
                self._get_paged(
                    f"{ARM}{acct_id}/providers/Microsoft.Insights/diagnosticSettings"
                    f"?api-version={_API_DIAG}"
                )
            )
            deployments = self._get_paged(f"{ARM}{acct_id}/deployments?api-version={_API_ACCOUNTS}")
            for dep in deployments:
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

        return sorted(
            (self._merge(sub, vendor, name, version, obs)
             for (vendor, name, version), obs in groups.items()),
            key=lambda m: (m.vendor, m.model_name),
        )

    def _merge(self, sub: str, vendor: str, name: str, version: str | None,
               obs: list[dict]) -> DiscoveredModel:
        """Collapse per-region observations into one logical model, fail-closed."""
        regions = sorted({o["region"] for o in obs if o["region"]})
        filters = {o["content_filter"] for o in obs}
        upgrade_opts = {o["version_upgrade_option"] for o in obs}
        caps = {k.lower() for o in obs for k in o["capabilities"]}
        facts = {
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
