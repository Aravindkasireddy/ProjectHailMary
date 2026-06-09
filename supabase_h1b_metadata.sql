-- Alter H1B sponsors table to support rich metadata
ALTER TABLE public.h1b_sponsors ADD COLUMN IF NOT EXISTS company_type text;
ALTER TABLE public.h1b_sponsors ADD COLUMN IF NOT EXISTS w2_contractor text;
ALTER TABLE public.h1b_sponsors ADD COLUMN IF NOT EXISTS employee_count double precision;
ALTER TABLE public.h1b_sponsors ADD COLUMN IF NOT EXISTS linkedin_account text;
ALTER TABLE public.h1b_sponsors ADD COLUMN IF NOT EXISTS career_portal text;
ALTER TABLE public.h1b_sponsors ADD COLUMN IF NOT EXISTS website text;
ALTER TABLE public.h1b_sponsors ADD COLUMN IF NOT EXISTS sponsor_status text;
ALTER TABLE public.h1b_sponsors ADD COLUMN IF NOT EXISTS recommended_action text;
ALTER TABLE public.h1b_sponsors ADD COLUMN IF NOT EXISTS opt_friendly_score double precision;
ALTER TABLE public.h1b_sponsors ADD COLUMN IF NOT EXISTS cases_2024 integer;
ALTER TABLE public.h1b_sponsors ADD COLUMN IF NOT EXISTS cases_2025 integer;
ALTER TABLE public.h1b_sponsors ADD COLUMN IF NOT EXISTS cases_2026 integer;
ALTER TABLE public.h1b_sponsors ADD COLUMN IF NOT EXISTS recent_cases integer;
ALTER TABLE public.h1b_sponsors ADD COLUMN IF NOT EXISTS recent_approvals integer;
ALTER TABLE public.h1b_sponsors ADD COLUMN IF NOT EXISTS trend_label text;
ALTER TABLE public.h1b_sponsors ADD COLUMN IF NOT EXISTS top_state text;
