-- Application tracking columns for public.jobs
-- application_status: null = not applied, 'applied', 'phone_screen', 'interview', 'offer', 'rejected'
ALTER TABLE public.jobs
  ADD COLUMN IF NOT EXISTS application_status TEXT DEFAULT NULL,
  ADD COLUMN IF NOT EXISTS applied_at TIMESTAMPTZ DEFAULT NULL,
  ADD COLUMN IF NOT EXISTS application_notes TEXT DEFAULT NULL;

CREATE INDEX IF NOT EXISTS idx_jobs_application_status
  ON public.jobs(user_id, application_status)
  WHERE application_status IS NOT NULL;
