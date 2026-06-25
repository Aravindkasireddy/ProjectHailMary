-- Fast-poll support for OPT-friendly watched companies (watched_companies_scheduler.py).
-- poll_interval_minutes: when set, overrides scrape_frequency's daily/weekly text logic
--   with an exact minute interval (e.g. 10) - used for OPT-friendly companies that have a
--   genuine Greenhouse/Lever/Workday/iCIMS board worth checking far more often than daily.
-- is_opt_friendly: when true, a new job found for this company triggers an instant
--   per-job webhook alert instead of waiting for the next daily digest.
ALTER TABLE public.watched_companies ADD COLUMN IF NOT EXISTS poll_interval_minutes INTEGER;
ALTER TABLE public.watched_companies ADD COLUMN IF NOT EXISTS is_opt_friendly BOOLEAN DEFAULT false;
