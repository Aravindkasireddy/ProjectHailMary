import type { SupabaseClient } from '@supabase/supabase-js';

/** PostgREST / Supabase caps each response at 1000 rows unless you paginate with .range(). */
const PAGE = 1000;

/**
 * Load every row from public.jobs for the authenticated user (RLS-scoped).
 * An unpaginated .select() silently truncates at 1000 — that is why the
 * dashboard previously showed ~1k jobs when the table had 4k+.
 */
export async function fetchAllSupabaseJobs<T = Record<string, unknown>>(
  client: SupabaseClient,
  columns = '*'
): Promise<{ data: T[] | null; error: Error | null }> {
  const rows: T[] = [];
  let offset = 0;
  try {
    while (true) {
      const { data, error } = await client
        .from('jobs')
        .select(columns)
        .order('scraped_at', { ascending: false })
        .range(offset, offset + PAGE - 1);
      if (error) {
        return { data: null, error: new Error(error.message) };
      }
      const page = (data || []) as T[];
      rows.push(...page);
      if (page.length < PAGE) break;
      offset += PAGE;
    }
    return { data: rows, error: null };
  } catch (e) {
    return { data: null, error: e instanceof Error ? e : new Error(String(e)) };
  }
}
