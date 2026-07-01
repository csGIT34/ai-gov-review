"""End-to-end API tests: discovery -> review -> score -> approval gate + audit."""
from __future__ import annotations

from tests.conftest import ADMIN, APPROVER, REVIEWER

API = "/api/v1"


# --- helpers -------------------------------------------------------------------

def _azure_source(client):
    sources = client.get(f"{API}/discovery/sources", headers=REVIEWER).json()
    return next(s for s in sources if s["cloud"] == "azure")


def _first_openai_model(client, source_id):
    models = client.get(
        f"{API}/discovery/sources/{source_id}/vendors/openai/models", headers=REVIEWER
    ).json()
    return models[0]


def _open_review_for_openai(client):
    source = _azure_source(client)
    m = _first_openai_model(client, source["id"])
    resp = client.post(
        f"{API}/reviews",
        headers=REVIEWER,
        json={
            "source_id": source["id"],
            "vendor": "openai",
            "resource_id": m["resource_id"],
            "model_version": m["model_version"],
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _answer_all(client, review_id, *, overrides=None):
    overrides = overrides or {}
    controls = client.get(f"{API}/reviews/{review_id}/controls", headers=REVIEWER).json()
    for c in controls:
        ans = overrides.get(c["control_key"], "yes")
        r = client.patch(
            f"{API}/reviews/{review_id}/controls/{c['id']}",
            headers=REVIEWER,
            json={"answer": ans},
        )
        assert r.status_code == 200, r.text
    return controls


# --- health + discovery --------------------------------------------------------

def test_health(client):
    assert client.get("/healthz").json() == {"status": "ok"}


def test_discovery_cascade(client):
    source = _azure_source(client)
    vendors = client.get(
        f"{API}/discovery/sources/{source['id']}/vendors", headers=REVIEWER
    ).json()
    assert "openai" in vendors
    models = client.get(
        f"{API}/discovery/sources/{source['id']}/vendors/openai/models", headers=REVIEWER
    ).json()
    assert models and models[0]["resource_id"]
    assert "label" in models[0]


# --- happy path: all-yes -> tier 1 -> approve ----------------------------------

def test_full_flow_all_yes_approves(client):
    review = _open_review_for_openai(client)
    assert review["state"] == "pending_review"

    _answer_all(client, review["id"])

    submit = client.post(f"{API}/reviews/{review['id']}/submit", headers=REVIEWER)
    assert submit.status_code == 200, submit.text
    score = submit.json()["score"]
    assert score["overall_score"] == 0.0
    assert score["tier"] == 1
    assert submit.json()["review"]["state"] == "scored"

    decision = client.post(
        f"{API}/reviews/{review['id']}/decision",
        headers=APPROVER,
        json={"decision": "approve", "justification": "All controls evidenced."},
    )
    assert decision.status_code == 201, decision.text

    detail = client.get(f"{API}/reviews/{review['id']}", headers=REVIEWER).json()
    assert detail["state"] == "approved"
    assert detail["current_score"]["tier"] == 1


def test_cannot_submit_with_unanswered(client):
    review = _open_review_for_openai(client)
    # Answer only one control, then try to submit.
    controls = client.get(f"{API}/reviews/{review['id']}/controls", headers=REVIEWER).json()
    client.patch(
        f"{API}/reviews/{review['id']}/controls/{controls[0]['id']}",
        headers=REVIEWER,
        json={"answer": "yes"},
    )
    r = client.post(f"{API}/reviews/{review['id']}/submit", headers=REVIEWER)
    assert r.status_code == 422
    assert "unanswered" in r.json()["details"]


# --- KO failure forces tier 4; admin override required -------------------------

def test_ko_failure_blocks_and_needs_admin_override(client):
    review = _open_review_for_openai(client)
    # data_residency is a KO control; answer No.
    _answer_all(client, review["id"], overrides={"data_residency": "no"})
    submit = client.post(f"{API}/reviews/{review['id']}/submit", headers=REVIEWER).json()
    assert submit["score"]["tier"] == 4
    assert any(g["type"] == "ko_fail" for g in submit["score"]["triggered_gates"])

    # A plain approver cannot approve a Tier 4.
    blocked = client.post(
        f"{API}/reviews/{review['id']}/decision",
        headers=APPROVER,
        json={"decision": "approve", "justification": "looks fine"},
    )
    assert blocked.status_code == 403

    # Admin without a reason is rejected...
    no_reason = client.post(
        f"{API}/reviews/{review['id']}/decision",
        headers=ADMIN,
        json={"decision": "approve", "justification": "override"},
    )
    assert no_reason.status_code == 422

    # ...admin WITH an override reason succeeds and is recorded.
    ok = client.post(
        f"{API}/reviews/{review['id']}/decision",
        headers=ADMIN,
        json={
            "decision": "approve",
            "justification": "Residency exception granted by CISO.",
            "override_reason": "Documented compensating controls; time-boxed pilot.",
        },
    )
    assert ok.status_code == 201, ok.text
    body = ok.json()
    assert body["overridden_tier"] == 4
    assert body["override_reason"]


# --- tier 3: high-weight No needs a risk owner ---------------------------------

def test_tier3_requires_risk_owner(client):
    review = _open_review_for_openai(client)
    # infosec_genai is high-weight but NOT a KO -> high_weight_no gate -> min Tier 3.
    _answer_all(client, review["id"], overrides={"infosec_genai": "no"})
    submit = client.post(f"{API}/reviews/{review['id']}/submit", headers=REVIEWER).json()
    assert submit["score"]["tier"] >= 3
    assert submit["score"]["tier"] != 4  # not a KO

    missing_owner = client.post(
        f"{API}/reviews/{review['id']}/decision",
        headers=APPROVER,
        json={"decision": "approve", "justification": "acceptable"},
    )
    assert missing_owner.status_code == 422

    me = client.get(f"{API}/me", headers=APPROVER).json()
    ok = client.post(
        f"{API}/reviews/{review['id']}/decision",
        headers=APPROVER,
        json={
            "decision": "approve",
            "justification": "Risk accepted with remediation plan.",
            "risk_owner_id": me["id"],
        },
    )
    assert ok.status_code == 201, ok.text


# --- tier 2: needs compensating conditions -------------------------------------

def test_tier2_requires_conditions(client):
    review = _open_review_for_openai(client)
    # Fail all 9 medium-weight, non-KO controls (deficit 18 of total weight 50 ->
    # score 36.0, the 21-40 band) with no high-weight or KO failure -> Tier 2.
    _answer_all(
        client,
        review["id"],
        overrides={
            "intended_use": "no",
            "eval_accuracy": "no",
            "bias_fairness": "no",
            "encryption_logging": "no",
            "monitoring": "no",
            "version_change_process": "no",
            "ip_licensing": "no",
            "human_oversight": "no",
            "incident_response": "no",
        },
    )
    submit = client.post(f"{API}/reviews/{review['id']}/submit", headers=REVIEWER).json()
    tier = submit["score"]["tier"]
    assert tier == 2, submit["score"]

    plain = client.post(
        f"{API}/reviews/{review['id']}/decision",
        headers=APPROVER,
        json={"decision": "approve", "justification": "ok"},
    )
    assert plain.status_code == 422

    with_conditions = client.post(
        f"{API}/reviews/{review['id']}/decision",
        headers=APPROVER,
        json={
            "decision": "approve_with_conditions",
            "justification": "Approve with logging + non-sensitive data only.",
            "conditions": "Enable full request logging; restrict to non-PII workloads.",
        },
    )
    assert with_conditions.status_code == 201, with_conditions.text


# --- duplicate open review guard ----------------------------------------------

def test_duplicate_open_review_conflicts(client):
    review = _open_review_for_openai(client)
    # Second attempt for the same model while the first is open -> 409.
    source = _azure_source(client)
    m = _first_openai_model(client, source["id"])
    dup = client.post(
        f"{API}/reviews",
        headers=REVIEWER,
        json={
            "source_id": source["id"],
            "vendor": "openai",
            "resource_id": m["resource_id"],
            "model_version": m["model_version"],
        },
    )
    assert dup.status_code == 409
    assert dup.json()["details"]["review_id"] == review["id"]


# --- separation of duty --------------------------------------------------------

def test_separation_of_duty(client):
    review = _open_review_for_openai(client)
    # Assign approver@dev as the REVIEWER of this review.
    me_appr = client.get(f"{API}/me", headers=APPROVER).json()
    client.patch(
        f"{API}/reviews/{review['id']}/assign",
        headers=REVIEWER,
        json={"reviewer_id": me_appr["id"]},
    )
    _answer_all(client, review["id"])
    client.post(f"{API}/reviews/{review['id']}/submit", headers=REVIEWER)

    # The assigned reviewer (also an approver) may not approve their own review.
    sod = client.post(
        f"{API}/reviews/{review['id']}/decision",
        headers=APPROVER,
        json={"decision": "approve", "justification": "self-approve attempt"},
    )
    assert sod.status_code == 403


# --- audit trail ---------------------------------------------------------------

def test_audit_trail_records_lifecycle(client):
    review = _open_review_for_openai(client)
    _answer_all(client, review["id"])
    client.post(f"{API}/reviews/{review['id']}/submit", headers=REVIEWER)
    client.post(
        f"{API}/reviews/{review['id']}/decision",
        headers=APPROVER,
        json={"decision": "approve", "justification": "ok"},
    )
    entries = client.get(
        f"{API}/audit/review/{review['id']}", headers=APPROVER
    ).json()
    actions = {e["action"] for e in entries}
    assert {"review_opened", "review_submitted", "review_scored", "review_decided"} <= actions


def test_reviewer_cannot_read_audit(client):
    # Audit is approver/admin only.
    r = client.get(f"{API}/audit", headers=REVIEWER)
    assert r.status_code == 403
