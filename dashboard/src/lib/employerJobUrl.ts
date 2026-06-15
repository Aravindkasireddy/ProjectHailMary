/**
 * Company-hosted (or employer-tenant) apply URLs only — no LinkedIn, boards, or shared ATS
 * hosts (Greenhouse, Lever, Ashby, …). Workday *.myworkdayjobs.com / *.workdayjobs.com and
 * Oracle recruiting cloud allowed.
 *
 * Keep in sync with ``employer_job_url.py`` at repo root.
 */
const BLOCKED_HOST_SUFFIXES = [
  'linkedin.com',
  'linkedin.cn',
  'indeed.com',
  'glassdoor.com',
  'glassdoor.co.uk',
  'monster.com',
  'ziprecruiter.com',
  'dice.com',
  'careerbuilder.com',
  'snagajob.com',
  'simplyhired.com',
  'talent.com',
  'jobrapido.com',
  'jooble.org',
  'jooble.com',
  'reddit.com',
  'twitter.com',
  'x.com',
  't.co',
  'facebook.com',
  'instagram.com',
  'tiktok.com',
  'medium.com',
  'substack.com',
  'weworkremotely.com',
  'remote.co',
  'remotive.com',
  'remoteok.io',
  'dynamitejobs.com',
  'wellfound.com',
  'angel.co',
  'hn.algolia.com',
  'news.ycombinator.com',
] as const;

const MULTI_TENANT_ATS_SUFFIXES = [
  'greenhouse.io',
  'lever.co',
  'ashbyhq.com',
  'workable.com',
  'smartrecruiters.com',
  'icims.com',
  'bamboohr.com',
  'rippling.com',
  'pinpointhq.com',
  'breezy.hr',
  'recruitee.com',
  'teamtailor.com',
  'ultipro.com',
  'taleo.net',
  'brassring.com',
  'eightfold.ai',
  'jobvite.com',
  'hrmdirect.com',
  'paycomonline.net',
  'successfactors.com',
] as const;

function hostOf(url: string): string {
  try {
    let h = new URL(url.trim()).hostname.toLowerCase();
    if (h.startsWith('www.')) h = h.slice(4);
    return h;
  } catch {
    return '';
  }
}

function blockedAggregator(h: string): boolean {
  for (const suf of BLOCKED_HOST_SUFFIXES) {
    if (h === suf || h.endsWith('.' + suf)) return true;
  }
  return false;
}

function multiTenantAtsHost(h: string): boolean {
  for (const suf of MULTI_TENANT_ATS_SUFFIXES) {
    if (h === suf || h.endsWith('.' + suf)) return true;
  }
  return false;
}

export function isOfficialCompanyCareersJobUrl(url: string): boolean {
  const u = (url || '').trim();
  if (!u) return false;
  const low = u.toLowerCase();
  const h = hostOf(u);
  if (!h) return false;
  if (blockedAggregator(h)) return false;
  if (multiTenantAtsHost(h)) return false;

  if (h.endsWith('.myworkdayjobs.com') || h.endsWith('.workdayjobs.com')) return true;
  if (low.includes('oraclecloud.com') || h.endsWith('.oraclecloud.com')) return true;
  if (h.startsWith('careers.') || h.startsWith('jobs.') || h.startsWith('apply.')) return true;

  try {
    const path = new URL(u.trim()).pathname.toLowerCase();
    if (
      path.includes('/careers') ||
      path.includes('/job/') ||
      path.includes('/jobs/') ||
      path.includes('/openings') ||
      path.includes('/positions')
    ) {
      return true;
    }
  } catch {
    /* ignore */
  }
  return false;
}
