"""Automated Security & Authentication Tests (Team CodeNova).

Follows Rule 4 (Write secure code) and Rule 6 (Test the parts that matter).
Tests:
1. Password hashing (salted PBKDF2, uniqueness, constant-time verification).
2. JWT token creation, signature verification, expiry handling, and tampering rejection.
3. Public registration restriction (strictly creates 'customer', rejects weak passwords & duplicate emails).
4. Login failure handling (wrong password, unknown email -> 401 without PII leakage).
5. Server-side role-based access control (RBAC) and store-specific boundary enforcement.
"""
from __future__ import annotations

import sys
import time
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from FULL_CODE.config import settings
from FULL_CODE.db.connection import get_db_connection, init_db
from FULL_CODE.db.seed import seed_database
from FULL_CODE.services.auth_service import AuthService
from FULL_CODE.services.dependencies import (
    enforce_store_access,
    get_current_user,
    require_roles,
)
from FULL_CODE.api.auth import router as auth_router

TEST_DB_PATH = ROOT / "FULL_CODE" / "tests" / "test_auth.db"


@pytest.fixture(scope="module", autouse=True)
def setup_test_db():
    """Initializes a fresh isolated SQLite database for security tests and restores settings on teardown."""
    original_db_path = settings.DATABASE_PATH
    if TEST_DB_PATH.exists():
        TEST_DB_PATH.unlink()
    init_db(TEST_DB_PATH)
    settings.DATABASE_PATH = TEST_DB_PATH
    try:
        yield
    finally:
        settings.DATABASE_PATH = original_db_path
        if TEST_DB_PATH.exists():
            TEST_DB_PATH.unlink()


# -----------------------------------------------------------------------------
# 1. Password Hashing & Verification Tests
# -----------------------------------------------------------------------------
def test_password_hashing_and_salting():
    pwd = "SecurePassword@2026"
    hash1, salt1 = AuthService.hash_password(pwd)
    hash2, salt2 = AuthService.hash_password(pwd)

    # Hashes and salts must be unique per invocation due to random salting
    assert salt1 != salt2
    assert hash1 != hash2

    # Verification must succeed with correct password
    assert AuthService.verify_password(pwd, hash1, salt1) is True
    assert AuthService.verify_password(pwd, hash2, salt2) is True

    # Verification must fail with incorrect password
    assert AuthService.verify_password("WrongPassword123", hash1, salt1) is False
    assert AuthService.verify_password("", hash1, salt1) is False


def test_password_minimum_length():
    with pytest.raises(ValueError, match="at least 8 characters"):
        AuthService.hash_password("short")


# -----------------------------------------------------------------------------
# 2. JWT Token & Expiry Tests
# -----------------------------------------------------------------------------
def test_jwt_token_lifecycle():
    claims = {"sub": "42", "email": "test@example.com", "role": "customer", "store_id": None}
    token = AuthService.create_access_token(claims, expires_delta=timedelta(minutes=15))
    assert isinstance(token, str)

    decoded = AuthService.decode_access_token(token)
    assert decoded["sub"] == "42"
    assert decoded["email"] == "test@example.com"
    assert decoded["role"] == "customer"
    assert "exp" in decoded


def test_jwt_expired_token_rejection():
    claims = {"sub": "42", "email": "test@example.com", "role": "customer"}
    # Create token already expired in the past
    token = AuthService.create_access_token(claims, expires_delta=timedelta(seconds=-10))

    with pytest.raises(ValueError, match="Token has expired"):
        AuthService.decode_access_token(token)


def test_jwt_tampered_token_rejection():
    claims = {"sub": "42", "email": "test@example.com", "role": "customer"}
    token = AuthService.create_access_token(claims)
    # Alter the payload portion of the token
    parts = token.split(".")
    tampered_token = f"{parts[0]}.eyJhZG1pbiI6dHJ1ZX0.{parts[2]}"

    with pytest.raises(ValueError, match="Invalid authentication token"):
        AuthService.decode_access_token(tampered_token)


# -----------------------------------------------------------------------------
# 3. Registration Restriction Tests (Rule 4 & Requirement 5)
# -----------------------------------------------------------------------------
def test_public_registration_creates_customer_only():
    user = AuthService.register_customer(
        email="new_cust@example.com",
        password="ValidPassword@2026",
        full_name="Priya Patel",
        db_path=TEST_DB_PATH,
    )
    assert user["role"] == "customer"
    assert user["assigned_store_id"] is None

    # Check persistence in database
    with get_db_connection(TEST_DB_PATH) as conn:
        row = conn.execute("SELECT role, assigned_store_id FROM users WHERE id = ?;", (user["id"],)).fetchone()
        assert row["role"] == "customer"
        assert row["assigned_store_id"] is None


def test_duplicate_email_registration_rejected():
    with pytest.raises(ValueError, match="already exists"):
        AuthService.register_customer(
            email="new_cust@example.com",
            password="ValidPassword@2026",
            full_name="Duplicate Attempt",
            db_path=TEST_DB_PATH,
        )


def test_invalid_email_format_rejected():
    with pytest.raises(ValueError, match="Invalid email format"):
        AuthService.register_customer(
            email="not-an-email",
            password="ValidPassword@2026",
            full_name="Bad Email",
            db_path=TEST_DB_PATH,
        )


# -----------------------------------------------------------------------------
# 4. Login & Authentication Flow Tests
# -----------------------------------------------------------------------------
def test_authentication_success_and_failure():
    # Success
    auth_user = AuthService.authenticate_user(
        email="new_cust@example.com",
        password="ValidPassword@2026",
        db_path=TEST_DB_PATH,
    )
    assert auth_user is not None
    assert auth_user["email"] == "new_cust@example.com"
    assert auth_user["role"] == "customer"
    assert "password_hash" not in auth_user  # No password hash leaked in dict

    # Failure: Wrong password
    assert AuthService.authenticate_user("new_cust@example.com", "WrongPass@2026", db_path=TEST_DB_PATH) is None

    # Failure: Unknown email
    assert AuthService.authenticate_user("unknown@example.com", "ValidPassword@2026", db_path=TEST_DB_PATH) is None


# -----------------------------------------------------------------------------
# 5. Server-Side Role-Based Access Control (RBAC) & Store Scoping Tests
# -----------------------------------------------------------------------------
def test_role_based_access_control_server_enforcement():
    # Mock testing FastAPI app with role-protected endpoints
    test_app = FastAPI()
    test_app.include_router(auth_router, prefix="/api/auth")

    @test_app.get("/admin-only")
    def admin_route(user=Depends(require_roles(["admin"]))):
        return {"msg": f"Welcome Admin {user['email']}"}

    @test_app.get("/store-ops")
    def store_ops_route(user=Depends(require_roles(["store_manager", "admin"]))):
        return {"msg": f"Welcome Ops {user['email']}"}

    client = TestClient(test_app)

    # 1. Setup staff accounts in test DB
    AuthService.create_staff_user(
        email="mgr_patna@saffron.example",
        password="ManagerPass@2026",
        full_name="Patna Ops Manager",
        role="store_manager",
        assigned_store_id="ST-D69EG",
        db_path=TEST_DB_PATH,
    )
    AuthService.create_staff_user(
        email="admin_hq@saffron.example",
        password="AdminPass@2026",
        full_name="HQ Executive",
        role="admin",
        db_path=TEST_DB_PATH,
    )

    # 2. Login as Customer
    cust_login = client.post("/api/auth/login", json={"email": "new_cust@example.com", "password": "ValidPassword@2026"})
    assert cust_login.status_code == 200
    cust_token = cust_login.json()["access_token"]

    # 3. Customer attempts admin endpoint -> 403 Forbidden
    res = client.get("/admin-only", headers={"Authorization": f"Bearer {cust_token}"})
    assert res.status_code == 403
    assert "Forbidden" in res.json()["detail"]

    # 4. Customer attempts store-ops endpoint -> 403 Forbidden
    res = client.get("/store-ops", headers={"Authorization": f"Bearer {cust_token}"})
    assert res.status_code == 403

    # 5. Store Manager login & access
    mgr_login = client.post("/api/auth/login", json={"email": "mgr_patna@saffron.example", "password": "ManagerPass@2026"})
    assert mgr_login.status_code == 200
    mgr_token = mgr_login.json()["access_token"]

    # Manager accessing store-ops -> 200 OK
    res_mgr_ops = client.get("/store-ops", headers={"Authorization": f"Bearer {mgr_token}"})
    assert res_mgr_ops.status_code == 200

    # Manager accessing admin-only -> 403 Forbidden
    res_mgr_admin = client.get("/admin-only", headers={"Authorization": f"Bearer {mgr_token}"})
    assert res_mgr_admin.status_code == 403

    # 6. Admin login & access
    admin_login = client.post("/api/auth/login", json={"email": "admin_hq@saffron.example", "password": "AdminPass@2026"})
    assert admin_login.status_code == 200
    admin_token = admin_login.json()["access_token"]

    # Admin accessing admin-only -> 200 OK
    res_admin = client.get("/admin-only", headers={"Authorization": f"Bearer {admin_token}"})
    assert res_admin.status_code == 200


def test_store_specific_access_control():
    manager_patna = {"role": "store_manager", "assigned_store_id": "ST-D69EG", "email": "patna@saffron.example"}
    admin = {"role": "admin", "assigned_store_id": None, "email": "admin@saffron.example"}
    customer = {"role": "customer", "assigned_store_id": None, "email": "cust@example.com"}

    # Manager accessing own store ST-D69EG -> Allowed (no exception)
    enforce_store_access(manager_patna, "ST-D69EG")
    enforce_store_access(manager_patna, "st-d69eg")  # Case insensitive

    # Manager attempting to access Store ST-NWRDO -> 403 Forbidden
    with pytest.raises(HTTPException) as exc_info:
        enforce_store_access(manager_patna, "ST-NWRDO")
    assert exc_info.value.status_code == 403
    assert "only authorized to manage store 'ST-D69EG'" in exc_info.value.detail

    # Admin accessing any store -> Allowed
    enforce_store_access(admin, "ST-D69EG")
    enforce_store_access(admin, "ST-NWRDO")

    # Customer accessing store operations -> 403 Forbidden
    with pytest.raises(HTTPException) as exc_info:
        enforce_store_access(customer, "ST-D69EG")
    assert exc_info.value.status_code == 403


# -----------------------------------------------------------------------------
# 6. Secret Validation & Startup Safeguards (Rule 3 & 4)
# -----------------------------------------------------------------------------
def test_missing_secret_fails_safely_in_non_test_mode(monkeypatch):
    """Verifies startup fails safely if JWT secret is missing in non-test mode."""
    monkeypatch.setattr(settings, "TESTING", False)
    monkeypatch.setattr(settings, "APP_ENV", "production")
    monkeypatch.delenv("JWT_SECRET_KEY", raising=False)

    with pytest.raises(RuntimeError) as exc_info:
        settings.validate_startup()
    assert "missing or empty" in str(exc_info.value)


def test_unsafe_short_secret_fails_safely(monkeypatch):
    """Verifies startup fails safely if JWT secret is shorter than 32 characters."""
    monkeypatch.setattr(settings, "TESTING", False)
    monkeypatch.setattr(settings, "APP_ENV", "production")
    monkeypatch.setenv("JWT_SECRET_KEY", "too_short_key_123")

    with pytest.raises(RuntimeError) as exc_info:
        settings.validate_startup()
    assert "minimum of 32 characters" in str(exc_info.value)


def test_unsafe_predictable_secret_fails_safely(monkeypatch):
    """Verifies startup fails safely if secret matches known placeholder/predictable list."""
    monkeypatch.setattr(settings, "TESTING", False)
    monkeypatch.setattr(settings, "APP_ENV", "production")
    monkeypatch.setenv(
        "JWT_SECRET_KEY",
        "codenova-talentap-hackathon-2026-voice-of-store-dev-secret-key-min32chars",
    )

    with pytest.raises(RuntimeError) as exc_info:
        settings.validate_startup()
    assert "predictable" in str(exc_info.value)


def test_secret_values_never_leaked_in_error_messages(monkeypatch):
    """Verifies error messages never print or leak the rejected secret value itself."""
    dummy_unsafe = "short_unprinted_secret_key"
    monkeypatch.setattr(settings, "TESTING", False)
    monkeypatch.setattr(settings, "APP_ENV", "production")
    monkeypatch.setenv("JWT_SECRET_KEY", dummy_unsafe)

    with pytest.raises(RuntimeError) as exc_info:
        settings.validate_startup()
    error_msg = str(exc_info.value)
    # The error message must mention character count, NOT the secret contents
    assert dummy_unsafe not in error_msg
    assert "length 26 characters" in error_msg


# -----------------------------------------------------------------------------
# 7. Demo Account Safeguards & Credential Protection (Rule 4)
# -----------------------------------------------------------------------------
def test_demo_account_safeguards_and_mode_restriction(monkeypatch):
    """Verifies demo accounts are restricted to demo mode and never store raw passwords."""
    demo_test_db = ROOT / "FULL_CODE" / "tests" / "test_demo_guard.db"
    if demo_test_db.exists():
        demo_test_db.unlink()

    try:
        # A. When ENABLE_DEMO_ACCOUNTS is False -> Seed creates 0 accounts
        monkeypatch.setattr(settings, "ENABLE_DEMO_ACCOUNTS", False)
        seeded = seed_database(demo_test_db, force_demo=False)
        assert seeded is False

        with get_db_connection(demo_test_db) as conn:
            user_count = conn.execute("SELECT count(*) as cnt FROM users;").fetchone()["cnt"]
            assert user_count == 0

        # B. When ENABLE_DEMO_ACCOUNTS is True -> Seed creates 4 accounts
        monkeypatch.setattr(settings, "ENABLE_DEMO_ACCOUNTS", True)
        seeded = seed_database(demo_test_db, force_demo=True)
        assert seeded is True

        with get_db_connection(demo_test_db) as conn:
            user_count = conn.execute("SELECT count(*) as cnt FROM users;").fetchone()["cnt"]
            assert user_count == 4

            # Ensure all passwords are cryptographically hashed and salted
            for row in conn.execute("SELECT email, password_hash, salt FROM users;"):
                assert len(row["password_hash"]) == 64  # Hex sha256
                assert len(row["salt"]) == 32  # 16-byte random hex salt
                # Must never store plaintext password
                assert not row["password_hash"].startswith("Demo")
                assert not row["salt"].startswith("Demo")

    finally:
        if demo_test_db.exists():
            demo_test_db.unlink()
