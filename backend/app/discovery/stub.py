"""Stub discovery drivers — deterministic sample data for v1.

Replaced by real, read-only Azure/GCP drivers in M5/M6:
  * Azure: Resource Graph (accounts) + azure-mgmt-cognitiveservices (deployments)
  * GCP:   Cloud Asset Inventory searchAllResources (Model/Endpoint)
The API and dropdowns depend only on the DiscoveryDriver interface, so swapping
the stub for real drivers is a drop-in change.
"""
from __future__ import annotations

from app.discovery.base import DiscoveredModel, DiscoveryDriver

# vendor -> list of sample models
_AZURE: dict[str, list[DiscoveredModel]] = {
    "openai": [
        DiscoveredModel(
            vendor="openai",
            model_name="gpt-4o",
            model_version="2024-11-20",
            model_format="OpenAI",
            resource_id="/subscriptions/DEMO/resourceGroups/rg-ai/providers/Microsoft.CognitiveServices/accounts/aoai-eastus/deployments/gpt-4o",
            resource_kind="CognitiveServices/accounts/deployments",
            subscription_or_project="DEMO",
            resource_group="rg-ai",
            region="eastus",
            sku="Standard",
            provisioning_state="Succeeded",
        ),
        DiscoveredModel(
            vendor="openai",
            model_name="o3-mini",
            model_version="2025-01-31",
            model_format="OpenAI",
            resource_id="/subscriptions/DEMO/resourceGroups/rg-ai/providers/Microsoft.CognitiveServices/accounts/aoai-eastus/deployments/o3-mini",
            resource_kind="CognitiveServices/accounts/deployments",
            subscription_or_project="DEMO",
            resource_group="rg-ai",
            region="eastus",
            sku="Standard",
            provisioning_state="Succeeded",
        ),
    ],
    "meta": [
        DiscoveredModel(
            vendor="meta",
            model_name="Llama-3.3-70B-Instruct",
            model_version="1",
            model_format="Meta",
            resource_id="/subscriptions/DEMO/resourceGroups/rg-ai/providers/Microsoft.CognitiveServices/accounts/aifoundry-weu/deployments/llama-33-70b",
            resource_kind="CognitiveServices/accounts/deployments",
            subscription_or_project="DEMO",
            resource_group="rg-ai",
            region="westeurope",
            sku="Standard",
            provisioning_state="Succeeded",
        ),
    ],
    "mistral": [
        DiscoveredModel(
            vendor="mistral",
            model_name="Mistral-Large-2411",
            model_version="1",
            model_format="Mistral",
            resource_id="/subscriptions/DEMO/resourceGroups/rg-ai/providers/Microsoft.CognitiveServices/accounts/aifoundry-weu/deployments/mistral-large",
            resource_kind="CognitiveServices/accounts/deployments",
            subscription_or_project="DEMO",
            resource_group="rg-ai",
            region="westeurope",
            sku="Standard",
            provisioning_state="Succeeded",
        ),
    ],
}

_GCP: dict[str, list[DiscoveredModel]] = {
    "google": [
        DiscoveredModel(
            vendor="google",
            model_name="gemini-2.5-pro",
            model_version="001",
            model_format="Google",
            resource_id="projects/demo-proj/locations/us-central1/publishers/google/models/gemini-2.5-pro",
            resource_kind="aiplatform.googleapis.com/PublisherModel",
            subscription_or_project="demo-proj",
            region="us-central1",
            provisioning_state="ACTIVE",
        ),
    ],
    "anthropic": [
        DiscoveredModel(
            vendor="anthropic",
            model_name="claude-opus-4-8",
            model_version="1",
            model_format="Anthropic",
            resource_id="projects/demo-proj/locations/us-east5/endpoints/1234567890/deployedModels/claude-opus",
            resource_kind="aiplatform.googleapis.com/Endpoint.deployedModel",
            subscription_or_project="demo-proj",
            region="us-east5",
            provisioning_state="ACTIVE",
        ),
    ],
    "meta": [
        DiscoveredModel(
            vendor="meta",
            model_name="llama-3.3-70b-instruct-maas",
            model_version="1",
            model_format="Meta",
            resource_id="projects/demo-proj/locations/us-central1/publishers/meta/models/llama-3.3-70b-instruct-maas",
            resource_kind="aiplatform.googleapis.com/PublisherModel",
            subscription_or_project="demo-proj",
            region="us-central1",
            provisioning_state="ACTIVE",
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
