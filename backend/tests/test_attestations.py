"""Platform attestation registry: documented cloud/vendor commitments become
attested (accepted, cited) answers instead of suggestions to re-confirm."""
from __future__ import annotations

from app.services.attestations import lookup
from app.services.autoanswer import collect


def test_azure_openai_full_attestation_set():
    r = collect({}, "openai", cloud="azure")
    for key in ("data_handling", "provider_slas", "ip_licensing", "safety_redteam"):
        assert r[key].source == "attested", key
        assert r[key].answer == "yes", key
        assert r[key].evidence_url and r[key].evidence_url.startswith("https://"), key
    # The Azure OpenAI-specific data-privacy note wins over the cloud-wide entry.
    assert "openai/data-privacy" in r["data_handling"].evidence_url


def test_azure_wildcard_covers_all_vendors_but_not_vendor_specifics():
    r = collect({}, "mistral", cloud="azure")
    # Cloud-wide: Microsoft's platform compliance + Foundry data-processing terms.
    assert r["provider_slas"].source == "attested"
    assert r["data_handling"].source == "attested"
    assert "ai-foundry" in r["data_handling"].evidence_url
    # But no documented copyright indemnity for third-party publishers -> human path.
    assert r["ip_licensing"].source == "suggested"
    assert r["safety_redteam"].source == "suggested"


def test_gcp_anthropic_attestations():
    r = collect({}, "anthropic", cloud="gcp")
    for key in ("data_handling", "provider_slas", "ip_licensing", "safety_redteam"):
        assert r[key].source == "attested", key
    assert "anthropic.com" in r["ip_licensing"].evidence_url


def test_no_cloud_no_attestations():
    assert lookup(None, "openai") == {}
    r = collect({}, "openai")  # cloud unknown -> nothing attested, fail closed
    assert r["data_handling"].source == "suggested"
    assert r["provider_slas"].source == "suggested"


def test_attestations_apply_to_catalog_models_too():
    facts = {"deployment_status": "catalog", "regions": ["eastus"]}
    r = collect(facts, "openai", cloud="azure")
    # Posture stays a pre-deployment suggestion...
    assert r["safety_filters"].source == "suggested"
    assert r["safety_filters"].answer == "partial"
    # ...but platform commitments hold whether or not the model is deployed.
    assert r["data_handling"].source == "attested"
    assert r["provider_slas"].source == "attested"


def test_registry_entries_are_well_formed():
    from app.services.attestations import _REGISTRY
    from app.services.questionnaire import load_questionnaire

    valid_keys = {c.key for c in load_questionnaire().controls}
    for (cloud, vendor), entries in _REGISTRY.items():
        assert cloud in ("azure", "gcp")
        for key, att in entries.items():
            assert key in valid_keys, f"unknown control {key} in ({cloud}, {vendor})"
            assert att.answer in ("yes", "partial")
            assert att.evidence_url.startswith("https://")
            assert len(att.rationale) > 40
