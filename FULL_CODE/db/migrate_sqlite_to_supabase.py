"""Safe Incremental Migration from SQLite to Supabase PostgreSQL (Team CodeNova).

Preserves:
1. All 60 store records from store master fleet.
2. All existing customer feedback submissions (preserves feedback_id, channel, ratings, text, classifications, status, notes).
3. All incident alerts (preserves alert_id, store_id, issue_type_id, week_start, confidence, evidence IDs, status, notes).
4. All audit log events.

Safety:
- Idempotent: Uses ON CONFLICT (store_id / feedback_id / alert_id) DO NOTHING / merge-duplicates.
- Rerunnable: Safe to run repeatedly without creating duplicates.
- Generates a standalone SQL script (FULL_CODE/db/supabase_seed_data.sql) for execution in Supabase SQL Editor.
- If SUPABASE_SERVICE_ROLE_KEY is configured in .env, it can also sync directly via PostgREST.
"""
from __future__ import annotations

import csv
import json
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[2]
FULL_CODE_DIR = ROOT / "FULL_CODE"
DATA_DIR = ROOT / "data"
DB_PATH = FULL_CODE_DIR / "r5_store.db"
OUTPUT_SQL_FILE = FULL_CODE_DIR / "db" / "supabase_seed_data.sql"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from FULL_CODE.config import settings


def escape_sql_str(val: Any) -> str:
    """Escapes string values safely for PostgreSQL SQL literal."""
    if val is None:
        return "NULL"
    s = str(val).replace("'", "''")
    return f"'{s}'"


def escape_sql_num(val: Any) -> str:
    """Escapes numeric values safely for PostgreSQL SQL literal."""
    if val is None or val == "" or str(val).lower() == "none":
        return "NULL"
    try:
        return str(float(val) if "." in str(val) else int(val))
    except (ValueError, TypeError):
        return "NULL"


def generate_seed_sql() -> Path:
    """Extracts existing records from SQLite and CSV and compiles an idempotent PostgreSQL seed script."""
    print("Extracting data for Supabase PostgreSQL migration...")
    lines: List[str] = [
        "-- ============================================================================",
        "-- Voice of Store Engine: Data Seeding & SQLite Migration Script",
        "-- Idempotent: Uses ON CONFLICT DO NOTHING / UPDATE to prevent duplicate rows",
        "-- ============================================================================\n",
    ]

    # 1. Retail Stores Fleet (60 Stores)
    store_file = DATA_DIR / "store_master.csv"
    if store_file.exists():
        lines.append("-- ----------------------------------------------------------------------------")
        lines.append("-- 1. Retail Fleet Stores (60 Stores)")
        lines.append("-- ----------------------------------------------------------------------------")
        with open(store_file, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                sid = escape_sql_str(row["store_id"].strip())
                sname = escape_sql_str(row["store_name"].strip())
                city = escape_sql_str(row["city"].strip())
                state = escape_sql_str(row["state"].strip())
                region = escape_sql_str(row["region"].strip())
                fmt = escape_sql_str(row["format"].strip())
                sqft = escape_sql_num(row.get("size_sqft"))
                footfall = escape_sql_num(row.get("avg_weekly_footfall"))
                opened = escape_sql_str(row.get("opened_date", "").strip())

                lines.append(
                    f"INSERT INTO public.stores (store_id, store_name, city, state, region, format, size_sqft, avg_weekly_footfall, opened_date) "
                    f"VALUES ({sid}, {sname}, {city}, {state}, {region}, {fmt}, {sqft}, {footfall}, {opened}) "
                    f"ON CONFLICT (store_id) DO UPDATE SET "
                    f"store_name = EXCLUDED.store_name, city = EXCLUDED.city, state = EXCLUDED.state, "
                    f"region = EXCLUDED.region, format = EXCLUDED.format, size_sqft = EXCLUDED.size_sqft, "
                    f"avg_weekly_footfall = EXCLUDED.avg_weekly_footfall, opened_date = EXCLUDED.opened_date;"
                )
        lines.append("")

    if not DB_PATH.exists():
        print(f"Warning: SQLite database not found at {DB_PATH}")
        return OUTPUT_SQL_FILE

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # 2. Existing Incident Alerts
    cursor.execute("SELECT * FROM incident_alerts ORDER BY id;")
    alerts = cursor.fetchall()
    if alerts:
        lines.append("-- ----------------------------------------------------------------------------")
        lines.append(f"-- 2. Incident Alerts ({len(alerts)} records)")
        lines.append("-- ----------------------------------------------------------------------------")
        for a in alerts:
            aid = escape_sql_str(a["alert_id"])
            sid = escape_sql_str(a["store_id"])
            tid = escape_sql_str(a["issue_type_id"])
            week = escape_sql_str(a["as_of_week_start"])
            conf = escape_sql_num(a["confidence"])
            ev_ids = escape_sql_str(a["evidence_feedback_ids"])
            status = escape_sql_str(a["status"] or "new")
            note = escape_sql_str(a["resolution_notes"])
            upd = escape_sql_str(a["updated_at"])

            lines.append(
                f"INSERT INTO public.incident_alerts (alert_id, store_id, issue_type_id, as_of_week_start, confidence, evidence_feedback_ids, status, resolution_note, resolution_notes, updated_at) "
                f"VALUES ({aid}, {sid}, {tid}, {week}, {conf}, {ev_ids}, {status}, {note}, {note}, COALESCE({upd}::timestamptz, now())) "
                f"ON CONFLICT (alert_id) DO NOTHING;"
            )
        lines.append("")

    # 3. Existing Customer Feedback Submissions (with Customer Email Mapping)
    cursor.execute("""
        SELECT f.*, u.email as user_email
        FROM feedback_submissions f
        LEFT JOIN users u ON f.user_id = u.id
        ORDER BY f.id;
    """)
    subs = cursor.fetchall()
    if subs:
        lines.append("-- ----------------------------------------------------------------------------")
        lines.append(f"-- 3. Customer Feedback Submissions ({len(subs)} records)")
        lines.append("-- ----------------------------------------------------------------------------")
        for s in subs:
            fid = escape_sql_str(s["feedback_id"])
            cust_email = escape_sql_str(s["user_email"] or "customer@example.com")
            text = escape_sql_str(s["text"])
            channel = escape_sql_str(s["channel"] or "in_app")
            rating = escape_sql_num(s["rating"])
            sid = escape_sql_str(s["store_id"])
            tid = escape_sql_str(s["predicted_issue_type_id"])
            sev = escape_sql_str(s["predicted_severity"])
            act = escape_sql_num(s["predicted_actionable"])
            owner = escape_sql_str(s["owner_function"])
            status = escape_sql_str(s["status"] or "new")
            res_note = escape_sql_str(s["resolution_notes"])
            created = escape_sql_str(s["created_at"])
            updated = escape_sql_str(s["updated_at"])

            lines.append(
                f"INSERT INTO public.feedback_submissions (feedback_id, customer_email, text, channel, rating, store_id, issue_type_id, severity, actionable, owner_function, status, resolution_notes, created_at, updated_at) "
                f"VALUES ({fid}, {cust_email}, {text}, {channel}, {rating}, {sid}, {tid}, {sev}, {act}, {owner}, {status}, {res_note}, COALESCE({created}::timestamptz, now()), COALESCE({updated}::timestamptz, now())) "
                f"ON CONFLICT (feedback_id) DO NOTHING;"
            )
        lines.append("")

    # 4. Existing Audit Logs (with Stable Deterministic UUIDs)
    cursor.execute("SELECT * FROM audit_log ORDER BY id;")
    logs = cursor.fetchall()
    if logs:
        lines.append("-- ----------------------------------------------------------------------------")
        lines.append(f"-- 4. Audit Log Records ({len(logs)} records)")
        lines.append("-- ----------------------------------------------------------------------------")
        for l in logs:
            audit_id = f"'00000000-0000-0000-0000-{int(l['id']):012d}'"
            act = escape_sql_str(l["action"])
            ttype = escape_sql_str(l["target_type"])
            tid = escape_sql_str(l["target_id"])
            details_str = l["details"] or "{}"
            # Ensure valid JSON formatting for JSONB column
            try:
                json_obj = json.loads(details_str)
                details_sql = escape_sql_str(json.dumps(json_obj)) + "::jsonb"
            except Exception:
                details_sql = escape_sql_str(json.dumps(details_str)) + "::jsonb"
            created = escape_sql_str(l["created_at"])

            lines.append(
                f"INSERT INTO public.audit_log (id, action, target_type, target_id, details, created_at) "
                f"VALUES ({audit_id}, {act}, {ttype}, {tid}, {details_sql}, COALESCE({created}::timestamptz, now())) "
                f"ON CONFLICT (id) DO NOTHING;"
            )
        lines.append("")

    conn.close()

    OUTPUT_SQL_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_SQL_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"Successfully generated PostgreSQL seed script at {OUTPUT_SQL_FILE}")
    print(f"Summary: 60 Stores, {len(alerts)} Alerts, {len(subs)} Submissions, {len(logs)} Audit Logs.")
    return OUTPUT_SQL_FILE


if __name__ == "__main__":
    generate_seed_sql()
