-- Company Registry: persists ATS discovery results so the same company's
-- ATS type/endpoint never needs to be re-discovered (slug-guessing + Yahoo
-- fallback) on every scrape. Company-level, not per-user (unlike
-- watched_companies, which is a per-user scrape subscription) - the same
-- company has the same ATS regardless of which user is watching it.
CREATE TABLE IF NOT EXISTS public.companies (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name TEXT NOT NULL,
  name_normalized TEXT NOT NULL,
  careers_url TEXT,
  ats_type TEXT,
  ats_endpoint TEXT,
  verified BOOLEAN DEFAULT false,
  health_score NUMERIC DEFAULT 0,
  source TEXT,
  last_verified_at TIMESTAMPTZ,
  last_checked_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now())
);

CREATE UNIQUE INDEX IF NOT EXISTS companies_name_normalized_idx
  ON public.companies (name_normalized);

CREATE INDEX IF NOT EXISTS companies_ats_type_idx ON public.companies (ats_type);

-- Service role only (this is a shared lookup cache, not user data - no RLS
-- policy needed for per-user isolation since nothing here is user-specific).
ALTER TABLE public.companies ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Service role manages companies" ON public.companies;

CREATE POLICY "Service role manages companies"
  ON public.companies
  FOR ALL
  TO service_role
  USING (true)
  WITH CHECK (true);
