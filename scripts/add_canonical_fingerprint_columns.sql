-- Canonical job fingerprinting for cross-source dedup (job_fingerprint.py).
-- canonical_fingerprint: sha256(normalized company|title|location) - same role
--   reposted via a different ATS/source collapses to the same fingerprint.
-- ats_source: which connector/source produced this row (greenhouse, lever, workday, ...).
-- sources: JSONB array of {ats_source, source_url, scraped_at} for every source
--   that was merged into this canonical row, so "1 job, N sources" is queryable
--   without losing the original source URLs.
ALTER TABLE public.jobs ADD COLUMN IF NOT EXISTS canonical_fingerprint TEXT;
ALTER TABLE public.jobs ADD COLUMN IF NOT EXISTS ats_source TEXT;
ALTER TABLE public.jobs ADD COLUMN IF NOT EXISTS sources JSONB DEFAULT '[]'::JSONB;

CREATE INDEX IF NOT EXISTS jobs_canonical_fingerprint_idx
  ON public.jobs (user_id, canonical_fingerprint);
