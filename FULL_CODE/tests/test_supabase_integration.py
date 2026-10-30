"""Automated Tests for Supabase Client Initialization & Integration (Team CodeNova).

Validates:
1. Safe public configuration delivery (never exposing backend secrets).
2. Fail-safe startup validation when Supabase parameters are missing.
3. Token rejection on invalid/expired Supabase tokens.
"""
from __future__ import annotations

import os
import pytest
from fastapi.testclient import TestClient

from FULL_CODE.app import app, load_application_state
from FULL_CODE.config import settings
from FULL_CODE.services.supabase_service import SupabaseService
from FULL_CODE.services.dependencies import get_current_user
from FULL_CODE.db.seed import seed_database


@pytest.fixture(scope="module")
def client():
    seed_database(force_demo=True)
    load_application_state()
    with TestClient(app) as c:
        yield c


def test_public_config_endpoint_delivers_safe_keys_only(client):
    """Verifies GET /api/config/public returns public credentials and never leaks secrets."""
    res = client.get("/api/config/public")
    assert res.status_code == 200
    data = res.json()

    assert "app_mode" in data
    assert "supabase_url" in data
    assert "supabase_publishable_key" in data

    # Security check: must NEVER contain confidential keys
    assert "service_role" not in str(data).lower()
    assert "jwt_secret" not in str(data).lower()
    assert "password" not in str(data).lower()


def test_supabase_mode_fails_safely_if_url_missing(monkeypatch):
    """Verifies non-test startup fails safely if SUPABASE_URL is missing."""
    monkeypatch.setattr(settings, "TESTING", False)
    monkeypatch.setattr(settings, "APP_ENV", "production")
    monkeypatch.setattr(settings, "APP_MODE", "supabase")
    monkeypatch.setattr(settings, "SUPABASE_URL", "")
    monkeypatch.setattr(settings, "SUPABASE_PUBLISHABLE_KEY", "sb_publishable_dummy_key_12345")

    with pytest.raises(RuntimeError) as exc_info:
        settings.validate_startup()
    assert "SUPABASE_URL" in str(exc_info.value)


def test_supabase_mode_fails_safely_if_key_missing(monkeypatch):
    """Verifies non-test startup fails safely if SUPABASE_PUBLISHABLE_KEY is missing."""
    monkeypatch.setattr(settings, "TESTING", False)
    monkeypatch.setattr(settings, "APP_ENV", "production")
    monkeypatch.setattr(settings, "APP_MODE", "supabase")
    monkeypatch.setattr(settings, "SUPABASE_URL", "https://xyzproject.supabase.co")
    monkeypatch.setattr(settings, "SUPABASE_PUBLISHABLE_KEY", "")

    with pytest.raises(RuntimeError) as exc_info:
        settings.validate_startup()
    assert "SUPABASE_PUBLISHABLE_KEY" in str(exc_info.value)


def test_supabase_invalid_token_rejected_by_service():
    """Verifies SupabaseService.verify_token rejects bogus or malformed tokens safely."""
    with pytest.raises(ValueError) as exc_info:
        SupabaseService.verify_token("invalid-malformed-token-xyz")
    assert "rejected" in str(exc_info.value).lower() or "unable" in str(exc_info.value).lower()


def test_supabase_protected_route_rejects_bogus_token(client, monkeypatch):
    """Verifies protected endpoints return 401 when provided with invalid bearer token."""
    monkeypatch.setattr(settings, "APP_MODE", "supabase")
    monkeypatch.setattr(settings, "TESTING", False)

    res = client.get("/api/auth/me", headers={"Authorization": "Bearer bogus-token-12345"})
    assert res.status_code == 401
    assert "credentials" in res.json().get("detail", "").lower() or "rejected" in res.json().get("detail", "").lower()


def test_supabase_service_header_generation():
    """Verifies SupabaseService.get_headers generates correct headers and hides secrets."""
    headers = SupabaseService.get_headers()
    assert "apikey" in headers
    assert "Content-Type" in headers
    assert "Authorization" in headers

    # Header with access token
    auth_headers = SupabaseService.get_headers(access_token="custom-user-token")
    assert auth_headers["Authorization"] == "Bearer custom-user-token"


def test_feedback_persistence_retains_status_across_refresh(client):
    """Verifies feedback submission persistence and status transition retention (Fix for disappearing feedback)."""
    # 1. Register test customer and obtain token
    reg_res = client.post(
        "/api/auth/register",
        json={
            "email": "persist.tester@example.com",
            "password": "Password#123456",
            "full_name": "Persistence Tester",
        },
    )
    assert reg_res.status_code in (201, 400)
    login_res = client.post(
        "/api/auth/login",
        json={"email": "persist.tester@example.com", "password": "Password#123456"},
    )
    assert login_res.status_code == 200
    token = login_res.json()["access_token"]
    cust_headers = {"Authorization": f"Bearer {token}"}

    # 2. Submit customer feedback
    sub_res = client.post(
        "/api/customer/submissions",
        headers=cust_headers,
        json={
            "store_id": "ST-D69EG",
            "channel": "in_app",
            "rating": 4,
            "text": "Apples were remarkably crisp and fresh today in Kankarbagh store.",
        },
    )
    assert sub_res.status_code == 201
    fid = sub_res.json()["feedback_id"]

    # 3. Simulate page refresh: query submissions and dashboard
    list_res = client.get("/api/customer/submissions", headers=cust_headers)
    assert list_res.status_code == 200
    sub_list = list_res.json()["submissions"]
    assert any(s["feedback_id"] == fid for s in sub_list)
    found_sub = next(s for s in sub_list if s["feedback_id"] == fid)
    assert found_sub["status"] == "new"

    # 4. Store manager acknowledges and resolves feedback
    mgr_login = client.post(
        "/api/auth/login",
        json={"email": "manager.kankarbagh@saffron.example", "password": "DemoMgr#2026!Kankarbagh"},
    )
    assert mgr_login.status_code == 200
    mgr_token = mgr_login.json()["access_token"]
    mgr_headers = {"Authorization": f"Bearer {mgr_token}"}

    act_res = client.post(
        f"/api/manager/feedback/{fid}/action",
        headers=mgr_headers,
        json={
            "action": "resolve",
            "note": "Checked fresh produce counter; inspected and verified top tier quality.",
        },
    )
    assert act_res.status_code == 200
    assert act_res.json()["status"] == "resolved"

    # 5. Simulate second refresh: verify resolution note and status persisted
    refresh_res = client.get("/api/customer/submissions", headers=cust_headers)
    assert refresh_res.status_code == 200
    updated_sub = next(s for s in refresh_res.json()["submissions"] if s["feedback_id"] == fid)
    assert updated_sub["status"] == "resolved"
    assert "inspected and verified" in updated_sub["resolution_notes"]


def test_sqlite_to_supabase_migration_script_is_rerunnable():
    """Verifies migrate_sqlite_to_supabase.py runs idempotently and produces valid seed script."""
    from FULL_CODE.db.migrate_sqlite_to_supabase import generate_seed_sql

    sql_path = generate_seed_sql()
    assert sql_path.exists()
    content = sql_path.read_text(encoding="utf-8")

    # Confirm key structures are populated and idempotent without overwriting live status
    assert "INSERT INTO public.stores" in content
    assert "ON CONFLICT (store_id) DO UPDATE" in content
    assert "INSERT INTO public.incident_alerts" in content
    assert "ON CONFLICT (alert_id) DO NOTHING" in content
    assert "INSERT INTO public.feedback_submissions" in content
    assert "ON CONFLICT (feedback_id) DO NOTHING" in content
    assert "INSERT INTO public.audit_log" in content
    assert "ON CONFLICT (id) DO NOTHING" in content

    # Confirm every audit_log details value is valid JSON (prevents PostgreSQL error 22P02)
    import json
    import re
    for line in content.splitlines():
        if "INSERT INTO public.audit_log" in line:
            m = re.search(r"VALUES\s*\((?:'[^']*',\s*){4}(.*)::jsonb,", line)
            assert m is not None, f"Failed to parse audit line: {line}"
            raw_sql = m.group(1).strip()
            assert raw_sql.startswith("'") and raw_sql.endswith("'")
            val = raw_sql[1:-1].replace("''", "'")
            # Must parse without JSONDecodeError
            json.loads(val)


def test_supabase_phase2_migration_unique_indices_and_safeguards():
    """Verifies migration SQL has pre-checks and UNIQUE indices for feedback_id and alert_id."""
    from pathlib import Path
    import sqlite3
    from FULL_CODE.config import settings

    migration_file = Path(__file__).resolve().parents[1] / "db" / "supabase_phase2_migration.sql"
    assert migration_file.exists()
    sql_text = migration_file.read_text(encoding="utf-8")

    # Assert UNIQUE index definitions exist
    assert "CREATE UNIQUE INDEX IF NOT EXISTS idx_feedback_fid_unique ON public.feedback_submissions(feedback_id);" in sql_text
    assert "CREATE UNIQUE INDEX IF NOT EXISTS idx_alerts_aid_unique ON public.incident_alerts(alert_id);" in sql_text

    # Assert pre-migration duplicate and NULL guardrails exist
    assert "have NULL feedback_id" in sql_text
    assert "duplicate feedback_id values exist" in sql_text
    assert "have NULL alert_id" in sql_text
    assert "duplicate alert_id values exist" in sql_text

    # Assert SQLite database has 0 duplicates and 0 nulls for feedback_id and alert_id
    if settings.DATABASE_PATH.exists():
        conn = sqlite3.connect(str(settings.DATABASE_PATH))
        cursor = conn.cursor()

        cursor.execute("SELECT feedback_id, COUNT(*) FROM feedback_submissions GROUP BY feedback_id HAVING COUNT(*) > 1")
        assert len(cursor.fetchall()) == 0

        cursor.execute("SELECT COUNT(*) FROM feedback_submissions WHERE feedback_id IS NULL OR feedback_id = ''")
        assert cursor.fetchone()[0] == 0

        cursor.execute("SELECT alert_id, COUNT(*) FROM incident_alerts GROUP BY alert_id HAVING COUNT(*) > 1")
        assert len(cursor.fetchall()) == 0

        cursor.execute("SELECT COUNT(*) FROM incident_alerts WHERE alert_id IS NULL OR alert_id = ''")
        assert cursor.fetchone()[0] == 0

        conn.close()


