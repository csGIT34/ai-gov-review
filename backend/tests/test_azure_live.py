"""AzureLiveDriver unit tests against canned ARM responses (no network).

The fixture models a realistic footprint:
  * gpt-4o deployed in TWO accounts (eastus hardened, brazilsouth weak) — must
    collapse into ONE logical model whose facts merge FAIL-CLOSED
  * a Mistral deployment ("Mistral AI" format) on the weak account
  * a fine-tuned gpt-4o (name contains .ft-) — its own logical model
  * a Speech account (kind != OpenAI/AIServices) that must be ignored
  * account paging via nextLink
"""
from __future__ import annotations

import pytest

from app.discovery.azure_live import ARM, AzureLiveDriver
from app.services.errors import ValidationError

SUB = "60d84843-f38e-453d-bf20-34b8b0909860"
_API = "2024-10-01"
_DIAG_API = "2021-05-01-preview"

RG = f"/subscriptions/{SUB}/resourceGroups/ai-rg/providers/Microsoft.CognitiveServices"
ACCT_EAST = f"{RG}/accounts/aoai-east"
ACCT_BRAZIL = f"{RG}/accounts/aoai-brazil"
ACCT_SPEECH = f"{RG}/accounts/speech-1"


def _acct(rid: str, location: str, kind: str = "OpenAI", *, pna: str, local_auth_disabled: bool,
          cmk: bool) -> dict:
    return {
        "id": rid, "name": rid.rsplit("/", 1)[-1], "kind": kind, "location": location,
        "properties": {
            "endpoint": f"https://{rid.rsplit('/', 1)[-1]}.openai.azure.com/",
            "publicNetworkAccess": pna,
            "disableLocalAuth": local_auth_disabled,
            "encryption": {"keySource": "Microsoft.KeyVault"} if cmk else {"keySource": "Microsoft.CognitiveServices"},
        },
    }


def _dep(name: str, version: str, fmt: str = "OpenAI", *, rai: str | None, upgrade: str,
         caps: dict | None = None) -> dict:
    return {
        "name": f"{name}-dep",
        "sku": {"name": "Standard", "capacity": 100},
        "properties": {
            "model": {"format": fmt, "name": name, "version": version},
            "raiPolicyName": rai,
            "versionUpgradeOption": upgrade,
            "provisioningState": "Succeeded",
            "capabilities": caps or {"chatCompletion": "true"},
        },
    }


# Canned ARM responses, keyed by URL. Account list is split over two pages to
# exercise nextLink handling.
PAGE2 = f"{ARM}/subscriptions/{SUB}/providers/Microsoft.CognitiveServices/accounts?page=2"
RESPONSES = {
    f"{ARM}/subscriptions/{SUB}/providers/Microsoft.CognitiveServices/accounts?api-version={_API}": {
        "value": [
            _acct(ACCT_EAST, "eastus", pna="Disabled", local_auth_disabled=True, cmk=True),
            _acct(ACCT_SPEECH, "eastus", kind="SpeechServices", pna="Enabled",
                  local_auth_disabled=False, cmk=False),
        ],
        "nextLink": PAGE2,
    },
    PAGE2: {
        "value": [
            _acct(ACCT_BRAZIL, "brazilsouth", kind="AIServices", pna="Enabled",
                  local_auth_disabled=False, cmk=False),
        ],
    },
    f"{ARM}{ACCT_EAST}/deployments?api-version={_API}": {
        "value": [
            _dep("gpt-4o", "2024-11-20", rai="DefaultV2", upgrade="NoAutoUpgrade",
                 caps={"chatCompletion": "true", "imageInput": "true"}),
            _dep("gpt-4o.ft-support-bot", "1", rai="DefaultV2", upgrade="NoAutoUpgrade"),
        ],
    },
    f"{ARM}{ACCT_BRAZIL}/deployments?api-version={_API}": {
        "value": [
            _dep("gpt-4o", "2024-11-20", rai=None, upgrade="OnceNewDefaultVersionAvailable",
                 caps={"chatCompletion": "true", "imageInput": "true"}),
            _dep("Mistral-Large-2411", "1", fmt="Mistral AI", rai=None, upgrade="NoAutoUpgrade"),
        ],
    },
    f"{ARM}{ACCT_EAST}/providers/Microsoft.Insights/diagnosticSettings?api-version={_DIAG_API}": {
        "value": [{
            "name": "to-log-analytics",
            "properties": {
                "workspaceId": f"/subscriptions/{SUB}/resourceGroups/ops/providers/Microsoft.OperationalInsights/workspaces/logs",
                "logs": [{"categoryGroup": "audit", "enabled": True}],
                "metrics": [{"category": "AllMetrics", "enabled": False}],
            },
        }],
    },
    f"{ARM}{ACCT_BRAZIL}/providers/Microsoft.Insights/diagnosticSettings?api-version={_DIAG_API}": {
        "value": [],
    },
}


@pytest.fixture()
def driver():
    calls: list[str] = []

    def fake_fetch(url: str) -> dict:
        calls.append(url)
        if url not in RESPONSES:
            raise AssertionError(f"unexpected ARM call: {url}")
        return RESPONSES[url]

    d = AzureLiveDriver(fetch=fake_fetch)
    d._calls = calls  # for cache assertions
    return d


def test_vendors_and_ignored_kinds(driver):
    vendors = driver.list_vendors(SUB)
    assert vendors == ["mistral", "openai"]  # Speech account contributes nothing
    assert not any("speech-1" in c for c in driver._calls)


def test_multiregion_merge_fails_closed(driver):
    models = driver.list_models(SUB, "openai")
    gpt = next(m for m in models if m.model_name == "gpt-4o")
    assert gpt.regions == ["brazilsouth", "eastus"]
    assert gpt.resource_id == f"azure:{SUB}:openai:gpt-4o"
    f = gpt.facts
    # Worst posture across the footprint wins:
    assert f["public_network_access"] == "Enabled"      # brazil is open
    assert f["local_auth_disabled"] is False            # brazil allows key auth
    assert f["encryption_cmk"] is False                 # brazil has no CMK
    assert f["diagnostic_settings"] is False            # brazil has no sink
    assert f["content_filter"] is None                  # brazil lacks a RAI policy
    assert f["version_upgrade_option"] == "OnceNewDefaultVersionAvailable"
    assert f["modality"] == "multimodal"                # imageInput capability
    assert f["min_tls"] == "1.2"
    assert f["terms"]["id"] == "azure-openai-service-terms"


def test_finetune_is_its_own_model(driver):
    models = driver.list_models(SUB, "openai")
    ft = next(m for m in models if ".ft-" in m.model_name)
    assert ft.facts["is_finetuned"] is True
    assert ft.regions == ["eastus"]
    # Single hardened account -> clean facts.
    assert ft.facts["public_network_access"] == "Disabled"
    assert ft.facts["diagnostic_settings"] is True


def test_vendor_format_mapping_and_terms(driver):
    mistral = driver.list_models(SUB, "mistral")
    assert len(mistral) == 1
    m = mistral[0]
    assert m.model_format == "Mistral AI"
    assert m.facts["terms"]["id"] == "mistral-ai-terms"
    assert m.regions == ["brazilsouth"]


def test_diag_setting_without_enabled_logs_fails_closed():
    from app.discovery.azure_live import _has_enabled_log_sink
    ws = "/subscriptions/x/resourceGroups/ops/providers/Microsoft.OperationalInsights/workspaces/logs"
    # A bare resource, a metrics-only setting, and an all-disabled setting are
    # NOT evidence of logging.
    assert _has_enabled_log_sink([]) is False
    assert _has_enabled_log_sink([{"name": "empty"}]) is False
    assert _has_enabled_log_sink([{
        "name": "metrics-only",
        "properties": {"workspaceId": ws, "metrics": [{"enabled": True}], "logs": []},
    }]) is False
    assert _has_enabled_log_sink([{
        "name": "disabled",
        "properties": {"workspaceId": ws, "logs": [{"enabled": False}]},
    }]) is False
    # Enabled logs without any destination don't count either.
    assert _has_enabled_log_sink([{
        "name": "no-dest", "properties": {"logs": [{"enabled": True}]},
    }]) is False
    assert _has_enabled_log_sink([{
        "name": "good", "properties": {"workspaceId": ws, "logs": [{"enabled": True}]},
    }]) is True


def test_live_bootstrap_source_stable_across_restarts(monkeypatch):
    """Live mode must convert the demo source once and stay idempotent —
    no duplicate azure sources accumulating across restarts, and user-created
    sources are left untouched."""
    import app.config as config
    from app.bootstrap import seed_default_sources
    from app.models import Base, DiscoverySource
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import sessionmaker

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    monkeypatch.setenv("AZURE_DISCOVERY", "live")
    monkeypatch.setenv("AZURE_SUBSCRIPTION_ID", SUB)
    config.get_settings.cache_clear()
    try:
        with Session() as db:
            # Simulate a pre-live install: demo row exists, plus a user's custom source.
            db.add(DiscoverySource(cloud="azure", display_name="Azure (demo)",
                                   scope="DEMO-TENANT", enabled=True))
            db.add(DiscoverySource(cloud="azure", display_name="My special tenant",
                                   scope=SUB, enabled=True))
            db.commit()
            for _ in range(3):  # three restarts
                seed_default_sources(db)
            rows = list(db.execute(select(DiscoverySource).where(
                DiscoverySource.cloud == "azure")).scalars())
            assert len(rows) == 2  # no duplicates
            live = next(r for r in rows if r.display_name.startswith("Azure ("))
            assert live.scope == SUB
            custom = next(r for r in rows if r.display_name == "My special tenant")
            assert custom.scope == SUB  # untouched
    finally:
        config.get_settings.cache_clear()


def test_divergent_filters_fail_closed_with_explanation():
    """Filters attached everywhere but DIFFERENT per region -> answer 'no' with a
    rationale that says the posture is non-uniform (not 'no policy attached')."""
    from app.services.autoanswer import collect

    acct2 = f"{RG}/accounts/aoai-west"
    responses = {
        f"{ARM}/subscriptions/{SUB}/providers/Microsoft.CognitiveServices/accounts?api-version={_API}": {
            "value": [
                _acct(ACCT_EAST, "eastus", pna="Disabled", local_auth_disabled=True, cmk=True),
                _acct(acct2, "westus3", pna="Disabled", local_auth_disabled=True, cmk=True),
            ],
        },
        f"{ARM}{ACCT_EAST}/deployments?api-version={_API}": {
            "value": [_dep("gpt-4o", "2024-11-20", rai="DefaultV2", upgrade="NoAutoUpgrade")],
        },
        f"{ARM}{acct2}/deployments?api-version={_API}": {
            "value": [_dep("gpt-4o", "2024-11-20", rai="CustomStrict", upgrade="NoAutoUpgrade")],
        },
        f"{ARM}{ACCT_EAST}/providers/Microsoft.Insights/diagnosticSettings?api-version={_DIAG_API}": {"value": []},
        f"{ARM}{acct2}/providers/Microsoft.Insights/diagnosticSettings?api-version={_DIAG_API}": {"value": []},
    }
    d = AzureLiveDriver(fetch=lambda url: responses[url])
    m = d.list_models(SUB, "openai")[0]
    assert m.facts["content_filter"] is None
    assert m.facts["content_filter_mixed"] == ["CustomStrict", "DefaultV2"]
    result = collect(m.facts, "openai", cloud="azure")["safety_filters"]
    assert result.answer == "no"
    assert "differ across regional deployments" in result.rationale


def test_non_json_arm_response_is_a_clean_validation_error(monkeypatch):
    """A proxy returning 2xx HTML must surface as a helpful 422, and the bearer
    token must never appear in the error message."""
    import httpx as _httpx

    monkeypatch.setenv("AZURE_ACCESS_TOKEN", "sekret-token")

    def fake_get(url, headers=None, timeout=None):
        return _httpx.Response(200, text="<html>gateway</html>",
                               request=_httpx.Request("GET", url))

    monkeypatch.setattr(_httpx, "get", fake_get)
    d = AzureLiveDriver()
    with pytest.raises(ValidationError) as exc:
        d.list_vendors(SUB)
    assert "non-JSON" in str(exc.value.args[0])
    assert "sekret-token" not in str(exc.value.args)


def test_unknown_format_slug_has_no_terms():
    from app.discovery.azure_live import _VENDOR_TERMS, _slug
    assert _slug("Contoso Labs") == "contoso-labs"
    assert "contoso-labs" not in _VENDOR_TERMS  # terms=None -> precedent fails closed


def test_inventory_cached_across_calls(driver):
    driver.list_vendors(SUB)
    n = len(driver._calls)
    driver.list_models(SUB, "openai")  # same inventory, no new ARM calls
    assert len(driver._calls) == n


def test_scope_fallback_requires_subscription(driver, monkeypatch):
    from app import config
    monkeypatch.delenv("AZURE_SUBSCRIPTION_ID", raising=False)
    config.get_settings.cache_clear()
    try:
        with pytest.raises(ValidationError):
            driver.list_vendors("DEMO-TENANT")
        monkeypatch.setenv("AZURE_SUBSCRIPTION_ID", SUB)
        config.get_settings.cache_clear()
        assert driver.list_vendors("DEMO-TENANT") == ["mistral", "openai"]
    finally:
        config.get_settings.cache_clear()


def test_live_shaped_models_flow_through_review(client, driver):
    """End-to-end: swap the registry to the fixture driver, open a review, and
    check the auto-answer engine consumes live-shaped facts."""
    from app.discovery.base import register_driver
    from app.discovery.stub import StubAzureDriver
    from tests.conftest import REVIEWER

    register_driver(driver)
    try:
        api = "/api/v1"
        sources = client.get(f"{api}/discovery/sources", headers=REVIEWER).json()
        sid = next(s["id"] for s in sources if s["cloud"] == "azure")
        # The seeded demo source's scope isn't a GUID -> driver needs the env fallback.
        import app.config as config
        import os
        os.environ["AZURE_SUBSCRIPTION_ID"] = SUB
        config.get_settings.cache_clear()

        vendors = client.get(f"{api}/discovery/sources/{sid}/vendors", headers=REVIEWER).json()
        assert vendors == ["mistral", "openai"]
        models = client.get(
            f"{api}/discovery/sources/{sid}/vendors/openai/models", headers=REVIEWER
        ).json()
        gpt = next(m for m in models if m["model_name"] == "gpt-4o")
        assert gpt["regions"] == ["brazilsouth", "eastus"]

        r = client.post(f"{api}/reviews", headers=REVIEWER, json={
            "source_id": sid, "vendor": "openai",
            "resource_id": gpt["resource_id"], "model_version": gpt["model_version"],
        })
        assert r.status_code == 201, r.text
        controls = client.get(f"{api}/reviews/{r.json()['id']}/controls", headers=REVIEWER).json()
        residency = next(c for c in controls if c["control_key"] == "data_residency")
        # brazilsouth is outside the default approved set -> live facts drive the KO.
        assert residency["answer"] == "no"
        assert "brazilsouth" in residency["auto_rationale"]
        filters = next(c for c in controls if c["control_key"] == "safety_filters")
        assert filters["answer"] == "no"  # weakest regional deployment lacks a RAI policy
    finally:
        register_driver(StubAzureDriver())
        os.environ.pop("AZURE_SUBSCRIPTION_ID", None)
        config.get_settings.cache_clear()
