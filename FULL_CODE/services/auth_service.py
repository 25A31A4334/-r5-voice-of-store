"""Authentication & Cryptography Service (Team CodeNova).

Follows Rule 3 (Keep secrets out of code), Rule 4 (Write secure code), and safety requirements:
- Password hashing with salted PBKDF2-HMAC-SHA256 (NIST/OWASP standard).
- Time-constant comparison to prevent timing attacks.
- JWT token creation and verification using pyjwt.
- Public registration strictly restricted to 'customer' role.
- Never prints or logs passwords or tokens.
"""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import jwt

try:
    from FULL_CODE.config import settings
    from FULL_CODE.db.connection import get_db_connection
except ImportError:
    from config import settings
    from db.connection import get_db_connection

EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")


class AuthService:
    """Manages password hashing, JWT tokens, and user credentials."""

    @staticmethod
    def hash_password(password: str) -> Tuple[str, str]:
        """Hashes password with cryptographically random salt using PBKDF2-HMAC-SHA256."""
        if not password or len(password) < 8:
            raise ValueError("Password must be at least 8 characters long.")

        salt = secrets.token_hex(settings.SALT_BYTE_LENGTH)
        key = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt.encode("utf-8"),
            settings.PBKDF2_ITERATIONS,
        )
        return key.hex(), salt

    @staticmethod
    def verify_password(password: str, stored_hash: str, salt: str) -> bool:
        """Verifies password using constant-time comparison to prevent timing attacks."""
        if not password or not stored_hash or not salt:
            return False

        key = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt.encode("utf-8"),
            settings.PBKDF2_ITERATIONS,
        )
        return hmac.compare_digest(key.hex(), stored_hash)

    @staticmethod
    def create_access_token(data: Dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
        """Encodes user claims into a signed JWT token."""
        to_encode = data.copy()
        now = datetime.now(timezone.utc)
        expire = now + (expires_delta or timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES))

        to_encode.update({
            "exp": expire,
            "iat": now,
        })
        token = jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
        return token

    @staticmethod
    def decode_access_token(token: str) -> Dict[str, Any]:
        """Decodes and validates a JWT token."""
        try:
            payload = jwt.decode(
                token,
                settings.JWT_SECRET_KEY,
                algorithms=[settings.JWT_ALGORITHM],
            )
            return payload
        except jwt.ExpiredSignatureError:
            raise ValueError("Token has expired.")
        except jwt.InvalidTokenError:
            raise ValueError("Invalid authentication token.")

    @classmethod
    def register_customer(
        cls,
        email: str,
        password: str,
        full_name: str,
        db_path: Path | None = None,
    ) -> Dict[str, Any]:
        """Registers a new customer.

        SAFETY ENFORCEMENT (Requirement 5):
        Public registration strictly creates 'customer' accounts. Role input from client
        is NEVER accepted.
        """
        email_clean = email.strip().lower()
        name_clean = full_name.strip()

        if not EMAIL_REGEX.match(email_clean):
            raise ValueError("Invalid email format.")
        if len(name_clean) < 2:
            raise ValueError("Full name must be at least 2 characters.")
        if len(password) < 8:
            raise ValueError("Password must be at least 8 characters long.")

        pwd_hash, salt = cls.hash_password(password)

        with get_db_connection(db_path) as conn:
            # Check for existing email (parameterized query)
            existing = conn.execute("SELECT id FROM users WHERE email = ?;", (email_clean,)).fetchone()
            if existing:
                raise ValueError("An account with this email already exists.")

            cursor = conn.execute(
                """
                INSERT INTO users (email, password_hash, salt, full_name, role, assigned_store_id)
                VALUES (?, ?, ?, ?, 'customer', NULL);
                """,
                (email_clean, pwd_hash, salt, name_clean),
            )
            user_id = cursor.lastrowid

            # Log registration in audit trail
            conn.execute(
                """
                INSERT INTO audit_log (user_id, action, target_type, target_id, details)
                VALUES (?, 'USER_REGISTER', 'users', ?, 'Customer registered via public endpoint');
                """,
                (user_id, str(user_id)),
            )

        return {
            "id": user_id,
            "email": email_clean,
            "full_name": name_clean,
            "role": "customer",
            "assigned_store_id": None,
        }

    @classmethod
    def create_staff_user(
        cls,
        email: str,
        password: str,
        full_name: str,
        role: str,
        assigned_store_id: Optional[str] = None,
        db_path: Path | None = None,
    ) -> Dict[str, Any]:
        """Controlled setup utility for creating staff (admin, store_manager) users."""
        email_clean = email.strip().lower()
        name_clean = full_name.strip()
        role_clean = role.strip().lower()

        if role_clean not in ("admin", "store_manager"):
            raise ValueError("Privileged role must be 'admin' or 'store_manager'.")
        if role_clean == "store_manager" and not assigned_store_id:
            raise ValueError("Store manager must have an assigned store ID.")

        pwd_hash, salt = cls.hash_password(password)

        with get_db_connection(db_path) as conn:
            existing = conn.execute("SELECT id FROM users WHERE email = ?;", (email_clean,)).fetchone()
            if existing:
                # Update existing user if needed (idempotent setup)
                conn.execute(
                    """
                    UPDATE users
                    SET password_hash = ?, salt = ?, full_name = ?, role = ?, assigned_store_id = ?
                    WHERE email = ?;
                    """,
                    (pwd_hash, salt, name_clean, role_clean, assigned_store_id, email_clean),
                )
                user_id = existing["id"]
            else:
                cursor = conn.execute(
                    """
                    INSERT INTO users (email, password_hash, salt, full_name, role, assigned_store_id)
                    VALUES (?, ?, ?, ?, ?, ?);
                    """,
                    (email_clean, pwd_hash, salt, name_clean, role_clean, assigned_store_id),
                )
                user_id = cursor.lastrowid

        return {
            "id": user_id,
            "email": email_clean,
            "full_name": name_clean,
            "role": role_clean,
            "assigned_store_id": assigned_store_id,
        }

    @classmethod
    def authenticate_user(
        cls,
        email: str,
        password: str,
        db_path: Path | None = None,
    ) -> Optional[Dict[str, Any]]:
        """Authenticates user credentials using parameterized query and constant-time check."""
        email_clean = email.strip().lower()

        with get_db_connection(db_path) as conn:
            user = conn.execute(
                """
                SELECT id, email, password_hash, salt, full_name, role, assigned_store_id
                FROM users
                WHERE email = ?;
                """,
                (email_clean,),
            ).fetchone()

            if not user:
                return None

            if not cls.verify_password(password, user["password_hash"], user["salt"]):
                return None

            return {
                "id": user["id"],
                "email": user["email"],
                "full_name": user["full_name"],
                "role": user["role"],
                "assigned_store_id": user["assigned_store_id"],
            }
