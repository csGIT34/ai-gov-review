"""Auto-answer engine.

Given a model's cloud `facts`, pre-answers the machine-answerable controls so the
reviewer only handles judgment calls. Two tiers:

  * fact collectors  -> answer_source="auto"      (deterministic; accepted as-is)
  * doc collectors    -> answer_source="suggested" (needs human confirmation)

Real Azure/GCP drivers (M5/M6) populate the same `facts` shape, so this engine is
unchanged when discovery goes live.
"""
from __future__ import annotations

from dataclasses import dataclass

# --- policy (would move to per-org config / DiscoverySource.config) -----------

# Default data-residency policy, keyed by cloud (Azure and GCP region names live
# in separate buckets). The LIVE policy is admin-editable (GovernancePolicy, with
# optional per-DiscoverySource override); this is only the seed default / fallback.
DEFAULT_APPROVED_REGIONS: dict[str, list[str]] = {
    "azure": ["eastus", "eastus2", "westus3", "westeurope", "northeurope", "uksouth"],
    "gcp": ["us-central1", "us-east4", "us-east5", "europe-west4"],
}


@dataclass(frozen=True)
class Policy:
    """Resolved org policy the engine compares cloud facts against.

    approved_regions is keyed by cloud: {"azure": frozenset(...), "gcp": frozenset(...)}.
    """

    approved_regions: dict  # {cloud: frozenset[str]}

    def residency_ok(self, cloud: str | None, region: str | None) -> bool:
        if not cloud or not region:
            return False
        return region in self.approved_regions.get(cloud, frozenset())

    def region_count(self, cloud: str | None) -> int:
        return len(self.approved_regions.get(cloud, ())) if cloud else 0

    @classmethod
    def from_default(cls) -> "Policy":
        return cls({c: frozenset(v) for c, v in DEFAULT_APPROVED_REGIONS.items()})

# Provider documentation used as evidence for the "suggested" controls.
PROVIDER_DOCS: dict[str, dict[str, str]] = {
    "openai": {
        "model_card": "https://learn.microsoft.com/azure/ai-services/openai/concepts/models",
        "data_handling": "https://learn.microsoft.com/legal/cognitive-services/openai/data-privacy",
        "safety": "https://openai.com/safety",
        "trust": "https://servicetrust.microsoft.com",
        "license": "https://learn.microsoft.com/legal/cognitive-services/openai/",
    },
    "anthropic": {
        "model_card": "https://docs.anthropic.com/en/docs/about-claude/models",
        "data_handling": "https://www.anthropic.com/legal/commercial-terms",
        "safety": "https://www.anthropic.com/research",
        "trust": "https://trust.anthropic.com",
        "license": "https://www.anthropic.com/legal/commercial-terms",
    },
    "google": {
        "model_card": "https://cloud.google.com/vertex-ai/generative-ai/docs/learn/models",
        "data_handling": "https://cloud.google.com/terms/data-processing-addendum",
        "safety": "https://cloud.google.com/vertex-ai/generative-ai/docs/multimodal/configure-safety-attributes",
        "trust": "https://cloud.google.com/security/compliance",
        "license": "https://cloud.google.com/terms",
    },
    "meta": {
        "model_card": "https://www.llama.com/docs/model-cards-and-prompt-formats/",
        "safety": "https://www.llama.com/trust-and-safety/",
        "license": "https://www.llama.com/llama3_3/license/",
    },
    "mistral": {
        "model_card": "https://docs.mistral.ai/getting-started/models/",
        "license": "https://mistral.ai/terms/",
    },
}


@dataclass(frozen=True)
class AutoResult:
    answer: str
    source: str  # "auto" | "suggested"
    confidence: str  # "high" | "medium"
    rationale: str
    evidence_url: str | None = None


def _auto(answer: str, rationale: str, url: str | None = None) -> AutoResult:
    return AutoResult(answer, "auto", "high", rationale, url)


def _suggest(answer: str, rationale: str, url: str | None) -> AutoResult:
    return AutoResult(answer, "suggested", "medium", rationale, url)


# --- fact collectors (deterministic) ------------------------------------------

def _data_residency(f: dict, vendor: str, docs: dict, policy: Policy, cloud: str | None) -> AutoResult:
    regions = f.get("regions") or ([f["region"]] if f.get("region") else [])
    approved = policy.approved_regions.get(cloud, frozenset())
    if not regions:
        return _auto("unknown", f"No deployment regions reported for this {cloud} model.")
    offenders = sorted(r for r in regions if r not in approved)
    if not offenders:
        return _auto(
            "yes",
            f"All {len(regions)} deployment region(s) are within your approved {cloud} "
            f"data-residency policy: {', '.join(sorted(regions))}.",
        )
    return _auto(
        "no",
        f"Deployed to region(s) outside your approved {cloud} data-residency policy: "
        f"{', '.join(offenders)} (of {len(regions)} total: {', '.join(sorted(regions))}).",
    )


def _safety_filters(f: dict, vendor: str, docs: dict) -> AutoResult:
    cf = f.get("content_filter")
    if cf:
        return _auto("yes", f"Content-safety policy '{cf}' is attached to the endpoint.")
    mixed = f.get("content_filter_mixed")
    if mixed:
        return _auto(
            "no",
            f"Content-safety policies differ across regional deployments ({', '.join(mixed)}); "
            "posture is not uniform across the footprint.",
        )
    return _auto("no", "No content-safety / responsible-AI policy is attached to the endpoint.")


def _access_controls(f: dict, vendor: str, docs: dict) -> AutoResult:
    private = f.get("public_network_access") == "Disabled"
    keyless = bool(f.get("local_auth_disabled"))
    if private and keyless:
        return _auto("yes", "Private networking and identity-based auth (local key auth disabled).")
    if private or keyless:
        missing = "local key auth is enabled" if not keyless else "public network access is enabled"
        have = "private networking" if private else "identity-based auth"
        return _auto("partial", f"{have} in place, but {missing}.")
    return _auto("no", "Public network access and local key auth are both enabled.")


def _encryption_logging(f: dict, vendor: str, docs: dict) -> AutoResult:
    cmk = bool(f.get("encryption_cmk"))
    tls_ok = f.get("min_tls") in ("1.2", "1.3")
    if cmk and tls_ok:
        return _auto("yes", f"Customer-managed-key encryption + TLS {f.get('min_tls')} enforced.")
    if tls_ok:
        return _auto("partial", f"TLS {f.get('min_tls')} enforced, but customer-managed key not configured.")
    return _auto("no", "Transport/at-rest encryption not confirmed.")


def _monitoring(f: dict, vendor: str, docs: dict) -> AutoResult:
    on = bool(f.get("diagnostic_settings"))
    return _auto(
        "yes" if on else "no",
        "At least one enabled log category is routed to a diagnostic sink."
        if on
        else "No diagnostic sink with enabled log categories is configured.",
    )


def _version_change(f: dict, vendor: str, docs: dict) -> AutoResult:
    vuo = f.get("version_upgrade_option")
    if vuo == "NoAutoUpgrade":
        return _auto("yes", "Model version is pinned (NoAutoUpgrade); a version change requires a new review.")
    if vuo:
        return _auto("partial", f"Auto-upgrade is enabled ({vuo}); the model version can change without review.")
    return _auto("unknown", "Version-upgrade policy not reported by the cloud API.")


def _categorization(f: dict, vendor: str, docs: dict) -> AutoResult:
    kind = "fine-tuned" if f.get("is_finetuned") else "foundation"
    modality = f.get("modality", "text")
    return _auto("yes", f"Classified as a {kind} generative {modality} model; NIST AI 600-1 GenAI profile applies.")


def _model_card(f: dict, vendor: str, docs: dict) -> AutoResult:
    return _auto(
        "yes",
        "Exact model name, version and publisher captured from the cloud resource; provider model card linked.",
        docs.get("model_card"),
    )


# NOTE: "vendor vetted / active contract" is intentionally NOT auto-answered.
# The cloud API can tell us the provider identity, but whether an active
# contract / enterprise agreement exists is procurement data it does not expose.
# Auto-answering it would be false confidence — it is a manual control (below).


# --- doc collectors (need confirmation) ---------------------------------------

def _provenance(f, v, d):
    return _suggest("partial", "Base model and publisher identified from the cloud API; confirm fine-tuning data and third-party components against the provider's model card.", d.get("model_card"))


def _data_handling(f, v, d):
    return _suggest("partial", "Provider standard terms typically exclude training on your inputs; confirm retention/opt-out in the DPA.", d.get("data_handling") or d.get("license"))


def _safety_redteam(f, v, d):
    return _suggest("partial", "Provider publishes a safety/system card; confirm it covers CBRN, violent, and obscene/abusive testing.", d.get("safety"))


def _eval_accuracy(f, v, d):
    return _suggest("partial", "Provider model card includes benchmark results; confirm they represent the intended use.", d.get("model_card"))


def _bias_fairness(f, v, d):
    return _suggest("partial", "Provider may publish fairness evaluations; confirm coverage for relevant demographic groups.", d.get("safety"))


def _infosec_genai(f, v, d):
    return _suggest("unknown", "No automated signal for prompt-injection/jailbreak resistance; assess and list connected tools/plugins.", d.get("safety"))


def _explainability(f, v, d):
    return _suggest("partial", "Model card documents known limitations/failure modes; confirm adequacy.", d.get("model_card"))


def _ip_licensing(f, v, d):
    return _suggest("partial", "License and IP/indemnity terms are available from the provider; confirm commercial-use rights and output ownership.", d.get("license"))


def _provider_slas(f, v, d):
    return _suggest("partial", "Provider trust center lists SOC 2 / ISO attestations and SLAs; confirm currency.", d.get("trust"))


def _environmental(f, v, d):
    return _suggest("unknown", "Per-inference environmental footprint is rarely published; estimate from expected inference volume.", None)


# key -> collector. Controls not listed are manual (org policy/process).
COLLECTORS = {
    # fact-based (auto). data_residency is handled separately in collect() because
    # it needs the resolved Policy.
    "safety_filters": _safety_filters,
    "access_controls": _access_controls,
    "encryption_logging": _encryption_logging,
    "monitoring": _monitoring,
    "version_change_process": _version_change,
    "categorization": _categorization,
    "model_card": _model_card,
    # doc-based (suggested)
    "provenance": _provenance,
    "data_handling": _data_handling,
    "safety_redteam": _safety_redteam,
    "eval_accuracy": _eval_accuracy,
    "bias_fairness": _bias_fairness,
    "infosec_genai": _infosec_genai,
    "explainability": _explainability,
    "ip_licensing": _ip_licensing,
    "provider_slas": _provider_slas,
    "environmental": _environmental,
}

# Controls with no reliable cloud signal — a human must answer these. Each gets a
# guidance note (what to confirm and why the cloud API can't answer it).
MANUAL_GUIDANCE: dict[str, str] = {
    "vendor_vetted": (
        "Not derivable from the cloud resource: the API shows the provider identity, "
        "but an active contract / enterprise agreement and approved-vendor-register "
        "entry are procurement facts. Confirm with procurement. If the model was "
        "deployed via Azure/GCP Marketplace, the accepted agreement id on the resource "
        "is supporting evidence."
    ),
    "intended_use": "Confirm the documented intended-use and acceptable-use statement scoped to this deployment.",
    "human_oversight": "Confirm the human-in-the-loop / oversight configuration appropriate to the use case.",
    "incident_response": "Confirm the runbook: named risk owner, disable/kill-switch procedure, and provider escalation path.",
    "impact_assessment": "Confirm an impact assessment covering affected populations and plausible harms for the stated use.",
}
MANUAL_CONTROLS = set(MANUAL_GUIDANCE.keys())


def _catalog_overrides(facts: dict, docs: dict, policy: Policy, cloud: str | None) -> dict[str, AutoResult]:
    """Pre-deployment answers for a CATALOG model (facts.deployment_status ==
    "catalog"): the model is offered by the cloud but no resource exists yet, so
    there is no posture to measure. Answering "no"/"unknown" would auto-reject
    every not-yet-deployed model through the KO gates; answering "yes" would be
    false confidence. So these are SUGGESTED "partial" — the reviewer confirms
    the deployment plan, and the answers carry via precedent like any other
    human-owned judgment."""
    regions = sorted(facts.get("regions") or [])
    approved = policy.approved_regions.get(cloud, frozenset())
    offenders = [r for r in regions if r not in approved]
    note = "Model is in the cloud catalog but not deployed yet; "
    out = {
        "data_residency": _suggest(
            "partial",
            note + f"it is offered in {len(regions)} approved region(s) "
            f"({', '.join(regions)}). Confirm the deployment will target only "
            "approved regions.",
            None,
        ),
        "safety_filters": _suggest(
            "partial",
            note + "content-safety policies attach per deployment. Confirm a "
            "content-filter policy will be required at deployment.",
            docs.get("safety"),
        ),
        "access_controls": _suggest(
            "partial",
            note + "network/auth posture exists only on a deployed resource. "
            "Confirm the deployment standard (private networking, key auth disabled).",
            None,
        ),
        "encryption_logging": _suggest(
            "partial",
            note + "TLS 1.2+ is platform-enforced; confirm customer-managed-key "
            "encryption in the deployment standard.",
            None,
        ),
        "monitoring": _suggest(
            "partial",
            note + "confirm diagnostic log routing will be enabled at deployment.",
            None,
        ),
        "version_change_process": _suggest(
            "partial",
            note + "confirm the deployment will pin the model version (NoAutoUpgrade).",
            None,
        ),
    }
    if not regions or offenders:
        # Catalog listings are policy-scoped upstream, so offenders here mean a
        # misconfigured source — surface it instead of a soft "partial".
        out["data_residency"] = _suggest(
            "no",
            note + (
                f"it is offered in region(s) outside the approved {cloud} "
                f"data-residency policy: {', '.join(offenders)}."
                if offenders else "no candidate regions were reported."
            ),
            None,
        )
    return out


def collect(
    facts: dict | None, vendor: str, policy: Policy | None = None, cloud: str | None = None
) -> dict[str, AutoResult]:
    """Return {control_key: AutoResult} for every control the engine can pre-answer."""
    facts = facts or {}
    policy = policy or Policy.from_default()
    docs = PROVIDER_DOCS.get(vendor, {})
    out: dict[str, AutoResult] = {}
    for key, fn in COLLECTORS.items():
        result = fn(facts, vendor, docs)
        if result is not None:
            out[key] = result
    # Residency needs the resolved policy + the model's cloud.
    out["data_residency"] = _data_residency(facts, vendor, docs, policy, cloud)
    # A catalog (not-yet-deployed) model has no resource posture to measure —
    # replace the posture answers with pre-deployment suggestions.
    if facts.get("deployment_status") == "catalog":
        out.update(_catalog_overrides(facts, docs, policy, cloud))
    return out
