import { Job, AnalyticsData, SalaryInsights } from './types';
import { NON_US_TERMS } from './constants';
import { isOfficialCompanyCareersJobUrl } from '../../lib/employerJobUrl';

export function getJobSource(url: string): string {
  if (!url) return 'Other';
  const lUrl = url.toLowerCase();
  if (lUrl.includes('greenhouse.io')) return 'Greenhouse';
  if (lUrl.includes('lever.co')) return 'Lever';
  if (lUrl.includes('myworkdayjobs.com')) return 'Workday';
  if (lUrl.includes('ashbyhq.com')) return 'Ashby';
  if (lUrl.includes('workable.com')) return 'Workable';
  if (lUrl.includes('smartrecruiters.com')) return 'SmartRecruiters';
  if (lUrl.includes('weworkremotely.com')) return 'We Work Remotely';
  if (lUrl.includes('remote.co')) return 'Remote.co';
  if (lUrl.includes('linkedin.com')) return 'LinkedIn';
  if (lUrl.includes('workatastartup.com') || lUrl.includes('ycombinator.com')) return 'Y Combinator';
  return 'Other';
}

export function isUsLocation(location: string | null | undefined): boolean {
  if (!location) return true;
  const loc = location.toLowerCase();

  if (/\bunited states\b/.test(loc) || /\busa\b/.test(loc) || /\bu\.s\.a?\b/.test(loc)) return true;

  const usStates = [
    'alabama','alaska','arizona','arkansas','california','colorado','connecticut','delaware',
    'florida','georgia','hawaii','idaho','illinois','indiana','iowa','kansas','kentucky',
    'louisiana','maine','maryland','massachusetts','michigan','minnesota','mississippi',
    'missouri','montana','nebraska','nevada','new hampshire','new jersey','new mexico',
    'new york','north carolina','north dakota','ohio','oklahoma','oregon','pennsylvania',
    'rhode island','south carolina','south dakota','tennessee','texas','utah','vermont',
    'virginia','washington','west virginia','wisconsin','wyoming',
  ];
  if (usStates.some(s => loc.includes(s))) return true;

  const usCities = [
    'san francisco','seattle','austin','chicago','boston','denver','los angeles','atlanta',
    'dallas','houston','miami','philadelphia','phoenix','san diego','san jose','new york',
    'nyc','sunnyvale','mountain view','palo alto','redmond','bellevue','raleigh','charlotte',
    'nashville','salt lake','las vegas','orlando','tampa','portland','pittsburgh','minneapolis',
  ];
  if (usCities.some(c => loc.includes(c))) return true;

  for (const term of NON_US_TERMS) {
    if (new RegExp(`\\b${term.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\b`).test(loc)) return false;
  }

  return true;
}

export function filterJobsOfficialCareersOnly(jobs: Job[], enabled: boolean): Job[] {
  if (!enabled) return jobs;
  return jobs.filter(j => isOfficialCompanyCareersJobUrl(j.job_url || ''));
}

export function jobListPollUnchanged(prev: Job[], next: Job[]): boolean {
  if (prev.length !== next.length) return false;
  for (let i = 0; i < prev.length; i++) {
    const a = prev[i];
    const b = next[i];
    if (!b || a.job_url !== b.job_url) return false;
    if (
      a.scraped_at !== b.scraped_at ||
      a.apply_decision !== b.apply_decision ||
      a.pipeline_stage !== b.pipeline_stage ||
      a.archived !== b.archived
    ) return false;
  }
  return true;
}

export function computeAnalytics(jobsList: Job[]): AnalyticsData {
  const total_sourced = jobsList.length;
  const approvedJobs = jobsList.filter(j => j.apply_decision === 'APPLY');
  const rejectedJobs = jobsList.filter(j => j.apply_decision === 'DO_NOT_APPLY');
  const approved = approvedJobs.length;
  const rejected = rejectedJobs.length;
  const approval_rate = total_sourced > 0 ? (approved / total_sourced) * 100 : 0;

  const labels_distribution: Record<string, number> = {};
  const sources_distribution: Record<string, number> = {};
  const rejection_reasons: Record<string, number> = {};

  jobsList.forEach(j => {
    const label = j.strongest_label || 'OutOfScope';
    labels_distribution[label] = (labels_distribution[label] || 0) + 1;

    const source = getJobSource(j.job_url);
    sources_distribution[source] = (sources_distribution[source] || 0) + 1;

    if (j.apply_decision === 'DO_NOT_APPLY' && j.red_flags) {
      j.red_flags.forEach(flag => {
        rejection_reasons[flag] = (rejection_reasons[flag] || 0) + 1;
      });
    }
  });

  return { total_sourced, approved, rejected, approval_rate, labels_distribution, sources_distribution, rejection_reasons };
}

export function computeSalaryInsights(jobsList: Job[]): SalaryInsights {
  const approvedJobs = jobsList.filter(j => j.apply_decision === 'APPLY' && !j.archived);
  const yearly_salaries: number[] = [];
  const hourly_salaries: number[] = [];

  approvedJobs.forEach(j => {
    const min = j.min_salary;
    const max = j.max_salary;
    if (min != null && max != null) {
      const avg = (min + max) / 2;
      if (j.is_hourly) hourly_salaries.push(avg);
      else yearly_salaries.push(avg);
    }
  });

  const stats = (arr: number[]) => {
    if (!arr.length) return { count: 0, avg: 0, min: 0, max: 0, distribution: [] as number[] };
    const sum = arr.reduce((a, b) => a + b, 0);
    return { count: arr.length, avg: sum / arr.length, min: Math.min(...arr), max: Math.max(...arr), distribution: arr };
  };

  const yearly = stats(yearly_salaries);
  const hourly = stats(hourly_salaries);

  return {
    yearly_count: yearly.count, yearly_avg: yearly.avg, yearly_min: yearly.min, yearly_max: yearly.max,
    hourly_count: hourly.count, hourly_avg: hourly.avg, hourly_min: hourly.min, hourly_max: hourly.max,
    yearly_distribution: yearly.distribution, hourly_distribution: hourly.distribution,
  };
}
