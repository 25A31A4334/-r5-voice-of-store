-- TalentAP Mega Hackathon 2026 - Database Schema (Rule 2 & 4)
-- R5 Voice-of-Store Engine

PRAGMA foreign_keys = ON;

-- 1. Users & Authentication
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    salt TEXT NOT NULL,
    full_name TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('customer', 'store_manager', 'admin')),
    assigned_store_id TEXT, -- Null for customer/admin; valid store_id for store_manager
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
CREATE INDEX IF NOT EXISTS idx_users_role ON users(role);

-- 2. Customer Feedback Submissions & Triage
CREATE TABLE IF NOT EXISTS feedback_submissions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    feedback_id TEXT UNIQUE NOT NULL,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    store_id TEXT,
    channel TEXT NOT NULL,
    rating INTEGER,
    text TEXT NOT NULL,
    predicted_issue_type_id TEXT,
    predicted_severity TEXT,
    predicted_actionable INTEGER,
    owner_function TEXT,
    status TEXT DEFAULT 'new' CHECK(status IN ('new', 'acknowledged', 'investigating', 'resolved')),
    resolution_notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_feedback_store ON feedback_submissions(store_id);
CREATE INDEX IF NOT EXISTS idx_feedback_issue ON feedback_submissions(predicted_issue_type_id);

-- 3. Incident Alerts & Store Actions
CREATE TABLE IF NOT EXISTS incident_alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    alert_id TEXT UNIQUE NOT NULL,
    store_id TEXT NOT NULL,
    issue_type_id TEXT NOT NULL,
    as_of_week_start TEXT NOT NULL,
    confidence REAL NOT NULL,
    evidence_feedback_ids TEXT NOT NULL,
    status TEXT DEFAULT 'new' CHECK(status IN ('new', 'acknowledged', 'investigating', 'resolved')),
    acknowledged_by_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    resolution_notes TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_alerts_store ON incident_alerts(store_id);
CREATE INDEX IF NOT EXISTS idx_alerts_week ON incident_alerts(as_of_week_start);

-- 4. Audit Trail for Security & Actions (Rule 10)
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    action TEXT NOT NULL,
    target_type TEXT NOT NULL,
    target_id TEXT NOT NULL,
    details TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_log(user_id);
