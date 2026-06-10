-- Add jooble_api_key column to user_configs table
ALTER TABLE public.user_configs ADD COLUMN IF NOT EXISTS jooble_api_key TEXT;
