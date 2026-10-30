-- ============================================================================
-- R5 — Voice-of-Store Engine: Supabase PostgreSQL Migration Script
-- Team: CodeNova | TalentAP Mega Hackathon 2026
-- ============================================================================
-- Architecture:
-- 1. Relational schema: stores, profiles, feedback_submissions, incident_alerts, audit_log.
-- 2. Foreign key constraints and check constraints.
-- 3. Row Level Security (RLS) enabled on every table.
-- 4. SECURITY DEFINER helper functions with pinned search_path.
-- 5. Immutability triggers to prevent client privilege escalation.
-- 6. Automated database-level audit logging for alert status updates.
-- ============================================================================

-- ----------------------------------------------------------------------------
-- 1. Table Definitions
-- ----------------------------------------------------------------------------

-- A. Retail Stores Fleet
CREATE TABLE IF NOT EXISTS public.stores (
    store_id TEXT PRIMARY KEY,
    store_name TEXT NOT NULL,
    city TEXT NOT NULL,
    state TEXT NOT NULL,
    region TEXT NOT NULL CHECK (region IN ('North', 'South', 'East', 'West', 'Central')),
    format TEXT NOT NULL CHECK (format IN ('Saffron Hyper', 'Saffron Market', 'Saffron Express')),
    size_sqft INTEGER,
    avg_weekly_footfall INTEGER,
    opened_date TEXT
);

-- B. User Profiles (1:1 with auth.users)
CREATE TABLE IF NOT EXISTS public.profiles (
    id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    email TEXT NOT NULL,
    full_name TEXT NOT NULL DEFAULT 'User',
    role TEXT NOT NULL DEFAULT 'customer' CHECK (role IN ('admin', 'store_manager', 'customer')),
    assigned_store_id TEXT REFERENCES public.stores(store_id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now()),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now())
);

-- C. Customer Feedback Submissions
CREATE TABLE IF NOT EXISTS public.feedback_submissions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    customer_user_id UUID DEFAULT auth.uid() REFERENCES public.profiles(id) ON DELETE SET NULL,
    feedback_id TEXT UNIQUE NOT NULL,
    text TEXT NOT NULL,
    channel TEXT NOT NULL CHECK (channel IN ('online_review', 'in_app', 'staff_shift_note', 'call_centre_ticket')),
    rating NUMERIC CHECK (rating >= 1.0 AND rating <= 5.0),
    store_id TEXT REFERENCES public.stores(store_id) ON DELETE SET NULL,
    issue_type_id TEXT,
    severity TEXT CHECK (severity IN ('low', 'medium', 'high', 'critical')),
    actionable SMALLINT CHECK (actionable IN (0, 1)),
    is_routable SMALLINT CHECK (is_routable IN (0, 1)),
    owner_function TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now())
);

-- D. Emerging Incident Alerts Radar
CREATE TABLE IF NOT EXISTS public.incident_alerts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    store_id TEXT NOT NULL REFERENCES public.stores(store_id) ON DELETE CASCADE,
    issue_type_id TEXT NOT NULL,
    as_of_week_start TEXT NOT NULL,
    confidence NUMERIC NOT NULL CHECK (confidence >= 0.0 AND confidence <= 1.0),
    evidence_feedback_ids TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'detected' CHECK (status IN ('detected', 'acknowledged', 'investigating', 'resolved')),
    resolved_by_user_id UUID REFERENCES public.profiles(id) ON DELETE SET NULL,
    resolution_note TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now()),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now())
);

-- E. Immutable System Audit Log
CREATE TABLE IF NOT EXISTS public.audit_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES auth.users(id) ON DELETE SET NULL,
    action TEXT NOT NULL,
    target_type TEXT NOT NULL,
    target_id TEXT NOT NULL,
    details JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now())
);

-- ----------------------------------------------------------------------------
-- 2. Performance & Query Indices
-- ----------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_stores_region ON public.stores(region);
CREATE INDEX IF NOT EXISTS idx_profiles_role ON public.profiles(role);
CREATE INDEX IF NOT EXISTS idx_profiles_store ON public.profiles(assigned_store_id);
CREATE INDEX IF NOT EXISTS idx_feedback_store ON public.feedback_submissions(store_id);
CREATE INDEX IF NOT EXISTS idx_feedback_customer ON public.feedback_submissions(customer_user_id);
CREATE INDEX IF NOT EXISTS idx_alerts_store ON public.incident_alerts(store_id);
CREATE INDEX IF NOT EXISTS idx_alerts_status ON public.incident_alerts(status);
CREATE INDEX IF NOT EXISTS idx_audit_created ON public.audit_log(created_at DESC);

-- ----------------------------------------------------------------------------
-- 3. Security Helper Functions (SECURITY DEFINER with Pinned Search Path)
-- ----------------------------------------------------------------------------

-- Helper A: Resolve Authenticated User's Role (Avoids Recursive RLS on profiles)
CREATE OR REPLACE FUNCTION public.get_my_role()
RETURNS text STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
  SELECT coalesce((SELECT role FROM public.profiles WHERE id = auth.uid()), 'anon');
$$ LANGUAGE sql;

-- Helper B: Resolve Authenticated User's Assigned Store
CREATE OR REPLACE FUNCTION public.get_my_store()
RETURNS text STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
  SELECT assigned_store_id FROM public.profiles WHERE id = auth.uid();
$$ LANGUAGE sql;

-- Revoke default public execute grants and assign to authenticated only
REVOKE EXECUTE ON FUNCTION public.get_my_role() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.get_my_role() TO authenticated;
GRANT EXECUTE ON FUNCTION public.get_my_role() TO service_role;

REVOKE EXECUTE ON FUNCTION public.get_my_store() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.get_my_store() TO authenticated;
GRANT EXECUTE ON FUNCTION public.get_my_store() TO service_role;

-- ----------------------------------------------------------------------------
-- 4. Automatic User Profile Provisioning Trigger (auth.users -> public.profiles)
-- ----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS trigger SECURITY DEFINER SET search_path = public, pg_temp AS $$
BEGIN
  -- SAFETY RULE: Public registration strictly creates 'customer' accounts with NULL store
  INSERT INTO public.profiles (id, email, full_name, role, assigned_store_id)
  VALUES (
    new.id,
    coalesce(new.email, 'unknown@example.com'),
    coalesce(new.raw_user_meta_data->>'full_name', 'Customer'),
    'customer',
    NULL
  )
  ON CONFLICT (id) DO NOTHING;
  RETURN new;
END;
$$ LANGUAGE plpgsql;

REVOKE EXECUTE ON FUNCTION public.handle_new_user() FROM PUBLIC;

DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;
CREATE TRIGGER on_auth_user_created
  AFTER INSERT ON auth.users
  FOR EACH ROW EXECUTE FUNCTION public.handle_new_user();

-- ----------------------------------------------------------------------------
-- 5. Anti-Privilege Escalation Trigger (Protects email, role, store & id)
-- ----------------------------------------------------------------------------
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
-- 6. Automated Audit Log Trigger (Captures Real Actor & Prevents Forged Logs)
-- ----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.log_alert_status_change()
RETURNS trigger SECURITY DEFINER SET search_path = public, pg_temp AS $$
BEGIN
  IF (OLD.status IS DISTINCT FROM NEW.status) THEN
    INSERT INTO public.audit_log (user_id, action, target_type, target_id, details)
    VALUES (
      auth.uid(),
      'ALERT_STATUS_UPDATE',
      'incident_alerts',
      NEW.id::text,
      jsonb_build_object(
        'old_status', OLD.status,
        'new_status', NEW.status,
        'store_id', NEW.store_id,
        'resolved_by', NEW.resolved_by_user_id,
        'resolution_note', NEW.resolution_note
      )
    );
  END IF;
  NEW.updated_at = timezone('utc'::text, now());
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

REVOKE EXECUTE ON FUNCTION public.log_alert_status_change() FROM PUBLIC;

DROP TRIGGER IF EXISTS trg_log_alert_status_change ON public.incident_alerts;
CREATE TRIGGER trg_log_alert_status_change
  BEFORE UPDATE ON public.incident_alerts
  FOR EACH ROW EXECUTE FUNCTION public.log_alert_status_change();

-- ----------------------------------------------------------------------------
-- 7. Alert Core Immutability Trigger (Protects store_id, metrics & evidence)
-- ----------------------------------------------------------------------------
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
-- 8. Row Level Security (RLS) Policies
-- ----------------------------------------------------------------------------

-- Enable RLS on all tables
ALTER TABLE public.stores ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.feedback_submissions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.incident_alerts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.audit_log ENABLE ROW LEVEL SECURITY;

-- Policy A: public.stores
-- Read-only directory open to all authenticated users and anon for store lookups
DROP POLICY IF EXISTS "stores_read_policy" ON public.stores;
CREATE POLICY "stores_read_policy" ON public.stores
    FOR SELECT TO authenticated, anon
    USING (true);

-- Policy B: public.profiles
-- Users can view own profile; Admin can view all profiles
DROP POLICY IF EXISTS "profiles_select_policy" ON public.profiles;
CREATE POLICY "profiles_select_policy" ON public.profiles
    FOR SELECT TO authenticated
    USING (
        id = auth.uid() 
        OR public.get_my_role() = 'admin'
    );

-- Users can only update their own display name (trigger blocks role/store changes)
DROP POLICY IF EXISTS "profiles_update_policy" ON public.profiles;
CREATE POLICY "profiles_update_policy" ON public.profiles
    FOR UPDATE TO authenticated
    USING (id = auth.uid())
    WITH CHECK (id = auth.uid());

-- Policy C: public.feedback_submissions
-- Customers can submit feedback bound to their own identity (no impersonation)
DROP POLICY IF EXISTS "feedback_insert_policy" ON public.feedback_submissions;
CREATE POLICY "feedback_insert_policy" ON public.feedback_submissions
    FOR INSERT TO authenticated
    WITH CHECK (customer_user_id = auth.uid());

-- Customers see only own feedback; Store Managers see assigned store feedback; Admin sees all
DROP POLICY IF EXISTS "feedback_select_policy" ON public.feedback_submissions;
CREATE POLICY "feedback_select_policy" ON public.feedback_submissions
    FOR SELECT TO authenticated
    USING (
        customer_user_id = auth.uid()
        OR (
            public.get_my_role() = 'store_manager'
            AND public.get_my_store() IS NOT NULL
            AND store_id = public.get_my_store()
        )
        OR public.get_my_role() = 'admin'
    );

-- Policy D: public.incident_alerts
-- Store Managers see alerts for assigned store only; Admin sees all; Customers/Anon denied (0 rows)
DROP POLICY IF EXISTS "alerts_select_policy" ON public.incident_alerts;
CREATE POLICY "alerts_select_policy" ON public.incident_alerts
    FOR SELECT TO authenticated
    USING (
        (
            public.get_my_role() = 'store_manager'
            AND public.get_my_store() IS NOT NULL
            AND store_id = public.get_my_store()
        )
        OR public.get_my_role() = 'admin'
    );

-- Store Managers can acknowledge/resolve alerts for their store only; Admin can update all
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

-- Policy E: public.audit_log
-- Admin can view audit logs; All clients DENIED direct INSERT/UPDATE/DELETE (written via triggers only)
DROP POLICY IF EXISTS "audit_select_policy" ON public.audit_log;
CREATE POLICY "audit_select_policy" ON public.audit_log
    FOR SELECT TO authenticated
    USING (public.get_my_role() = 'admin');

-- ----------------------------------------------------------------------------
-- 9. Table & Column-Level Grants (Principle of Least Privilege)
-- ----------------------------------------------------------------------------
-- Grant schema usage to standard Supabase roles
GRANT USAGE ON SCHEMA public TO anon, authenticated, service_role;

-- A. Stores: read-only directory open to all
GRANT SELECT ON public.stores TO anon, authenticated, service_role;

-- B. Profiles: authenticated users can only update 'full_name'
-- Role, email, and assigned_store_id are strictly non-grantable to authenticated
GRANT SELECT ON public.profiles TO authenticated, service_role;
GRANT UPDATE (full_name) ON public.profiles TO authenticated;
GRANT ALL ON public.profiles TO service_role;

-- C. Feedback Submissions: authenticated users can only select and submit
GRANT SELECT, INSERT ON public.feedback_submissions TO authenticated, service_role;
GRANT ALL ON public.feedback_submissions TO service_role;

-- D. Incident Alerts: authenticated users can only update status, resolved_by, and resolution_note
-- store_id, issue_type_id, confidence, and evidence IDs are strictly protected from modification
GRANT SELECT ON public.incident_alerts TO authenticated, service_role;
GRANT UPDATE (status, resolved_by_user_id, resolution_note) ON public.incident_alerts TO authenticated;
GRANT ALL ON public.incident_alerts TO service_role;

-- E. Audit Log: read-only for authenticated (RLS restricts to admin); write restricted to service_role/triggers
GRANT SELECT ON public.audit_log TO authenticated, service_role;
GRANT ALL ON public.audit_log TO service_role;

-- ============================================================================
-- End of Migration Script
-- ============================================================================
