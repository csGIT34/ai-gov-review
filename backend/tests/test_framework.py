"""Framework version display + review-freshness tracking."""
from __future__ import annotations

from tests.conftest import ADMIN, REVIEWER

API = "/api/v1"


def test_framework_status_reports_nist_version(client):
    f = client.get(f"{API}/framework", headers=REVIEWER).json()
    assert f["id"] == "nist-ai-rmf-1.0+genai-600-1"
    assert "NIST AI Risk Management Framework" in f["name"]
    assert f["rmf_version"] == "1.0"
    assert f["questionnaire_version"] == 1
    assert f["control_count"] == 23
    # NIST doc references are surfaced for the admin.
    docs = {r["doc"] for r in f["references"]}
    assert {"NIST AI 100-1", "NIST AI 600-1"} <= docs
    # Never reviewed yet -> no last-reviewed, and that isn't treated as "overdue".
    assert f["last_reviewed_at"] is None
    assert f["overdue"] is False
    assert f["review_interval_days"] == 180


def test_framework_status_includes_update_flag(client):
    f = client.get(f"{API}/framework", headers=REVIEWER).json()
    assert f["update_available"] is False
    assert f["latest_known_version"] == "1.0"


def test_check_updates(client):
    c = client.get(f"{API}/framework/check-updates", headers=REVIEWER).json()
    assert c["up_to_date"] is True
    assert c["implemented_version"] == "1.0"
    assert c["latest_known_version"] == "1.0"
    assert c["latest_url"].startswith("https://www.nist.gov")


def test_reviewer_cannot_mark_reviewed(client):
    r = client.post(f"{API}/framework/reviewed", headers=REVIEWER, json={})
    assert r.status_code == 403


def test_admin_marks_reviewed(client):
    r = client.post(f"{API}/framework/reviewed", headers=ADMIN,
                    json={"notes": "Confirmed against NIST AI 600-1; no change.", "interval_days": 90})
    assert r.status_code == 200
    f = r.json()
    assert f["last_reviewed_at"] is not None
    assert f["reviewed_by"] == "Dev Admin"
    assert f["review_interval_days"] == 90
    assert f["next_review_due"] is not None
    assert f["overdue"] is False
    assert "600-1" in f["notes"]


def test_mark_reviewed_is_audited(client):
    client.post(f"{API}/framework/reviewed", headers=ADMIN, json={})
    entries = client.get(f"{API}/audit?action=framework_reviewed", headers=ADMIN).json()
    assert len(entries) >= 1
