"""Secure Administrative Account Provisioning Utility (Team CodeNova).

Usage (from terminal on local server):
    python FULL_CODE/db/provision_admin.py --email admin@saffron.example --name "Saffron HQ Admin"

Security Safeguards:
- Strictly executes locally using SUPABASE_SERVICE_ROLE_KEY from .env.
- Zero credentials or service-role keys are exposed to the browser or client-side code.
- Provisions confirmed user via Supabase GoTrue Admin API and elevates role in public.profiles.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Optional

import httpx

ROOT = Path(__file__).resolve().parents[2]
FULL_CODE_DIR = ROOT / "FULL_CODE"


def _load_env_file(env_path: Path) -> None:
    """Minimal standard-library .env loader."""
    if not env_path.is_file():
        return
    try:
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip().strip("'\"")
                if k and k not in os.environ:
                    os.environ[k] = v
    except Exception:
        pass


_load_env_file(ROOT / ".env")
_load_env_file(FULL_CODE_DIR / ".env")


def provision_admin(email: str, full_name: str, password: Optional[str] = None) -> bool:
    """Provisions a verified administrative user directly in Supabase."""
    supabase_url = os.getenv("SUPABASE_URL", "").rstrip("/")
    service_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")

    if not supabase_url or not service_key:
        print("[Error] Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY in environment/.env.")
        print("Please configure them in your local .env file before running provisioning.")
        return False

    headers = {
        "apikey": service_key,
        "Authorization": f"Bearer {service_key}",
        "Content-Type": "application/json",
    }

    # Generate or read password (never print to stdout)
    admin_password = password or os.getenv("DEMO_ADMIN_PASSWORD", "AdminPass#2026!HQSecure")

    with httpx.Client(timeout=15.0) as client:
        # 1. Create or retrieve user via GoTrue Admin API
        create_payload = {
            "email": email.strip().lower(),
            "password": admin_password,
            "email_confirm": True,
            "user_metadata": {"full_name": full_name.strip()},
        }

        res = client.post(f"{supabase_url}/auth/v1/admin/users", headers=headers, json=create_payload)
        user_id = None

        if res.status_code in (200, 201):
            user_data = res.json()
            user_id = user_data.get("id")
            print(f"[Provision] Created new Supabase auth user with email: {email}")
        elif res.status_code == 422 or "already registered" in res.text.lower():
            # User already exists; lookup user ID
            list_res = client.get(f"{supabase_url}/auth/v1/admin/users", headers=headers)
            if list_res.status_code == 200:
                users_list = list_res.json().get("users", [])
                for u in users_list:
                    if u.get("email", "").lower() == email.strip().lower():
                        user_id = u.get("id")
                        break
            print(f"[Provision] User already exists in Supabase auth. Updating permissions...")
        else:
            print(f"[Error] Failed to create user in Supabase Auth (Status {res.status_code}): {res.text}")
            return False

        if not user_id:
            print("[Error] Could not resolve user UUID.")
            return False

        # 2. Update role in public.profiles table using service-role privileges
        patch_payload = {
            "role": "admin",
            "full_name": full_name.strip(),
            "assigned_store_id": None,
        }

        patch_res = client.patch(
            f"{supabase_url}/rest/v1/profiles?id=eq.{user_id}",
            headers=headers,
            json=patch_payload,
        )

        if patch_res.status_code in (200, 204):
            print(f"[Success] Successfully granted 'admin' role to {email} (User ID: {user_id}).")
            return True
        else:
            print(f"[Error] Failed to update profile role (Status {patch_res.status_code}): {patch_res.text}")
            return False


def main():
    parser = argparse.ArgumentParser(description="Securely provision administrative accounts for R5 Engine.")
    parser.add_argument("--email", default="admin@saffron.example", help="Administrator email address")
    parser.add_argument("--name", default="Saffron HQ Executive", help="Full name of administrator")
    parser.add_argument("--password", default=None, help="Optional initial password (or set via DEMO_ADMIN_PASSWORD)")
    args = parser.parse_args()

    success = provision_admin(email=args.email, full_name=args.name, password=args.password)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
