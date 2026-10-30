-- ============================================================================
-- Voice of Store Engine — Phase 2 Consolidated Supabase SQL Migration
-- Architecture: Supabase PostgreSQL + GoTrue Auth + Row Level Security (RLS)
-- ============================================================================
-- Safeguards:
-- 1. Idempotent: Uses IF NOT EXISTS, DROP POLICY IF EXISTS, etc.
-- 2. Non-destructive: NO DROP TABLE, NO TRUNCATE, NO DELETE statements.
-- 3. Zero data loss: Preserves all existing records in PostgreSQL.
-- 4. Principle of Least Privilege: Column-level grants and strict RLS isolation.
-- ============================================================================

-- ----------------------------------------------------------------------------
-- 1. Base Table Schema Verification & Column Harmonization
-- ----------------------------------------------------------------------------

-- A. Retail Stores Fleet
CREATE TABLE IF NOT EXISTS public.stores (
    store_id TEXT PRIMARY KEY,
    store_name TEXT NOT NULL,
    city TEXT NOT NULL,
    state TEXT NOT NULL,
    region TEXT NOT NULL,
    format TEXT NOT NULL,
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

-- Ensure incremental columns exist on profiles if created previously
ALTER TABLE public.profiles ADD COLUMN IF NOT EXISTS role TEXT NOT NULL DEFAULT 'customer';
ALTER TABLE public.profiles ADD COLUMN IF NOT EXISTS assigned_store_id TEXT REFERENCES public.stores(store_id) ON DELETE SET NULL;
ALTER TABLE public.profiles ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT timezone('utc'::text, now());

-- C. Customer Feedback Submissions
CREATE TABLE IF NOT EXISTS public.feedback_submissions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    customer_user_id UUID REFERENCES public.profiles(id) ON DELETE SET NULL,
    customer_email TEXT,
    feedback_id TEXT UNIQUE NOT NULL,
    text TEXT NOT NULL,
    channel TEXT NOT NULL DEFAULT 'in_app',
    rating NUMERIC CHECK (rating >= 1.0 AND rating <= 5.0),
    store_id TEXT REFERENCES public.stores(store_id) ON DELETE SET NULL,
    issue_type_id TEXT,
    severity TEXT,
    actionable SMALLINT DEFAULT 0,
    is_routable SMALLINT DEFAULT 1,
    owner_function TEXT,
    status TEXT DEFAULT 'new',
    resolution_notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now()),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now())
);

-- Ensure incremental columns exist on feedback_submissions if created previously
ALTER TABLE public.feedback_submissions ADD COLUMN IF NOT EXISTS customer_user_id UUID REFERENCES public.profiles(id) ON DELETE SET NULL;
ALTER TABLE public.feedback_submissions ADD COLUMN IF NOT EXISTS customer_email TEXT;
ALTER TABLE public.feedback_submissions ALTER COLUMN customer_user_id SET DEFAULT auth.uid();
ALTER TABLE public.feedback_submissions ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'new';
ALTER TABLE public.feedback_submissions ADD COLUMN IF NOT EXISTS resolution_notes TEXT;
ALTER TABLE public.feedback_submissions ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT timezone('utc'::text, now());
ALTER TABLE public.feedback_submissions ADD COLUMN IF NOT EXISTS is_routable SMALLINT DEFAULT 1;
ALTER TABLE public.feedback_submissions DROP CONSTRAINT IF EXISTS feedback_submissions_status_check;
ALTER TABLE public.feedback_submissions ADD CONSTRAINT feedback_submissions_status_check 
    CHECK (status IN ('new', 'acknowledged', 'investigating', 'resolved'));

-- D. Emerging Incident Alerts Radar
CREATE TABLE IF NOT EXISTS public.incident_alerts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    alert_id TEXT UNIQUE,
    store_id TEXT NOT NULL REFERENCES public.stores(store_id) ON DELETE CASCADE,
    issue_type_id TEXT NOT NULL,
    as_of_week_start TEXT NOT NULL,
    confidence NUMERIC NOT NULL DEFAULT 0.5,
    evidence_feedback_ids TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'new',
    resolved_by_user_id UUID REFERENCES public.profiles(id) ON DELETE SET NULL,
    resolution_note TEXT,
    resolution_notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now()),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now())
);

-- Ensure incremental columns exist on incident_alerts if created previously
ALTER TABLE public.incident_alerts ADD COLUMN IF NOT EXISTS alert_id TEXT;
ALTER TABLE public.incident_alerts ADD COLUMN IF NOT EXISTS resolution_notes TEXT;
ALTER TABLE public.incident_alerts ADD COLUMN IF NOT EXISTS resolution_note TEXT;
ALTER TABLE public.incident_alerts ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT timezone('utc'::text, now());
-- Harmonize status check constraint to allow 'new' as well as legacy 'detected'
ALTER TABLE public.incident_alerts DROP CONSTRAINT IF EXISTS incident_alerts_status_check;
ALTER TABLE public.incident_alerts ADD CONSTRAINT incident_alerts_status_check 
    CHECK (status IN ('new', 'detected', 'acknowledged', 'investigating', 'resolved'));

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

-- Uniqueness Safeguard 1: public.feedback_submissions(feedback_id)
-- Required by seed script's "ON CONFLICT (feedback_id)" clause.
-- Pre-checks existing records for duplicates or NULLs before applying UNIQUE index.
DO $$
DECLARE
    v_dup_count integer;
    v_null_count integer;
BEGIN
    SELECT count(*) INTO v_null_count 
    FROM public.feedback_submissions 
    WHERE feedback_id IS NULL;

    IF v_null_count > 0 THEN
        RAISE EXCEPTION 'Pre-migration check failed: % rows in public.feedback_submissions have NULL feedback_id. Resolve NULLs before creating UNIQUE index.', v_null_count;
    END IF;

    SELECT count(*) INTO v_dup_count 
    FROM (
        SELECT feedback_id 
        FROM public.feedback_submissions 
        GROUP BY feedback_id 
        HAVING count(*) > 1
    ) sub;

    IF v_dup_count > 0 THEN
        RAISE EXCEPTION 'Pre-migration check failed: % duplicate feedback_id values exist in public.feedback_submissions. Resolve duplicates before creating UNIQUE index.', v_dup_count;
    END IF;

    -- Drop legacy non-unique index if present so it can be replaced by the unique index
    IF EXISTS (
        SELECT 1 FROM pg_index i
        JOIN pg_class c ON c.oid = i.indexrelid
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public' 
          AND c.relname = 'idx_feedback_fid' 
          AND NOT i.indisunique
    ) THEN
        DROP INDEX public.idx_feedback_fid;
    END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS idx_feedback_fid_unique ON public.feedback_submissions(feedback_id);

-- Uniqueness Safeguard 2: public.incident_alerts(alert_id)
-- Required by seed script's "ON CONFLICT (alert_id)" clause.
-- Pre-checks existing records for duplicates or NULLs before applying UNIQUE index.
DO $$
DECLARE
    v_dup_count integer;
    v_null_count integer;
BEGIN
    SELECT count(*) INTO v_null_count 
    FROM public.incident_alerts 
    WHERE alert_id IS NULL;

    IF v_null_count > 0 THEN
        RAISE EXCEPTION 'Pre-migration check failed: % rows in public.incident_alerts have NULL alert_id. Resolve NULLs before creating UNIQUE index.', v_null_count;
    END IF;

    SELECT count(*) INTO v_dup_count 
    FROM (
        SELECT alert_id 
        FROM public.incident_alerts 
        GROUP BY alert_id 
        HAVING count(*) > 1
    ) sub;

    IF v_dup_count > 0 THEN
        RAISE EXCEPTION 'Pre-migration check failed: % duplicate alert_id values exist in public.incident_alerts. Resolve duplicates before creating UNIQUE index.', v_dup_count;
    END IF;

    -- Drop legacy non-unique index if present so it can be replaced by the unique index
    IF EXISTS (
        SELECT 1 FROM pg_index i
        JOIN pg_class c ON c.oid = i.indexrelid
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public' 
          AND c.relname = 'idx_alerts_aid' 
          AND NOT i.indisunique
    ) THEN
        DROP INDEX public.idx_alerts_aid;
    END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS idx_alerts_aid_unique ON public.incident_alerts(alert_id);

-- ----------------------------------------------------------------------------
-- 3. Security Helper Functions (SECURITY DEFINER with Pinned Search Path)
-- ----------------------------------------------------------------------------

-- Helper A: Resolve Authenticated User's Role without Recursive RLS
CREATE OR REPLACE FUNCTION public.get_my_role()
RETURNS text STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
  SELECT coalesce((SELECT role FROM public.profiles WHERE id = auth.uid()), 'anon');
$$ LANGUAGE sql;

-- Helper B: Resolve Authenticated User's Assigned Store
CREATE OR REPLACE FUNCTION public.get_my_store()
RETURNS text STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
  SELECT assigned_store_id FROM public.profiles WHERE id = auth.uid();
$$ LANGUAGE sql;

REVOKE EXECUTE ON FUNCTION public.get_my_role() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.get_my_role() TO anon, authenticated, service_role;

REVOKE EXECUTE ON FUNCTION public.get_my_store() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.get_my_store() TO anon, authenticated, service_role;

-- ----------------------------------------------------------------------------
-- 4. Automated User Profile Provisioning Trigger (auth.users -> public.profiles)
-- ----------------------------------------------------------------------------
-- Security Hardening:
-- 1. Standard/public signups ALWAYS default to role = 'customer' and assigned_store_id = NULL.
--    Client-provided raw_user_meta_data can NEVER grant 'admin' or 'store_manager'.
-- 2. Customer Ownership: Automatically binds historical feedback submitted under this email
--    to the customer's verified Supabase user UUID (preserving strict RLS ownership).
-- ----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS trigger SECURITY DEFINER SET search_path = public, pg_temp AS $$
BEGIN
  INSERT INTO public.profiles (id, email, full_name, role, assigned_store_id)
  VALUES (
    new.id,
    coalesce(new.email, 'unknown@example.com'),
    coalesce(new.raw_user_meta_data->>'full_name', 'Customer'),
    'customer',  -- STRICT: Never trust client/public signup metadata for role
    NULL          -- STRICT: Never trust client/public signup metadata for store assignment
  )
  ON CONFLICT (id) DO UPDATE SET
    full_name = EXCLUDED.full_name,
    updated_at = timezone('utc'::text, now());

  -- Securely claim historical feedback matching this verified customer email
  UPDATE public.feedback_submissions
  SET customer_user_id = new.id
  WHERE lower(customer_email) = lower(new.email)
    AND customer_user_id IS NULL;

  RETURN new;
END;
$$ LANGUAGE plpgsql;

REVOKE EXECUTE ON FUNCTION public.handle_new_user() FROM PUBLIC;
DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;
CREATE TRIGGER on_auth_user_created
  AFTER INSERT ON auth.users
  FOR EACH ROW EXECUTE FUNCTION public.handle_new_user();

-- ----------------------------------------------------------------------------
-- 4b. Role Assignment Function (Restricted to Postgres / Service Role)
-- ----------------------------------------------------------------------------
-- Used by the project owner in Supabase SQL Editor to safely assign
-- admin or store manager roles and store relationships.
-- ----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.assign_user_role(
    target_email text,
    new_role text,
    new_store_id text DEFAULT NULL
)
RETURNS void SECURITY DEFINER SET search_path = public, pg_temp AS $$
BEGIN
    IF new_role NOT IN ('admin', 'store_manager', 'customer') THEN
        RAISE EXCEPTION 'Invalid role: %. Must be admin, store_manager, or customer.', new_role;
    END IF;

    IF new_role = 'store_manager' AND new_store_id IS NULL THEN
        RAISE EXCEPTION 'Store manager must be assigned a valid store_id.';
    END IF;

    IF new_store_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM public.stores WHERE store_id = new_store_id) THEN
        RAISE EXCEPTION 'Store ID % does not exist in stores fleet. Ensure stores are seeded first.', new_store_id;
    END IF;

    UPDATE public.profiles
    SET 
        role = new_role,
        assigned_store_id = CASE WHEN new_role = 'store_manager' THEN new_store_id ELSE NULL END,
        updated_at = timezone('utc'::text, now())
    WHERE lower(email) = lower(target_email);

    IF NOT FOUND THEN
        RAISE EXCEPTION 'User profile with email % not found. User must exist in Auth first.', target_email;
    END IF;
END;
$$ LANGUAGE plpgsql;

REVOKE EXECUTE ON FUNCTION public.assign_user_role(text, text, text) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.assign_user_role(text, text, text) FROM anon, authenticated;
GRANT EXECUTE ON FUNCTION public.assign_user_role(text, text, text) TO service_role, postgres;

-- ----------------------------------------------------------------------------
-- 5. Anti-Privilege Escalation Trigger (Protects role, store & identity)
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
    IF NOT (
      v_jwt_role = 'service_role'
      OR (v_jwt_role = '' AND current_user IN ('service_role', 'postgres', 'supabase_admin'))
    ) THEN
      RAISE EXCEPTION 'Unauthorized: User role, store assignments, email, and identity are server-controlled.';
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
-- 6. Automated Alert Audit Trail Trigger
-- ----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.log_alert_status_change()
RETURNS trigger SECURITY DEFINER SET search_path = public, pg_temp AS $$
BEGIN
  IF (OLD.status IS DISTINCT FROM NEW.status OR OLD.resolution_notes IS DISTINCT FROM NEW.resolution_notes OR OLD.resolution_note IS DISTINCT FROM NEW.resolution_note) THEN
    INSERT INTO public.audit_log (user_id, action, target_type, target_id, details)
    VALUES (
      auth.uid(),
      'ALERT_STATUS_UPDATE',
      'incident_alerts',
      coalesce(NEW.alert_id, NEW.id::text),
      jsonb_build_object(
        'old_status', OLD.status,
        'new_status', NEW.status,
        'store_id', NEW.store_id,
        'resolved_by', NEW.resolved_by_user_id,
        'resolution_note', coalesce(NEW.resolution_notes, NEW.resolution_note)
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
-- 7. Table and Schema Grants (Principle of Least Privilege)
-- ----------------------------------------------------------------------------
GRANT USAGE ON SCHEMA public TO anon, authenticated, service_role;

-- Stores: Public directory open to anon and authenticated
GRANT SELECT ON public.stores TO anon, authenticated, service_role;

-- Profiles: Authenticated users can view; updates restricted to full_name only
GRANT SELECT ON public.profiles TO authenticated, service_role;
GRANT UPDATE (full_name) ON public.profiles TO authenticated;

-- Feedback Submissions: Authenticated users can select, insert, and update operational notes
GRANT SELECT, INSERT ON public.feedback_submissions TO authenticated, service_role;
GRANT UPDATE (status, resolution_notes, updated_at) ON public.feedback_submissions TO authenticated;

-- Incident Alerts: Authenticated users can select and update resolution status
GRANT SELECT ON public.incident_alerts TO authenticated, service_role;
GRANT UPDATE (status, resolved_by_user_id, resolution_note, resolution_notes, updated_at) ON public.incident_alerts TO authenticated;

-- Audit Log: Authenticated users can read (filtered by RLS) and insert audit actions
GRANT SELECT, INSERT ON public.audit_log TO authenticated, service_role;

-- Service role retains full administrative privileges
GRANT ALL ON ALL TABLES IN SCHEMA public TO service_role;
GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO service_role;

-- ----------------------------------------------------------------------------
-- 8. Row Level Security (RLS) Policies
-- ----------------------------------------------------------------------------
ALTER TABLE public.stores ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.feedback_submissions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.incident_alerts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.audit_log ENABLE ROW LEVEL SECURITY;

-- Policy A: public.stores
DROP POLICY IF EXISTS "stores_read_policy" ON public.stores;
CREATE POLICY "stores_read_policy" ON public.stores
    FOR SELECT TO anon, authenticated
    USING (true);

-- Policy B: public.profiles
DROP POLICY IF EXISTS "profiles_select_policy" ON public.profiles;
CREATE POLICY "profiles_select_policy" ON public.profiles
    FOR SELECT TO authenticated
    USING (
        id = auth.uid() 
        OR public.get_my_role() = 'admin'
    );

DROP POLICY IF EXISTS "profiles_update_policy" ON public.profiles;
CREATE POLICY "profiles_update_policy" ON public.profiles
    FOR UPDATE TO authenticated
    USING (id = auth.uid())
    WITH CHECK (id = auth.uid());

-- Policy C: public.feedback_submissions
DROP POLICY IF EXISTS "feedback_insert_policy" ON public.feedback_submissions;
CREATE POLICY "feedback_insert_policy" ON public.feedback_submissions
    FOR INSERT TO authenticated
    WITH CHECK (
        customer_user_id = auth.uid() 
        OR customer_user_id IS NULL 
        OR public.get_my_role() = 'admin'
    );

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

DROP POLICY IF EXISTS "feedback_update_policy" ON public.feedback_submissions;
CREATE POLICY "feedback_update_policy" ON public.feedback_submissions
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
        (
            public.get_my_role() = 'store_manager'
            AND public.get_my_store() IS NOT NULL
            AND store_id = public.get_my_store()
        )
        OR public.get_my_role() = 'admin'
    );

-- Policy D: public.incident_alerts
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
        (
            public.get_my_role() = 'store_manager'
            AND public.get_my_store() IS NOT NULL
            AND store_id = public.get_my_store()
        )
        OR public.get_my_role() = 'admin'
    );

-- Policy E: public.audit_log
DROP POLICY IF EXISTS "audit_select_policy" ON public.audit_log;
CREATE POLICY "audit_select_policy" ON public.audit_log
    FOR SELECT TO authenticated
    USING (public.get_my_role() = 'admin');

DROP POLICY IF EXISTS "audit_insert_policy" ON public.audit_log;
CREATE POLICY "audit_insert_policy" ON public.audit_log
    FOR INSERT TO authenticated
    WITH CHECK (
        user_id = auth.uid() 
        OR user_id IS NULL
        OR public.get_my_role() = 'admin'
    );

-- ============================================================================
-- End of Phase 2 Migration Script
-- ============================================================================
