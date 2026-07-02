"""Review deletion: open reviews are clutter, decided reviews are records.

Rules under test:
  * any reviewer may delete an OPEN (undecided) review
  * decided reviews: admin only + mandatory reason
  * a review cited as another review's fast-track precedent is undeletable
  * deletion cascades (controls/scores), clears Model.current_review_id,
    is audited, and frees the model for a fresh review
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


def test_precedent_review_is_undeletable(client):
    rid1 = _approved_precedent(client, "gcp", "anthropic", "claude-opus-4-8")
    rid2 = _open(client, "gcp", "anthropic", "claude-fable-5")
    assert client.post(f"{API}/reviews/{rid2}/adopt-precedent", headers=REVIEWER).status_code == 200

    res = client.delete(f"{API}/reviews/{rid1}?reason=cleanup", headers=ADMIN)
    assert res.status_code == 409
    assert rid2 in res.json()["details"]["dependent_review_ids"]

    # delete the dependent first, then the precedent becomes deletable
    assert client.delete(f"{API}/reviews/{rid2}", headers=REVIEWER).status_code == 204
    assert client.delete(f"{API}/reviews/{rid1}?reason=cleanup", headers=ADMIN).status_code == 204


def test_delete_clears_current_review_pointer(client):
    rid = _open(client, "azure", "openai", "gpt-4o")
    model = next(m for m in client.get(f"{API}/models", headers=REVIEWER).json()
                 if m["model_name"] == "gpt-4o")
    assert model["current_review_id"] == rid
    assert client.delete(f"{API}/reviews/{rid}", headers=REVIEWER).status_code == 204
    model = next(m for m in client.get(f"{API}/models", headers=REVIEWER).json()
                 if m["model_name"] == "gpt-4o")
    assert model["current_review_id"] != rid  # pointer no longer dangles
