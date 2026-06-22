/**
 * Canonical job URL for deduplication (aligned with ``company_scraper/url_normalize.canonical_job_url``).
 * Strips fragments and known tracking query params only — preserves functional query strings so links work.
 */

const TRACKING_PARAM_NAMES = new Set([
  'fbclid',
  'gclid',
  'mc_cid',
  'mc_eid',
  '_ga',
  'igshid',
  'si',
  'mkt_tok',
  'oly_enc_id',
  'spm',
  'trk',
  'trkcorp',
  'trkpublic',
  'gbraid',
  'wbraid',
]);

function isTrackingParam(key: string): boolean {
  const k = key.trim().toLowerCase();
  if (!k) return false;
  if (TRACKING_PARAM_NAMES.has(k)) return true;
  if (k.startsWith('utm_')) return true;
  return false;
}

/**
 * LinkedIn "job search shell" URLs (`/jobs/search?currentJobId=…`) are not stable apply targets.
 * Normalize to `/jobs/view/{id}/` so the browser opens the job detail page (employer apply link may appear there).
 * Employer/ATS URLs are returned unchanged.
 */
export function linkedInJobsSearchToViewUrl(url: string): string {
  const s = (url || '').trim();
  if (!s) return '';
  try {
    const u = new URL(s);
    const host = u.hostname.toLowerCase();
    if (!host.endsWith('linkedin.com')) return s;
    if (!u.pathname.toLowerCase().includes('/jobs/search')) return s;
    const jid = u.searchParams.get('currentJobId')?.trim();
    if (jid && /^\d+$/.test(jid)) {
      return `https://www.linkedin.com/jobs/view/${jid}/`;
    }
    return s;
  } catch {
    return s;
  }
}

/** Prefer employer URL from DB; otherwise open LinkedIn job view instead of search shell when applicable. */
export function browserOpenJobUrl(storedJobUrl: string): string {
  return linkedInJobsSearchToViewUrl((storedJobUrl || '').trim());
}

export function canonicalJobUrl(url: string): string {
  const s = (url || '').trim();
  if (!s) return '';
  try {
    const u = new URL(s);
    u.hash = '';
    const keys = [...u.searchParams.keys()];
    for (const key of keys) {
      if (isTrackingParam(key)) u.searchParams.delete(key);
    }
    const q = u.searchParams.toString();
    u.search = q ? `?${q}` : '';
    u.protocol = 'https:';
    u.hostname = u.hostname.toLowerCase();
    const path = u.pathname.replace(/\/$/, '') || '';
    u.pathname = path || '/';
    return u.toString();
  } catch {
    return s.split('#')[0].replace(/\/$/, '');
  }
}

/** Dedupe key: treat LinkedIn search ?currentJobId=… as same posting as /jobs/view/{id}/. */
function dedupeKeyForJobUrl(url: string): string {
  return canonicalJobUrl(linkedInJobsSearchToViewUrl(url));
}

/** After merge, keep employer/ATS URL if either side has it; else richer LinkedIn URL (view over search shell). */
function preferStoredApplyUrl(a: string, b: string): string {
  const aa = (a || '').trim();
  const bb = (b || '').trim();
  if (dedupeKeyForJobUrl(aa) !== dedupeKeyForJobUrl(bb)) return aa || bb;
  const candidates = [aa, bb].filter(Boolean);
  const external = candidates.find((u) => !u.toLowerCase().includes('linkedin.com'));
  if (external) return external;
  const v = candidates.map(linkedInJobsSearchToViewUrl);
  return v[0].length >= v[1].length ? v[0] : v[1];
}

export function dedupeJobsByCanonicalUrl<T extends { job_url: string; scraped_at?: string | null }>(
  rows: T[]
): T[] {
  const m = new Map<string, T>();
  for (const row of rows) {
    const orig = (row.job_url || '').trim();
    const k = dedupeKeyForJobUrl(orig);
    if (!k) continue;
    const prev = m.get(k);
    if (!prev) {
      m.set(k, { ...row, job_url: linkedInJobsSearchToViewUrl(orig) || orig || k } as T);
      continue;
    }
    const pt = prev.scraped_at ? new Date(prev.scraped_at).getTime() : 0;
    const nt = row.scraped_at ? new Date(row.scraped_at).getTime() : 0;
    const richer = preferStoredApplyUrl(prev.job_url || '', row.job_url || '');
    if (nt >= pt) {
      m.set(k, { ...row, job_url: richer } as T);
    } else {
      m.set(k, { ...prev, job_url: richer } as T);
    }
  }
  return [...m.values()];
}
