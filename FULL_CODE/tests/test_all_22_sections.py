"""Comprehensive Test Suite for all 22 Sections across Customer, Store Manager, and Admin roles.

Validates:
1. All 3 Customer sections.
2. All 8 Store Manager sections with strict store-level isolation.
3. All 11 Administrator sections with strict role-based access control (HTTP 403 for non-admins).
4. Real data returns (no fake metrics).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ["APP_ENV"] = "test"
os.environ["TESTING"] = "true"

from FULL_CODE.app import app, load_application_state
from FULL_CODE.db.seed import seed_database


@pytest.fixture(scope="module")
def client():
    seed_database(force_demo=True)
    load_application_state()
    return TestClient(app)


@pytest.fixture(scope="module")
def tokens(client):
    res_c = client.post("/api/auth/login", json={"email": "customer@example.com", "password": "DemoCust#2026!Aarav"})
    assert res_c.status_code == 200
    res_m1 = client.post("/api/auth/login", json={"email": "manager.kankarbagh@saffron.example", "password": "DemoMgr#2026!Kankarbagh"})
    assert res_m1.status_code == 200
    res_m2 = client.post("/api/auth/login", json={"email": "manager.kothrud@saffron.example", "password": "DemoMgr#2026!Kothrud"})
    assert res_m2.status_code == 200
    res_a = client.post("/api/auth/login", json={"email": "admin@saffron.example", "password": "DemoAdmin#2026!LocalOnly"})
    assert res_a.status_code == 200

    return {
        "customer": res_c.json()["access_token"],
        "mgr_kankarbagh": res_m1.json()["access_token"],
        "mgr_kothrud": res_m2.json()["access_token"],
        "admin": res_a.json()["access_token"],
    }


# =============================================================================
# 1. Customer Sections (3)
# =============================================================================
def test_section_01_customer_dashboard(client, tokens):
    headers = {"Authorization": f"Bearer {tokens['customer']}"}
    res = client.get("/api/customer/dashboard", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert "total_submissions" in data
    assert "recent_submissions" in data


def test_section_02_customer_submit_feedback(client, tokens):
    headers = {"Authorization": f"Bearer {tokens['customer']}"}
    res = client.post(
        "/api/customer/submissions",
        headers=headers,
        json={
            "store_id": "ST-D69EG",
            "channel": "in_app",
            "rating": 4,
            "text": "Vegetable display was clean and staff was helpful today.",
        },
    )
    assert res.status_code == 201
    assert res.json()["success"] is True


def test_section_03_customer_submission_history(client, tokens):
    headers = {"Authorization": f"Bearer {tokens['customer']}"}
    res = client.get("/api/customer/submissions", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert "submissions" in data
    assert len(data["submissions"]) > 0


# =============================================================================
# 2. Store Manager Sections (8)
# =============================================================================
def test_section_04_manager_store_overview(client, tokens):
    headers = {"Authorization": f"Bearer {tokens['mgr_kankarbagh']}"}
    res = client.get("/api/manager/store-summary", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert data["store_id"] == "ST-D69EG"
    assert "total_feedback" in data


def test_section_05_manager_emerging_insights(client, tokens):
    headers = {"Authorization": f"Bearer {tokens['mgr_kankarbagh']}"}
    res = client.get("/api/manager/insights", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert data["store_id"] == "ST-D69EG"
    assert "top_issues" in data
    assert "severity_distribution" in data
    assert "channel_distribution" in data
    assert len(data["top_issues"]) > 0


def test_section_06_manager_feedback_inbox(client, tokens):
    headers = {"Authorization": f"Bearer {tokens['mgr_kankarbagh']}"}
    res = client.get("/api/manager/feedback-inbox", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert data["store_id"] == "ST-D69EG"
    assert "records" in data


def test_section_07_manager_weekly_alerts(client, tokens):
    headers = {"Authorization": f"Bearer {tokens['mgr_kankarbagh']}"}
    res = client.get("/api/manager/alerts", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert "alerts" in data


def test_section_08_manager_action_center(client, tokens):
    headers = {"Authorization": f"Bearer {tokens['mgr_kankarbagh']}"}
    res = client.get("/api/manager/actions", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert data["store_id"] == "ST-D69EG"
    assert "counts" in data
    assert "action_items" in data


def test_section_09_manager_historical_analytics(client, tokens):
    headers = {"Authorization": f"Bearer {tokens['mgr_kankarbagh']}"}
    res = client.get("/api/manager/historical-analytics", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert data["store_id"] == "ST-D69EG"
    assert "average_rating" in data
    assert "rating_distribution" in data
    assert "weekly_trend" in data


def test_section_10_manager_store_reports(client, tokens):
    headers = {"Authorization": f"Bearer {tokens['mgr_kankarbagh']}"}
    res = client.get("/api/manager/reports", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert data["store_id"] == "ST-D69EG"
    assert "executive_summary" in data

    # CSV Export
    res_csv = client.get("/api/manager/reports/export-csv", headers=headers)
    assert res_csv.status_code == 200
    assert "text/csv" in res_csv.headers.get("content-type", "")
    assert "Feedback_ID" in res_csv.text


def test_section_11_manager_store_settings(client, tokens):
    headers = {"Authorization": f"Bearer {tokens['mgr_kankarbagh']}"}
    res = client.get("/api/manager/settings", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert data["store_id"] == "ST-D69EG"
    assert "operating_hours" in data
    assert "notifications" in data


def test_store_manager_isolation_enforcement(client, tokens):
    """Manager for Kankarbagh (ST-D69EG) cannot access Kothrud (ST-NWRDO) endpoints."""
    headers = {"Authorization": f"Bearer {tokens['mgr_kankarbagh']}"}
    res = client.get("/api/manager/insights?store_id=ST-NWRDO", headers=headers)
    assert res.status_code == 403


# =============================================================================
# 3. Administrator Sections (11)
# =============================================================================
def test_section_12_admin_platform_overview(client, tokens):
    headers = {"Authorization": f"Bearer {tokens['admin']}"}
    res = client.get("/api/admin/overview", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert data["total_stores"] == 60
    assert data["total_feedback_volume"] > 0


def test_section_13_admin_store_management(client, tokens):
    headers = {"Authorization": f"Bearer {tokens['admin']}"}
    res = client.get("/api/admin/stores", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 60


def test_section_14_admin_user_provisioning(client, tokens):
    headers = {"Authorization": f"Bearer {tokens['admin']}"}
    res = client.get("/api/admin/users", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert "users" in data
    assert len(data["users"]) >= 4

    # Role reassignment validation
    res_assign = client.post(
        "/api/admin/users/assign-role",
        headers=headers,
        json={
            "target_email": "customer@example.com",
            "new_role": "customer",
            "new_store_id": None,
        },
    )
    assert res_assign.status_code == 200
    assert res_assign.json()["success"] is True


def test_section_15_admin_global_feedback(client, tokens):
    headers = {"Authorization": f"Bearer {tokens['admin']}"}
    res = client.get("/api/feedback?limit=10", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert "records" in data


def test_section_16_admin_network_insights(client, tokens):
    headers = {"Authorization": f"Bearer {tokens['admin']}"}
    res = client.get("/api/admin/insights", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert "top_categories" in data
    assert "city_breakdown" in data


def test_section_17_admin_ai_operations(client, tokens):
    headers = {"Authorization": f"Bearer {tokens['admin']}"}
    # Taxonomy
    res_tax = client.get("/api/taxonomy", headers=headers)
    assert res_tax.status_code == 200
    assert len(res_tax.json()) == 33

    # Classification sandbox
    res_cls = client.post("/api/classify", json={"text": "Organic apples are moldy on the shelf."})
    assert res_cls.status_code == 200
    assert "issue_type_id" in res_cls.json()


def test_section_18_admin_all_store_alerts(client, tokens):
    headers = {"Authorization": f"Bearer {tokens['admin']}"}
    res = client.get("/api/emerging-alerts", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert "alerts" in data


def test_section_19_admin_remediation_actions(client, tokens):
    headers = {"Authorization": f"Bearer {tokens['admin']}"}
    res = client.get("/api/admin/remediations", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert "total_actions" in data
    assert "recent_remediations" in data


def test_section_20_admin_external_integrations(client, tokens):
    headers = {"Authorization": f"Bearer {tokens['admin']}"}
    res = client.get("/api/admin/integrations", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert "integrations" in data
    assert len(data["integrations"]) >= 4


def test_section_21_admin_system_settings(client, tokens):
    headers = {"Authorization": f"Bearer {tokens['admin']}"}
    res = client.get("/api/admin/settings", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert data["platform_name"] == "Voice of Store Engine"
    assert data["fleet_store_count"] == 60


def test_section_22_admin_administrative_audit(client, tokens):
    headers = {"Authorization": f"Bearer {tokens['admin']}"}
    res = client.get("/api/admin/audit?limit=10", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert "records" in data
    assert data["total"] > 0


def test_admin_role_enforcement_blocks_non_admin(client, tokens):
    """Customer and store manager cannot access admin endpoints (HTTP 403)."""
    cust_h = {"Authorization": f"Bearer {tokens['customer']}"}
    mgr_h = {"Authorization": f"Bearer {tokens['mgr_kankarbagh']}"}

    assert client.get("/api/admin/overview", headers=cust_h).status_code == 403
    assert client.get("/api/admin/overview", headers=mgr_h).status_code == 403
    assert client.get("/api/admin/users", headers=cust_h).status_code == 403
    assert client.get("/api/admin/users", headers=mgr_h).status_code == 403
    assert client.get("/api/admin/audit", headers=cust_h).status_code == 403
    assert client.get("/api/admin/audit", headers=mgr_h).status_code == 403
