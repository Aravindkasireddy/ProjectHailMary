-- Alter H1B sponsors table to track each company's detected ATS platform
-- (Greenhouse/Lever/Workday/iCIMS/generic), via company_scraper.detector.detect_ats().
ALTER TABLE public.h1b_sponsors ADD COLUMN IF NOT EXISTS ats_platform text;
ALTER TABLE public.h1b_sponsors ADD COLUMN IF NOT EXISTS ats_platform_detected_at timestamp with time zone;
