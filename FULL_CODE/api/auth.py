"""Authentication REST API Routes (Team CodeNova).

Follows Rule 4: "Validate every input... Check permissions on the server."
Follows Safety Requirement 5: Public registration strictly creates customer accounts.
"""
from __future__ import annotations

import re
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator

# Standard-library regex validator for basic email format checking (user@domain.tld).
# Limitation: This is a lightweight syntax check and is NOT equivalent to full RFC 5322 compliance,
# internationalized domain name (IDN) parsing, or DNS MX deliverability checks performed by `email-validator` / `EmailStr`.
EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")

try:
    from FULL_CODE.services.auth_service import AuthService
    from FULL_CODE.services.dependencies import get_current_user
except ImportError:
    from services.auth_service import AuthService
    from services.dependencies import get_current_user

router = APIRouter()


class RegisterRequest(BaseModel):
    email: str = Field(..., description="Valid customer email address")
    password: str = Field(..., min_length=8, description="Password (minimum 8 characters)")
    full_name: str = Field(..., min_length=2, max_length=100, description="Customer full name")

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: str) -> str:
        clean = v.strip().lower()
        if not EMAIL_REGEX.match(clean):
            raise ValueError("Invalid email format.")
        return clean


class LoginRequest(BaseModel):
    email: str = Field(..., description="Registered email address")
    password: str = Field(..., min_length=1, description="Account password")

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: str) -> str:
        clean = v.strip().lower()
        if not EMAIL_REGEX.match(clean):
            raise ValueError("Invalid email format.")
        return clean


class UserProfileResponse(BaseModel):
    id: int | str
    email: str
    full_name: str
    role: str
    assigned_store_id: str | None


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "Bearer"
    user: UserProfileResponse


@router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
def register(req: RegisterRequest) -> AuthResponse:
    """Public customer registration endpoint.

    SAFETY: Always creates 'customer' accounts. Privileged staff accounts cannot be created here.
    """
    try:
        user = AuthService.register_customer(
            email=req.email,
            password=req.password,
            full_name=req.full_name,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    token = AuthService.create_access_token({
        "sub": str(user["id"]),
        "email": user["email"],
        "role": user["role"],
        "store_id": user["assigned_store_id"],
    })

    return AuthResponse(
        access_token=token,
        user=UserProfileResponse(**user),
    )


@router.post("/login", response_model=AuthResponse)
def login(req: LoginRequest) -> AuthResponse:
    """Authenticates credentials and returns a secure JWT bearer token."""
    user = AuthService.authenticate_user(email=req.email, password=req.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = AuthService.create_access_token({
        "sub": str(user["id"]),
        "email": user["email"],
        "role": user["role"],
        "store_id": user["assigned_store_id"],
    })

    return AuthResponse(
        access_token=token,
        user=UserProfileResponse(**user),
    )


@router.get("/me", response_model=UserProfileResponse)
def get_current_user_profile(user: Dict[str, Any] = Depends(get_current_user)) -> UserProfileResponse:
    """Returns profile for currently authenticated user."""
    return UserProfileResponse(
        id=user["id"],
        email=user["email"],
        full_name=user["full_name"],
        role=user["role"],
        assigned_store_id=user["assigned_store_id"],
    )
