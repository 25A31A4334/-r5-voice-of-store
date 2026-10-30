"""SQLite Database Backup & Export Utility (Team CodeNova).

Usage:
    # Verify existing backups and exports without creating new files:
    python FULL_CODE/db/export_sqlite.py --verify

    # Create a fresh timestamped backup snapshot:
    python FULL_CODE/db/export_sqlite.py --backup

Safeguards:
- Never deletes or overwrites existing database or backups.
- Backups are stored with immutable UTC timestamps.
- Sanitizes sensitive password hashes and salts in JSON dumps.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[2]
FULL_CODE_DIR = ROOT / "FULL_CODE"
DB_PATH = FULL_CODE_DIR / "r5_store.db"
BACKUP_DIR = FULL_CODE_DIR / "db" / "backups"


def verify_backups() -> bool:
    """Verifies existing SQLite database and backup integrity without modifying files."""
    print("=" * 70)
    print("SQLITE DATABASE & BACKUP VERIFICATION REPORT")
    print("=" * 70)

    # 1. Verify Primary Database
    if not DB_PATH.exists():
        print(f"[FAIL] Primary database not found at {DB_PATH}")
        return False

    db_size = DB_PATH.stat().st_size
    print(f"[OK] Primary SQLite DB: {DB_PATH.name} ({db_size:,} bytes)")

    try:
        conn = sqlite3.connect(str(DB_PATH))
        cur = conn.cursor()
        integrity = cur.execute("PRAGMA integrity_check;").fetchall()
        cur.execute("SELECT COUNT(*) FROM users;")
        user_count = cur.fetchone()[0]
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';")
        tables = [r[0] for r in cur.fetchall()]
        conn.close()
        print(f"     -> Integrity check: {integrity[0][0]}")
        print(f"     -> Tables found: {', '.join(tables)}")
        print(f"     -> Users registered: {user_count}")
    except Exception as exc:
        print(f"[FAIL] Primary database check error: {exc}")
        return False

    # 2. Verify Backup Directory & Snapshots
    if not BACKUP_DIR.exists():
        print(f"[WARN] Backup directory {BACKUP_DIR} does not exist yet.")
        return False

    backup_dbs = sorted(BACKUP_DIR.glob("*.db"))
    if not backup_dbs:
        print(f"[WARN] No binary .db backups found in {BACKUP_DIR}")
        return False

    print(f"\n[OK] Found {len(backup_dbs)} binary database backup(s):")
    all_backups_ok = True
    for b_path in backup_dbs:
        try:
            b_size = b_path.stat().st_size
            b_conn = sqlite3.connect(str(b_path))
            b_cur = b_conn.cursor()
            b_integrity = b_cur.execute("PRAGMA integrity_check;").fetchall()
            b_cur.execute("SELECT COUNT(*) FROM users;")
            b_users = b_cur.fetchone()[0]
            b_conn.close()
            status = "OK" if b_integrity and b_integrity[0][0] == "ok" else "CORRUPT"
            print(f"     * {b_path.name} ({b_size:,} bytes) -> {status} | {b_users} users verified")
        except Exception as b_exc:
            print(f"     * [FAIL] {b_path.name}: {b_exc}")
            all_backups_ok = False

    # 3. Verify JSON Data Dumps
    json_dumps = sorted(BACKUP_DIR.glob("*.json"))
    print(f"\n[OK] Found {len(json_dumps)} structured JSON export dump(s):")
    for j_path in json_dumps:
        try:
            with open(j_path, "r", encoding="utf-8") as f:
                dump_data = json.load(f)
            t_counts = {t: info.get("row_count", 0) for t, info in dump_data.get("tables", {}).items()}
            print(f"     * {j_path.name} ({j_path.stat().st_size:,} bytes) -> Valid JSON | Rows: {t_counts}")
        except Exception as j_exc:
            print(f"     * [FAIL] {j_path.name}: {j_exc}")
            all_backups_ok = False

    print("=" * 70)
    print("VERIFICATION COMPLETE: ALL ARTIFACTS VERIFIED SUCCESSFULLY" if all_backups_ok else "VERIFICATION FAILED")
    print("=" * 70)
    return all_backups_ok


def backup_and_export_sqlite() -> Dict[str, Any]:
    """Creates a fresh timestamped binary backup copy and a structured JSON data dump."""
    if not DB_PATH.exists():
        print(f"[Error] Database not found at {DB_PATH}, nothing to backup.")
        sys.exit(1)

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup_file = BACKUP_DIR / f"r5_store.backup_{timestamp}.db"

    # 1. Binary copy of SQLite database file (unique timestamp, never overwriting)
    shutil.copy2(DB_PATH, backup_file)
    print(f"[Backup] Successfully created snapshot: {backup_file.name}")

    # 2. Extract structured JSON data dump
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    dump_data: Dict[str, Any] = {
        "metadata": {
            "source_db": str(DB_PATH),
            "backup_file": str(backup_file),
            "timestamp": timestamp,
        },
        "tables": {},
    }

    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';")
    tables = [row["name"] for row in cursor.fetchall()]

    for table in tables:
        cursor.execute(f"SELECT * FROM {table};")
        rows = [dict(r) for r in cursor.fetchall()]
        sanitized_rows: List[Dict[str, Any]] = []
        for r in rows:
            clean_r = dict(r)
            if "password_hash" in clean_r:
                clean_r["password_hash_present"] = bool(clean_r["password_hash"])
                del clean_r["password_hash"]
            if "salt" in clean_r:
                clean_r["salt_present"] = bool(clean_r["salt"])
                del clean_r["salt"]
            sanitized_rows.append(clean_r)

        dump_data["tables"][table] = {
            "row_count": len(rows),
            "rows": sanitized_rows,
        }
        print(f"[Export] Table '{table}': {len(rows)} rows dumped.")

    conn.close()

    dump_file = BACKUP_DIR / f"sqlite_data_dump_{timestamp}.json"
    with open(dump_file, "w", encoding="utf-8") as f:
        json.dump(dump_data, f, indent=2)

    latest_dump_file = FULL_CODE_DIR / "db" / "sqlite_data_dump_latest.json"
    with open(latest_dump_file, "w", encoding="utf-8") as f:
        json.dump(dump_data, f, indent=2)

    print(f"[Export] Successfully wrote JSON data snapshot to {dump_file.name}")
    return dump_data


def main() -> None:
    parser = argparse.ArgumentParser(description="SQLite Backup & Verification Utility (Team CodeNova)")
    parser.add_argument("--verify", action="store_true", help="Verify existing database and backups without modifying files.")
    parser.add_argument("--backup", action="store_true", help="Create a fresh timestamped backup snapshot.")
    args = parser.parse_args()

    # Default to verify mode if no action is specified, protecting against accidental writes
    if args.backup:
        backup_and_export_sqlite()
    else:
        success = verify_backups()
        if not success:
            sys.exit(1)


if __name__ == "__main__":
    main()
