"""Precedent fast-track ("rubber stamp"): eligibility, adoption, and its limits.

The scenarios mirror the intended process:
  * approve one model from a vendor -> the next model under the SAME terms can
    adopt its judgment answers and go straight to scoring/approval
  * a variant with DIFFERENT governing terms (claude-mythos-5 vs the approved
    claude-fable-5/opus line) is blocked with an explanation
  * adopted answers never include auto (cloud-fact) controls, so a model with a
    worse footprint still trips its own gates (o3-mini's residency KO)
"""
from __future__ import annotations

from tests.conftest import ADMIN, APPROVER, REVIEWER

API = "/api/v1"


# --- helpers --------------------------------------------------------------------

def _open(client, cloud: str, vendor: str, model_name: str) -> str:
    sources = client.get(f"{API}/discovery/sources", headers=REVIEWER).json()
    sid = next(s["id"] for s in sources if s["cloud"] == cloud)
    models = client.get(
        f"{API}/discovery/sources/{sid}/vendors/{vendor}/models", headers=REVIEWER
    ).json()
    m = next(x for x in models if x["model_name"] == model_name)
    r = client.post(f"{API}/reviews", headers=REVIEWER, json={
        "source_id": sid, "vendor": vendor,
        "resource_id": m["resource_id"], "model_version": m["model_version"],
    })
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _controls(client, rid: str) -> list[dict]:
    return client.get(f"{API}/reviews/{rid}/controls", headers=REVIEWER).json()


def _full_review_submit(client, rid: str) -> dict:
    """Answer every non-auto control 'yes' and submit."""
    for c in _controls(client, rid):
        if c["answer_source"] != "auto":
            client.patch(f"{API}/reviews/{rid}/controls/{c['id']}", headers=REVIEWER,
                         json={"answer": "yes"})
    res = client.post(f"{API}/reviews/{rid}/submit", headers=REVIEWER)
    assert res.status_code == 200, res.text
    return res.json()


def _approve(client, rid: str, tier: int) -> dict:
    body = {"decision": "approve", "justification": "governance review complete"}
    if tier == 2:
        body = {"decision": "approve_with_conditions", "justification": "ok",
                "conditions": "logging + restricted data"}
    res = client.post(f"{API}/reviews/{rid}/decision", headers=APPROVER, json=body)
    assert res.status_code == 201, res.text
    return res.json()


def _approved_precedent(client, cloud: str, vendor: str, model_name: str) -> str:
    """Full-review + approve one model; returns its review id."""
    rid = _open(client, cloud, vendor, model_name)
    result = _full_review_submit(client, rid)
    _approve(client, rid, result["score"]["tier"])
    return rid


# --- happy path: same vendor + same terms ---------------------------------------

def test_fasttrack_same_terms_carries_judgment_answers(client):
    rid1 = _approved_precedent(client, "gcp", "anthropic", "claude-opus-4-8")

    rid2 = _open(client, "gcp", "anthropic", "claude-fable-5")
    p = client.get(f"{API}/reviews/{rid2}/precedent", headers=REVIEWER).json()
    assert p["available"] is True
    assert p["reasons"] == []
    assert p["precedent"]["source_review_id"] == rid1
    assert p["model_terms"]["id"] == "anthropic-commercial-tos"
    assert p["precedent"]["terms"]["id"] == "anthropic-commercial-tos"
    # 6 suggested + 5 manual = 11 judgment controls; 8 auto + 4 attested
    # (documented anthropic/gcp platform commitments) stay fresh.
    assert p["carryable_count"] == 11

    res = client.post(f"{API}/reviews/{rid2}/adopt-precedent", headers=REVIEWER)
    assert res.status_code == 200, res.text
    assert res.json()["carried_count"] == 11
    assert res.json()["precedent_id"]  # standalone precedent row, not a review id

    controls = _controls(client, rid2)
    carried = [c for c in controls if c["answer_source"] == "carried"]
    auto = [c for c in controls if c["answer_source"] == "auto"]
    attested = [c for c in controls if c["answer_source"] == "attested"]
    assert len(carried) == 11
    assert len(auto) == 8       # cloud facts untouched by adoption
    assert len(attested) == 4   # platform attestations untouched by adoption
    assert all(c["answer"] == "yes" for c in carried)

    review = client.get(f"{API}/reviews/{rid2}", headers=REVIEWER).json()
    assert review["precedent_id"]  # links to the precedents table

    # Straight to scoring: clean facts + approved footprint -> Tier 1, approvable.
    result = client.post(f"{API}/reviews/{rid2}/submit", headers=REVIEWER)
    assert result.status_code == 200, result.text
    assert result.json()["score"]["tier"] == 1
    decision = _approve(client, rid2, 1)
    assert decision["decision"] == "approve"


def test_rereview_of_same_model_uses_own_approved_review_as_precedent(client):
    rid1 = _approved_precedent(client, "azure", "openai", "gpt-4o")
    model_id = client.get(f"{API}/reviews/{rid1}", headers=REVIEWER).json()["model_id"]

    r = client.post(f"{API}/reviews", headers=REVIEWER,
                    json={"model_id": model_id, "trigger": "rereview"})
    assert r.status_code == 201, r.text
    rid2 = r.json()["id"]

    p = client.get(f"{API}/reviews/{rid2}/precedent", headers=REVIEWER).json()
    assert p["available"] is True
    assert p["precedent"]["source_review_id"] == rid1

    client.post(f"{API}/reviews/{rid2}/adopt-precedent", headers=REVIEWER)
    result = client.post(f"{API}/reviews/{rid2}/submit", headers=REVIEWER).json()
    assert result["score"]["tier"] == 1


# --- the caveat: different terms block the rubber stamp --------------------------

def test_different_terms_block_fasttrack(client):
    _approved_precedent(client, "gcp", "anthropic", "claude-fable-5")

    rid = _open(client, "gcp", "anthropic", "claude-mythos-5")
    p = client.get(f"{API}/reviews/{rid}/precedent", headers=REVIEWER).json()
    assert p["available"] is False
    # The explanation names both terms so the reviewer sees exactly why.
    reasons = " ".join(p["reasons"])
    assert "Mythos" in reasons
    assert "Anthropic Commercial Terms of Service" in reasons
    assert "full review" in reasons.lower()
    # The examined-but-blocked candidate is surfaced for context.
    assert p["precedent"]["model_name"] == "claude-fable-5"

    res = client.post(f"{API}/reviews/{rid}/adopt-precedent", headers=REVIEWER)
    assert res.status_code == 409, res.text


def test_first_of_vendor_has_no_precedent(client):
    rid = _open(client, "azure", "mistral", "Mistral-Large-2411")
    p = client.get(f"{API}/reviews/{rid}/precedent", headers=REVIEWER).json()
    assert p["available"] is False
    assert any("No precedent exists" in r for r in p["reasons"])
    assert p["precedent"] is None

    res = client.post(f"{API}/reviews/{rid}/adopt-precedent", headers=REVIEWER)
    assert res.status_code == 409


# --- safety: adoption never bypasses fresh cloud facts ---------------------------

def test_adoption_keeps_fresh_auto_facts_and_gates(client):
    _approved_precedent(client, "azure", "openai", "gpt-4o")

    # o3-mini: SAME terms (fast-track eligible) but a worse cloud footprint.
    rid = _open(client, "azure", "openai", "o3-mini")
    p = client.get(f"{API}/reviews/{rid}/precedent", headers=REVIEWER).json()
    assert p["available"] is True

    client.post(f"{API}/reviews/{rid}/adopt-precedent", headers=REVIEWER)
    controls = _controls(client, rid)
    residency = next(c for c in controls if c["control_key"] == "data_residency")
    # o3-mini's own facts, not gpt-4o's: brazilsouth is outside the approved set.
    assert residency["answer_source"] == "auto"
    assert residency["answer"] == "no"
    assert "brazilsouth" in residency["auto_rationale"]

    result = client.post(f"{API}/reviews/{rid}/submit", headers=REVIEWER).json()
    # Residency is a knock-out -> Tier 4. The rubber stamp cannot launder facts.
    assert result["score"]["tier"] == 4
    assert any(g["type"] == "ko_fail" for g in result["score"]["triggered_gates"])

    # And the approval gate still requires an admin override.
    blocked = client.post(f"{API}/reviews/{rid}/decision", headers=APPROVER,
                          json={"decision": "approve", "justification": "rubber stamp"})
    assert blocked.status_code == 403


# --- guards & provenance ----------------------------------------------------------

def test_adopt_twice_conflicts(client):
    _approved_precedent(client, "gcp", "anthropic", "claude-opus-4-8")
    rid = _open(client, "gcp", "anthropic", "claude-fable-5")
    assert client.post(f"{API}/reviews/{rid}/adopt-precedent", headers=REVIEWER).status_code == 200
    again = client.post(f"{API}/reviews/{rid}/adopt-precedent", headers=REVIEWER)
    assert again.status_code == 409
    p = client.get(f"{API}/reviews/{rid}/precedent", headers=REVIEWER).json()
    assert p["available"] is False
    assert any("already adopted" in r for r in p["reasons"])


def test_adopt_after_submit_conflicts(client):
    _approved_precedent(client, "gcp", "anthropic", "claude-opus-4-8")
    rid = _open(client, "gcp", "anthropic", "claude-fable-5")
    _full_review_submit(client, rid)  # scored without adopting
    res = client.post(f"{API}/reviews/{rid}/adopt-precedent", headers=REVIEWER)
    assert res.status_code == 409


def test_carried_answers_can_still_be_overridden(client):
    _approved_precedent(client, "gcp", "anthropic", "claude-opus-4-8")
    rid = _open(client, "gcp", "anthropic", "claude-fable-5")
    client.post(f"{API}/reviews/{rid}/adopt-precedent", headers=REVIEWER)
    carried = next(c for c in _controls(client, rid) if c["answer_source"] == "carried")
    res = client.patch(f"{API}/reviews/{rid}/controls/{carried['id']}", headers=REVIEWER,
                       json={"answer": "partial"})
    assert res.status_code == 200
    assert res.json()["answer_source"] == "human"  # override re-owns the answer


def test_adoption_is_audited_and_decision_references_precedent(client):
    rid1 = _approved_precedent(client, "gcp", "anthropic", "claude-opus-4-8")
    rid2 = _open(client, "gcp", "anthropic", "claude-fable-5")
    client.post(f"{API}/reviews/{rid2}/adopt-precedent", headers=REVIEWER)

    trail = client.get(f"{API}/audit/review/{rid2}", headers=ADMIN).json()
    adopted = [e for e in trail if e["action"] == "review_precedent_adopted"]
    assert len(adopted) == 1
    assert adopted[0]["after"]["precedent_source_review_id"] == rid1
    assert adopted[0]["after"]["carried_count"] == 11

    client.post(f"{API}/reviews/{rid2}/submit", headers=REVIEWER)
    _approve(client, rid2, 1)
    trail = client.get(f"{API}/audit/review/{rid2}", headers=ADMIN).json()
    decided = next(e for e in trail if e["action"] == "review_decided")
    assert decided["after"]["precedent_id"]  # decision records the precedent used
