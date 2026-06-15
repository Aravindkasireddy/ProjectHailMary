-- Prefer showing / uploading only company-hosted apply URLs (not LinkedIn, shared Greenhouse/Lever boards, etc.)
ALTER TABLE public.user_configs
  ADD COLUMN IF NOT EXISTS search_official_career_job_urls_only BOOLEAN DEFAULT false;

COMMENT ON COLUMN public.user_configs.search_official_career_job_urls_only IS
  'When true, dashboard hides URLs that are not company-hosted apply pages; upload_user_jobs skips them. See employer_job_url.py.';
