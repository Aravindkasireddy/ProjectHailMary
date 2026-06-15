/**
 * Canonical job URL for client-side deduplication (matches Python ``canonical_job_url``).
 */
export function canonicalJobUrl(url: string): string {
  const s = (url || '').trim();
  if (!s) return '';
  try {
    const u = new URL(s);
    u.hash = '';
    u.search = '';
    u.protocol = 'https:';
    u.hostname = u.hostname.toLowerCase();
    const path = u.pathname.replace(/\/$/, '') || '';
    u.pathname = path;
    return u.toString();
  } catch {
    return s.split('#')[0].split('?')[0].replace(/\/$/, '').toLowerCase();
  }
}

export function dedupeJobsByCanonicalUrl<T extends { job_url: string; scraped_at?: string | null }>(
  rows: T[]
): T[] {
  const m = new Map<string, T>();
  for (const row of rows) {
    const k = canonicalJobUrl(row.job_url || '');
    if (!k) continue;
    const next = { ...row, job_url: k } as T;
    const prev = m.get(k);
    if (!prev) {
      m.set(k, next);
      continue;
    }
    const pt = prev.scraped_at ? new Date(prev.scraped_at).getTime() : 0;
    const nt = row.scraped_at ? new Date(row.scraped_at).getTime() : 0;
    if (nt >= pt) m.set(k, next);
  }
  return [...m.values()];
}
