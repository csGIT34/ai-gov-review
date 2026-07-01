"""Stub discovery drivers — deterministic sample data for v1.

Each model carries a `facts` dict mirroring the cloud resource properties the
auto-answer engine reads (region, content filter, network exposure, encryption,
monitoring, version pinning, ...). Real Azure/GCP drivers (M5/M6) populate the
same `facts` shape from Resource Graph / cognitiveservices / Cloud Asset APIs.

Scenarios are intentionally varied to exercise the engine:
  * gpt-4o        clean, well-governed deployment
  * o3-mini       gap: public network + key auth + no monitoring + auto-upgrade
  * Mistral       residency violation: region not in the approved list (auto KO)
"""
from __future__ import annotations

from app.discovery.base import DiscoveredModel, DiscoveryDriver


def _m(**kwargs) -> DiscoveredModel:
    return DiscoveredModel(**kwargs)


_AZURE: dict[str, list[DiscoveredModel]] = {
    "openai": [
        _m(
            vendor="openai", model_name="gpt-4o", model_version="2024-11-20",
            model_format="OpenAI", region="eastus", sku="Standard",
            resource_id="/subscriptions/DEMO/resourceGroups/rg-ai/providers/Microsoft.CognitiveServices/accounts/aoai-eastus/deployments/gpt-4o",
            resource_kind="CognitiveServices/accounts/deployments",
            subscription_or_project="DEMO", resource_group="rg-ai",
            provisioning_state="Succeeded",
            facts={
                "region": "eastus", "content_filter": "DefaultV2",
                "public_network_access": "Disabled", "local_auth_disabled": True,
                "encryption_cmk": True, "min_tls": "1.2", "diagnostic_settings": True,
                "version_upgrade_option": "NoAutoUpgrade", "is_finetuned": False,
                "modality": "multimodal",
            },
        ),
        _m(
            vendor="openai", model_name="o3-mini", model_version="2025-01-31",
            model_format="OpenAI", region="eastus", sku="Standard",
            resource_id="/subscriptions/DEMO/resourceGroups/rg-ai/providers/Microsoft.CognitiveServices/accounts/aoai-eastus/deployments/o3-mini",
            resource_kind="CognitiveServices/accounts/deployments",
            subscription_or_project="DEMO", resource_group="rg-ai",
            provisioning_state="Succeeded",
            facts={
                "region": "eastus", "content_filter": "DefaultV2",
                "public_network_access": "Enabled", "local_auth_disabled": False,
                "encryption_cmk": False, "min_tls": "1.2", "diagnostic_settings": False,
                "version_upgrade_option": "OnceNewDefaultVersionAvailable",
                "is_finetuned": False, "modality": "text",
            },
        ),
    ],
    "meta": [
        _m(
            vendor="meta", model_name="Llama-3.3-70B-Instruct", model_version="1",
            model_format="Meta", region="westeurope", sku="Standard",
            resource_id="/subscriptions/DEMO/resourceGroups/rg-ai/providers/Microsoft.CognitiveServices/accounts/aifoundry-weu/deployments/llama-33-70b",
            resource_kind="CognitiveServices/accounts/deployments",
            subscription_or_project="DEMO", resource_group="rg-ai",
            provisioning_state="Succeeded",
            facts={
                "region": "westeurope", "content_filter": "DefaultV2",
                "public_network_access": "Disabled", "local_auth_disabled": True,
                "encryption_cmk": False, "min_tls": "1.2", "diagnostic_settings": True,
                "version_upgrade_option": "NoAutoUpgrade", "is_finetuned": False,
                "modality": "text",
            },
        ),
    ],
    "mistral": [
        _m(
            vendor="mistral", model_name="Mistral-Large-2411", model_version="1",
            model_format="Mistral", region="switzerlandnorth", sku="Standard",
            resource_id="/subscriptions/DEMO/resourceGroups/rg-ai/providers/Microsoft.CognitiveServices/accounts/aifoundry-chn/deployments/mistral-large",
            resource_kind="CognitiveServices/accounts/deployments",
            subscription_or_project="DEMO", resource_group="rg-ai",
            provisioning_state="Succeeded",
            facts={
                "region": "switzerlandnorth", "content_filter": None,
                "public_network_access": "Enabled", "local_auth_disabled": False,
                "encryption_cmk": False, "min_tls": "1.2", "diagnostic_settings": False,
                "version_upgrade_option": "NoAutoUpgrade", "is_finetuned": False,
                "modality": "text",
            },
        ),
    ],
}

_GCP: dict[str, list[DiscoveredModel]] = {
    "google": [
        _m(
            vendor="google", model_name="gemini-2.5-pro", model_version="001",
            model_format="Google", region="us-central1",
            resource_id="projects/demo-proj/locations/us-central1/publishers/google/models/gemini-2.5-pro",
            resource_kind="aiplatform.googleapis.com/PublisherModel",
            subscription_or_project="demo-proj", provisioning_state="ACTIVE",
            facts={
                "region": "us-central1", "content_filter": "vertex-safety-default",
                "public_network_access": "Disabled", "local_auth_disabled": True,
                "encryption_cmk": True, "min_tls": "1.2", "diagnostic_settings": True,
                "version_upgrade_option": "NoAutoUpgrade", "is_finetuned": False,
                "modality": "multimodal",
            },
        ),
    ],
    "anthropic": [
        _m(
            vendor="anthropic", model_name="claude-opus-4-8", model_version="1",
            model_format="Anthropic", region="us-east5",
            resource_id="projects/demo-proj/locations/us-east5/endpoints/1234567890/deployedModels/claude-opus",
            resource_kind="aiplatform.googleapis.com/Endpoint.deployedModel",
            subscription_or_project="demo-proj", provisioning_state="ACTIVE",
            facts={
                "region": "us-east5", "content_filter": "vertex-safety-default",
                "public_network_access": "Disabled", "local_auth_disabled": True,
                "encryption_cmk": True, "min_tls": "1.2", "diagnostic_settings": True,
                "version_upgrade_option": "NoAutoUpgrade", "is_finetuned": False,
                "modality": "text",
            },
        ),
    ],
    "meta": [
        _m(
            vendor="meta", model_name="llama-3.3-70b-instruct-maas", model_version="1",
            model_format="Meta", region="us-central1",
            resource_id="projects/demo-proj/locations/us-central1/publishers/meta/models/llama-3.3-70b-instruct-maas",
            resource_kind="aiplatform.googleapis.com/PublisherModel",
            subscription_or_project="demo-proj", provisioning_state="ACTIVE",
            facts={
                "region": "us-central1", "content_filter": "vertex-safety-default",
                "public_network_access": "Enabled", "local_auth_disabled": True,
                "encryption_cmk": False, "min_tls": "1.2", "diagnostic_settings": True,
                "version_upgrade_option": "NoAutoUpgrade", "is_finetuned": False,
                "modality": "text",
            },
        ),
    ],
}


class StubAzureDriver(DiscoveryDriver):
    cloud = "azure"

    def list_vendors(self, scope: str, config: dict | None = None) -> list[str]:
        return sorted(_AZURE.keys())

    def list_models(self, scope: str, vendor: str, config: dict | None = None) -> list[DiscoveredModel]:
        return list(_AZURE.get(vendor, []))


class StubGcpDriver(DiscoveryDriver):
    cloud = "gcp"

    def list_vendors(self, scope: str, config: dict | None = None) -> list[str]:
        return sorted(_GCP.keys())

    def list_models(self, scope: str, vendor: str, config: dict | None = None) -> list[DiscoveredModel]:
        return list(_GCP.get(vendor, []))
