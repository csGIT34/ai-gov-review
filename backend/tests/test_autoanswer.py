"""Auto-answer engine unit tests + the pre-fill / confirm API flow."""
from __future__ import annotations

from app.services.autoanswer import MANUAL_CONTROLS, collect
from tests.conftest import ADMIN, APPROVER, REVIEWER

API = "/api/v1"

CLEAN = {
    "region": "eastus", "content_filter": "DefaultV2", "public_network_access": "Disabled",
    "local_auth_disabled": True, "encryption_cmk": True, "min_tls": "1.2",
    "diagnostic_settings": True, "version_upgrade_option": "NoAutoUpgrade",
    "is_finetuned": False, "modality": "multimodal",
}
BAD = {
    "region": "switzerlandnorth", "content_filter": None, "public_network_access": "Enabled",
    "local_auth_disabled": False, "encryption_cmk": False, "min_tls": "1.2",
    "diagnostic_settings": False, "version_upgrade_option": "OnceNewDefaultVersionAvailable",
    "is_finetuned": False, "modality": "text",
}


# --- engine units --------------------------------------------------------------

def test_clean_facts_autoanswer_yes():
    r = collect(CLEAN, "openai", cloud="azure")
    for key in ("data_residency", "safety_filters", "access_controls", "encryption_logging",
                "monitoring", "version_change_process", "categorization", "model_card"):
        assert r[key].source == "auto", key
        assert r[key].answer == "yes", (key, r[key].answer)


def test_vendor_vetted_is_not_auto_answered():
    # Contract/EA status is procurement data the cloud API can't see -> manual, no auto answer.
    r = collect(CLEAN, "openai")
    assert "vendor_vetted" not in r
    assert "vendor_vetted" in MANUAL_CONTROLS


def test_bad_facts_autoanswer_flags():
    r = collect(BAD, "mistral", cloud="azure")
    assert r["data_residency"].answer == "no"          # region not approved
    assert r["safety_filters"].answer == "no"          # no content filter
    assert r["access_controls"].answer == "no"         # public + key auth
    assert r["monitoring"].answer == "no"              # no diagnostics
    assert r["version_change_process"].answer == "partial"  # auto-upgrade
    assert "vendor_vetted" not in r                    # contract status is not auto-answerable


def test_doc_controls_are_suggested_with_evidence():
    r = collect(CLEAN, "openai")
    assert r["provenance"].source == "suggested"
    assert r["ip_licensing"].evidence_url  # license link attached
    assert r["model_card"].evidence_url    # model card link attached


def test_manual_controls_have_no_collector():
    r = collect(CLEAN, "openai")
    for key in MANUAL_CONTROLS:
        assert key not in r
    assert MANUAL_CONTROLS == {
        "vendor_vetted", "intended_use", "human_oversight", "incident_response", "impact_assessment"
    }


def test_partial_access_when_only_one_control_present():
    facts = {**CLEAN, "local_auth_disabled": False}  # private net but key auth on
    r = collect(facts, "openai")
    assert r["access_controls"].answer == "partial"


def test_multiregion_residency():
    from app.services.autoanswer import Policy
    p = Policy(approved_regions={"azure": frozenset({"eastus", "eastus2", "westus3", "westeurope"})})
    # A footprint entirely inside the approved set passes.
    ok = collect({"regions": ["eastus", "westus3", "westeurope"]}, "openai", p, cloud="azure")
    assert ok["data_residency"].answer == "yes"
    # A single offending region fails the whole model, and is named.
    bad = collect({"regions": ["eastus", "eastus2", "brazilsouth"]}, "openai", p, cloud="azure")
    assert bad["data_residency"].answer == "no"
    assert "brazilsouth" in bad["data_residency"].rationale
    # The approved regions are NOT reported as offenders.
    assert "outside" in bad["data_residency"].rationale


# --- API: pre-fill on open, confirm-to-submit ----------------------------------

def _open_gpt4o(client):
    sources = client.get(f"{API}/discovery/sources", headers=REVIEWER).json()
    sid = next(s["id"] for s in sources if s["cloud"] == "azure")
    m = client.get(f"{API}/discovery/sources/{sid}/vendors/openai/models", headers=REVIEWER).json()[0]
    r = client.post(f"{API}/reviews", headers=REVIEWER, json={
        "source_id": sid, "vendor": "openai",
        "resource_id": m["resource_id"], "model_version": m["model_version"],
    })
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_review_opens_prefilled(client):
    rid = _open_gpt4o(client)
    controls = client.get(f"{API}/reviews/{rid}/controls", headers=REVIEWER).json()
    auto = [c for c in controls if c["answer_source"] == "auto"]
    attested = [c for c in controls if c["answer_source"] == "attested"]
    suggested = [c for c in controls if c["answer_source"] == "suggested"]
    manual = [c for c in controls if c["answer_source"] is None]
    assert len(auto) == 8
    # openai-on-azure has documented platform commitments for data handling,
    # IP indemnity, red-teaming and compliance attestations.
    assert sorted(c["control_key"] for c in attested) == [
        "data_handling", "ip_licensing", "provider_slas", "safety_redteam",
    ]
    assert len(suggested) == 6
    assert len(manual) == 5
    # auto answers carry a rationale; docs carry evidence links.
    assert all(c["auto_rationale"] for c in auto)
    assert any(c["evidence_url"] for c in suggested)
    # every attested answer cites its document.
    assert all(c["evidence_url"] for c in attested)
    assert all(c["answer"] == "yes" for c in attested)
    # manual controls carry guidance but no answer, and each is notated with its NIST control.
    assert all(c["answer"] is None for c in manual)
    assert all(c["auto_rationale"] for c in manual)  # guidance note
    assert all(c["nist_control"] for c in controls)


def test_controls_carry_nist_reference_and_evidence(client):
    rid = _open_gpt4o(client)
    controls = client.get(f"{API}/reviews/{rid}/controls", headers=REVIEWER).json()
    # Every control has the exact NIST subcategory statement, a Playbook link, and
    # the "evidence to look for" hint.
    assert all(c["nist_control"] for c in controls)
    assert all(c["nist_url"] and "airc.nist.gov" in c["nist_url"] for c in controls)
    assert all(c["evidence_needed"] for c in controls)
    gov = next(c for c in controls if c["control_id"] == "GOVERN 1.1")
    assert "Legal and regulatory requirements" in gov["nist_control"]
    assert gov["nist_url"].endswith("/govern/")


def test_submit_blocked_until_confirmed_and_manual_answered(client):
    rid = _open_gpt4o(client)
    blocked = client.post(f"{API}/reviews/{rid}/submit", headers=REVIEWER)
    assert blocked.status_code == 422
    details = blocked.json()["details"]
    assert len(details["unanswered"]) == 5          # the manual controls
    assert len(details["needs_confirmation"]) == 6  # suggested controls (attested need none)


def test_confirm_as_is_then_submit_flags_infosec(client):
    rid = _open_gpt4o(client)
    controls = client.get(f"{API}/reviews/{rid}/controls", headers=REVIEWER).json()
    for c in controls:
        if c["answer_source"] == "suggested":
            # Confirm the suggestion as-is (accept the machine's answer).
            client.patch(f"{API}/reviews/{rid}/controls/{c['id']}", headers=REVIEWER,
                         json={"answer": c["auto_answer"]})
        elif c["answer_source"] is None:
            client.patch(f"{API}/reviews/{rid}/controls/{c['id']}", headers=REVIEWER,
                         json={"answer": "yes"})
        # auto controls need no action.
    res = client.post(f"{API}/reviews/{rid}/submit", headers=REVIEWER)
    assert res.status_code == 200, res.text
    score = res.json()["score"]
    # infosec_genai is high-weight and left "unknown" -> high_weight gate -> min Tier 3.
    assert score["tier"] == 3
    assert any(g["control_key"] == "infosec_genai" for g in score["triggered_gates"])


def test_confirm_positively_gives_tier1(client):
    rid = _open_gpt4o(client)
    controls = client.get(f"{API}/reviews/{rid}/controls", headers=REVIEWER).json()
    for c in controls:
        if c["answer_source"] != "auto":
            client.patch(f"{API}/reviews/{rid}/controls/{c['id']}", headers=REVIEWER,
                         json={"answer": "yes"})
    res = client.post(f"{API}/reviews/{rid}/submit", headers=REVIEWER).json()
    assert res["score"]["tier"] == 1
    assert res["score"]["overall_score"] == 0.0


def test_controls_grouped_by_answering_team(client):
    """Every control declares its answering team: 'platform' (inherent to the
    model / hosting platform — infra + governance) or 'use_case' (the consuming
    team). All machine-settled answers land on the platform side."""
    rid = _open_gpt4o(client)
    controls = client.get(f"{API}/reviews/{rid}/controls", headers=REVIEWER).json()
    owners = {c["control_key"]: c["owner"] for c in controls}
    assert set(owners.values()) == {"platform", "use_case"}
    use_case = {k for k, o in owners.items() if o == "use_case"}
    assert use_case == {
        "intended_use", "eval_accuracy", "bias_fairness", "infosec_genai",
        "explainability", "human_oversight", "incident_response",
        "impact_assessment", "environmental",
    }
    # auto + attested answers are all platform-side: an infra admin can settle
    # their whole section without the consuming team.
    for c in controls:
        if c["answer_source"] in ("auto", "attested"):
            assert c["owner"] == "platform", c["control_key"]
