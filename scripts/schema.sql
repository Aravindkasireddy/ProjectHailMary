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
