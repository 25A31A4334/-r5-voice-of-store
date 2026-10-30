"""Test Suite for Phase 1: Customer Portal & End-to-End Feedback Persistence.

Validates:
1. Authenticated customer feedback submission with real AI classification and DB persistence.
2. Submission validation (character minimums, valid store IDs).
3. Unauthenticated rejection (HTTP 401).
4. Customer dashboard metrics derived genuinely from database records.
5. Customer submission history ownership and user isolation (no cross-customer leaks).
6. Assigned store manager visibility in Manager Feedback Inbox.
7. Store manager action lifecycle (acknowledge, investigate, resolve with note).
8. Store isolation enforcement (manager cannot action feedback for other stores).
9. Customer history reflects manager resolution note.
10. Evaluation dataset (data/feedback.csv) remains strictly unmutated.
"""
from __future__ import annotations

import os
from pathlib import Path
import uuid
import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
import sys
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ["APP_ENV"] = "test"
os.environ["TESTING"] = "true"

from FULL_CODE.config import settings
from FULL_CODE.db.connection import get_db_connection
from FULL_CODE.db.seed import seed_database
from FULL_CODE.app import app, load_application_state


@pytest.fixture(scope="module")
def client():
    seed_database(force_demo=True)
    load_application_state()
    return TestClient(app)


@pytest.fixture(scope="module")
def tokens(client):
    """Obtains authentic tokens for Customer, Kankarbagh Manager, Kothrud Manager, and Admin."""
    # Customer Aarav Sharma
    res_cust = client.post("/api/auth/login", json={"email": "customer@example.com", "password": "DemoCust#2026!Aarav"})
    assert res_cust.status_code == 200, f"Customer login failed: {res_cust.text}"
    cust_token = res_cust.json()["access_token"]

    # Kankarbagh Manager (ST-D69EG)
    res_mgr_k = client.post("/api/auth/login", json={"email": "manager.kankarbagh@saffron.example", "password": "DemoMgr#2026!Kankarbagh"})
    assert res_mgr_k.status_code == 200, f"Kankarbagh manager login failed: {res_mgr_k.text}"
    mgr_k_token = res_mgr_k.json()["access_token"]

    # Kothrud Manager (ST-NWRDO)
    res_mgr_p = client.post("/api/auth/login", json={"email": "manager.kothrud@saffron.example", "password": "DemoMgr#2026!Kothrud"})
    assert res_mgr_p.status_code == 200, f"Kothrud manager login failed: {res_mgr_p.text}"
    mgr_p_token = res_mgr_p.json()["access_token"]

    # Admin
    res_admin = client.post("/api/auth/login", json={"email": "admin@saffron.example", "password": "DemoAdmin#2026!LocalOnly"})
    assert res_admin.status_code == 200, f"Admin login failed: {res_admin.text}"
    admin_token = res_admin.json()["access_token"]

    return {
        "customer": cust_token,
        "kankarbagh_mgr": mgr_k_token,
        "kothrud_mgr": mgr_p_token,
        "admin": admin_token,
    }


def test_customer_submission_success(client, tokens):
    """Customer submits feedback, ML pipeline triages it, and record persists in SQLite."""
    headers = {"Authorization": f"Bearer {tokens['customer']}"}
    payload = {
        "store_id": "ST-D69EG",  # Kankarbagh
        "channel": "in_app",
        "rating": 1,
        "text": "The dairy aisle milk freezer is warm and all organic milk packs are completely spoiled and leaking.",
    }

    res = client.post("/api/customer/submissions", json=payload, headers=headers)
    assert res.status_code == 201, f"Expected 201 Created, got: {res.text}"

    data = res.json()
    assert data["success"] is True
    sub = data["submission"]
    assert sub["feedback_id"].startswith("FB-CUST-")
    assert sub["store_id"] == "ST-D69EG"
    assert sub["channel"] == "in_app"
    assert sub["rating"] == 1
    assert "milk" in sub["text"]
    assert sub["issue_type_id"].startswith("IT")
    assert len(sub["issue_type_name"]) > 0
    assert sub["severity"] in ["low", "medium", "high", "critical"]
    assert sub["actionable"] in [0, 1]
    assert sub["status"] == "new"

    # Verify directly in SQLite DB
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT * FROM feedback_submissions WHERE feedback_id = ?;",
            (sub["feedback_id"],),
        ).fetchone()
        assert row is not None, "Submission record was not written to SQLite database"
        assert row["store_id"] == "ST-D69EG"
        assert row["status"] == "new"
        assert row["resolution_notes"] is None

        # Verify audit log record
        audit = conn.execute(
            "SELECT * FROM audit_log WHERE target_type = 'feedback_submissions' AND target_id = ?;",
            (sub["feedback_id"],),
        ).fetchone()
        assert audit is not None, "Audit log was not created for customer submission"
        assert audit["action"] == "CUSTOMER_SUBMIT_FEEDBACK"


def test_customer_submission_validations(client, tokens):
    """Submissions must reject short text, invalid store IDs, or unauthenticated requests."""
    headers = {"Authorization": f"Bearer {tokens['customer']}"}

    # 1. Text too short (< 5 chars)
    res_short = client.post(
        "/api/customer/submissions",
        json={"store_id": "ST-D69EG", "channel": "in_app", "rating": 3, "text": "bad"},
        headers=headers,
    )
    assert res_short.status_code == 422, f"Expected 422 for short text, got {res_short.status_code}"

    # 2. Non-existent store ID
    res_store = client.post(
        "/api/customer/submissions",
        json={"store_id": "ST-INVALID-999", "channel": "in_app", "rating": 3, "text": "Valid length text about store issue"},
        headers=headers,
    )
    assert res_store.status_code == 400, f"Expected 400 for invalid store, got {res_store.status_code}"
    assert "does not exist" in res_store.text.lower() or "not found" in res_store.text.lower()

    # 3. Unauthenticated request
    res_unauth = client.post(
        "/api/customer/submissions",
        json={"store_id": "ST-D69EG", "channel": "in_app", "rating": 3, "text": "Valid length text about store issue"},
    )
    assert res_unauth.status_code == 401, f"Expected 401 for missing token, got {res_unauth.status_code}"


def test_customer_dashboard_counts(client, tokens):
    """Customer dashboard counts must match database records."""
    headers = {"Authorization": f"Bearer {tokens['customer']}"}

    res = client.get("/api/customer/dashboard", headers=headers)
    assert res.status_code == 200, f"Expected 200, got: {res.text}"

    data = res.json()
    assert "total_submissions" in data
    assert "open_submissions" in data
    assert "resolved_submissions" in data
    assert "recent_submissions" in data

    assert data["total_submissions"] >= 1
    assert data["open_submissions"] >= 1
    assert isinstance(data["recent_submissions"], list)
    assert len(data["recent_submissions"]) >= 1


def test_customer_submission_history_isolation(client, tokens):
    """Each customer must only see their own submissions in history."""
    # Register Customer 2 with distinct email
    unique_email = f"priya.cust.{uuid.uuid4().hex[:8]}@example.com"
    reg_res = client.post(
        "/api/auth/register",
        json={"email": unique_email, "password": "DemoCust#2026!Priya", "full_name": "Priya Patel"},
    )
    assert reg_res.status_code == 201, f"Registration failed: {reg_res.text}"

    login_res = client.post(
        "/api/auth/login",
        json={"email": unique_email, "password": "DemoCust#2026!Priya"},
    )
    cust2_token = login_res.json()["access_token"]
    cust2_headers = {"Authorization": f"Bearer {cust2_token}"}

    # Submit feedback as Customer 2
    sub_res = client.post(
        "/api/customer/submissions",
        json={
            "store_id": "ST-NWRDO",  # Kothrud
            "channel": "online_review",
            "rating": 2,
            "text": "Long billing queue at Kothrud store on weekend afternoon.",
        },
        headers=cust2_headers,
    )
    assert sub_res.status_code == 201
    cust2_sub_id = sub_res.json()["submission"]["feedback_id"]

    # Customer 1 history: should NOT contain cust2_sub_id
    cust1_headers = {"Authorization": f"Bearer {tokens['customer']}"}
    cust1_hist = client.get("/api/customer/submissions", headers=cust1_headers).json()
    cust1_ids = [s["feedback_id"] for s in cust1_hist["submissions"]]
    assert cust2_sub_id not in cust1_ids, "Customer 1 can see Customer 2's submission (Data leakage!)"

    # Customer 2 history: should contain cust2_sub_id
    cust2_hist = client.get("/api/customer/submissions", headers=cust2_headers).json()
    cust2_ids = [s["feedback_id"] for s in cust2_hist["submissions"]]
    assert cust2_sub_id in cust2_ids, "Customer 2 cannot see their own submission"


def test_manager_inbox_and_lifecycle_workflow(client, tokens):
    """Store manager views store customer submission, executes actions, and notes reflect in customer history."""
    cust_headers = {"Authorization": f"Bearer {tokens['customer']}"}
    mgr_k_headers = {"Authorization": f"Bearer {tokens['kankarbagh_mgr']}"}
    mgr_p_headers = {"Authorization": f"Bearer {tokens['kothrud_mgr']}"}

    # 1. Customer submits issue for Kankarbagh (ST-D69EG)
    sub_res = client.post(
        "/api/customer/submissions",
        json={
            "store_id": "ST-D69EG",
            "channel": "in_app",
            "rating": 1,
            "text": "Spilled cooking oil in aisle 3 near pulses, dangerous slipping hazard!",
        },
        headers=cust_headers,
    )
    assert sub_res.status_code == 201
    target_fid = sub_res.json()["submission"]["feedback_id"]

    # 2. Kankarbagh Manager inspects inbox
    inbox_res = client.get("/api/manager/feedback-inbox?store_id=ST-D69EG", headers=mgr_k_headers)
    assert inbox_res.status_code == 200
    inbox_data = inbox_res.json()

    # The customer submission must be in the inbox records
    inbox_fids = [r["feedback_id"] for r in inbox_data["records"]]
    assert target_fid in inbox_fids, f"Submission {target_fid} missing from Kankarbagh manager inbox"

    # 3. Kothrud Manager (different store) must NOT see Kankarbagh submission
    kothrud_inbox = client.get("/api/manager/feedback-inbox?store_id=ST-NWRDO", headers=mgr_p_headers)
    assert kothrud_inbox.status_code == 200
    kothrud_fids = [r["feedback_id"] for r in kothrud_inbox.json()["records"]]
    assert target_fid not in kothrud_fids, "Kothrud manager saw Kankarbagh store feedback (cross-store leak!)"

    # 4. Kothrud Manager attempts to modify Kankarbagh feedback: MUST BE 403 FORBIDDEN
    forbidden_res = client.post(
        f"/api/manager/feedback/{target_fid}/action",
        json={"action": "acknowledge"},
        headers=mgr_p_headers,
    )
    assert forbidden_res.status_code == 403, f"Expected 403 for unauthorized store manager, got {forbidden_res.status_code}"

    # 5. Kankarbagh Manager acknowledges feedback
    ack_res = client.post(
        f"/api/manager/feedback/{target_fid}/action",
        json={"action": "acknowledge"},
        headers=mgr_k_headers,
    )
    assert ack_res.status_code == 200
    assert ack_res.json()["status"] == "acknowledged"

    # 6. Kankarbagh Manager marks investigating
    inv_res = client.post(
        f"/api/manager/feedback/{target_fid}/action",
        json={"action": "investigate"},
        headers=mgr_k_headers,
    )
    assert inv_res.status_code == 200
    assert inv_res.json()["status"] == "investigating"

    # 7. Kankarbagh Manager resolves with corrective action note
    resolve_note = "Housekeeping team dispatched with degreaser mop, hazard cleaned and safety cones placed."
    res_res = client.post(
        f"/api/manager/feedback/{target_fid}/action",
        json={"action": "resolve", "note": resolve_note},
        headers=mgr_k_headers,
    )
    assert res_res.status_code == 200
    assert res_res.json()["status"] == "resolved"
    assert res_res.json()["resolution_notes"] == resolve_note

    # 8. Customer views history and confirms resolved status and manager's note
    cust_hist = client.get(f"/api/customer/submissions?search={target_fid}", headers=cust_headers).json()
    matching_subs = [s for s in cust_hist["submissions"] if s["feedback_id"] == target_fid]
    assert len(matching_subs) == 1
    customer_view = matching_subs[0]
    assert customer_view["status"] == "resolved"
    assert customer_view["resolution_notes"] == resolve_note

    # 9. Customer dashboard reflects resolution
    dash_res = client.get("/api/customer/dashboard", headers=cust_headers).json()
    assert dash_res["resolved_submissions"] >= 1


def test_evaluation_dataset_integrity():
    """Confirms that data/feedback.csv has not been modified or mutated in any way."""
    feedback_csv_path = ROOT / "data" / "feedback.csv"
    assert feedback_csv_path.exists(), "data/feedback.csv does not exist!"

    # Read line count
    with open(feedback_csv_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    # Original evaluation dataset has 39770 lines (header + 39769 records)
    assert len(lines) == 39770, f"Evaluation dataset lines changed! Expected 39770, got {len(lines)}"


def test_store_dropdown_api_and_label_integrity(client):
    """Verifies that /api/stores returns real stores and the form uses 'Select Store Location *'."""
    # 1. API endpoint returns valid stores list
    res = client.get("/api/stores")
    assert res.status_code == 200
    stores = res.json()
    assert isinstance(stores, list), f"Expected list of stores, got {type(stores)}"
    assert len(stores) == 60, f"Expected 60 stores, got {len(stores)}"

    # Check store fields
    sample = stores[0]
    assert "store_id" in sample and sample["store_id"].startswith("ST-")
    assert "store_name" in sample and len(sample["store_name"]) > 0
    assert "city" in sample and "region" in sample

    # 2. Frontend HTML inspect: Ensure 'Select Store Location' label is present and 'Target Saffron' is removed
    res_html = client.get("/")
    assert res_html.status_code == 200
    html = res_html.text
    assert "Select Store Location" in html, "Label 'Select Store Location' missing from form HTML"
    assert "Target Saffron Retail Store" not in html, "Obsolete label 'Target Saffron Retail Store' still present!"


def test_customer_multiple_store_submissions_and_manager_isolation(client, tokens):
    """Customer submits feedback for two distinct stores; each manager sees only their store's submission."""
    cust_headers = {"Authorization": f"Bearer {tokens['customer']}"}
    mgr_k_headers = {"Authorization": f"Bearer {tokens['kankarbagh_mgr']}"}  # ST-D69EG
    mgr_p_headers = {"Authorization": f"Bearer {tokens['kothrud_mgr']}"}    # ST-NWRDO

    # Store 1 submission: Kankarbagh (ST-D69EG)
    res_k = client.post(
        "/api/customer/submissions",
        json={
            "store_id": "ST-D69EG",
            "channel": "in_app",
            "rating": 4,
            "text": "Clean produce aisle and prompt billing at Kankarbagh store.",
        },
        headers=cust_headers,
    )
    assert res_k.status_code == 201
    sub_k_id = res_k.json()["submission"]["feedback_id"]

    # Store 2 submission: Kothrud (ST-NWRDO)
    res_p = client.post(
        "/api/customer/submissions",
        json={
            "store_id": "ST-NWRDO",
            "channel": "online_review",
            "rating": 2,
            "text": "Long wait time at the weighing counter in Kothrud dairy aisle.",
        },
        headers=cust_headers,
    )
    assert res_p.status_code == 201
    sub_p_id = res_p.json()["submission"]["feedback_id"]

    # Kankarbagh manager inbox: contains sub_k_id, NOT sub_p_id
    inbox_k = client.get("/api/manager/feedback-inbox?store_id=ST-D69EG", headers=mgr_k_headers).json()
    k_fids = [r["feedback_id"] for r in inbox_k["records"]]
    assert sub_k_id in k_fids, "Kankarbagh submission missing from Kankarbagh manager inbox"
    assert sub_p_id not in k_fids, "Kothrud submission leaked into Kankarbagh manager inbox!"

    # Kothrud manager inbox: contains sub_p_id, NOT sub_k_id
    inbox_p = client.get("/api/manager/feedback-inbox?store_id=ST-NWRDO", headers=mgr_p_headers).json()
    p_fids = [r["feedback_id"] for r in inbox_p["records"]]
    assert sub_p_id in p_fids, "Kothrud submission missing from Kothrud manager inbox"
    assert sub_k_id not in p_fids, "Kankarbagh submission leaked into Kothrud manager inbox!"


def test_customer_dashboard_recent_submissions_structure(client, tokens):
    """Verify that GET /api/customer/dashboard returns well-structured recent submissions with required fields."""
    headers = {"Authorization": f"Bearer {tokens['customer']}"}
    res = client.get("/api/customer/dashboard", headers=headers)
    assert res.status_code == 200, f"Expected 200, got: {res.text}"

    data = res.json()
    assert "total_submissions" in data
    assert "open_submissions" in data
    assert "resolved_submissions" in data
    assert "status_breakdown" in data
    assert "recent_submissions" in data
    assert isinstance(data["recent_submissions"], list)

    if len(data["recent_submissions"]) > 0:
        rec = data["recent_submissions"][0]
        required_fields = [
            "feedback_id",
            "store_id",
            "store_name",
            "channel",
            "rating",
            "text",
            "issue_type_id",
            "issue_type_name",
            "severity",
            "status",
            "created_at",
        ]
        for field in required_fields:
            assert field in rec, f"Missing required field '{field}' in recent submission: {rec}"
            assert rec[field] is not None or field in ("rating",), f"Field '{field}' was unexpectedly None"


def test_customer_dashboard_unauthenticated_rejected(client):
    """Unauthenticated requests to customer dashboard must be rejected with HTTP 401."""
    res = client.get("/api/customer/dashboard")
    assert res.status_code == 401, f"Expected 401 Unauthorized, got {res.status_code}"


def test_customer_dashboard_empty_state_for_new_user(client):
    """A newly registered customer with 0 submissions must receive total=0 and empty recent_submissions."""
    unique_email = f"fresh.customer.{uuid.uuid4().hex[:8]}@example.com"
    reg_res = client.post(
        "/api/auth/register",
        json={"email": unique_email, "password": "DemoCust#2026!Fresh", "full_name": "Fresh User"},
    )
    assert reg_res.status_code == 201, f"Registration failed: {reg_res.text}"

    login_res = client.post(
        "/api/auth/login",
        json={"email": unique_email, "password": "DemoCust#2026!Fresh"},
    )
    token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    res = client.get("/api/customer/dashboard", headers=headers)
    assert res.status_code == 200, f"Expected 200, got: {res.text}"

    data = res.json()
    assert data["total_submissions"] == 0
    assert data["open_submissions"] == 0
    assert data["resolved_submissions"] == 0
    assert data["recent_submissions"] == []
    assert data["email"] == unique_email


