"""Platform attestation registry: documented cloud/vendor commitments that
answer controls PER PLATFORM rather than per model.

Microsoft and Google publish standing, citable commitments — data-privacy terms
(customer prompts/outputs not used for training), compliance attestations
(SOC 2 Type 2, ISO/IEC 27001, ISO/IEC 42001 AI-management certification, NIST
AI RMF crosswalks), output copyright indemnification, and provider red-teaming
transparency notes. These hold for every model served on the platform (or for a
specific publisher on it), so the engine can pre-fill them with a citation
instead of asking the reviewer to re-confirm the same document on every review.

Answers sourced here get answer_source="attested": accepted without per-review
confirmation (like "auto"), but distinguishable in the audit trail because the
evidence is a published document, not a measured cloud fact.

Curation rules (fail closed):
  * only commitments stated in a public, linkable document — the URL ships as
    the control's evidence
  * vendor-specific entries only where the document names that publisher's
    models; everything else stays "suggested" for a human
  * when a document is withdrawn or scoped down, DELETE the entry — absence
    falls back to the suggested/manual path, never to a stale "yes"

Registry last verified against the linked documents: 2026-07.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Attestation:
    answer: str
    rationale: str
    evidence_url: str


# (cloud, vendor) -> {control_key: Attestation}. vendor "*" applies to every
# vendor on that cloud; a vendor-specific entry overrides the wildcard per key.
_REGISTRY: dict[tuple[str, str], dict[str, Attestation]] = {
    ("azure", "*"): {
        "provider_slas": Attestation(
            "yes",
            "Azure AI services carry current SOC 2 Type 2, ISO/IEC 27001 and "
            "ISO/IEC 42001 (AI management system) attestations, and Microsoft "
            "publishes a NIST AI RMF crosswalk; a financially backed SLA applies. "
            "Attestation reports are on the Microsoft Service Trust Portal.",
            "https://servicetrust.microsoft.com",
        ),
        "data_handling": Attestation(
            "yes",
            "Microsoft documents that for models hosted in Azure AI Foundry it "
            "acts as data processor: prompts and outputs are not shared with the "
            "model provider and are not used to train or improve the foundation "
            "models.",
            "https://learn.microsoft.com/azure/ai-foundry/how-to/concept-data-privacy",
        ),
    },
    ("azure", "openai"): {
        "data_handling": Attestation(
            "yes",
            "Microsoft's Azure OpenAI data-privacy note states prompts and "
            "completions are NOT used to train or improve Microsoft or OpenAI "
            "models, are not shared with OpenAI, and abuse-monitoring retention "
            "is capped at 30 days (exemption process available).",
            "https://learn.microsoft.com/legal/cognitive-services/openai/data-privacy",
        ),
        "ip_licensing": Attestation(
            "yes",
            "Microsoft's Customer Copyright Commitment (Product Terms) "
            "indemnifies customers against third-party IP claims over Azure "
            "OpenAI output, provided the documented mitigations (content "
            "filters, metaprompts) are enabled.",
            "https://learn.microsoft.com/legal/cognitive-services/openai/customer-copyright-commitment",
        ),
        "safety_redteam": Attestation(
            "yes",
            "Microsoft's Azure OpenAI transparency note documents provider-level "
            "red-teaming and Responsible AI evaluation of the underlying OpenAI "
            "models across harmful-content categories (including CBRN, violence, "
            "sexual content and self-harm).",
            "https://learn.microsoft.com/legal/cognitive-services/openai/transparency-note",
        ),
    },
    ("azure", "microsoft"): {
        "ip_licensing": Attestation(
            "yes",
            "Microsoft's Customer Copyright Commitment (Product Terms) covers "
            "output of Microsoft-published models when the documented "
            "mitigations are enabled.",
            "https://learn.microsoft.com/legal/cognitive-services/openai/customer-copyright-commitment",
        ),
    },
    ("gcp", "*"): {
        "provider_slas": Attestation(
            "yes",
            "Google Cloud / Vertex AI carry current SOC 2 Type 2, ISO/IEC 27001 "
            "and ISO/IEC 42001 attestations, and Google publishes NIST AI RMF "
            "alignment via its Secure AI Framework; a financially backed SLA "
            "applies. Reports are in the Google Cloud compliance resource center.",
            "https://cloud.google.com/security/compliance",
        ),
    },
    ("gcp", "google"): {
        "data_handling": Attestation(
            "yes",
            "Google's Vertex AI generative-AI data-governance documentation "
            "states customer prompts and outputs are not used to train "
            "foundation models without permission, with configurable retention.",
            "https://cloud.google.com/vertex-ai/generative-ai/docs/data-governance",
        ),
        "ip_licensing": Attestation(
            "yes",
            "Google's generative-AI indemnified-services terms provide a "
            "two-pronged indemnity covering both training data and generated "
            "output for covered Vertex AI models.",
            "https://cloud.google.com/terms/generative-ai-indemnified-services",
        ),
        "safety_redteam": Attestation(
            "yes",
            "Google publishes Responsible AI documentation and safety "
            "evaluations for Vertex AI foundation models under its Secure AI "
            "Framework, covering harmful-content and misuse categories.",
            "https://cloud.google.com/vertex-ai/generative-ai/docs/learn/responsible-ai",
        ),
    },
    ("gcp", "anthropic"): {
        "data_handling": Attestation(
            "yes",
            "Anthropic's commercial terms state customer inputs and outputs are "
            "not used to train models; Vertex AI partner-model traffic is "
            "additionally covered by Google's Vertex data-governance "
            "commitments.",
            "https://www.anthropic.com/legal/commercial-terms",
        ),
        "ip_licensing": Attestation(
            "yes",
            "Anthropic's commercial terms include copyright indemnification for "
            "paid-tier model output.",
            "https://www.anthropic.com/legal/commercial-terms",
        ),
        "safety_redteam": Attestation(
            "yes",
            "Anthropic publishes model system cards and a Responsible Scaling "
            "Policy documenting red-team evaluation including CBRN, cyber and "
            "autonomy risk categories.",
            "https://www.anthropic.com/transparency",
        ),
    },
}


def lookup(cloud: str | None, vendor: str | None) -> dict[str, Attestation]:
    """Attested control answers for a cloud/vendor: cloud-wide entries first,
    publisher-specific entries override per control key."""
    if not cloud:
        return {}
    merged: dict[str, Attestation] = {}
    merged.update(_REGISTRY.get((cloud, "*"), {}))
    if vendor:
        merged.update(_REGISTRY.get((cloud, vendor), {}))
    return merged
