/**
 * Employer / ATS-hosted job URLs only (exclude LinkedIn, Indeed, boards, social).
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

const ATS_URL_HINTS = [
  'greenhouse.io',
  'lever.co',
  'myworkdayjobs.com',
  'workdayjobs.com',
  'ashbyhq.com',
  'apply.workable.com',
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
  'successfactors.com',
  'oraclecloud.com',
  'fa.us2.oraclecloud.com',
  'jobvite.com',
  'hrmdirect.com',
  'paycomonline.net',
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

export function isOfficialCompanyCareersJobUrl(url: string): boolean {
  const u = (url || '').trim();
  if (!u) return false;
  const low = u.toLowerCase();
  const h = hostOf(u);
  for (const suf of BLOCKED_HOST_SUFFIXES) {
    if (h === suf || h.endsWith('.' + suf)) return false;
  }
  for (const hint of ATS_URL_HINTS) {
    if (low.includes(hint)) return true;
  }
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
