-- Optional: IT filter tuning for company-targeted scraper (per user).
-- Run in Supabase SQL Editor once.

ALTER TABLE public.user_configs
  ADD COLUMN IF NOT EXISTS company_scraper_it JSONB DEFAULT '{
    "min_it_score": 0.28,
    "strict_engineering_only": false,
    "include_data_roles": true,
    "include_analyst_roles": true
  }'::jsonb;

COMMENT ON COLUMN public.user_configs.company_scraper_it IS
  'Company scraper IT filter: min_it_score 0-1, strict_engineering_only, include_data_roles, include_analyst_roles';
