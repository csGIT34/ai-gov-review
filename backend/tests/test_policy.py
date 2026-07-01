"""Configurable per-cloud governance policy: engine honors it, admin edits it."""
from __future__ import annotations

from app.services.autoanswer import Policy, collect
from tests.conftest import ADMIN, REVIEWER

API = "/api/v1"

BAD = {"region": "switzerlandnorth", "content_filter": None, "public_network_access": "Enabled",
       "local_auth_disabled": False, "encryption_cmk": False, "min_tls": "1.2",
       "diagnostic_settings": False, "version_upgrade_option": "NoAutoUpgrade",
       "is_finetuned": False, "modality": "text"}


def test_engine_honors_custom_per_cloud_policy():
    # Default policy: switzerlandnorth is not an approved Azure region.
    assert collect(BAD, "mistral", cloud="azure")["data_residency"].answer == "no"
    # A policy that approves it for Azure flips the answer...
    p = Policy(approved_regions={"azure": frozenset({"switzerlandnorth"})})
    assert collect(BAD, "mistral", p, cloud="azure")["data_residency"].answer == "yes"
    # ...but approving it only for GCP does NOT help an Azure model.
    p_gcp = Policy(approved_regions={"gcp": frozenset({"switzerlandnorth"})})
    assert collect(BAD, "mistral", p_gcp, cloud="azure")["data_residency"].answer == "no"


def test_regions_are_cloud_scoped():
    # An Azure region approved for Azure does not implicitly approve it on GCP.
    p = Policy(approved_regions={"azure": frozenset({"eastus"}), "gcp": frozenset({"us-central1"})})
    assert collect({"region": "eastus"}, "openai", p, cloud="azure")["data_residency"].answer == "yes"
    assert collect({"region": "eastus"}, "openai", p, cloud="gcp")["data_residency"].answer == "no"
    assert collect({"region": "us-central1"}, "google", p, cloud="gcp")["data_residency"].answer == "yes"


def test_get_policy_default_is_per_cloud(client):
    p = client.get(f"{API}/policy", headers=REVIEWER).json()["approved_regions"]
    assert "eastus" in p["azure"]
    assert "us-central1" in p["gcp"]
    assert "eastus" not in p["gcp"]
    assert "switzerlandnorth" not in p["azure"]


def test_reviewer_cannot_update_policy(client):
    r = client.put(f"{API}/policy", headers=REVIEWER,
                   json={"approved_regions": {"azure": ["eastus"], "gcp": []}})
    assert r.status_code == 403


def test_admin_edit_changes_autoanswer(client):
    cur = client.get(f"{API}/policy", headers=ADMIN).json()["approved_regions"]
    upd = client.put(f"{API}/policy", headers=ADMIN, json={
        # Approve Mistral's whole footprint.
        "approved_regions": {
            "azure": cur["azure"] + ["switzerlandnorth", "francecentral", "uaenorth"],
            "gcp": cur["gcp"],
        }
    })
    assert upd.status_code == 200
    assert "switzerlandnorth" in upd.json()["approved_regions"]["azure"]

    # A newly opened Mistral (Azure) review now auto-answers residency "yes".
    sources = client.get(f"{API}/discovery/sources", headers=REVIEWER).json()
    sid = next(s["id"] for s in sources if s["cloud"] == "azure")
    m = client.get(f"{API}/discovery/sources/{sid}/vendors/mistral/models", headers=REVIEWER).json()[0]
    rid = client.post(f"{API}/reviews", headers=REVIEWER, json={
        "source_id": sid, "vendor": "mistral",
        "resource_id": m["resource_id"], "model_version": m["model_version"],
    }).json()["id"]
    controls = client.get(f"{API}/reviews/{rid}/controls", headers=REVIEWER).json()
    dr = next(c for c in controls if c["control_key"] == "data_residency")
    assert dr["answer"] == "yes"
    assert dr["answer_source"] == "auto"
    assert "azure" in dr["auto_rationale"]


def test_update_drops_unknown_clouds_and_dedupes(client):
    upd = client.put(f"{API}/policy", headers=ADMIN, json={
        "approved_regions": {"azure": ["eastus", "eastus", " westus3 "], "gcp": [], "aws": ["us-east-1"]}
    }).json()["approved_regions"]
    assert upd["azure"] == ["eastus", "westus3"]  # deduped + stripped + sorted
    assert "aws" not in upd  # unknown cloud dropped


def test_partial_put_preserves_other_cloud(client):
    before = client.get(f"{API}/policy", headers=ADMIN).json()["approved_regions"]
    # A body with only GCP must NOT wipe Azure (merge, not overwrite).
    upd = client.put(f"{API}/policy", headers=ADMIN,
                     json={"approved_regions": {"gcp": ["us-central1"]}}).json()["approved_regions"]
    assert upd["gcp"] == ["us-central1"]
    assert upd["azure"] == before["azure"]


def test_explicit_empty_clears_a_cloud(client):
    upd = client.put(f"{API}/policy", headers=ADMIN,
                     json={"approved_regions": {"azure": []}}).json()["approved_regions"]
    assert upd["azure"] == []  # explicit [] is an intentional clear


def test_per_source_override_applies_and_is_cleaned(client):
    # A source whose own config approves the Mistral footprint for Azure (with
    # sloppy whitespace) overrides the global policy for models from that source.
    src = client.post(f"{API}/discovery/sources", headers=ADMIN, json={
        "cloud": "azure", "display_name": "Azure CH", "scope": "SUB-CH",
        "config": {"approved_regions": [" switzerlandnorth ", "francecentral", "uaenorth"]},
    }).json()
    m = client.get(f"{API}/discovery/sources/{src['id']}/vendors/mistral/models",
                   headers=REVIEWER).json()[0]
    rid = client.post(f"{API}/reviews", headers=REVIEWER, json={
        "source_id": src["id"], "vendor": "mistral",
        "resource_id": m["resource_id"], "model_version": m["model_version"],
    }).json()["id"]
    controls = client.get(f"{API}/reviews/{rid}/controls", headers=REVIEWER).json()
    dr = next(c for c in controls if c["control_key"] == "data_residency")
    assert dr["answer"] == "yes"
    assert dr["answer_source"] == "auto"


def test_policy_update_is_audited(client):
    client.put(f"{API}/policy", headers=ADMIN,
               json={"approved_regions": {"azure": ["eastus"], "gcp": ["us-central1"]}})
    entries = client.get(f"{API}/audit?action=policy_updated", headers=ADMIN).json()
    assert len(entries) >= 1
