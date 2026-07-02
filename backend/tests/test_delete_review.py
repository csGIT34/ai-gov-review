"""Review deletion: open reviews are clutter, decided reviews are records.

Rules under test:
  * any reviewer may delete an OPEN (undecided) review
  * decided reviews: admin only + mandatory reason
  * precedents are standalone: deleting a review detaches (never breaks) the
    precedent it minted; admin can disable/delete precedents independently
  * deletion cascades (controls/scores), clears Model.current_review_id,
    is audited, and frees the model for a fresh review
  * reviews freeze a point-in-time CSP facts + attestations snapshot
"""
from __future__ import annotations

from tests.conftest import ADMIN, REVIEWER
from tests.test_precedent import _approved_precedent, _open

API = "/api/v1"


def test_reviewer_deletes_open_review(client):
    rid = _open(client, "azure", "openai", "gpt-4o")
    assert client.delete(f"{API}/reviews/{rid}", headers=REVIEWER).status_code == 204
    assert client.get(f"{API}/reviews/{rid}", headers=REVIEWER).status_code == 404

    # audited, with the review's state at deletion time
    trail = client.get(f"{API}/audit/review/{rid}", headers=ADMIN).json()
    deleted = [e for e in trail if e["action"] == "review_deleted"]
    assert len(deleted) == 1
    assert deleted[0]["before"]["state"] == "pending_review"

    # the model is freed: a fresh review can be opened (no duplicate-open 409)
    rid2 = _open(client, "azure", "openai", "gpt-4o")
    assert rid2 != rid


def test_decided_review_needs_admin_and_reason(client):
    rid = _approved_precedent(client, "azure", "openai", "gpt-4o")
    # reviewer: forbidden
    assert client.delete(f"{API}/reviews/{rid}", headers=REVIEWER).status_code == 403
    # admin without a reason: rejected
    assert client.delete(f"{API}/reviews/{rid}", headers=ADMIN).status_code == 422
    # admin with a reason: gone, and the reason is in the audit trail
    res = client.delete(f"{API}/reviews/{rid}?reason=test+data+cleanup", headers=ADMIN)
    assert res.status_code == 204
    trail = client.get(f"{API}/audit/review/{rid}", headers=ADMIN).json()
    deleted = next(e for e in trail if e["action"] == "review_deleted")
    assert deleted["before"]["reason"] == "test data cleanup"
    assert deleted["before"]["state"] == "approved"


def test_precedent_survives_review_deletion(client):
    """The rubber stamp must not depend on review records: delete the approved
    review and the standalone precedent still fast-tracks the next model."""
    rid1 = _approved_precedent(client, "gcp", "anthropic", "claude-opus-4-8")

    # A precedent row was minted at approval, pointing at its source review.
    ps = client.get(f"{API}/precedents", headers=REVIEWER).json()
    p = next(x for x in ps if x["source_review_id"] == rid1)
    assert p["enabled"] is True
    assert p["terms"]["id"] == "anthropic-commercial-tos"
    assert len(p["answers"]) > 0

    # Delete the review the precedent came from — allowed, precedent detaches.
    assert client.delete(f"{API}/reviews/{rid1}?reason=cleanup", headers=ADMIN).status_code == 204
    p2 = next(x for x in client.get(f"{API}/precedents", headers=REVIEWER).json()
              if x["id"] == p["id"])
    assert p2["source_review_id"] is None
    assert p2["model_name"] == "claude-opus-4-8"  # provenance kept as data

    # Fast-track still works from the surviving precedent.
    rid2 = _open(client, "gcp", "anthropic", "claude-fable-5")
    assessment = client.get(f"{API}/reviews/{rid2}/precedent", headers=REVIEWER).json()
    assert assessment["available"] is True
    assert assessment["precedent"]["id"] == p["id"]
    res = client.post(f"{API}/reviews/{rid2}/adopt-precedent", headers=REVIEWER)
    assert res.status_code == 200
    # 11 of the stored answers land on carryable controls; the new review's
    # auto + attested controls stay fresh and are never overwritten.
    assert res.json()["carried_count"] == 11


def test_disabled_precedent_blocks_fast_track(client):
    rid1 = _approved_precedent(client, "gcp", "anthropic", "claude-opus-4-8")
    p = next(x for x in client.get(f"{API}/precedents", headers=ADMIN).json()
             if x["source_review_id"] == rid1)

    # Reviewer cannot toggle; admin can.
    assert client.patch(f"{API}/precedents/{p['id']}", headers=REVIEWER,
                        json={"enabled": False}).status_code == 403
    assert client.patch(f"{API}/precedents/{p['id']}", headers=ADMIN,
                        json={"enabled": False}).json()["enabled"] is False

    rid2 = _open(client, "gcp", "anthropic", "claude-fable-5")
    a = client.get(f"{API}/reviews/{rid2}/precedent", headers=REVIEWER).json()
    assert a["available"] is False
    assert client.post(f"{API}/reviews/{rid2}/adopt-precedent", headers=REVIEWER).status_code == 409

    # Re-enable -> fast-track is back; both toggles are audited.
    client.patch(f"{API}/precedents/{p['id']}", headers=ADMIN, json={"enabled": True})
    assert client.get(f"{API}/reviews/{rid2}/precedent", headers=REVIEWER).json()["available"] is True
    trail = client.get(f"{API}/audit/precedent/{p['id']}", headers=ADMIN).json()
    actions = [e["action"] for e in trail]
    assert "precedent_disabled" in actions and "precedent_enabled" in actions


def test_admin_deletes_precedent_detaches_adopters(client):
    rid1 = _approved_precedent(client, "gcp", "anthropic", "claude-opus-4-8")
    p = next(x for x in client.get(f"{API}/precedents", headers=ADMIN).json()
             if x["source_review_id"] == rid1)
    rid2 = _open(client, "gcp", "anthropic", "claude-fable-5")
    client.post(f"{API}/reviews/{rid2}/adopt-precedent", headers=REVIEWER)

    assert client.delete(f"{API}/precedents/{p['id']}", headers=REVIEWER).status_code == 403
    assert client.delete(f"{API}/precedents/{p['id']}", headers=ADMIN).status_code == 204

    # The adopting review keeps its carried answers but drops the dangling link.
    review = client.get(f"{API}/reviews/{rid2}", headers=REVIEWER).json()
    assert review["precedent_id"] is None
    carried = [c for c in review["controls"] if c["answer_source"] == "carried"]
    assert len(carried) > 0


def test_delete_clears_current_review_pointer(client):
    rid = _open(client, "azure", "openai", "gpt-4o")
    model = next(m for m in client.get(f"{API}/models", headers=REVIEWER).json()
                 if m["model_name"] == "gpt-4o")
    assert model["current_review_id"] == rid
    assert client.delete(f"{API}/reviews/{rid}", headers=REVIEWER).status_code == 204
    model = next(m for m in client.get(f"{API}/models", headers=REVIEWER).json()
                 if m["model_name"] == "gpt-4o")
    assert model["current_review_id"] != rid  # pointer no longer dangles


def test_review_freezes_point_in_time_csp_snapshot(client):
    """A review documents the CSP data its machine answers came from — even if
    the model's live facts change later, the review's evidence doesn't drift."""
    rid = _open(client, "azure", "openai", "gpt-4o")
    review = client.get(f"{API}/reviews/{rid}", headers=REVIEWER).json()
    snap = review["facts_snapshot"]
    assert snap["cloud"] == "azure" and snap["vendor"] == "openai"
    assert snap["captured_at"]
    assert snap["cloud_facts"]["regions"]           # the cloud posture seen at open
    att = snap["attestations"]
    assert "data_handling" in att and att["data_handling"]["evidence_url"].startswith("https://")


def test_cross_cloud_precedent_same_publisher_terms(client):
    """Publisher terms are cloud-agnostic: a precedent minted from an approved
    Claude review on GCP must fast-track a Claude model served from the Azure
    catalog (same anthropic-commercial-tos)."""
    import os
    import app.config as config
    from app.discovery.azure_live import ARM, AzureLiveDriver
    from app.discovery.base import register_driver
    from app.discovery.stub import StubAzureDriver
    from tests.test_azure_live import SUB, _API, _cat, _catalog_urls

    rid1 = _approved_precedent(client, "gcp", "anthropic", "claude-opus-4-8")

    # Live-shaped Azure driver: empty subscription, Claude offered in the catalog.
    responses = {
        f"{ARM}/subscriptions/{SUB}/providers/Microsoft.CognitiveServices"
        f"/accounts?api-version={_API}": {"value": []},
        **_catalog_urls(SUB, {
            "eastus": [_cat("claude-opus-4-7", "1", fmt="Anthropic", kind="AIServices")],
        }),
    }
    driver = AzureLiveDriver(fetch=lambda url: responses[url])
    register_driver(driver)
    try:
        os.environ["AZURE_SUBSCRIPTION_ID"] = SUB
        config.get_settings.cache_clear()
        sources = client.get(f"{API}/discovery/sources", headers=REVIEWER).json()
        sid = next(s["id"] for s in sources if s["cloud"] == "azure")
        m = next(x for x in client.get(
            f"{API}/discovery/sources/{sid}/vendors/anthropic/models", headers=REVIEWER
        ).json() if x["model_name"] == "claude-opus-4-7")
        assert m["provisioning_state"] == "NotDeployed"  # catalog-only, zero resources

        r = client.post(f"{API}/reviews", headers=REVIEWER, json={
            "source_id": sid, "vendor": "anthropic",
            "resource_id": m["resource_id"], "model_version": m["model_version"],
        })
        assert r.status_code == 201, r.text
        rid2 = r.json()["id"]

        a = client.get(f"{API}/reviews/{rid2}/precedent", headers=REVIEWER).json()
        assert a["available"] is True, a["reasons"]
        assert a["model_terms"]["id"] == "anthropic-commercial-tos"
        assert a["precedent"]["source_review_id"] == rid1
        assert a["precedent"]["cloud"] == "gcp"  # precedent minted on the other cloud
        assert client.post(f"{API}/reviews/{rid2}/adopt-precedent", headers=REVIEWER).status_code == 200
    finally:
        register_driver(StubAzureDriver())
        os.environ.pop("AZURE_SUBSCRIPTION_ID", None)
        config.get_settings.cache_clear()
