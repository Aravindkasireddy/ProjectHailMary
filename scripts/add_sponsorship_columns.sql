-- Sponsorship intelligence (sponsorship_classifier.py).
-- sponsorship_status: one of clearance_required|us_citizen_only|green_card_only|
--   requires_sponsorship|future_sponsorship_available|opt_friendly|h1b_sponsor|unknown.
-- sponsorship_confidence: 0-100, how confident the classifier is in that status.
ALTER TABLE public.jobs ADD COLUMN IF NOT EXISTS sponsorship_status TEXT;
ALTER TABLE public.jobs ADD COLUMN IF NOT EXISTS sponsorship_confidence NUMERIC;

CREATE INDEX IF NOT EXISTS jobs_sponsorship_status_idx
  ON public.jobs (user_id, sponsorship_status);
