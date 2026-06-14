-- scrape_runs: real-time scrape tracking (apply in Supabase SQL editor or via migration tool)
-- Service-role API writes bypass RLS; authenticated users SELECT their own rows.

CREATE TABLE IF NOT EXISTS public.scrape_runs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE,
  user_email TEXT,
  run_type TEXT NOT NULL,
  status TEXT NOT NULL,
  stage TEXT,
  input_value TEXT,
  company_name TEXT,
  ats_platform TEXT,
  total_scraped INTEGER,
  it_jobs_found INTEGER,
  saved_to_db INTEGER,
  error_message TEXT,
  started_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now()),
  finished_at TIMESTAMPTZ,
  duration_seconds INTEGER,
  summary JSONB DEFAULT '{}'::JSONB
);

CREATE INDEX IF NOT EXISTS idx_scrape_runs_user_started
  ON public.scrape_runs (user_id, started_at DESC);

CREATE INDEX IF NOT EXISTS idx_scrape_runs_status
  ON public.scrape_runs (status);

ALTER TABLE public.scrape_runs ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Users can view own scrape runs" ON public.scrape_runs;

CREATE POLICY "Users can view own scrape runs"
  ON public.scrape_runs
  FOR SELECT
  TO authenticated
  USING (auth.uid() = user_id);
