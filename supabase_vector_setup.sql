-- 1. Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- 2. Add embedding columns to our tables
-- We use 768 dimensions because Gemini's text-embedding-004 outputs 768-dimensional vectors.
ALTER TABLE public.jobs ADD COLUMN IF NOT EXISTS embedding vector(768);
ALTER TABLE public.user_configs ADD COLUMN IF NOT EXISTS resume_embedding vector(768);

-- 3. Create a Postgres function (RPC) to perform cosine similarity search
CREATE OR REPLACE FUNCTION match_jobs (
  query_embedding vector(768),
  match_threshold float,
  match_count int,
  user_id_filter uuid
)
RETURNS TABLE (
  id uuid,
  job_title text,
  company_name text,
  job_url text,
  similarity float
)
LANGUAGE plpgsql
AS $$
BEGIN
  RETURN QUERY
  SELECT
    jobs.id,
    jobs.job_title,
    jobs.company_name,
    jobs.job_url,
    1 - (jobs.embedding <=> query_embedding) AS similarity
  FROM jobs
  WHERE jobs.user_id = user_id_filter
    AND jobs.embedding IS NOT NULL
    AND 1 - (jobs.embedding <=> query_embedding) > match_threshold
  ORDER BY jobs.embedding <=> query_embedding
  LIMIT match_count;
END;
$$;
