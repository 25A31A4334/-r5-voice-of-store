"""FastAPI Security Dependencies & Server-Side Access Control (Team CodeNova).

Follows Rule 4: "Check permissions on the server. Hiding a button in the UI is not access control."
Enforces JWT bearer authentication and role-based access control.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from fastapi import Depends, Header, HTTPException, status

try:
    from FULL_CODE.config import settings
    from FULL_CODE.db.connection import get_db_connection
    from FULL_CODE.services.auth_service import AuthService
    from FULL_CODE.services.supabase_service import SupabaseService
except ImportError:
    from config import settings
    from db.connection import get_db_connection
    from services.auth_service import AuthService
    from services.supabase_service import SupabaseService


def get_current_user(authorization: Optional[str] = Header(None)) -> Dict[str, Any]:
    """Validates JWT bearer token from Authorization header and returns user profile.

    Supports both local JWT tokens (signed by backend JWT_SECRET_KEY) and Supabase Auth (APP_MODE=supabase).
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if not authorization or not authorization.startswith("Bearer "):
        raise credentials_exception

    token = authorization.split(" ", 1)[1].strip()
    if not token:
        raise credentials_exception

    # 1. First, check if the token is a valid locally-issued JWT signed by this backend
    try:
        payload = AuthService.decode_access_token(token)
        user_id = payload.get("sub")
        email = payload.get("email")

        if user_id or email:
            with get_db_connection() as conn:
                user = conn.execute(
                    """
                    SELECT id, email, full_name, role, assigned_store_id
                    FROM users
                    WHERE id = ? OR email = ?;
                    """,
                    (user_id, email or str(user_id)),
                ).fetchone()

                if user:
                    return {
                        "id": user["id"],
                        "email": user["email"],
                        "full_name": user["full_name"],
                        "role": user["role"],
                        "assigned_store_id": user["assigned_store_id"],
                        "provider": "local",
                        "token": token,
                    }
    except ValueError as e:
        # If token was signed locally but expired, fail immediately with 401
        if "expired" in str(e).lower():
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token has expired",
                headers={"WWW-Authenticate": "Bearer"},
            )
        # Otherwise (invalid signature / wrong secret), proceed to check Supabase
        pass
    except Exception:
        pass

    # 2. Supabase Mode: Verify token against Supabase Auth API
    if settings.APP_MODE == "supabase" and not settings.TESTING:
        try:
            supa_user = SupabaseService.verify_token(token)
            supa_user["token"] = token
            return supa_user
        except Exception:
            pass

    # If neither local verification nor Supabase verification succeeded, deny credentials
    raise credentials_exception


def require_roles(allowed_roles: List[str]) -> Callable[[Dict[str, Any]], Dict[str, Any]]:
    """Dependency factory checking that user holds at least one of allowed_roles on the server."""

    def role_checker(current_user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
        user_role = current_user.get("role")
        if user_role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Forbidden: Action requires one of {allowed_roles} roles. Your role: '{user_role}'.",
            )
        return current_user

    return role_checker


def enforce_store_access(current_user: Dict[str, Any], requested_store_id: Optional[str]) -> None:
    """Enforces store-specific boundaries on the server.

    - Admin: Permitted access across all stores.
    - Store Manager: Strictly limited to their assigned_store_id.
    - Customer: Denied management access.
    """
    role = current_user.get("role")
    if role == "admin":
        return

    if role == "store_manager":
        assigned_sid = current_user.get("assigned_store_id")
        if not assigned_sid or (requested_store_id and requested_store_id.upper() != assigned_sid.upper()):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Forbidden: You are only authorized to manage store '{assigned_sid}'. Access to '{requested_store_id}' denied.",
            )
        return

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Forbidden: Customer role is not authorized for store operational management.",
    )
