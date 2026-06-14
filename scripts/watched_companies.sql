-- watched_companies: scheduled company-targeted scrapes (Supabase SQL editor / migration)
-- Service role bypasses RLS for scheduler writes; authenticated users manage their own rows.

CREATE TABLE IF NOT EXISTS public.watched_companies (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE,
  user_email TEXT,
  input_value TEXT NOT NULL,
  company_name TEXT,
  careers_url TEXT,
  ats_platform TEXT,
  is_active BOOLEAN DEFAULT true,
  scrape_frequency TEXT DEFAULT 'daily',
  last_scraped_at TIMESTAMPTZ,
  last_jobs_found INTEGER,
  created_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now())
);

CREATE INDEX IF NOT EXISTS idx_watched_companies_user_active
  ON public.watched_companies (user_id, is_active);

ALTER TABLE public.watched_companies ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Users manage own watched companies" ON public.watched_companies;

CREATE POLICY "Users manage own watched companies"
  ON public.watched_companies
  FOR ALL
  TO authenticated
  USING (auth.uid() = user_id)
  WITH CHECK (auth.uid() = user_id);
