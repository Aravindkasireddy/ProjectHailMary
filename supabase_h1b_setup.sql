-- Create H1B sponsors table
CREATE TABLE IF NOT EXISTS public.h1b_sponsors (
  company_name text PRIMARY KEY,
  is_sponsor boolean DEFAULT true,
  last_updated timestamp with time zone DEFAULT now()
);

-- Note: We don't add a foreign key to `jobs` because companies in jobs might not exist in `h1b_sponsors`.
-- Instead, we will do a left join or lookup in the application layer.
