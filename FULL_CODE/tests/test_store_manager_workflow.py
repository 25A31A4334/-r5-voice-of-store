"""Test Suite for Store Manager Operational Workflow (Team CodeNova).

Validates:
1. Manager Feedback Inbox access for assigned store.
2. Cross-store access denial (manager of Store A rejected when requesting Store B).
3. Customer denial on manager-only endpoints (403 Forbidden).
4. Valid alert status transitions (acknowledge, investigate, resolve).
5. Invalid alert action rejection (400 Bad Request) & missing resolution note rejection.
6. Cross-store alert modification denial (manager cannot resolve another store's alert).
7. Persistence across restart (status and notes retained in SQLite database).
8. Audit trail logging for every alert action.
"""
from __future__ import annotations

from datetime import timedelta
import os
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
import sys
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Ensure test mode settings
os.environ["APP_ENV"] = "test"
os.environ["TESTING"] = "true"

from FULL_CODE.config import settings
from FULL_CODE.db.connection import get_db_connection
from FULL_CODE.db.seed import seed_database
from FULL_CODE.services.auth_service import AuthService
from FULL_CODE.app import app, load_application_state


@pytest.fixture(scope="module")
def client():
    # Initialize database and in-memory state
    seed_database(force_demo=True)
    load_application_state()
    return TestClient(app)


@pytest.fixture(scope="module")
def tokens(client):
    """Generates authentic tokens for Admin, Kankarbagh Manager (ST-D69EG), Kothrud Manager (ST-NWRDO), and Customer."""
    # 1. Admin
    admin_res = client.post("/api/auth/login", json={"email": "admin@saffron.example", "password": "DemoAdmin#2026!LocalOnly"})
    assert admin_res.status_code == 200, f"Admin login failed: {admin_res.text}"
    admin_token = admin_res.json()["access_token"]

    # 2. Kankarbagh Manager (ST-D69EG)
    kankarbagh_res = client.post("/api/auth/login", json={"email": "manager.kankarbagh@saffron.example", "password": "DemoMgr#2026!Kankarbagh"})
    assert kankarbagh_res.status_code == 200, f"Kankarbagh login failed: {kankarbagh_res.text}"
    kankarbagh_token = kankarbagh_res.json()["access_token"]

    # 3. Kothrud Manager (ST-NWRDO)
    kothrud_res = client.post("/api/auth/login", json={"email": "manager.kothrud@saffron.example", "password": "DemoMgr#2026!Kothrud"})
    assert kothrud_res.status_code == 200, f"Kothrud login failed: {kothrud_res.text}"
    kothrud_token = kothrud_res.json()["access_token"]

    # 4. Customer
    cust_res = client.post("/api/auth/login", json={"email": "customer@example.com", "password": "DemoCust#2026!Aarav"})
    assert cust_res.status_code == 200, f"Customer login failed: {cust_res.text}"
    cust_token = cust_res.json()["access_token"]

    return {
        "admin": admin_token,
        "kankarbagh": kankarbagh_token,
        "kothrud": kothrud_token,
        "customer": cust_token,
    }


def test_customer_denied_manager_endpoints(client, tokens):
    """Customer role MUST be denied access to manager endpoints with HTTP 403."""
    headers = {"Authorization": f"Bearer {tokens['customer']}"}

    # Summary endpoint
    res = client.get("/api/manager/store-summary", headers=headers)
    assert res.status_code == 403, f"Expected 403 for customer, got {res.status_code}"

    # Inbox endpoint
    res = client.get("/api/manager/feedback-inbox", headers=headers)
    assert res.status_code == 403, f"Expected 403 for customer, got {res.status_code}"

    # Alerts endpoint
    res = client.get("/api/manager/alerts", headers=headers)
    assert res.status_code == 403, f"Expected 403 for customer, got {res.status_code}"

    # Alert action endpoint
    res = client.post("/api/manager/alerts/ALT-2026-05-11-ST-D69EG-IT17/action", json={"action": "acknowledge"}, headers=headers)
    assert res.status_code == 403, f"Expected 403 for customer, got {res.status_code}"


def test_unauthenticated_request_denied(client):
    """Unauthenticated requests without Bearer token must return HTTP 401 across manager endpoints."""
    # Alerts endpoint
    res = client.get("/api/manager/alerts")
    assert res.status_code == 401
    assert "credentials" in res.json().get("detail", "").lower()

    # Store summary
    res = client.get("/api/manager/store-summary")
    assert res.status_code == 401

    # Feedback inbox
    res = client.get("/api/manager/feedback-inbox")
    assert res.status_code == 401

    # Alert history
    res = client.get("/api/manager/alerts/ALT-2026-05-11-ST-D69EG-IT17/history")
    assert res.status_code == 401

    # Alert action
    res = client.post("/api/manager/alerts/ALT-2026-05-11-ST-D69EG-IT17/action", json={"action": "acknowledge"})
    assert res.status_code == 401


def test_invalid_and_malformed_tokens_denied(client):
    """Requests with malformed tokens or invalid headers must return HTTP 401."""
    # Malformed token string
    res = client.get("/api/manager/alerts", headers={"Authorization": "Bearer not-a-valid-jwt-token-string"})
    assert res.status_code == 401

    # Missing Bearer prefix
    res = client.get("/api/manager/alerts", headers={"Authorization": "Basic dXNlcjpwYXNz"})
    assert res.status_code == 401

    # Empty Bearer
    res = client.get("/api/manager/alerts", headers={"Authorization": "Bearer "})
    assert res.status_code == 401


def test_expired_token_request_denied(client):
    """Requests with expired JWT tokens must return HTTP 401."""
    expired_token = AuthService.create_access_token(
        {"sub": "1", "email": "manager.kankarbagh@saffron.example", "role": "store_manager", "store_id": "ST-D69EG"},
        expires_delta=timedelta(seconds=-60),
    )
    res = client.get("/api/manager/alerts", headers={"Authorization": f"Bearer {expired_token}"})
    assert res.status_code == 401
    assert "expired" in res.json().get("detail", "").lower() or "credentials" in res.json().get("detail", "").lower()


def test_store_manager_summary_and_inbox_for_assigned_store(client, tokens):
    """Kankarbagh manager (ST-D69EG) accesses store summary and inbox for their store."""
    headers = {"Authorization": f"Bearer {tokens['kankarbagh']}"}

    # Summary
    res = client.get("/api/manager/store-summary", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert data["store_id"] == "ST-D69EG"
    assert "Kankarbagh" in data["store_name"]
    assert data["total_feedback"] > 0
    assert "alerts_summary" in data

    # Inbox
    res = client.get("/api/manager/feedback-inbox?limit=10", headers=headers)
    assert res.status_code == 200
    inbox = res.json()
    assert inbox["store_id"] == "ST-D69EG"
    assert len(inbox["records"]) > 0
    # Every record must be for ST-D69EG
    for r in inbox["records"]:
        assert r["store_id"] == "ST-D69EG"
        assert "feedback_id" in r
        assert "severity" in r
        assert "issue_type_id" in r


def test_cross_store_access_denial(client, tokens):
    """Store manager of ST-D69EG attempting to access ST-NWRDO must be rejected with HTTP 403."""
    headers = {"Authorization": f"Bearer {tokens['kankarbagh']}"}

    # Attempt to request Kothrud store summary
    res = client.get("/api/manager/store-summary?store_id=ST-NWRDO", headers=headers)
    assert res.status_code == 403
    assert "You are only authorized to manage store 'ST-D69EG'" in res.json()["detail"]

    # Attempt to request Kothrud feedback inbox
    res = client.get("/api/manager/feedback-inbox?store_id=ST-NWRDO", headers=headers)
    assert res.status_code == 403


def test_manager_alerts_retrieval(client, tokens):
    """Store manager of ST-D69EG retrieves their own alerts with evidence quotes, severity, and week."""
    headers = {"Authorization": f"Bearer {tokens['kankarbagh']}"}

    res = client.get("/api/manager/alerts", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert data["store_id"] == "ST-D69EG"
    assert data["total_alerts"] >= 2

    # Check alert structure and alignment with frontend expectations
    alert = next(a for a in data["alerts"] if a["alert_id"] == "ALT-2026-05-11-ST-D69EG-IT17")
    assert alert["store_id"] == "ST-D69EG"
    assert "alert_id" in alert
    assert "severity" in alert
    assert alert["severity"] in ["low", "medium", "high", "critical"]
    assert "severity_floor" in alert
    assert "week" in alert
    assert "as_of_week_start" in alert
    assert alert["week"] == alert["as_of_week_start"]
    assert "issue_type_name" in alert
    assert "issue_name" in alert
    assert "current_count" in alert
    assert "baseline_count" in alert
    assert "ratio" in alert
    assert "evidence_samples" in alert
    assert len(alert["evidence_samples"]) > 0


def test_manager_alerts_missing_optional_fields_resilience(client, tokens):
    """Regression test: Alerts with missing/null optional fields do not crash API or frontend rendering."""
    # Insert an alert with minimal/missing optional fields into SQLite
    minimal_alert_id = "ALT-MINIMAL-TEST-ST-D69EG"
    try:
        with get_db_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO incident_alerts (
                    alert_id, store_id, issue_type_id, as_of_week_start,
                    confidence, evidence_feedback_ids, status, resolution_notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (minimal_alert_id, "ST-D69EG", "IT01", "2026-06-01", 0.5, "", "new", None),
            )

        headers = {"Authorization": f"Bearer {tokens['kankarbagh']}"}
        res = client.get("/api/manager/alerts", headers=headers)
        assert res.status_code == 200
        alerts = res.json()["alerts"]

        minimal_alert = next((a for a in alerts if a["alert_id"] == minimal_alert_id), None)
        assert minimal_alert is not None, "Minimal alert must be returned in alerts list"

        # Verify safe fallbacks in backend API response
        assert "severity" in minimal_alert and isinstance(minimal_alert["severity"], str)
        assert minimal_alert["severity"] in ["low", "medium", "high", "critical"]
        assert "week" in minimal_alert and minimal_alert["week"] == "2026-06-01"
        assert "issue_type_name" in minimal_alert and minimal_alert["issue_type_name"] != ""
        assert isinstance(minimal_alert["evidence_samples"], list)
        assert len(minimal_alert["evidence_samples"]) == 0
        assert minimal_alert["status"] == "new"

        # Verify simulate frontend field access: .toUpperCase() on severity and status
        assert minimal_alert["severity"].upper() in ["LOW", "MEDIUM", "HIGH", "CRITICAL"]
        assert minimal_alert["status"].upper() == "NEW"

        # Verify normal operational workflow still functions on the alert
        res_ack = client.post(f"/api/manager/alerts/{minimal_alert_id}/action", json={"action": "acknowledge"}, headers=headers)
        assert res_ack.status_code == 200
        assert res_ack.json()["status"] == "acknowledged"

        res_res = client.post(f"/api/manager/alerts/{minimal_alert_id}/action", json={"action": "resolve", "note": "Resolved billing queue by adding 2 new POS systems."}, headers=headers)
        assert res_res.status_code == 200
        assert res_res.json()["status"] == "resolved"
    finally:
        with get_db_connection() as conn:
            conn.execute("DELETE FROM incident_alerts WHERE alert_id = ?;", (minimal_alert_id,))
            conn.execute("DELETE FROM audit_log WHERE target_id = ?;", (minimal_alert_id,))


def test_manager_alerts_supabase_row_compatibility(client):
    """Regression test: Alerts fetched from Supabase (which lack acknowledged_by_user_id) serialize without KeyError."""
    from unittest.mock import patch
    from FULL_CODE.services.supabase_service import SupabaseService
    from FULL_CODE.app import get_current_user

    fake_supa_user = {
        "id": "c1f10c12-3456-7890-abcd-ef0123456789",
        "email": "manager.kankarbagh@saffron.example",
        "role": "store_manager",
        "assigned_store_id": "ST-D69EG",
        "token": "fake_supabase_jwt_token",
        "provider": "supabase",
    }
    supa_rows = [
        {
            "id": "e3b0c442-98fc-1c14-9afbf4c8996fb924",
            "alert_id": "ALT-2026-05-18-ST-D69EG-IT17",
            "store_id": "ST-D69EG",
            "issue_type_id": "IT17",
            "as_of_week_start": "2026-05-18",
            "confidence": 0.95,
            "evidence_feedback_ids": "FB-001;FB-002",
            "status": "new",
            "resolved_by_user_id": None,
            "resolution_note": None,
            "created_at": "2026-05-18T00:00:00Z",
            "updated_at": "2026-05-18T00:00:00Z",
        }
    ]

    app.dependency_overrides[get_current_user] = lambda: fake_supa_user
    try:
        with patch.object(SupabaseService, "get_alerts", return_value=supa_rows):
            res = client.get("/api/manager/alerts?store_id=ST-D69EG", headers={"Authorization": "Bearer fake_supabase_jwt_token"})
            assert res.status_code == 200
            data = res.json()
            assert len(data["alerts"]) == 1
            alert = data["alerts"][0]
            assert alert["alert_id"] == "ALT-2026-05-18-ST-D69EG-IT17"
            assert alert["status"] == "new"
            assert alert["acknowledged_by_user_id"] is None
    finally:
        app.dependency_overrides.clear()



def test_alert_status_workflow_transitions_and_audit(client, tokens):
    """Test full operational lifecycle: acknowledge -> investigate -> resolve, with audit trail."""
    headers = {"Authorization": f"Bearer {tokens['kankarbagh']}"}
    alert_id = "ALT-2026-05-11-ST-D69EG-IT17"

    # Reset alert to pristine 'new' state and clear prior test logs for determinism
    with get_db_connection() as conn:
        conn.execute("UPDATE incident_alerts SET status = 'new', resolution_notes = NULL, acknowledged_by_user_id = NULL WHERE alert_id = ?;", (alert_id,))
        conn.execute("DELETE FROM audit_log WHERE target_id = ?;", (alert_id,))

    # 1. Acknowledge Alert
    res = client.post(f"/api/manager/alerts/{alert_id}/action", json={"action": "acknowledge"}, headers=headers)
    assert res.status_code == 200
    ack_data = res.json()
    assert ack_data["status"] == "acknowledged"

    # 2. Mark Investigating
    res = client.post(f"/api/manager/alerts/{alert_id}/action", json={"action": "investigate", "note": "Checked dairy stock with vendor."}, headers=headers)
    assert res.status_code == 200
    inv_data = res.json()
    assert inv_data["status"] == "investigating"

    # 3. Resolve without note -> MUST FAIL with HTTP 400
    res = client.post(f"/api/manager/alerts/{alert_id}/action", json={"action": "resolve", "note": ""}, headers=headers)
    assert res.status_code == 400
    assert "Resolution note is required" in res.json()["detail"]

    # 4. Resolve with valid note -> MUST SUCCEED
    resolution_note = "All contaminated batch SKUs recalled and supplier credit note issued."
    res = client.post(f"/api/manager/alerts/{alert_id}/action", json={"action": "resolve", "note": resolution_note}, headers=headers)
    assert res.status_code == 200
    res_data = res.json()
    assert res_data["status"] == "resolved"
    assert res_data["resolution_notes"] == resolution_note

    # 5. Check Audit History for this alert
    res = client.get(f"/api/manager/alerts/{alert_id}/history", headers=headers)
    assert res.status_code == 200
    history = res.json()
    assert history["current_status"] == "resolved"
    assert history["store_id"] == "ST-D69EG"
    actions = [h["action"] for h in history["history"]]
    assert "ALERT_RESOLVE" in actions
    assert "ALERT_INVESTIGATE" in actions
    assert "ALERT_ACKNOWLEDGE" in actions

    # Verify structured audit metadata for timeline rendering
    resolve_event = next(h for h in history["history"] if h["action"] == "ALERT_RESOLVE")
    assert resolve_event["old_status"] == "investigating"
    assert resolve_event["new_status"] == "resolved"
    assert resolve_event["resolution_note"] == resolution_note
    assert resolve_event["store_id"] == "ST-D69EG"
    assert "actor_email" in resolve_event and resolve_event["actor_email"]
    assert resolve_event["actor_role"] in ["store_manager", "admin"]

    ack_event = next(h for h in history["history"] if h["action"] == "ALERT_ACKNOWLEDGE")
    assert ack_event["old_status"] == "new"
    assert ack_event["new_status"] == "acknowledged"
    assert not ack_event["resolution_note"]  # Must be empty or None


def test_audit_history_enterprise_timeline_representation(client, tokens):
    """Verifies that audit events contain all fields required for enterprise SaaS timeline rendering."""
    headers = {"Authorization": f"Bearer {tokens['kankarbagh']}"}
    alert_id = "ALT-2026-05-11-ST-D69EG-IT17"

    res = client.get(f"/api/manager/alerts/{alert_id}/history", headers=headers)
    assert res.status_code == 200
    data = res.json()

    # Required top-level references
    assert "alert_id" in data and data["alert_id"] == alert_id
    assert "store_id" in data and data["store_id"] == "ST-D69EG"
    assert "current_status" in data and data["current_status"] == "resolved"
    assert "history" in data and len(data["history"]) >= 3

    # Check each event in the history timeline
    for event in data["history"]:
        assert "action" in event
        assert "created_at" in event
        assert "actor_email" in event
        assert "actor_role" in event
        assert "store_id" in event
        # Confirm complete audit record is preserved in storage
        assert "details" in event and isinstance(event["details"], str)

    # Verify transitions present
    transitions = [(h["old_status"], h["new_status"]) for h in data["history"] if h.get("old_status") and h.get("new_status")]
    assert ("new", "acknowledged") in transitions
    assert ("acknowledged", "investigating") in transitions
    assert ("investigating", "resolved") in transitions


def test_cross_store_alert_action_denial(client, tokens):
    """Manager of Kothrud (ST-NWRDO) attempting to modify Kankarbagh (ST-D69EG) alert must be rejected with 403."""
    kothrud_headers = {"Authorization": f"Bearer {tokens['kothrud']}"}
    kankarbagh_alert_id = "ALT-2026-05-11-ST-D69EG-IT17"

    res = client.post(
        f"/api/manager/alerts/{kankarbagh_alert_id}/action",
        json={"action": "acknowledge"},
        headers=kothrud_headers,
    )
    assert res.status_code == 403
    assert "Forbidden: You are only authorized to manage alerts for store 'ST-NWRDO'" in res.json()["detail"]

    # History access cross-store must also be denied
    res = client.get(f"/api/manager/alerts/{kankarbagh_alert_id}/history", headers=kothrud_headers)
    assert res.status_code == 403


def test_invalid_action_rejected(client, tokens):
    """Invalid actions like 'delete', 'archive', 'bypass' must return HTTP 400."""
    headers = {"Authorization": f"Bearer {tokens['kankarbagh']}"}
    alert_id = "ALT-2026-05-11-ST-D69EG-IT17"

    res = client.post(f"/api/manager/alerts/{alert_id}/action", json={"action": "invalid_action"}, headers=headers)
    assert res.status_code == 400
    assert "Invalid action" in res.json()["detail"]


def test_persistence_across_app_reload(client, tokens):
    """Verify that resolution notes and status persist in SQLite even after reload_application_state."""
    alert_id = "ALT-2026-05-11-ST-D69EG-IT17"

    # Simulate application restart / reload
    load_application_state()

    headers = {"Authorization": f"Bearer {tokens['kankarbagh']}"}
    res = client.get("/api/manager/alerts", headers=headers)
    assert res.status_code == 200
    alerts = res.json()["alerts"]

    resolved_alert = next((a for a in alerts if a["alert_id"] == alert_id), None)
    assert resolved_alert is not None
    assert resolved_alert["status"] == "resolved"
    assert "recalled" in (resolved_alert["resolution_notes"] or "")


def test_all_three_demo_logins_and_protected_access(client):
    """Verifies that all three documented demo logins succeed via /api/auth/login and can access protected endpoints."""
    # 1. Kankarbagh Store Manager
    res_kankarbagh = client.post(
        "/api/auth/login",
        json={"email": "manager.kankarbagh@saffron.example", "password": "DemoMgr#2026!Kankarbagh"},
    )
    assert res_kankarbagh.status_code == 200, f"Kankarbagh login failed: {res_kankarbagh.text}"
    kb_data = res_kankarbagh.json()
    assert kb_data["user"]["role"] == "store_manager"
    assert kb_data["user"]["assigned_store_id"] == "ST-D69EG"
    kb_token = kb_data["access_token"]

    # Verify protected access
    me_kb = client.get("/api/auth/me", headers={"Authorization": f"Bearer {kb_token}"})
    assert me_kb.status_code == 200
    assert me_kb.json()["email"] == "manager.kankarbagh@saffron.example"

    sum_kb = client.get("/api/manager/store-summary", headers={"Authorization": f"Bearer {kb_token}"})
    assert sum_kb.status_code == 200
    assert sum_kb.json()["store_id"] == "ST-D69EG"

    # Verify cross-store restriction
    cross_kb = client.get("/api/manager/store-summary?store_id=ST-NWRDO", headers={"Authorization": f"Bearer {kb_token}"})
    assert cross_kb.status_code == 403

    # 2. Kothrud Store Manager
    res_kothrud = client.post(
        "/api/auth/login",
        json={"email": "manager.kothrud@saffron.example", "password": "DemoMgr#2026!Kothrud"},
    )
    assert res_kothrud.status_code == 200, f"Kothrud login failed: {res_kothrud.text}"
    kt_data = res_kothrud.json()
    assert kt_data["user"]["role"] == "store_manager"
    assert kt_data["user"]["assigned_store_id"] == "ST-NWRDO"
    kt_token = kt_data["access_token"]

    sum_kt = client.get("/api/manager/store-summary", headers={"Authorization": f"Bearer {kt_token}"})
    assert sum_kt.status_code == 200
    assert sum_kt.json()["store_id"] == "ST-NWRDO"

    # Verify cross-store restriction
    cross_kt = client.get("/api/manager/store-summary?store_id=ST-D69EG", headers={"Authorization": f"Bearer {kt_token}"})
    assert cross_kt.status_code == 403

    # 3. HQ Admin
    res_admin = client.post(
        "/api/auth/login",
        json={"email": "admin@saffron.example", "password": "DemoAdmin#2026!LocalOnly"},
    )
    assert res_admin.status_code == 200, f"Admin login failed: {res_admin.text}"
    admin_data = res_admin.json()
    assert admin_data["user"]["role"] == "admin"
    admin_token = admin_data["access_token"]

    # Verify admin can inspect any store
    sum_adm_kb = client.get("/api/manager/store-summary?store_id=ST-D69EG", headers={"Authorization": f"Bearer {admin_token}"})
    assert sum_adm_kb.status_code == 200
    assert sum_adm_kb.json()["store_id"] == "ST-D69EG"

    sum_adm_kt = client.get("/api/manager/store-summary?store_id=ST-NWRDO", headers={"Authorization": f"Bearer {admin_token}"})
    assert sum_adm_kt.status_code == 200
    assert sum_adm_kt.json()["store_id"] == "ST-NWRDO"


def test_manager_settings_persistence_and_update(client, tokens):
    """Test that store settings can be updated and are persisted across reads."""
    kb_headers = {"Authorization": f"Bearer {tokens['kankarbagh']}"}

    update_payload = {
        "store_id": "ST-D69EG",
        "operating_hours": "06:30 AM - 11:30 PM IST (Daily)",
        "monitoring_tier": "Tier-2 Escalation Only",
        "notifications": {
            "email_on_critical_alert": False,
            "daily_summary_brief": True,
            "instant_actionable_notification": True,
        },
    }

    res = client.post("/api/manager/settings", json=update_payload, headers=kb_headers)
    assert res.status_code == 200, f"Settings update failed: {res.text}"
    data = res.json()
    assert data["success"] is True
    assert data["operating_hours"] == "06:30 AM - 11:30 PM IST (Daily)"
    assert data["monitoring_tier"] == "Tier-2 Escalation Only"
    assert data["notifications"]["email_on_critical_alert"] is False

    # Read back settings
    get_res = client.get("/api/manager/settings", headers=kb_headers)
    assert get_res.status_code == 200
    get_data = get_res.json()
    assert get_data["operating_hours"] == "06:30 AM - 11:30 PM IST (Daily)"
    assert get_data["monitoring_tier"] == "Tier-2 Escalation Only"
    assert get_data["notifications"]["email_on_critical_alert"] is False
    assert get_data["updated_at"] is not None


def test_manager_settings_cross_store_denial(client, tokens):
    """Store manager cannot modify settings of another store."""
    kt_headers = {"Authorization": f"Bearer {tokens['kothrud']}"}

    cross_payload = {
        "store_id": "ST-D69EG",
        "operating_hours": "08:00 AM - 10:00 PM IST",
        "monitoring_tier": "Tier-1 Autonomous Triage",
    }
    res = client.post("/api/manager/settings", json=cross_payload, headers=kt_headers)
    assert res.status_code == 403, f"Cross-store settings update should be 403, got {res.status_code}"


def test_customer_denied_manager_settings_update(client, tokens):
    """Customer role is denied from updating store settings."""
    cust_headers = {"Authorization": f"Bearer {tokens['customer']}"}
    payload = {"operating_hours": "10:00 AM - 09:00 PM IST"}
    res = client.post("/api/manager/settings", json=payload, headers=cust_headers)
    assert res.status_code == 403, f"Customer should be 403, got {res.status_code}"


def test_manager_settings_validation(client, tokens):
    """Invalid operating hours (too short) must return 400 Bad Request."""
    kb_headers = {"Authorization": f"Bearer {tokens['kankarbagh']}"}
    invalid_payload = {"operating_hours": "ab"}
    res = client.post("/api/manager/settings", json=invalid_payload, headers=kb_headers)
    assert res.status_code == 400, f"Expected 400 for short hours, got {res.status_code}"

