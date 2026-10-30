-- ============================================================================
-- R5 — Voice-of-Store Engine: Supabase Security Upgrade Script
-- Team: CodeNova | TalentAP Mega Hackathon 2026
-- ============================================================================
-- Purpose:
-- Applies targeted security hardening to an existing Supabase database where
-- all five tables (stores, profiles, feedback_submissions, incident_alerts,
-- audit_log) already exist.
--
-- Safety Safeguards:
-- 1. Preserves existing tables, schema structure, and data records without deletion.
-- 2. Revokes broad table-level UPDATE grants and applies column-level grants.
-- 3. Replaces triggers and policies idempotently.
-- 4. Contains NO table drops, NO truncations, and NO row deletions.
-- ============================================================================

-- ----------------------------------------------------------------------------
-- 1. Feedback Submissions: Set Default User Identity Binding
-- ----------------------------------------------------------------------------
-- Ensures every new submission without an explicit customer_user_id automatically
-- defaults to auth.uid() at the database level.
ALTER TABLE public.feedback_submissions 
    ALTER COLUMN customer_user_id SET DEFAULT auth.uid();

-- Re-verify customer insert policy (customers may submit feedback only as themselves)
DROP POLICY IF EXISTS "feedback_insert_policy" ON public.feedback_submissions;
CREATE POLICY "feedback_insert_policy" ON public.feedback_submissions
    FOR INSERT TO authenticated
    WITH CHECK (customer_user_id = auth.uid());

-- ----------------------------------------------------------------------------
-- 2. Profile Security: Revoke Broad Grants & Enforce Column-Level Update
-- ----------------------------------------------------------------------------
-- Revoke table-level UPDATE privileges from client roles
REVOKE UPDATE ON public.profiles FROM authenticated;
REVOKE UPDATE ON public.profiles FROM anon;

-- Grant UPDATE strictly on 'full_name'.
-- Email, role, assigned_store_id, id, and updated_at CANNOT be directly updated by authenticated users.
-- (updated_at is maintained automatically by the database trigger).
GRANT UPDATE (full_name) ON public.profiles TO authenticated;

-- Ensure service_role retains full administrative privileges
GRANT ALL ON public.profiles TO service_role;

-- Hardened Trigger: Rejects modifications to email, role, store, or id
-- Executed as SECURITY INVOKER to accurately inspect caller context and prevent escalation
CREATE OR REPLACE FUNCTION public.protect_profile_privileges()
RETURNS trigger SET search_path = public, pg_temp AS $$
DECLARE
  v_jwt_role text := coalesce(current_setting('request.jwt.claim.role', true), auth.role(), '');
BEGIN
  IF (OLD.role IS DISTINCT FROM NEW.role 
      OR OLD.assigned_store_id IS DISTINCT FROM NEW.assigned_store_id
      OR OLD.email IS DISTINCT FROM NEW.email
      OR OLD.id IS DISTINCT FROM NEW.id) THEN
    -- Default-Deny: Reject modifications unless caller is explicitly verified as service_role or database admin
    IF NOT (
      v_jwt_role = 'service_role'
      OR (v_jwt_role = '' AND current_user IN ('service_role', 'postgres', 'supabase_admin'))
    ) THEN
      RAISE EXCEPTION 'Unauthorized: User role, store assignments, email, and identity are server-controlled and cannot be modified by user.';
    END IF;
  END IF;
  NEW.updated_at = timezone('utc'::text, now());
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

REVOKE EXECUTE ON FUNCTION public.protect_profile_privileges() FROM PUBLIC;

DROP TRIGGER IF EXISTS trg_protect_profile_privileges ON public.profiles;
CREATE TRIGGER trg_protect_profile_privileges
  BEFORE UPDATE ON public.profiles
  FOR EACH ROW EXECUTE FUNCTION public.protect_profile_privileges();

-- ----------------------------------------------------------------------------
-- 3. Incident Alerts: Revoke Broad Grants, Restrict Columns & Enforce RLS
-- ----------------------------------------------------------------------------
-- Revoke table-level UPDATE privileges from client roles
REVOKE UPDATE ON public.incident_alerts FROM authenticated;
REVOKE UPDATE ON public.incident_alerts FROM anon;

-- Grant UPDATE strictly on operational resolution columns (status, resolved_by_user_id, resolution_note)
-- store_id, issue_type_id, as_of_week_start, confidence, evidence_ids, and updated_at cannot be updated by client
-- (updated_at is maintained automatically by the database trigger).
GRANT UPDATE (status, resolved_by_user_id, resolution_note) ON public.incident_alerts TO authenticated;

-- Ensure service_role retains full administrative privileges
GRANT ALL ON public.incident_alerts TO service_role;

-- Hardened RLS Policy: Enforces store isolation symmetrically in USING and WITH CHECK
DROP POLICY IF EXISTS "alerts_update_policy" ON public.incident_alerts;
CREATE POLICY "alerts_update_policy" ON public.incident_alerts
    FOR UPDATE TO authenticated
    USING (
        (
            public.get_my_role() = 'store_manager'
            AND public.get_my_store() IS NOT NULL
            AND store_id = public.get_my_store()
        )
        OR public.get_my_role() = 'admin'
    )
    WITH CHECK (
        status IN ('acknowledged', 'investigating', 'resolved')
        AND (
            public.get_my_role() = 'admin'
            OR (
                public.get_my_role() = 'store_manager'
                AND public.get_my_store() IS NOT NULL
                AND store_id = public.get_my_store()
            )
        )
    );

-- Anti-Tamper Trigger: Guards immutable alert fields (store_id, metrics, evidence)
-- Executed as SECURITY INVOKER to accurately inspect caller context and prevent tampering
CREATE OR REPLACE FUNCTION public.protect_alert_immutability()
RETURNS trigger SET search_path = public, pg_temp AS $$
DECLARE
  v_jwt_role text := coalesce(current_setting('request.jwt.claim.role', true), auth.role(), '');
BEGIN
  IF (OLD.store_id IS DISTINCT FROM NEW.store_id 
      OR OLD.issue_type_id IS DISTINCT FROM NEW.issue_type_id 
      OR OLD.as_of_week_start IS DISTINCT FROM NEW.as_of_week_start 
      OR OLD.confidence IS DISTINCT FROM NEW.confidence 
      OR OLD.evidence_feedback_ids IS DISTINCT FROM NEW.evidence_feedback_ids
      OR OLD.id IS DISTINCT FROM NEW.id) THEN
    -- Default-Deny: Reject modifications unless caller is explicitly verified as service_role or database admin
    IF NOT (
      v_jwt_role = 'service_role'
      OR (v_jwt_role = '' AND current_user IN ('service_role', 'postgres', 'supabase_admin'))
    ) THEN
      RAISE EXCEPTION 'Unauthorized: store_id and core detection metrics on incident alerts are immutable and cannot be altered.';
    END IF;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

REVOKE EXECUTE ON FUNCTION public.protect_alert_immutability() FROM PUBLIC;

DROP TRIGGER IF EXISTS trg_protect_alert_immutability ON public.incident_alerts;
CREATE TRIGGER trg_protect_alert_immutability
  BEFORE UPDATE ON public.incident_alerts
  FOR EACH ROW EXECUTE FUNCTION public.protect_alert_immutability();

-- ----------------------------------------------------------------------------
-- 4. Audit Log Immutability Verification
-- ----------------------------------------------------------------------------
-- Re-confirm that authenticated users can ONLY read audit logs (if admin)
-- and have zero INSERT, UPDATE, or DELETE grants.
REVOKE INSERT, UPDATE, DELETE ON public.audit_log FROM authenticated;
REVOKE INSERT, UPDATE, DELETE ON public.audit_log FROM anon;
GRANT SELECT ON public.audit_log TO authenticated, service_role;
GRANT ALL ON public.audit_log TO service_role;
