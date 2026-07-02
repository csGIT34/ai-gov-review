"""Admin-configurable discovery sources + keyless (WIF-only) credential chains.

Rules under test:
  * PATCH /discovery/sources/{id} is admin-only; scope/driver/enabled edits are
    audited and take effect immediately (per-source-id caching)
  * config.driver flips a source between stub and live WITHOUT a restart
  * credential-looking config keys are refused — sources never store secrets
  * Azure credential chain excludes the client-secret path (WIF/MI/CLI only)
  * GCP credential chain rejects service-account key files (WIF/ADC only)
"""
from __future__ import annotations

import pytest

from tests.conftest import ADMIN, REVIEWER

API = "/api/v1"


def _azure_source(client, headers=REVIEWER):
    return next(s for s in client.get(f"{API}/discovery/sources", headers=headers).json()
                if s["cloud"] == "azure")


def test_patch_source_is_admin_only_and_audited(client):
    src = _azure_source(client)
    r = client.patch(f"{API}/discovery/sources/{src['id']}", headers=REVIEWER,
                     json={"scope": "x"})
    assert r.status_code == 403

    r = client.patch(f"{API}/discovery/sources/{src['id']}", headers=ADMIN, json={
        "scope": "11111111-2222-3333-4444-555555555555",
        "config": {"driver": "live"},
        "display_name": "Azure (work)",
    })
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["scope"] == "11111111-2222-3333-4444-555555555555"
    assert out["config"]["driver"] == "live"
    assert out["display_name"] == "Azure (work)"

    trail = client.get(f"{API}/audit/discovery_source/{src['id']}", headers=ADMIN).json()
    entry = next(e for e in trail if e["action"] == "discovery_source_updated")
    assert entry["before"]["scope"] == src["scope"]
    assert entry["after"]["config"]["driver"] == "live"


def test_driver_flip_changes_results_without_restart(client):
    """stub -> live via PATCH: the dropdown immediately serves the live driver's
    data. Uses a canned live driver registered under the 'live' mode slot."""
    from app.discovery.base import register_driver
    from tests.test_azure_live import RESPONSES, SUB
    from app.discovery.azure_live import AzureLiveDriver

    live = AzureLiveDriver(fetch=lambda url: RESPONSES[url])
    register_driver(live, "live")  # replaces the real live driver for this test

    src = _azure_source(client)
    stub_vendors = client.get(
        f"{API}/discovery/sources/{src['id']}/vendors", headers=REVIEWER
    ).json()
    assert "meta" in stub_vendors  # stub demo data includes llama models

    r = client.patch(f"{API}/discovery/sources/{src['id']}", headers=ADMIN,
                     json={"scope": SUB, "config": {"driver": "live"}})
    assert r.status_code == 200
    live_vendors = client.get(
        f"{API}/discovery/sources/{src['id']}/vendors", headers=REVIEWER
    ).json()
    assert live_vendors == ["mistral", "openai"]  # the canned live inventory
    assert "meta" not in live_vendors

    # ...and back, still no restart.
    client.patch(f"{API}/discovery/sources/{src['id']}", headers=ADMIN,
                 json={"config": {"driver": "stub"}})
    assert "meta" in client.get(
        f"{API}/discovery/sources/{src['id']}/vendors", headers=REVIEWER
    ).json()


def test_invalid_driver_and_credential_keys_refused(client):
    src = _azure_source(client)
    r = client.patch(f"{API}/discovery/sources/{src['id']}", headers=ADMIN,
                     json={"config": {"driver": "yolo"}})
    assert r.status_code == 422

    for key in ("client_secret", "api_key", "sa_token", "password", "credential_json"):
        r = client.patch(f"{API}/discovery/sources/{src['id']}", headers=ADMIN,
                         json={"config": {key: "shhh"}})
        assert r.status_code == 422, key
        assert "never store credentials" in r.json()["detail"]


def test_disabled_source_hidden_from_reviewers_visible_to_admin_list(client):
    src = _azure_source(client)
    client.patch(f"{API}/discovery/sources/{src['id']}", headers=ADMIN,
                 json={"enabled": False})
    default = client.get(f"{API}/discovery/sources", headers=REVIEWER).json()
    assert all(s["id"] != src["id"] for s in default)
    everything = client.get(
        f"{API}/discovery/sources?include_disabled=true", headers=REVIEWER
    ).json()
    assert any(s["id"] == src["id"] and s["enabled"] is False for s in everything)


def test_azure_credential_chain_excludes_client_secret_path(monkeypatch):
    """DefaultAzureCredential must be constructed WITHOUT EnvironmentCredential —
    that's the path that would read AZURE_CLIENT_SECRET."""
    import azure.identity as azid
    from app.discovery.azure_live import _TokenSource

    captured = {}

    class FakeDAC:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def get_token(self, scope):
            class T:
                token = "t"
                expires_on = 9999999999
            return T()

    monkeypatch.delenv("AZURE_ACCESS_TOKEN", raising=False)
    monkeypatch.setattr(azid, "DefaultAzureCredential", FakeDAC)
    assert _TokenSource().bearer() == "t"
    assert captured["exclude_environment_credential"] is True


def test_gcp_credential_chain_rejects_service_account_keys(monkeypatch):
    """A long-lived service-account key in ADC must be refused with a clear
    keyless-by-design error; WIF / user credentials pass."""
    from unittest.mock import MagicMock

    import google.auth
    from google.oauth2 import service_account

    from app.discovery.gcp_live import _TokenSource
    from app.services.errors import ValidationError

    monkeypatch.delenv("GCP_ACCESS_TOKEN", raising=False)
    key_creds = MagicMock(spec=service_account.Credentials)
    monkeypatch.setattr(google.auth, "default", lambda scopes=None: (key_creds, "proj"))
    with pytest.raises(ValidationError) as exc:
        _TokenSource().bearer()
    assert "keyless" in str(exc.value.args[0])
