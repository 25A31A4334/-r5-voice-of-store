"""Integration & API Tests for R5 Voice-of-Store Engine Web App.

Author: Team CodeNova
Usage:
    python FULL_CODE/test_app.py
"""
from __future__ import annotations

import sys
from pathlib import Path

# Guarantee UTF-8 output encoding for Windows terminal
if sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import os

# Explicit test-only execution environment & secret (Rule 3 & 4)
os.environ["TESTING"] = "true"
os.environ["APP_ENV"] = "test"
os.environ["JWT_SECRET_KEY"] = "test-only-explicit-jwt-secret-for-integration-tests-min32chars"
os.environ["ENABLE_DEMO_ACCOUNTS"] = "true"

from fastapi.testclient import TestClient
from FULL_CODE.app import app, load_application_state


def run_tests() -> None:
    print("=" * 70)
    print("TESTING R5 VOICE-OF-STORE ENGINE WEB APPLICATION")
    print("=" * 70)

    # Initialize in-memory state
    load_application_state()
    client = TestClient(app)

    # 1. Health Check
    print("\n[Test 1/7] Testing GET /api/health...")
    res = client.get("/api/health")
    assert res.status_code == 200, f"Expected 200, got {res.status_code}"
    data = res.json()
    print(f"  -> Status: {data['status']}, Records Loaded: {data['records_loaded']}, Stores: {data['stores_monitored']}")
    assert data["status"] == "online"
    assert data["records_loaded"] == 39769

    # 2. KPIs
    print("\n[Test 2/7] Testing GET /api/kpis...")
    res = client.get("/api/kpis")
    assert res.status_code == 200
    kpis = res.json()
    print(f"  -> Total Feedback: {kpis['total_feedback']}, Actionable: {kpis['actionable_count']} ({kpis['actionable_pct']}%)")
    print(f"  -> Critical Hazards: {kpis['critical_count']}, Evaluator Score: {kpis['evaluator_primary_score']}")
    assert kpis["total_feedback"] == 39769
    assert kpis["stores_monitored"] == 60

    # 3. Regional Briefs
    print("\n[Test 3/7] Testing GET /api/regional-briefs (Deliverable #1)...")
    res = client.get("/api/regional-briefs?region=North&week=2026-05-18")
    assert res.status_code == 200
    brief = res.json()
    print(f"  -> Region: {brief['region']}, Week: {brief['week']}, Top Issues Count: {len(brief['top_5_issues'])}")
    assert len(brief["top_5_issues"]) > 0
    top1 = brief["top_5_issues"][0]
    print(f"  -> Rank #1 Issue: {top1['issue_name']} ({top1['issue_type_id']}) | Trend: {top1['trend_arrow']} | Volume: {top1['count']}")
    assert "trend_arrow" in top1
    assert "affected_stores" in top1
    assert "evidence_quotes" in top1

    # 4. Emerging Alerts Radar
    print("\n[Test 4/7] Testing GET /api/emerging-alerts (Deliverable #3)...")
    res = client.get("/api/emerging-alerts")
    assert res.status_code == 200
    alerts = res.json()
    print(f"  -> Total Active Alerts: {alerts['total_alerts']}")
    assert alerts["total_alerts"] > 0
    first_alert = alerts["alerts"][0]
    print(f"  -> Top Alert: Store {first_alert['store_id']} ({first_alert['store_name']}), Issue {first_alert['issue_type_id']}, Conf {first_alert['confidence']}")
    assert len(first_alert["evidence_ids"]) >= 2

    # 5. Live Classifier Form
    print("\n[Test 5/7] Testing POST /api/classify (Live ML Demo)...")
    test_payload = {
        "text": "The curd was expired 3 days ago and caused a bad stomach infection! Hospital visit required.",
        "channel": "call_centre_ticket",
        "rating": 1.0,
        "store_id": "ST-D69EG",
    }
    res = client.post("/api/classify", json=test_payload)
    assert res.status_code == 200
    clf_res = res.json()
    print(f"  -> Predicted Issue: {clf_res['issue_type_name']} ({clf_res['issue_type_id']})")
    print(f"  -> Owner Function: {clf_res['owner_function']}")
    print(f"  -> Severity: {clf_res['severity']} (Policy Floor: {clf_res['policy_severity_floor']})")
    print(f"  -> Actionable: {clf_res['actionable']}, Routable: {clf_res['is_routable']}")
    print(f"  -> Destination: {clf_res['routing_destination']}")
    assert clf_res["severity"] in ["high", "critical"]
    assert clf_res["actionable"] == 1

    # Test Non-Issue Classification via Form
    praise_payload = {"text": "Very clean store and fast billing, thank you Saffron Retail!"}
    res_praise = client.post("/api/classify", json=praise_payload)
    assert res_praise.status_code == 200
    p_data = res_praise.json()
    print(f"  -> Praise Test: {p_data['issue_type_id']} | Severity: {p_data['severity']} | Actionable: {p_data['actionable']}")
    assert p_data["issue_type_id"] in ["NI01", "NI02"]
    assert p_data["actionable"] == 0
    assert p_data["severity"] == "low"

    # 6. Feedback Explorer Pagination & Search
    print("\n[Test 6/7] Testing GET /api/feedback...")
    res = client.get("/api/feedback?page=1&limit=5&severity=critical")
    assert res.status_code == 200
    fb_data = res.json()
    print(f"  -> Total Critical Records: {fb_data['total']}, Returned on Page 1: {len(fb_data['records'])}")
    assert len(fb_data["records"]) == 5

    # 7. Frontend Serving
    print("\n[Test 7/7] Testing GET / (Static Dashboard Delivery)...")
    res = client.get("/")
    assert res.status_code == 200
    assert "Voice-of-Store Engine" in res.text
    print("  -> index.html successfully served (status 200 OK)")

    print("\n" + "=" * 70)
    print("ALL 7 API & INTEGRATION TESTS PASSED PERFECTLY (100%)")
    print("=" * 70)


if __name__ == "__main__":
    run_tests()
