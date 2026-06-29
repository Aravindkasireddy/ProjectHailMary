'use client';

import {
  ExternalLink,
  Edit3,
  FileText,
  Globe,
  Activity,
  AlertTriangle,
  XCircle,
} from 'lucide-react';
import CopyButton from './CopyButton';
import ResumeGenerator from './ResumeGenerator';

interface DecisionPayload {
  apply_decision?: string;
  strongest_label?: string;
  red_flags?: string[];
  confidence_score?: number;
  rationale?: string;
  recommendation?: string;
  fit_score?: number;
  ownership_strength?: string;
  review_reason?: string;
  cloud?: {
    primary_cloud?: string;
  };
  [key: string]: unknown;
}

interface SponsorMetadata {
  id?: string;
  company_name: string;
  company_type?: string;
  w2_contractor?: string;
  employee_count?: number;
  linkedin_account?: string;
  career_portal?: string;
  website?: string;
  sponsor_status?: string;
  recommended_action?: string;
  opt_friendly_score?: number;
  cases_2024?: number;
  cases_2025?: number;
  cases_2026?: number;
  recent_cases?: number;
  recent_approvals?: number;
  trend_label?: string;
  top_state?: string;
}

export interface JobCardJob {
  job_title: string;
  company_name: string;
  job_url: string;
  requirement_id: string;
  job_description: string;
  location_work_type: string;
  apply_decision: string;
  strongest_label: string;
  confidence_score: number;
  match_score?: number;
  rationale: string;
  red_flags?: string[];
  apply_decision_payload?: DecisionPayload;
  scraped_at?: string;
  posted_at?: string;
  stale?: boolean;
  archived?: boolean;
  cloud?: string;
  seniority?: string;
  source?: string;
  pipeline_stage?: string;
  min_salary?: number;
  max_salary?: number;
  is_hourly?: boolean;
  visa_sponsor?: boolean;
  sponsor_metadata?: SponsorMetadata;
  salary_text?: string;
  job_id?: string;
  description_hash?: string;
  id?: string;
  listing_health?: {
    uncertain: boolean;
    reason?: string;
    checked_at: string;
    http_status?: number | null;
  };
}

export type JobCardTabId = 'approved' | 'pending' | 'rejected' | 'human_review' | 'settings' | 'analytics' | 'policy' | 'resume';

interface JobCardProps {
  job: JobCardJob;
  activeTab: JobCardTabId;
  authRole: 'admin' | 'user' | null;
  authToken: string | null;
  checkingLiveJobUrl: string | null;
  browserOpenJobUrl: (url: string) => string;
  getRelativeScrapedTime: (dateStr?: string) => { isRecent: boolean; text: string } | null;
  formatScrapedDate: (dateStr: string) => string;
  onCheckLive: (job: JobCardJob) => void;
  onGenerateTailoring: (jobUrl: string) => void;
  onUpdatePipelineStage: (jobUrl: string, newStage: string) => void;
  onSubmitClassifierFeedback: (job: JobCardJob) => void;
  onOpenModal: (job: JobCardJob) => void;
  onApproveOverride: (job: JobCardJob) => void;
  onDeleteJob: (jobUrl: string) => void;
}

/** Single job card rendered in the job list grid (approved/pending/rejected/human_review tabs). */
export default function JobCard({
  job,
  activeTab,
  authRole,
  authToken,
  checkingLiveJobUrl,
  browserOpenJobUrl,
  getRelativeScrapedTime,
  formatScrapedDate,
  onCheckLive,
  onGenerateTailoring,
  onUpdatePipelineStage,
  onSubmitClassifierFeedback,
  onOpenModal,
  onApproveOverride,
  onDeleteJob,
}: JobCardProps) {
  return (
    <div
      className={`relative bg-slate-900/30 backdrop-blur-md rounded-2xl p-5 border flex flex-col justify-between shadow-lg hover:shadow-2xl transition-all duration-300 group ${activeTab === 'approved'
          ? 'border-emerald-500/20 hover:border-emerald-500/50 hover:bg-emerald-950/5'
          : activeTab === 'rejected'
            ? 'border-rose-500/20 hover:border-rose-500/50 hover:bg-rose-950/5'
            : activeTab === 'human_review'
              ? 'border-violet-500/25 hover:border-violet-500/50 hover:bg-violet-950/10'
            : 'border-amber-500/20 hover:border-amber-500/50 hover:bg-amber-950/5'
        }`}
    >
      {/* Top Job Headers */}
      <div>
        <div className="flex items-start justify-between">
          <div className="flex-1 min-w-0">
            <div className="flex items-center flex-wrap gap-1.5 mr-2">
              <h3 className="text-base font-bold text-white group-hover:text-violet-400 transition-colors truncate max-w-[250px] sm:max-w-md">
                {job.job_title}
              </h3>
              <CopyButton text={job.job_title} />
              {(() => {
                const rel = getRelativeScrapedTime(job.scraped_at);
                if (!rel) return null;
                return (
                  <span className={`inline-flex items-center px-2 py-0.5 rounded-lg text-[9px] font-bold uppercase tracking-wider shrink-0 transition-all ${
                    rel.isRecent
                      ? 'bg-emerald-950/80 text-emerald-400 border border-emerald-800/60 animate-pulse'
                      : 'bg-slate-950/60 text-slate-400 border border-slate-850'
                  }`}>
                    {rel.isRecent && <span className="w-1 h-1 rounded-full bg-emerald-400 mr-1 shrink-0 animate-ping"></span>}
                    {rel.text}
                  </span>
                );
              })()}
            </div>
            <p className="text-xs font-semibold text-slate-400 mt-0.5">{job.company_name}</p>
          </div>

          <div className="flex flex-col items-end space-y-1.5 shrink-0">
            {/* Label Badge */}
            <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wider ${activeTab === 'approved'
                ? 'bg-emerald-950/60 text-emerald-400 border border-emerald-800/40'
                : activeTab === 'rejected'
                  ? 'bg-rose-950/60 text-rose-400 border border-rose-800/40'
                  : activeTab === 'human_review'
                    ? 'bg-violet-950/60 text-violet-300 border border-violet-800/40'
                  : 'bg-amber-950/60 text-amber-400 border border-amber-800/40'
              }`}>
              {job.strongest_label}
            </span>

            {/* Stale / live probe badges */}
            {job.stale && (
              <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-[9px] font-extrabold uppercase tracking-wider bg-rose-950/80 text-rose-300 border border-rose-850 animate-pulse">
                Closed / Stale
              </span>
            )}
            {!job.stale && job.listing_health && !job.listing_health.uncertain && (
              <span
                className="inline-flex items-center px-2.5 py-0.5 rounded-full text-[9px] font-extrabold uppercase tracking-wider bg-emerald-950/80 text-emerald-300 border border-emerald-800/60"
                title={job.listing_health.reason || 'Checked via posting URL'}
              >
                Likely active
              </span>
            )}
            {job.listing_health?.uncertain && (
              <span
                className="inline-flex items-center px-2.5 py-0.5 rounded-full text-[9px] font-extrabold uppercase tracking-wider bg-amber-950/80 text-amber-200 border border-amber-800/50"
                title={job.listing_health.reason || 'Probe inconclusive'}
              >
                Unverified
              </span>
            )}
          </div>
        </div>

        {/* Per-job URL probe — placed here so it stays visible without scrolling long cards */}
        <div className="mt-2.5 flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => onCheckLive(job)}
            disabled={checkingLiveJobUrl === job.job_url || !authToken}
            className={`inline-flex items-center px-2.5 py-1 rounded-lg text-[10px] font-bold uppercase tracking-wide border transition-colors ${
              checkingLiveJobUrl === job.job_url
                ? 'bg-slate-800/90 text-slate-500 border-slate-700 cursor-wait'
                : !authToken
                  ? 'bg-slate-900/50 text-slate-600 border-slate-800 cursor-not-allowed'
                  : 'bg-violet-950/50 hover:bg-violet-900/55 text-violet-200 border-violet-800/50 hover:border-violet-600/50'
            }`}
            title={
              !authToken
                ? 'Log in to probe the posting URL'
                : 'Fetch the posting URL and mark Closed / Likely active (saved to your jobs)'
            }
          >
            <Activity
              className={`w-3 h-3 mr-1 ${checkingLiveJobUrl === job.job_url ? 'animate-spin' : ''}`}
            />
            {checkingLiveJobUrl === job.job_url ? 'Checking…' : 'Check live'}
          </button>
          <span className="text-[10px] text-slate-500 leading-snug max-w-[14rem]">
            HTTP probe on this URL · updates badges and Active-only filter
          </span>
        </div>

        {job.visa_sponsor && (
          <div className="mt-3 mb-3 p-4 bg-gradient-to-br from-slate-900/95 to-slate-950/95 border border-blue-900/30 rounded-2xl shadow-xl backdrop-blur-md">
            {/* Panel Header */}
            <div className="flex items-center justify-between mb-3 pb-2.5 border-b border-slate-800/60">
              <div className="flex items-center space-x-2">
                <div className="p-1.5 bg-blue-950/80 border border-blue-800/40 rounded-lg text-blue-400">
                  <Globe className="w-4 h-4" />
                </div>
                <div>
                  <span className="text-[10px] font-bold text-blue-400 uppercase tracking-wider block">Visa Sponsorship Profile</span>
                  <span className="text-xs text-slate-300 font-semibold">{job.company_name}</span>
                </div>
              </div>

              {/* Status Badge */}
              {job.sponsor_metadata?.sponsor_status && (
                <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-[9px] font-bold uppercase tracking-wider border ${
                  job.sponsor_metadata.sponsor_status.toLowerCase().includes('strong')
                    ? 'bg-emerald-950/80 text-emerald-400 border-emerald-800/60'
                    : job.sponsor_metadata.sponsor_status.toLowerCase().includes('active')
                      ? 'bg-blue-950/80 text-blue-400 border-blue-800/60'
                      : 'bg-amber-950/80 text-amber-400 border-amber-800/60'
                }`}>
                  {job.sponsor_metadata.sponsor_status}
                </span>
              )}
            </div>

            {/* Detailed Metadata Grid */}
            {job.sponsor_metadata ? (
              <div className="space-y-3">
                {/* Score Indicator & Trend */}
                <div className="grid grid-cols-2 gap-3 items-center">
                  {job.sponsor_metadata.opt_friendly_score !== undefined && job.sponsor_metadata.opt_friendly_score !== null && (
                    <div>
                      <div className="flex items-center justify-between mb-1">
                        <span className="text-[10px] font-bold text-slate-400 uppercase tracking-wider">Hiring Score</span>
                        <span className={`text-xs font-bold ${
                          job.sponsor_metadata.opt_friendly_score >= 75
                            ? 'text-emerald-400'
                            : job.sponsor_metadata.opt_friendly_score >= 40
                              ? 'text-blue-400'
                              : 'text-amber-400'
                        }`}>
                          {Math.round(job.sponsor_metadata.opt_friendly_score)}/100
                        </span>
                      </div>
                      {/* Gradient Progress Bar */}
                      <div className="w-full h-1.5 bg-slate-800 rounded-full overflow-hidden">
                        <div
                          className={`h-full rounded-full bg-gradient-to-r ${
                            job.sponsor_metadata.opt_friendly_score >= 75
                              ? 'from-emerald-500 to-teal-400'
                              : job.sponsor_metadata.opt_friendly_score >= 40
                                ? 'from-blue-500 to-indigo-400'
                                : 'from-amber-500 to-orange-400'
                          }`}
                          style={{ width: `${job.sponsor_metadata.opt_friendly_score}%` }}
                        />
                      </div>
                    </div>
                  )}

                  {/* Growth Trend */}
                  {job.sponsor_metadata.trend_label && (
                    <div className="bg-slate-950/40 p-2 rounded-xl border border-slate-800/30 flex items-center justify-between">
                      <div>
                        <span className="text-[9px] font-bold text-slate-500 uppercase tracking-wider block">Filing Trend</span>
                        <span className="text-xs font-medium text-slate-200">{job.sponsor_metadata.trend_label}</span>
                      </div>
                      {job.sponsor_metadata.trend_label.toLowerCase().includes('grow') ? (
                        <svg className="w-5 h-5 text-emerald-400 shrink-0 bg-emerald-950/40 p-1 border border-emerald-900/40 rounded-lg" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="2.5">
                          <path strokeLinecap="round" strokeLinejoin="round" d="M13 7h8m0 0v8m0-8L11 17l-5-5-5 5" />
                        </svg>
                      ) : (
                        <svg className="w-5 h-5 text-blue-400 shrink-0 bg-blue-950/40 p-1 border border-blue-900/40 rounded-lg" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="2.5">
                          <path strokeLinecap="round" strokeLinejoin="round" d="M5 12h14" />
                        </svg>
                      )}
                    </div>
                  )}
                </div>

                {/* Filings Grid (2024-2026) */}
                <div className="p-2.5 bg-slate-950/50 border border-slate-800/40 rounded-xl">
                  <div className="flex justify-between items-center mb-2">
                    <span className="text-[9px] font-bold text-slate-500 uppercase tracking-wider">Annual Sponsorship Cases</span>
                    {job.sponsor_metadata.recent_cases ? (
                      <span className="text-[10px] font-bold text-slate-300">
                        Total: {job.sponsor_metadata.recent_cases}
                      </span>
                    ) : null}
                  </div>
                  <div className="grid grid-cols-3 gap-2 text-center text-xs">
                    <div className="bg-slate-900/50 p-1.5 rounded-lg border border-slate-800/30">
                      <span className="text-[9px] text-slate-500 uppercase tracking-wider block">2024</span>
                      <span className="font-bold text-slate-200">{job.sponsor_metadata.cases_2024 !== null && job.sponsor_metadata.cases_2024 !== undefined ? job.sponsor_metadata.cases_2024 : '-'}</span>
                    </div>
                    <div className="bg-slate-900/50 p-1.5 rounded-lg border border-slate-800/30">
                      <span className="text-[9px] text-slate-500 uppercase tracking-wider block">2025</span>
                      <span className="font-bold text-slate-200">{job.sponsor_metadata.cases_2025 !== null && job.sponsor_metadata.cases_2025 !== undefined ? job.sponsor_metadata.cases_2025 : '-'}</span>
                    </div>
                    <div className="bg-slate-900/50 p-1.5 rounded-lg border border-slate-800/30">
                      <span className="text-[9px] text-slate-500 uppercase tracking-wider block">2026</span>
                      <span className="font-bold text-slate-200">{job.sponsor_metadata.cases_2026 !== null && job.sponsor_metadata.cases_2026 !== undefined ? job.sponsor_metadata.cases_2026 : '-'}</span>
                    </div>
                  </div>
                </div>

                {/* General Details Footer */}
                <div className="flex flex-wrap items-center justify-between gap-2 text-[10px] text-slate-400 bg-slate-950/20 p-2 rounded-xl border border-slate-800/20">
                  {job.sponsor_metadata.top_state && (
                    <div className="flex items-center space-x-1">
                      <span className="font-semibold text-slate-500 uppercase">Top State:</span>
                      <span className="text-slate-300 font-medium">{job.sponsor_metadata.top_state}</span>
                    </div>
                  )}
                  {job.sponsor_metadata.w2_contractor && (
                    <div className="flex items-center space-x-1">
                      <span className="font-semibold text-slate-500 uppercase">Type:</span>
                      <span className="text-slate-300 font-medium">{job.sponsor_metadata.w2_contractor}</span>
                    </div>
                  )}
                  {job.sponsor_metadata.employee_count !== undefined && job.sponsor_metadata.employee_count !== null && (
                    <div className="flex items-center space-x-1">
                      <span className="font-semibold text-slate-500 uppercase">Employees:</span>
                      <span className="text-slate-300 font-medium">
                        {job.sponsor_metadata.employee_count.toLocaleString()}
                      </span>
                    </div>
                  )}
                </div>

                {/* Recommended Action / Note */}
                {job.sponsor_metadata.recommended_action && (
                  <div className="text-[10px] text-blue-300/80 bg-blue-950/20 p-2 rounded-lg border border-blue-900/30 italic">
                    💡 <span className="font-medium text-slate-300">Recommendation:</span> {job.sponsor_metadata.recommended_action}
                  </div>
                )}

                {/* Portal & Social Links Row */}
                <div className="flex items-center space-x-2 pt-1">
                  {job.sponsor_metadata.website && (
                    <a
                      href={job.sponsor_metadata.website}
                      target="_blank"
                      rel="noreferrer"
                      className="flex-1 flex items-center justify-center space-x-1 py-1.5 bg-slate-800/40 hover:bg-slate-800/80 border border-slate-700/40 hover:border-slate-600/60 rounded-xl transition text-xs font-semibold text-slate-300 hover:text-slate-100"
                    >
                      <Globe className="w-3.5 h-3.5 text-slate-400" />
                      <span>Website</span>
                    </a>
                  )}

                  {job.sponsor_metadata.career_portal && (
                    <a
                      href={job.sponsor_metadata.career_portal}
                      target="_blank"
                      rel="noreferrer"
                      className="flex-1 flex items-center justify-center space-x-1 py-1.5 bg-blue-950/40 hover:bg-blue-950/80 border border-blue-900/40 hover:border-blue-800/60 rounded-xl transition text-xs font-semibold text-blue-300 hover:text-blue-200"
                    >
                      <ExternalLink className="w-3.5 h-3.5 text-blue-400" />
                      <span>Careers</span>
                    </a>
                  )}

                  {job.sponsor_metadata.linkedin_account && (
                    <a
                      href={job.sponsor_metadata.linkedin_account}
                      target="_blank"
                      rel="noreferrer"
                      className="flex items-center justify-center p-1.5 bg-sky-950/40 hover:bg-sky-950/80 border border-sky-900/40 hover:border-sky-800/60 rounded-xl transition text-sky-400 hover:text-sky-300"
                      title="Company LinkedIn Profile"
                      aria-label="Company LinkedIn profile"
                    >
                      <svg className="w-4 h-4 fill-current" viewBox="0 0 24 24">
                        <path d="M19 0h-14c-2.761 0-5 2.239-5 5v14c0 2.761 2.239 5 5 5h14c2.762 0 5-2.239 5-5v-14c0-2.761-2.238-5-5-5zm-11 19h-3v-11h3v11zm-1.5-12.268c-.966 0-1.75-.79-1.75-1.764s.784-1.764 1.75-1.764 1.75.79 1.75 1.764-.783 1.764-1.75 1.764zm13.5 12.268h-3v-5.604c0-3.368-4-3.113-4 0v5.604h-3v-11h3v1.765c1.396-2.586 7-2.777 7 2.476v6.759z"/>
                      </svg>
                    </a>
                  )}
                </div>
              </div>
            ) : (
              /* Fallback Card for historical visa sponsor when metadata is missing */
              <div className="flex items-center space-x-2 text-xs text-blue-200/70">
                <span className="w-1.5 h-1.5 bg-blue-500 rounded-full animate-pulse shrink-0" />
                <span>Historically sponsored H-1B visas. No detailed OPT metadata profile loaded.</span>
              </div>
            )}
          </div>
        )}

        {/* Location / Req ID details */}
        <div className={`mt-3 grid ${job.salary_text ? 'grid-cols-5' : 'grid-cols-4'} gap-3 text-xs text-slate-400 bg-slate-950/50 p-2.5 rounded-xl border border-slate-800/40`}>
          <div>
            <div className="flex items-center justify-between">
              <span className="font-bold text-slate-500 uppercase text-[9px] tracking-wider block">Location</span>
              <CopyButton text={job.location_work_type} />
            </div>
            <span className="mt-0.5 block truncate text-slate-300 font-medium" title={job.location_work_type}>
              {job.location_work_type}
            </span>
          </div>
          <div>
            <div className="flex items-center justify-between">
              <span className="font-bold text-slate-500 uppercase text-[9px] tracking-wider block">Requirement ID</span>
              {job.requirement_id && <CopyButton text={job.requirement_id} />}
            </div>
            <span className="mt-0.5 block truncate text-slate-300 font-mono font-medium" title={job.requirement_id}>
              {job.requirement_id || 'N/A'}
            </span>
          </div>
          <div>
            <div className="flex items-center justify-between">
              <span className="font-bold text-slate-500 uppercase text-[9px] tracking-wider block">Scraped At</span>
              {job.scraped_at && <CopyButton text={job.scraped_at} />}
            </div>
            <span className="mt-0.5 block truncate text-slate-300 font-medium" title={job.scraped_at}>
              {job.scraped_at ? formatScrapedDate(job.scraped_at) : 'N/A'}
            </span>
          </div>
          <div>
            <div className="flex items-center justify-between">
              <span className="font-bold text-slate-500 uppercase text-[9px] tracking-wider block">Posted At</span>
              {job.posted_at && <CopyButton text={job.posted_at} />}
            </div>
            <span className="mt-0.5 block truncate text-slate-300 font-medium" title={job.posted_at}>
              {job.posted_at ? formatScrapedDate(job.posted_at) : 'N/A'}
            </span>
          </div>
          {job.salary_text && (
            <div>
              <div className="flex items-center justify-between">
                <span className="font-bold text-slate-500 uppercase text-[9px] tracking-wider block">Salary Range</span>
                <CopyButton text={job.salary_text} />
              </div>
              <span className="mt-0.5 block truncate text-emerald-400 font-semibold" title={job.salary_text}>
                {job.salary_text}
              </span>
            </div>
          )}
        </div>

        {/* Red Flags warning if rejected */}
        {job.red_flags && job.red_flags.length > 0 && (
          <div className="mt-3 p-2.5 bg-rose-950/30 border border-rose-900/30 rounded-xl flex items-start space-x-2">
            <AlertTriangle className="w-3.5 h-3.5 text-rose-400 shrink-0 mt-0.5" />
            <div>
              <span className="text-[10px] font-bold text-rose-400 uppercase tracking-wider block">Flags Triggered</span>
              <div className="flex flex-wrap gap-1 mt-1">
                {job.red_flags.map((flag, fIdx) => (
                  <span key={fIdx} className="bg-rose-900/40 text-rose-300 px-2 py-0.5 rounded text-[9px] border border-rose-800/30 font-medium">
                    {flag}
                  </span>
                ))}
              </div>
            </div>
          </div>
        )}

        {/* Confidence Scorer */}
        {job.confidence_score !== undefined && (
          <div className="mt-3.5 flex items-center justify-between text-xs">
            <span className="text-slate-400 font-medium">Policy Confidence Score:</span>
            <div className="flex items-center space-x-1.5 font-bold">
              <span className={`text-[10px] font-bold uppercase tracking-wide px-1.5 py-0.5 rounded ${
                job.confidence_score >= 90 ? 'bg-emerald-950/60 text-emerald-400' : job.confidence_score >= 70 ? 'bg-amber-950/60 text-amber-400' : job.confidence_score >= 50 ? 'bg-orange-950/60 text-orange-400' : 'bg-rose-950/60 text-rose-400'
              }`}>
                {job.confidence_score >= 90 ? 'Very Strong' : job.confidence_score >= 70 ? 'Strong' : job.confidence_score >= 50 ? 'Borderline' : 'Review Needed'}
              </span>
              <span className={
                job.confidence_score >= 90 ? 'text-emerald-400' : job.confidence_score >= 70 ? 'text-amber-400' : 'text-rose-400'
              }>
                {job.confidence_score}%
              </span>
              <div className="w-20 bg-slate-800 rounded-full h-1.5 overflow-hidden">
                <div
                  className={`h-full rounded-full ${job.confidence_score >= 90 ? 'bg-emerald-500' : job.confidence_score >= 70 ? 'bg-amber-500' : 'bg-rose-500'
                    }`}
                  style={{ width: `${job.confidence_score}%` }}
                />
              </div>
            </div>
          </div>
        )}

        {/* Semantic Match Scorer */}
        {job.match_score !== undefined && (
          <div className="mt-2 flex items-center justify-between text-xs">
            <span className="text-purple-300 font-medium">Semantic Match Score:</span>
            <div className="flex items-center space-x-1.5 font-bold">
              <span className={
                job.match_score >= 80 ? 'text-purple-400' : job.match_score >= 60 ? 'text-indigo-400' : 'text-slate-400'
              }>
                {job.match_score}%
              </span>
              <div className="w-20 bg-slate-800 rounded-full h-1.5 overflow-hidden">
                <div
                  className={`h-full rounded-full ${job.match_score >= 80 ? 'bg-purple-500' : job.match_score >= 60 ? 'bg-indigo-500' : 'bg-slate-500'
                    }`}
                  style={{ width: `${job.match_score}%` }}
                />
              </div>
            </div>
          </div>
        )}

        {(() => {
          const pl = job.apply_decision_payload;
          if (!pl || typeof pl !== 'object') return null;
          const d = pl as DecisionPayload;
          if (
            !d.recommendation &&
            d.fit_score == null &&
            !d.ownership_strength &&
            !d.review_reason
          ) {
            return null;
          }
          return (
            <div className="mt-3 text-xs bg-violet-950/20 p-3 rounded-xl border border-violet-900/30 space-y-1.5">
              <span className="font-bold text-violet-400 uppercase text-[9px] tracking-wider block">Classifier output</span>
              <div className="flex flex-wrap gap-x-3 gap-y-1 text-slate-300">
                {d.recommendation != null && d.recommendation !== '' && (
                  <span>
                    <span className="text-slate-500">Recommendation:</span>{' '}
                    <span className="font-semibold text-white">{String(d.recommendation)}</span>
                  </span>
                )}
                {d.fit_score != null && (
                  <span>
                    <span className="text-slate-500">Fit:</span>{' '}
                    <span className="font-semibold text-white">{d.fit_score}</span>
                  </span>
                )}
                {d.ownership_strength != null && d.ownership_strength !== '' && (
                  <span>
                    <span className="text-slate-500">Ownership:</span>{' '}
                    <span className="font-semibold text-white">{String(d.ownership_strength)}</span>
                  </span>
                )}
              </div>
              {d.review_reason != null && String(d.review_reason).trim() !== '' && (
                <p className="text-slate-400 leading-relaxed">
                  <span className="text-slate-500">Review reason:</span> {String(d.review_reason)}
                </p>
              )}
            </div>
          );
        })()}

        {/* Decision Rationale */}
        {job.rationale && (
          <div className="mt-3 text-xs bg-slate-950/30 p-3 rounded-xl border border-slate-850">
            <span className="font-bold text-slate-500 uppercase text-[9px] tracking-wider block mb-1">Decision Rationale</span>
            <p className="text-slate-300 line-clamp-3 leading-relaxed">{job.rationale}</p>
          </div>
        )}
      </div>

      {/* Card Actions Bottom */}
      <div className="mt-5 pt-3.5 border-t border-slate-850 flex items-center justify-between">

        <a
          href={browserOpenJobUrl(job.job_url)}
          target="_blank"
          rel="noreferrer"
          className="inline-flex items-center text-xs text-violet-400 hover:text-violet-300 font-semibold group/link truncate min-w-0"
        >
          View Site
          <ExternalLink className="w-3 h-3 ml-1 shrink-0 group-hover/link:translate-x-0.5 group-hover/link:-translate-y-0.5 transition-transform" />
        </a>

        <div className="flex items-center space-x-2">
          {activeTab === 'approved' && authRole === 'admin' && (
            <>
              <button
                type="button"
                onClick={() => onGenerateTailoring(job.job_url)}
                className="p-1.5 bg-emerald-950/40 hover:bg-emerald-900/60 text-emerald-400 hover:text-emerald-300 border border-emerald-800/40 rounded-xl transition-all"
                title="AI Tailor Application"
                aria-label="AI tailor application"
              >
                <FileText className="w-4 h-4" />
              </button>
              <ResumeGenerator
                jd={job.job_description}
                jobTitle={job.job_title}
                companyName={job.company_name}
                compact={true}
              />
            </>
          )}
          {activeTab === 'approved' && (
            authRole === 'admin' ? (
              <select
                value={job.pipeline_stage || 'Approved'}
                onChange={e => onUpdatePipelineStage(job.job_url, e.target.value)}
                className="bg-slate-900 border border-slate-800 rounded-xl px-2 py-1.5 text-xs text-slate-300 focus:outline-none cursor-pointer hover:border-slate-700 transition-colors"
              >
                {['Approved', 'Applied', 'Phone Screen', 'Technical Interview', 'Offer', 'Rejected'].map(s => (
                  <option key={s} value={s}>{s}</option>
                ))}
              </select>
            ) : (
              <span className="inline-flex items-center text-xs font-semibold text-violet-400 bg-violet-950/40 px-2.5 py-1.5 rounded-xl border border-violet-900/30">
                {job.pipeline_stage || 'Approved'}
              </span>
            )
          )}

          {activeTab === 'human_review' && (
            <button
              type="button"
              onClick={() => onSubmitClassifierFeedback(job)}
              className="inline-flex items-center px-3 py-1.5 bg-violet-950/50 hover:bg-violet-900/60 text-violet-200 rounded-xl text-xs font-semibold border border-violet-800/40 transition-colors"
            >
              Log feedback
            </button>
          )}
          {/* Inspect details button */}
          <button
            onClick={() => onOpenModal(job)}
            className="inline-flex items-center px-3 py-1.5 bg-slate-800 hover:bg-slate-750 text-slate-300 hover:text-white rounded-xl text-xs font-semibold border border-slate-700 transition-colors"
          >
            <Edit3 className="w-3 h-3 mr-1" />
            {authRole === 'admin' ? 'Inspect & Edit' : 'Inspect'}
          </button>

          {/* Action specific buttons */}
          {activeTab === 'approved' ? null : (
            /* If rejected or candidate, show quick Approve Override */
            authRole === 'admin' && (
              <button
                onClick={() => onApproveOverride(job)}
                className="inline-flex items-center px-3 py-1.5 bg-gradient-to-r from-violet-600 to-indigo-600 hover:from-violet-500 hover:to-indigo-500 text-white rounded-xl text-xs font-bold border border-violet-500/20 active:scale-95 shadow-md shadow-violet-500/10 transition-all"
              >
                Approve Override
              </button>
            )
          )}

          {/* Delete/Archive Button */}
          {authRole === 'admin' && (
            <button
              onClick={() => onDeleteJob(job.job_url)}
              className="inline-flex items-center p-1.5 bg-rose-950/40 hover:bg-rose-900/60 text-rose-400 hover:text-rose-200 rounded-xl text-xs font-semibold border border-rose-800/40 transition-colors shrink-0"
              title="Delete / Archive job posting"
              aria-label="Delete or archive job posting"
            >
              <XCircle className="w-4 h-4" />
            </button>
          )}
        </div>
      </div>

    </div>
  );
}
