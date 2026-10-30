"""Thread-Safe Database Connection & Schema Management (Team CodeNova).

Follows Rule 4: Parameterized queries, foreign key enforcement, no SQL string building.
Follows Rule 2: Schema in repo, database files not committed to Git.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

try:
    from FULL_CODE.config import settings
except ImportError:
    from config import settings

DB_DIR = Path(__file__).resolve().parent
SCHEMA_FILE = DB_DIR / "schema.sql"


@contextmanager
def get_db_connection(db_path: Path | None = None) -> Generator[sqlite3.Connection, None, None]:
    """Context manager for SQLite connections with foreign keys and row factory."""
    target_path = db_path or settings.DATABASE_PATH
    target_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(target_path), timeout=10.0)
    conn.row_factory = sqlite3.Row
    # Rule 4: Enforce foreign key constraints in SQLite
    conn.execute("PRAGMA foreign_keys = ON;")

    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: Path | None = None) -> None:
    """Initializes SQLite database tables from schema.sql and runs backward-compatible migrations."""
    if not SCHEMA_FILE.exists():
        raise FileNotFoundError(f"Schema file not found at {SCHEMA_FILE}")

    with open(SCHEMA_FILE, "r", encoding="utf-8") as f:
        schema_sql = f.read()

    with get_db_connection(db_path) as conn:
        conn.executescript(schema_sql)
        # Backward-compatible column migration for feedback_submissions
        try:
            cols = [r["name"] for r in conn.execute("PRAGMA table_info(feedback_submissions)").fetchall()]
            if "resolution_notes" not in cols:
                conn.execute("ALTER TABLE feedback_submissions ADD COLUMN resolution_notes TEXT;")
            if "updated_at" not in cols:
                conn.execute("ALTER TABLE feedback_submissions ADD COLUMN updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;")
        except Exception:
            pass
