"""Stub discovery drivers — deterministic sample data for v1.

A model is one LOGICAL model (name + version) deployed across MANY regions for
quota — so each carries a `regions` footprint, not a single region. `facts`
mirrors the cloud resource properties the auto-answer engine reads. Real Azure/GCP
drivers (M5/M6) aggregate per-region deployments into the same shape.

`facts["terms"]` is the governing-terms identity (marketplace agreement /
publisher license on the resource) — the key the precedent fast-track matches
on. Models under the same vendor + terms can adopt an approved precedent's
judgment answers; a different terms id forces a full review.

Scenarios are varied to exercise the engine:
  * gpt-4o        footprint entirely within approved residency
  * o3-mini       same terms as gpt-4o (precedent-eligible) but footprint spills
                  into a non-approved region — fresh auto facts still gate it
  * Mistral       footprint entirely outside approved residency (auto residency KO)
  * claude-fable-5   same commercial ToS as claude-opus-4-8 (precedent-eligible)
  * claude-mythos-5  restricted-availability addendum — different terms, so NO
                     precedent fast-track despite the same vendor
"""
from __future__ import annotations

from app.discovery.base import DiscoveredModel, DiscoveryDriver

# Governing terms identities shared across models of a vendor.
_TERMS_AOAI = {
    "id": "azure-openai-service-terms",
    "label": "Azure OpenAI Service Terms",
    "url": "https://learn.microsoft.com/legal/cognitive-services/openai/",
}
_TERMS_LLAMA = {
    "id": "llama-3.3-community-license",
    "label": "Llama 3.3 Community License",
    "url": "https://www.llama.com/llama3_3/license/",
}
_TERMS_MISTRAL = {
    "id": "mistral-ai-terms",
    "label": "Mistral AI Terms of Service",
    "url": "https://mistral.ai/terms/",
}
_TERMS_GCP = {
    "id": "gcp-service-terms",
    "label": "Google Cloud Service Terms (Vertex AI)",
    "url": "https://cloud.google.com/terms",
}
_TERMS_ANTHROPIC = {
    "id": "anthropic-commercial-tos",
    "label": "Anthropic Commercial Terms of Service",
    "url": "https://www.anthropic.com/legal/commercial-terms",
}
_TERMS_MYTHOS = {
    "id": "anthropic-mythos-addendum",
    "label": "Anthropic Mythos Restricted-Availability Addendum",
    "url": "https://www.anthropic.com/news/claude-fable-5-mythos-5",
}


def _m(*, cloud: str, vendor: str, model_name: str, model_version: str, model_format: str,
       regions: list[str], resource_kind: str, subscription_or_project: str, facts: dict,
       terms: dict, provisioning_state: str = "Succeeded") -> DiscoveredModel:
    # Logical, region-independent id (the model, not one regional deployment).
    resource_id = f"{cloud}:{subscription_or_project}:{vendor}:{model_name}"
    return DiscoveredModel(
        vendor=vendor, model_name=model_name, model_version=model_version,
        model_format=model_format, regions=regions, resource_id=resource_id,
        resource_kind=resource_kind, subscription_or_project=subscription_or_project,
        provisioning_state=provisioning_state,
        facts={**facts, "regions": regions, "terms": terms},
    )


_AZURE: dict[str, list[DiscoveredModel]] = {
    "openai": [
        _m(cloud="azure", vendor="openai", model_name="gpt-4o", model_version="2024-11-20",
           model_format="OpenAI", subscription_or_project="DEMO",
           resource_kind="CognitiveServices/accounts/deployments",
           regions=["eastus", "eastus2", "westus3", "westeurope"], terms=_TERMS_AOAI,
           facts={"content_filter": "DefaultV2", "public_network_access": "Disabled",
                  "local_auth_disabled": True, "encryption_cmk": True, "min_tls": "1.2",
                  "diagnostic_settings": True, "version_upgrade_option": "NoAutoUpgrade",
                  "is_finetuned": False, "modality": "multimodal"}),
        _m(cloud="azure", vendor="openai", model_name="o3-mini", model_version="2025-01-31",
           model_format="OpenAI", subscription_or_project="DEMO",
           resource_kind="CognitiveServices/accounts/deployments",
           regions=["eastus", "eastus2", "brazilsouth"],  # brazilsouth not approved
           terms=_TERMS_AOAI,
           facts={"content_filter": "DefaultV2", "public_network_access": "Enabled",
                  "local_auth_disabled": False, "encryption_cmk": False, "min_tls": "1.2",
                  "diagnostic_settings": False, "version_upgrade_option": "OnceNewDefaultVersionAvailable",
                  "is_finetuned": False, "modality": "text"}),
    ],
    "meta": [
        _m(cloud="azure", vendor="meta", model_name="Llama-3.3-70B-Instruct", model_version="1",
           model_format="Meta", subscription_or_project="DEMO",
           resource_kind="CognitiveServices/accounts/deployments",
           regions=["westeurope", "northeurope"], terms=_TERMS_LLAMA,
           facts={"content_filter": "DefaultV2", "public_network_access": "Disabled",
                  "local_auth_disabled": True, "encryption_cmk": False, "min_tls": "1.2",
                  "diagnostic_settings": True, "version_upgrade_option": "NoAutoUpgrade",
                  "is_finetuned": False, "modality": "text"}),
    ],
    "mistral": [
        _m(cloud="azure", vendor="mistral", model_name="Mistral-Large-2411", model_version="1",
           model_format="Mistral", subscription_or_project="DEMO",
           resource_kind="CognitiveServices/accounts/deployments",
           regions=["switzerlandnorth", "francecentral", "uaenorth"],  # none approved
           terms=_TERMS_MISTRAL,
           facts={"content_filter": None, "public_network_access": "Enabled",
                  "local_auth_disabled": False, "encryption_cmk": False, "min_tls": "1.2",
                  "diagnostic_settings": False, "version_upgrade_option": "NoAutoUpgrade",
                  "is_finetuned": False, "modality": "text"}),
    ],
}

_GCP: dict[str, list[DiscoveredModel]] = {
    "google": [
        _m(cloud="gcp", vendor="google", model_name="gemini-2.5-pro", model_version="001",
           model_format="Google", subscription_or_project="demo-proj",
           resource_kind="aiplatform.googleapis.com/PublisherModel", provisioning_state="ACTIVE",
           regions=["us-central1", "us-east4", "europe-west4"], terms=_TERMS_GCP,
           facts={"content_filter": "vertex-safety-default", "public_network_access": "Disabled",
                  "local_auth_disabled": True, "encryption_cmk": True, "min_tls": "1.2",
                  "diagnostic_settings": True, "version_upgrade_option": "NoAutoUpgrade",
                  "is_finetuned": False, "modality": "multimodal"}),
    ],
    "anthropic": [
        _m(cloud="gcp", vendor="anthropic", model_name="claude-opus-4-8", model_version="1",
           model_format="Anthropic", subscription_or_project="demo-proj",
           resource_kind="aiplatform.googleapis.com/Endpoint.deployedModel", provisioning_state="ACTIVE",
           regions=["us-east5"], terms=_TERMS_ANTHROPIC,
           facts={"content_filter": "vertex-safety-default", "public_network_access": "Disabled",
                  "local_auth_disabled": True, "encryption_cmk": True, "min_tls": "1.2",
                  "diagnostic_settings": True, "version_upgrade_option": "NoAutoUpgrade",
                  "is_finetuned": False, "modality": "text"}),
        _m(cloud="gcp", vendor="anthropic", model_name="claude-fable-5", model_version="1",
           model_format="Anthropic", subscription_or_project="demo-proj",
           resource_kind="aiplatform.googleapis.com/Endpoint.deployedModel", provisioning_state="ACTIVE",
           regions=["us-east5", "us-central1"], terms=_TERMS_ANTHROPIC,  # same ToS as opus
           facts={"content_filter": "vertex-safety-default", "public_network_access": "Disabled",
                  "local_auth_disabled": True, "encryption_cmk": True, "min_tls": "1.2",
                  "diagnostic_settings": True, "version_upgrade_option": "NoAutoUpgrade",
                  "is_finetuned": False, "modality": "multimodal"}),
        _m(cloud="gcp", vendor="anthropic", model_name="claude-mythos-5", model_version="1",
           model_format="Anthropic", subscription_or_project="demo-proj",
           resource_kind="aiplatform.googleapis.com/Endpoint.deployedModel", provisioning_state="ACTIVE",
           regions=["us-east5"], terms=_TERMS_MYTHOS,  # different terms -> no fast-track
           facts={"content_filter": "vertex-safety-default", "public_network_access": "Disabled",
                  "local_auth_disabled": True, "encryption_cmk": True, "min_tls": "1.2",
                  "diagnostic_settings": True, "version_upgrade_option": "NoAutoUpgrade",
                  "is_finetuned": False, "modality": "multimodal"}),
    ],
    "meta": [
        _m(cloud="gcp", vendor="meta", model_name="llama-3.3-70b-instruct-maas", model_version="1",
           model_format="Meta", subscription_or_project="demo-proj",
           resource_kind="aiplatform.googleapis.com/PublisherModel", provisioning_state="ACTIVE",
           regions=["us-central1", "asia-southeast1"],  # asia-southeast1 not approved
           terms=_TERMS_LLAMA,
           facts={"content_filter": "vertex-safety-default", "public_network_access": "Enabled",
                  "local_auth_disabled": True, "encryption_cmk": False, "min_tls": "1.2",
                  "diagnostic_settings": True, "version_upgrade_option": "NoAutoUpgrade",
                  "is_finetuned": False, "modality": "text"}),
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
