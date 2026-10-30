"""Database Seeder for R5 Voice-of-Store Engine (Team CodeNova).

Follows Rule 2: Database schema in repo + small seed script.
Follows Rule 4: Synthetic demo accounts restricted to explicit development/demo mode.
"""
from __future__ import annotations

import os
from pathlib import Path
import sys
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from FULL_CODE.config import settings
from FULL_CODE.db.connection import init_db
from FULL_CODE.services.auth_service import AuthService


def get_demo_users() -> List[Dict[str, Any]]:
    """Returns synthetic demonstration user definitions for local offline development.

    DOCUMENTED DEMO CREDENTIALS (DEVELOPMENT/EVALUATION ONLY):
    - Admin: admin@saffron.example / (DEMO_ADMIN_PASSWORD or 'DemoAdmin#2026!LocalOnly')
    - Store Manager 1: manager.kankarbagh@saffron.example / (DEMO_MANAGER_PASSWORD or 'DemoMgr#2026!Kankarbagh')
    - Store Manager 2: manager.kothrud@saffron.example / (DEMO_MANAGER_PASSWORD or 'DemoMgr#2026!Kothrud')
    - Customer: customer@example.com / (DEMO_CUSTOMER_PASSWORD or 'DemoCust#2026!Aarav')

    SECURITY SAFEGUARDS:
    - Demo accounts use clearly designated non-production synthetic passwords, never real credentials.
    - Raw passwords and hashes are NEVER printed or logged.
    - In non-demo/production environments (ENABLE_DEMO_ACCOUNTS=false), this function is never called.
    """
    return [
        {
            "email": "admin@saffron.example",
            "password": os.getenv("DEMO_ADMIN_PASSWORD", "DemoAdmin#2026!LocalOnly"),
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


def seed_database(db_path: Path | None = None, force_demo: bool = False) -> bool:
    """Initializes tables and optionally seeds synthetic demonstration accounts.

    Returns True if demo accounts were seeded, False if skipped due to mode restriction.
    """
    init_db(db_path)

    # Restriction: Only seed demo accounts in explicit development/demo mode
    if not settings.ENABLE_DEMO_ACCOUNTS and not force_demo:
        print("Database tables initialized. Demo account seeding disabled.")
        return False

    demo_users = get_demo_users()
    for u in demo_users:
        if u["role"] == "customer":
            try:
                AuthService.register_customer(
                    email=u["email"],
                    password=u["password"],
                    full_name=u["full_name"],
                    db_path=db_path,
                )
            except ValueError:
                # If customer already exists, update password and salt to ensure demo credentials work
                pwd_hash, salt = AuthService.hash_password(u["password"])
                from FULL_CODE.db.connection import get_db_connection
                with get_db_connection(db_path) as conn:
                    conn.execute(
                        """
                        UPDATE users
                        SET password_hash = ?, salt = ?, full_name = ?
                        WHERE email = ?;
                        """,
                        (pwd_hash, salt, u["full_name"], u["email"].lower()),
                    )
        else:
            AuthService.create_staff_user(
                email=u["email"],
                password=u["password"],
                full_name=u["full_name"],
                role=u["role"],
                assigned_store_id=u["assigned_store_id"],
                db_path=db_path,
            )

    # Seed initial incident alerts into SQLite if table is empty
    seed_alerts_from_flags(db_path=db_path)

    print(f"Database seeded successfully with {len(demo_users)} demo accounts and incident alerts.")
    return True


def seed_alerts_from_flags(db_path: Path | None = None) -> int:
    """Populates incident_alerts table in SQLite from candidate/submission flags idempotently."""
    import pandas as pd
    from FULL_CODE.db.connection import get_db_connection

    candidate_flags = ROOT / "FULL_CODE" / "phase5_candidate" / "R5_emerging_flags.csv"
    flags_path = candidate_flags if candidate_flags.exists() else (ROOT / "submission" / "R5_emerging_flags.csv")

    if not flags_path.exists():
        return 0

    df = pd.read_csv(flags_path, dtype=str)
    inserted_count = 0

    with get_db_connection(db_path) as conn:
        for _, r in df.iterrows():
            w = str(r["as_of_week_start"]).strip()
            sid = str(r["store_id"]).strip().upper()
            tid = str(r["issue_type_id"]).strip().upper()
            conf = float(r["confidence"])
            ev_ids = str(r.get("evidence_feedback_ids", "")).strip()
            alert_id = f"ALT-{w}-{sid}-{tid}"

            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO incident_alerts (
                    alert_id, store_id, issue_type_id, as_of_week_start,
                    confidence, evidence_feedback_ids, status
                ) VALUES (?, ?, ?, ?, ?, ?, 'new');
                """,
                (alert_id, sid, tid, w, conf, ev_ids),
            )
            inserted_count += cursor.rowcount

    return inserted_count


if __name__ == "__main__":
    seed_database()
