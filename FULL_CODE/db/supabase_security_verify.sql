-- ============================================================================
-- R5 — Voice-of-Store Engine: Supabase Security Verification Queries
-- Team: CodeNova | TalentAP Mega Hackathon 2026
-- ============================================================================
-- Purpose:
-- Inspects and verifies grants, column permissions, defaults, RLS policies,
-- and triggers in Supabase PostgreSQL after running supabase_security_upgrade.sql.
--
-- Usage:
-- Run in Supabase Dashboard -> SQL Editor to audit active security posture.
-- ============================================================================

-- ----------------------------------------------------------------------------
-- Verification Query 1: Column-Level UPDATE Permissions for 'authenticated'
-- ----------------------------------------------------------------------------
-- EXPECTED RESULT:
--   incident_alerts | resolution_note     | UPDATE | authenticated
--   incident_alerts | resolved_by_user_id | UPDATE | authenticated
--   incident_alerts | status              | UPDATE | authenticated
--   profiles        | full_name           | UPDATE | authenticated
SELECT 
    table_name, 
    column_name, 
    privilege_type, 
    grantee
FROM information_schema.column_privileges
WHERE table_schema = 'public' 
  AND grantee = 'authenticated' 
  AND privilege_type = 'UPDATE'
ORDER BY table_name, column_name;

-- ----------------------------------------------------------------------------
-- Verification Query 2: Table-Level UPDATE Permissions for 'authenticated'
-- ----------------------------------------------------------------------------
-- EXPECTED RESULT:
--   0 rows returned.
--   Confirms that broad table-level UPDATE is completely revoked.
SELECT 
    table_name, 
    privilege_type, 
    grantee
FROM information_schema.table_privileges
WHERE table_schema = 'public' 
  AND grantee = 'authenticated' 
  AND privilege_type = 'UPDATE';

-- ----------------------------------------------------------------------------
-- Verification Query 3: Default User Identity on feedback_submissions
-- ----------------------------------------------------------------------------
-- EXPECTED RESULT:
--   customer_user_id column_default: auth.uid()
SELECT 
    table_name, 
    column_name, 
    column_default, 
    is_nullable
FROM information_schema.columns
WHERE table_schema = 'public' 
  AND table_name = 'feedback_submissions' 
  AND column_name = 'customer_user_id';

-- ----------------------------------------------------------------------------
-- Verification Query 4: Active Row Level Security (RLS) Policies
-- ----------------------------------------------------------------------------
-- EXPECTED RESULT:
--   Active policies for stores, profiles, feedback_submissions, incident_alerts, audit_log
SELECT 
    tablename, 
    policyname, 
    permissive, 
    roles, 
    cmd, 
    qual, 
    with_check
FROM pg_policies
WHERE schemaname = 'public'
ORDER BY tablename, policyname;

-- ----------------------------------------------------------------------------
-- Verification Query 5: Active Anti-Tamper & Audit Triggers
-- ----------------------------------------------------------------------------
-- EXPECTED RESULT:
--   profiles        | trg_protect_profile_privileges | BEFORE UPDATE
--   incident_alerts | trg_log_alert_status_change    | BEFORE UPDATE
--   incident_alerts | trg_protect_alert_immutability | BEFORE UPDATE
SELECT 
    event_object_table, 
    trigger_name, 
    action_timing, 
    event_manipulation, 
    action_statement
FROM information_schema.triggers
WHERE trigger_schema = 'public'
ORDER BY event_object_table, trigger_name;
