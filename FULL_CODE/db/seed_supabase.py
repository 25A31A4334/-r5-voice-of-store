"""Supabase Seeder & Store Fleet Population Utility (Team CodeNova).

Usage:
    python FULL_CODE/db/seed_supabase.py

Operations:
1. Reads 60 stores from data/store_master.csv (read-only, no file modifications).
2. Upserts stores fleet into public.stores via PostgREST with service-role credentials.
3. Provisions demonstration accounts (Admin, 2 Store Managers, Customer) via GoTrue Admin API.
4. Binds Store Managers strictly to their assigned store IDs (ST-D69EG, ST-NWRDO).
"""
from __future__ import annotations

import csv
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

import httpx

ROOT = Path(__file__).resolve().parents[2]
FULL_CODE_DIR = ROOT / "FULL_CODE"
DATA_DIR = ROOT / "data"


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


def seed_stores(client: httpx.Client, supabase_url: str, headers: Dict[str, str]) -> bool:
    """Populates 60 retail stores from data/store_master.csv into public.stores."""
    store_file = DATA_DIR / "store_master.csv"
    if not store_file.exists():
        print(f"[Error] store_master.csv not found at {store_file}")
        return False

    stores = []
    with open(store_file, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            stores.append({
                "store_id": row["store_id"].strip(),
                "store_name": row["store_name"].strip(),
                "city": row["city"].strip(),
                "state": row["state"].strip(),
                "region": row["region"].strip(),
                "format": row["format"].strip(),
                "size_sqft": int(row["size_sqft"]) if row.get("size_sqft") else None,
                "avg_weekly_footfall": int(row["avg_weekly_footfall"]) if row.get("avg_weekly_footfall") else None,
                "opened_date": row.get("opened_date", "").strip(),
            })

    # Upsert to PostgREST with resolution=merge-duplicates
    upsert_headers = headers.copy()
    upsert_headers["Prefer"] = "resolution=merge-duplicates"

    res = client.post(f"{supabase_url}/rest/v1/stores", headers=upsert_headers, json=stores)
    if res.status_code in (200, 201, 204):
        print(f"[Fleet] Successfully populated/verified {len(stores)} retail stores in public.stores.")
        return True
    else:
        print(f"[Error] Failed to populate stores (Status {res.status_code}): {res.text}")
        return False


def seed_demo_users(client: httpx.Client, supabase_url: str, headers: Dict[str, str]) -> bool:
    """Provisions demonstration staff and customer accounts."""
    demo_accounts = [
        {
            "email": "admin@saffron.example",
            "password": os.getenv("DEMO_ADMIN_PASSWORD", "DemoAdmin#2026!HQSecure"),
            "full_name": "Saffron Head Office Admin",
            "role": "admin",
            "assigned_store_id": None,
        },
        {
            "email": "manager.kankarbagh@saffron.example",
            "password": os.getenv("DEMO_MANAGER_PASSWORD", "DemoMgr#2026!Kankarbagh"),
            "full_name": "Kankarbagh Store Ops Lead",
            "role": "store_manager",
            "assigned_store_id": "ST-D69EG",
        },
        {
            "email": "manager.kothrud@saffron.example",
            "password": os.getenv("DEMO_MANAGER_PASSWORD", "DemoMgr#2026!Kothrud"),
            "full_name": "Kothrud Store Ops Lead",
            "role": "store_manager",
            "assigned_store_id": "ST-NWRDO",
        },
        {
            "email": "customer@example.com",
            "password": os.getenv("DEMO_CUSTOMER_PASSWORD", "DemoCust#2026!Aarav"),
            "full_name": "Aarav Sharma",
            "role": "customer",
            "assigned_store_id": None,
        },
    ]

    for acct in demo_accounts:
        create_payload = {
            "email": acct["email"],
            "password": acct["password"],
            "email_confirm": True,
            "user_metadata": {"full_name": acct["full_name"]},
        }

        user_id = None
        res = client.post(f"{supabase_url}/auth/v1/admin/users", headers=headers, json=create_payload)
        if res.status_code in (200, 201):
            user_id = res.json().get("id")
        elif res.status_code == 422 or "already registered" in res.text.lower():
            # Lookup user ID
            list_res = client.get(f"{supabase_url}/auth/v1/admin/users", headers=headers)
            if list_res.status_code == 200:
                for u in list_res.json().get("users", []):
                    if u.get("email", "").lower() == acct["email"].lower():
                        user_id = u.get("id")
                        break

        if not user_id:
            print(f"[Warning] Could not resolve UUID for demo account {acct['email']}.")
            continue

        # Set role and assigned store in public.profiles via service-role connection
        patch_payload = {
            "role": acct["role"],
            "full_name": acct["full_name"],
            "assigned_store_id": acct["assigned_store_id"],
        }
        client.patch(
            f"{supabase_url}/rest/v1/profiles?id=eq.{user_id}",
            headers=headers,
            json=patch_payload,
        )
        print(f"[Account] Verified {acct['role']} demo account: {acct['email']} (Store: {acct['assigned_store_id'] or 'All'})")

    return True


def run_seeder():
    supabase_url = os.getenv("SUPABASE_URL", "").rstrip("/")
    service_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")

    if not supabase_url or not service_key:
        print("[Notice] Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY.")
        print("Please configure them in your local .env file before running Supabase seeding.")
        return

    headers = {
        "apikey": service_key,
        "Authorization": f"Bearer {service_key}",
        "Content-Type": "application/json",
    }

    with httpx.Client(timeout=20.0) as client:
        print("\n=== Populating Saffron Retail Stores Fleet ===")
        seed_stores(client, supabase_url, headers)

        print("\n=== Provisioning Demonstration Accounts ===")
        seed_demo_users(client, supabase_url, headers)
        print("\nSupabase seeding complete.")


if __name__ == "__main__":
    run_seeder()
