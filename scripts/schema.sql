-- schema.sql
-- Setup jobs and user_configs tables for Gemini-jobsearch on Supabase Postgres database.

-- 1. Create jobs table
CREATE TABLE IF NOT EXISTS public.jobs (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE NOT NULL,
  job_title TEXT NOT NULL,
  company_name TEXT NOT NULL,
  job_url TEXT NOT NULL,
  requirement_id TEXT,
  job_description TEXT,
  location_work_type TEXT,
  apply_decision TEXT DEFAULT 'APPLY',
  strongest_label TEXT,
  confidence_score NUMERIC,
  rationale TEXT,
  red_flags JSONB DEFAULT '[]'::JSONB,
  apply_decision_payload JSONB DEFAULT '{}'::JSONB,
  synced BOOLEAN DEFAULT false,
  synced_data JSONB DEFAULT '{}'::JSONB,
  scraped_at TIMESTAMPTZ DEFAULT timezone('utc'::text, now()),
  stale BOOLEAN DEFAULT false,
  archived BOOLEAN DEFAULT false,
  pipeline_stage TEXT DEFAULT 'Scraped',
  min_salary NUMERIC,
  max_salary NUMERIC,
  is_hourly BOOLEAN DEFAULT false,
  salary_text TEXT,
  benefits JSONB DEFAULT '[]'::JSONB,
  created_at TIMESTAMPTZ DEFAULT timezone('utc'::text, now()),
  -- Unique constraint on user_id + job_url to allow different users to track the same job
  CONSTRAINT unique_user_job_url UNIQUE (user_id, job_url)
);

-- Enable Row-Level Security (RLS) on jobs
ALTER TABLE public.jobs ENABLE ROW LEVEL SECURITY;

-- Drop existing policies if they exist (allows safe re-runs)
DROP POLICY IF EXISTS "Users can perform all actions on their own jobs" ON public.jobs;

-- Create policy for jobs (authenticated user can access only their own jobs)
CREATE POLICY "Users can perform all actions on their own jobs"
  ON public.jobs
  FOR ALL
  TO authenticated
  USING (auth.uid() = user_id)
  WITH CHECK (auth.uid() = user_id);

-- Create indexes for performance
CREATE INDEX IF NOT EXISTS idx_jobs_user_id ON public.jobs(user_id);
CREATE INDEX IF NOT EXISTS idx_jobs_pipeline_stage ON public.jobs(pipeline_stage);
CREATE INDEX IF NOT EXISTS idx_jobs_status_archived ON public.jobs(user_id, apply_decision, archived);

-- 2. Create user_configs table
CREATE TABLE IF NOT EXISTS public.user_configs (
  user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE PRIMARY KEY,
  target_titles JSONB DEFAULT '[]'::JSONB,
  target_companies JSONB DEFAULT '{"greenhouse": [], "lever": [], "ashby": [], "smartrecruiters": []}'::JSONB,
  proxies JSONB DEFAULT '[]'::JSONB,
  scheduler_enabled BOOLEAN DEFAULT true,
  scheduler_run_at_hour INTEGER DEFAULT 8,
  scheduler_run_at_minute INTEGER DEFAULT 0,
  search_country_phrase TEXT DEFAULT 'United States',
  search_include_remote_primary_boards BOOLEAN DEFAULT true,
  search_merge_previous_scrape BOOLEAN DEFAULT true,
  search_send_digest_only BOOLEAN DEFAULT true,
  search_max_digest_items INTEGER DEFAULT 10,
  search_official_career_job_urls_only BOOLEAN DEFAULT false,
  policy_max_experience_years INTEGER DEFAULT 8,
  policy_min_salary_annual NUMERIC DEFAULT 80000,
  policy_min_salary_hourly NUMERIC DEFAULT 50,
  policy_enforce_visa_sponsorship BOOLEAN DEFAULT true,
  policy_enforce_no_clearance BOOLEAN DEFAULT true,
  policy_custom_red_flag_keywords JSONB DEFAULT '[]'::JSONB,
  notion_token TEXT,
  notion_database_id TEXT,
  webhook_url TEXT,
  base_resume TEXT,
  jooble_api_key TEXT,
  updated_at TIMESTAMPTZ DEFAULT timezone('utc'::text, now())
);

-- Enable RLS on user_configs
ALTER TABLE public.user_configs ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Users can manage their own config" ON public.user_configs;

CREATE POLICY "Users can manage their own config"
  ON public.user_configs
  FOR ALL
  TO authenticated
  USING (auth.uid() = user_id)
  WITH CHECK (auth.uid() = user_id);

-- 3. Scrape run history (see scripts/scrape_runs.sql for standalone migration)
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

-- 4. Watched companies (see scripts/watched_companies.sql)
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
