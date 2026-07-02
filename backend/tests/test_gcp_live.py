"""GcpLiveDriver unit tests against canned Vertex AI responses (no network).

The fixture models a realistic project:
  * Model Garden catalog offers gemini + claude in two approved regions
    (zero resources needed to discover them)
  * a tuned gemini model deployed to TWO endpoints (us-central1 private+CMEK,
    us-east4 public, no CMEK) — one logical model, facts merged FAIL-CLOSED
  * publisher/region combinations Vertex doesn't serve return 404 -> empty
  * pageToken pagination on the catalog list
"""
from __future__ import annotations

import pytest

from app.discovery.gcp_live import GcpLiveDriver, _PUBLISHERS
from app.services.errors import ValidationError

PROJECT = "aigov-demo-project"
REGIONS = ["europe-west4", "us-central1", "us-east4", "us-east5"]  # default policy, sorted


def _pub_model(publisher: str, name: str, version: str = "001",
               stage: str = "GA") -> dict:
    return {
        "name": f"publishers/{publisher}/models/{name}",
        "versionId": version,
        "launchStage": stage,
        "openSourceCategory": "PROPRIETARY",
    }


def _cat_url(region: str, publisher: str) -> str:
    return (f"https://{region}-aiplatform.googleapis.com/v1beta1"
            f"/publishers/{publisher}/models?pageSize=200")


def _ep_url(region: str) -> str:
    return (f"https://{region}-aiplatform.googleapis.com/v1"
            f"/projects/{PROJECT}/locations/{region}/endpoints?pageSize=100")


def _models_url(region: str) -> str:
    return (f"https://{region}-aiplatform.googleapis.com/v1"
            f"/projects/{PROJECT}/locations/{region}/models?pageSize=100")


TUNED = f"projects/{PROJECT}/locations/us-central1/models/8888"
TUNED_EAST = f"projects/{PROJECT}/locations/us-east4/models/9999"

RESPONSES: dict = {
    # --- catalog: gemini in two regions (us-central1 paginated), claude in one ---
    _cat_url("us-central1", "google"): {
        "publisherModels": [_pub_model("google", "gemini-2.5-pro")],
        "nextPageToken": "page2",
    },
    _cat_url("us-central1", "google") + "&pageToken=page2": {
        "publisherModels": [_pub_model("google", "gemini-2.5-flash", stage="PREVIEW")],
    },
    _cat_url("us-east4", "google"): {
        "publisherModels": [_pub_model("google", "gemini-2.5-pro")],
    },
    _cat_url("us-east5", "anthropic"): {
        "publisherModels": [_pub_model("anthropic", "claude-opus-4-8")],
    },
    # --- deployed: tuned gemini on two endpoints with divergent posture ---
    _ep_url("us-central1"): {
        "endpoints": [{
            "name": f"projects/{PROJECT}/locations/us-central1/endpoints/111",
            "network": f"projects/{PROJECT}/global/networks/private-net",
            "encryptionSpec": {"kmsKeyName": "projects/kms/keyRings/r/cryptoKeys/k"},
            "deployedModels": [{"model": TUNED, "displayName": "gemini-support-tuned"}],
        }],
    },
    _ep_url("us-east4"): {
        "endpoints": [{
            "name": f"projects/{PROJECT}/locations/us-east4/endpoints/222",
            "deployedModels": [{"model": TUNED_EAST, "displayName": "gemini-support-tuned"}],
        }],
    },
    _models_url("us-central1"): {
        "models": [{
            "name": TUNED, "displayName": "gemini-support-tuned", "versionId": "3",
            "encryptionSpec": {"kmsKeyName": "projects/kms/keyRings/r/cryptoKeys/k"},
            "baseModelSource": {"modelGardenSource": {"publicModelName": "publishers/google/models/gemini-2.5-pro"}},
        }],
    },
    _models_url("us-east4"): {
        "models": [{
            "name": TUNED_EAST, "displayName": "gemini-support-tuned", "versionId": "3",
            "baseModelSource": {"modelGardenSource": {"publicModelName": "publishers/google/models/gemini-2.5-pro"}},
        }],
    },
}


@pytest.fixture()
def driver():
    calls: list[str] = []

    def fake_fetch(url: str) -> dict:
        calls.append(url)
        if url in RESPONSES:
            return RESPONSES[url]
        # Everything else behaves like Vertex's 404 for unserved publisher/region
        # combos — the driver's _default_fetch maps that to {}.
        return {}

    d = GcpLiveDriver(fetch=fake_fetch)
    d._calls = calls
    return d


def test_catalog_vendors_with_zero_resources(driver):
    assert driver.list_vendors(PROJECT) == ["anthropic", "google"]


def test_catalog_model_merges_regions_and_paginates(driver):
    models = driver.list_models(PROJECT, "google")
    pro = next(m for m in models if m.model_name == "gemini-2.5-pro")
    assert pro.regions == ["us-central1", "us-east4"]  # merged catalog footprint
    assert pro.provisioning_state == "NotDeployed"
    assert pro.label().endswith("— not deployed")
    f = pro.facts
    assert f["deployment_status"] == "catalog"
    assert f["terms"]["id"] == "gcp-service-terms"
    assert f["modality"] == "multimodal"
    for key in ("public_network_access", "encryption_cmk", "content_filter"):
        assert key not in f  # no resource -> no fabricated posture
    # The paginated second page arrived:
    flash = next(m for m in models if m.model_name == "gemini-2.5-flash")
    assert flash.facts["lifecycle_status"] == "PREVIEW"


def test_anthropic_terms_match_across_clouds(driver):
    claude = driver.list_models(PROJECT, "anthropic")[0]
    # Same id as the Azure driver and the stub -> cross-cloud precedent works.
    assert claude.facts["terms"]["id"] == "anthropic-commercial-tos"


def test_deployed_endpoints_merge_fail_closed(driver):
    tuned = next(m for m in driver.list_models(PROJECT, "google")
                 if m.model_name == "gemini-support-tuned")
    assert tuned.provisioning_state == "Deployed"
    assert tuned.regions == ["us-central1", "us-east4"]
    f = tuned.facts
    assert f["deployment_status"] == "deployed"
    # us-east4 endpoint is public and has no CMEK -> worst posture wins.
    assert f["public_network_access"] == "Enabled"
    assert f["encryption_cmk"] is False
    assert f["is_finetuned"] is True          # baseModelSource present
    assert f["version_upgrade_option"] == "NoAutoUpgrade"  # deployments pin versions


def test_unknown_publisher_fails_closed():
    from app.discovery.gcp_live import _VENDOR_TERMS
    assert "cohere" in _PUBLISHERS
    assert "cohere" not in _VENDOR_TERMS  # terms=None -> no precedent fast-track


def test_scope_fallback_requires_project(driver, monkeypatch):
    from app import config
    monkeypatch.delenv("GCP_PROJECT_ID", raising=False)
    config.get_settings.cache_clear()
    try:
        with pytest.raises(ValidationError):
            driver.list_vendors("organizations/000000000000")
        monkeypatch.setenv("GCP_PROJECT_ID", PROJECT)
        config.get_settings.cache_clear()
        assert driver.list_vendors("organizations/000000000000") == ["anthropic", "google"]
    finally:
        config.get_settings.cache_clear()


def test_inventory_cached_across_calls(driver):
    driver.list_vendors(PROJECT)
    n = len(driver._calls)
    driver.list_models(PROJECT, "google")  # same inventory, no new API calls
    assert len(driver._calls) == n


def test_live_bootstrap_gcp_source_stable_across_restarts(monkeypatch):
    """Live GCP mode converts the demo source once and stays idempotent."""
    import app.config as config
    from app.bootstrap import seed_default_sources
    from app.models import Base, DiscoverySource
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import sessionmaker

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    monkeypatch.setenv("GCP_DISCOVERY", "live")
    monkeypatch.setenv("GCP_PROJECT_ID", PROJECT)
    config.get_settings.cache_clear()
    try:
        with Session() as db:
            db.add(DiscoverySource(cloud="gcp", display_name="GCP (demo)",
                                   scope="organizations/000000000000", enabled=True))
            db.commit()
            for _ in range(3):  # three restarts
                seed_default_sources(db)
            rows = list(db.execute(select(DiscoverySource).where(
                DiscoverySource.cloud == "gcp")).scalars())
            assert len(rows) == 1  # no duplicates
            assert rows[0].display_name == f"GCP ({PROJECT})"
            assert rows[0].scope == PROJECT
    finally:
        config.get_settings.cache_clear()


def test_gcp_catalog_review_through_api(client, driver):
    """End-to-end: registry swap -> review on a catalog-only Gemini model; KO
    gates don't fire, platform attestations land, residency reflects policy."""
    import os
    import app.config as config
    from app.discovery.base import register_driver
    from app.discovery.stub import StubGcpDriver
    from tests.conftest import REVIEWER

    register_driver(driver)
    try:
        os.environ["GCP_PROJECT_ID"] = PROJECT
        config.get_settings.cache_clear()
        api = "/api/v1"
        sources = client.get(f"{api}/discovery/sources", headers=REVIEWER).json()
        sid = next(s["id"] for s in sources if s["cloud"] == "gcp")
        models = client.get(
            f"{api}/discovery/sources/{sid}/vendors/google/models", headers=REVIEWER
        ).json()
        pro = next(m for m in models if m["model_name"] == "gemini-2.5-pro")
        assert pro["provisioning_state"] == "NotDeployed"

        r = client.post(f"{api}/reviews", headers=REVIEWER, json={
            "source_id": sid, "vendor": "google",
            "resource_id": pro["resource_id"], "model_version": pro["model_version"],
        })
        assert r.status_code == 201, r.text
        controls = client.get(f"{api}/reviews/{r.json()['id']}/controls", headers=REVIEWER).json()
        by_key = {c["control_key"]: c for c in controls}
        assert by_key["safety_filters"]["answer_source"] == "suggested"  # catalog: no KO fired
        assert by_key["data_handling"]["answer_source"] == "attested"    # Vertex data governance
        assert by_key["provider_slas"]["answer_source"] == "attested"
        assert "not deployed" in by_key["data_residency"]["auto_rationale"]
    finally:
        register_driver(StubGcpDriver())
        os.environ.pop("GCP_PROJECT_ID", None)
        config.get_settings.cache_clear()
