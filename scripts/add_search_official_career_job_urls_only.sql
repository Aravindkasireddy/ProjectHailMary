-- Prefer showing / uploading only employer or ATS-hosted job URLs (not LinkedIn, Indeed, etc.)
ALTER TABLE public.user_configs
  ADD COLUMN IF NOT EXISTS search_official_career_job_urls_only BOOLEAN DEFAULT false;

COMMENT ON COLUMN public.user_configs.search_official_career_job_urls_only IS
  'When true, dashboard hides non-official URLs; upload_user_jobs skips them when syncing JSON to Supabase.';
