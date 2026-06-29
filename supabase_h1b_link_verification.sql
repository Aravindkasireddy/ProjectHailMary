-- Alter H1B sponsors table to track whether each company's career_portal
-- link was actually verified live (vs the original Excel's "guessed"
-- link_data_source, which 97% of rows have - see scripts/verify_career_portal_links.py).
ALTER TABLE public.h1b_sponsors ADD COLUMN IF NOT EXISTS career_portal_verified boolean;
ALTER TABLE public.h1b_sponsors ADD COLUMN IF NOT EXISTS career_portal_verified_at timestamp with time zone;
