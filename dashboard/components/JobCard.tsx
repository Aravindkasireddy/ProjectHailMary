'use client';

import {
  ExternalLink,
  Edit3,
  FileText,
  Globe,
  Activity,
  AlertTriangle,
  XCircle,
  ChevronDown,
} from 'lucide-react';
import CopyButton from './CopyButton';
import ResumeGenerator from './ResumeGenerator';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Progress } from '@/components/ui/progress';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { cn } from '@/lib/utils';

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
  application_status?: 'applied' | 'phone_screen' | 'interview' | 'offer' | 'rejected' | null;
  applied_at?: string | null;
}

export type JobCardTabId = 'approved' | 'new_today' | 'applications' | 'pending' | 'rejected' | 'human_review' | 'settings' | 'analytics' | 'policy' | 'resume';

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
  onUpdateApplicationStatus: (jobUrl: string, status: string | null) => void;
}

const APP_STATUS_LABELS: Record<string, string> = {
  applied: '📨 Applied',
  phone_screen: '📞 Phone Screen',
  interview: '🎯 Interview',
  offer: '🎉 Offer',
  rejected: '❌ Rejected',
};

const PIPELINE_STAGES = ['Approved', 'Applied', 'Phone Screen', 'Technical Interview', 'Offer', 'Rejected'];

function confidenceBand(score: number) {
  if (score >= 90) return { label: 'Very Strong', color: 'text-emerald-400', bg: 'bg-emerald-950/60', bar: 'bg-emerald-500' };
  if (score >= 70) return { label: 'Strong',      color: 'text-amber-400',   bg: 'bg-amber-950/60',   bar: 'bg-amber-500' };
  if (score >= 50) return { label: 'Borderline',  color: 'text-orange-400',  bg: 'bg-orange-950/60',  bar: 'bg-orange-500' };
  return              { label: 'Review Needed', color: 'text-rose-400',    bg: 'bg-rose-950/60',    bar: 'bg-rose-500' };
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
  onUpdateApplicationStatus,
}: JobCardProps) {
  const band = confidenceBand(job.confidence_score ?? 0);

  return (
    <Card
      className={cn(
        'mission-card relative p-5 flex flex-col justify-between transition-all duration-300',
        'hover:-translate-y-0.5 hover:shadow-cyan-500/20 animate-in fade-in slide-in-from-bottom-2 group',
        activeTab === 'approved' && 'mc-approved',
        activeTab === 'rejected' && 'mc-rejected',
        activeTab === 'human_review' && 'mc-approved',
      )}
    >
      {/* ── Header ─────────────────────────────────────────── */}
      <div>
        <div className="flex items-start justify-between">
          <div className="flex-1 min-w-0">
            <div className="flex items-center flex-wrap gap-1.5 mr-2">
              <h3
                className="text-base font-bold text-[#D0E8FF] group-hover:text-[#00F0FF] transition-colors truncate max-w-[250px] sm:max-w-md"
                style={{ letterSpacing: '-0.01em' }}
              >
                {job.job_title}
              </h3>
              <CopyButton text={job.job_title} />
              {(() => {
                const rel = getRelativeScrapedTime(job.scraped_at);
                if (!rel) return null;
                return (
                  <Badge
                    variant="outline"
                    className={cn(
                      'text-[9px] font-bold uppercase tracking-wider shrink-0',
                      rel.isRecent
                        ? 'bg-emerald-950/80 text-emerald-400 border-emerald-800/60 animate-pulse'
                        : 'bg-slate-950/60 text-slate-400 border-slate-800',
                    )}
                  >
                    {rel.isRecent && (
                      <span className="w-1 h-1 rounded-full bg-emerald-400 mr-1 shrink-0 animate-ping" />
                    )}
                    {rel.text}
                  </Badge>
                );
              })()}
            </div>
            <p className="text-xs font-semibold text-slate-400 mt-0.5">{job.company_name}</p>
          </div>

          {/* Right badges */}
          <div className="flex flex-col items-end gap-1.5 shrink-0">
            <Badge
              variant={activeTab === 'approved' ? 'default' : activeTab === 'rejected' ? 'destructive' : 'outline'}
              className={cn(
                activeTab === 'human_review' && 'border-violet-700 text-violet-300 bg-violet-950/40',
                activeTab === 'pending' && 'border-amber-700 text-amber-300 bg-amber-950/40',
              )}
            >
              {job.strongest_label}
            </Badge>

            {job.stale && (
              <Badge variant="destructive" className="animate-pulse">Closed</Badge>
            )}
            {!job.stale && job.listing_health && !job.listing_health.uncertain && (
              <Badge variant="default" title={job.listing_health.reason || 'Checked via posting URL'}>
                Live
              </Badge>
            )}
            {job.listing_health?.uncertain && (
              <Badge variant="outline" className="border-amber-700 text-amber-300" title={job.listing_health.reason || 'Probe inconclusive'}>
                Unverified
              </Badge>
            )}
          </div>
        </div>

        {/* Live check row */}
        <div className="mt-2.5 flex flex-wrap items-center gap-2">
          <Button
            size="sm"
            variant={checkingLiveJobUrl === job.job_url ? 'ghost' : 'outline'}
            onClick={() => onCheckLive(job)}
            disabled={checkingLiveJobUrl === job.job_url || !authToken}
            className="h-7 text-[11px] border-cyan-800/50 text-cyan-300 hover:bg-cyan-950/40 hover:text-cyan-200"
            title={!authToken ? 'Log in to probe the posting URL' : 'Fetch the posting URL and mark Closed / Likely active'}
          >
            <Activity className={cn('w-3 h-3 mr-1', checkingLiveJobUrl === job.job_url && 'animate-spin')} />
            {checkingLiveJobUrl === job.job_url ? 'Checking…' : 'Check live'}
          </Button>
          <span className="text-[10px] text-slate-500 leading-snug max-w-[14rem]">
            HTTP probe · updates badges and Active-only filter
          </span>
        </div>

        {/* ── Visa Sponsor Panel ─────────────────────────────── */}
        {job.visa_sponsor && (
          <div className="mt-3 mb-3 p-4 bg-gradient-to-br from-slate-900/95 to-slate-950/95 border border-blue-900/30 rounded-2xl shadow-xl backdrop-blur-md">
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
              {job.sponsor_metadata?.sponsor_status && (
                <Badge
                  variant="outline"
                  className={cn(
                    'text-[9px] uppercase tracking-wider',
                    job.sponsor_metadata.sponsor_status.toLowerCase().includes('strong')
                      ? 'bg-emerald-950/80 text-emerald-400 border-emerald-800/60'
                      : job.sponsor_metadata.sponsor_status.toLowerCase().includes('active')
                        ? 'bg-blue-950/80 text-blue-400 border-blue-800/60'
                        : 'bg-amber-950/80 text-amber-400 border-amber-800/60',
                  )}
                >
                  {job.sponsor_metadata.sponsor_status}
                </Badge>
              )}
            </div>

            {job.sponsor_metadata ? (
              <div className="space-y-3">
                <div className="grid grid-cols-2 gap-3 items-center">
                  {job.sponsor_metadata.opt_friendly_score != null && (
                    <div>
                      <div className="flex items-center justify-between mb-1">
                        <span className="text-[10px] font-bold text-slate-400 uppercase tracking-wider">Hiring Score</span>
                        <span className={cn('text-xs font-bold',
                          job.sponsor_metadata.opt_friendly_score >= 75 ? 'text-emerald-400'
                            : job.sponsor_metadata.opt_friendly_score >= 40 ? 'text-blue-400'
                              : 'text-amber-400'
                        )}>
                          {Math.round(job.sponsor_metadata.opt_friendly_score)}/100
                        </span>
                      </div>
                      <Progress
                        value={job.sponsor_metadata.opt_friendly_score}
                        className="h-1.5 bg-slate-800"
                      />
                    </div>
                  )}
                  {job.sponsor_metadata.trend_label && (
                    <div className="bg-slate-950/40 p-2 rounded-xl border border-slate-800/30 flex items-center justify-between">
                      <div>
                        <span className="text-[9px] font-bold text-slate-500 uppercase tracking-wider block">Filing Trend</span>
                        <span className="text-xs font-medium text-slate-200">{job.sponsor_metadata.trend_label}</span>
                      </div>
                    </div>
                  )}
                </div>

                <div className="p-2.5 bg-slate-950/50 border border-slate-800/40 rounded-xl">
                  <div className="flex justify-between items-center mb-2">
                    <span className="text-[9px] font-bold text-slate-500 uppercase tracking-wider">Annual Sponsorship Cases</span>
                    {job.sponsor_metadata.recent_cases ? (
                      <span className="text-[10px] font-bold text-slate-300">Total: {job.sponsor_metadata.recent_cases}</span>
                    ) : null}
                  </div>
                  <div className="grid grid-cols-3 gap-2 text-center text-xs">
                    {(['cases_2024', 'cases_2025', 'cases_2026'] as const).map((key, i) => (
                      <div key={key} className="bg-slate-900/50 p-1.5 rounded-lg border border-slate-800/30">
                        <span className="text-[9px] text-slate-500 uppercase tracking-wider block">{2024 + i}</span>
                        <span className="font-bold text-slate-200">
                          {job.sponsor_metadata![key] != null ? job.sponsor_metadata![key] : '-'}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>

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
                  {job.sponsor_metadata.employee_count != null && (
                    <div className="flex items-center space-x-1">
                      <span className="font-semibold text-slate-500 uppercase">Employees:</span>
                      <span className="text-slate-300 font-medium">{job.sponsor_metadata.employee_count.toLocaleString()}</span>
                    </div>
                  )}
                </div>

                {job.sponsor_metadata.recommended_action && (
                  <div className="text-[10px] text-blue-300/80 bg-blue-950/20 p-2 rounded-lg border border-blue-900/30 italic">
                    💡 <span className="font-medium text-slate-300">Recommendation:</span> {job.sponsor_metadata.recommended_action}
                  </div>
                )}

                <div className="flex items-center space-x-2 pt-1">
                  {job.sponsor_metadata.website && (
                    <a href={job.sponsor_metadata.website} target="_blank" rel="noreferrer" className="flex-1">
                      <Button variant="outline" size="sm" className="w-full text-xs border-slate-700/40 text-slate-300 hover:text-slate-100">
                        <Globe className="w-3.5 h-3.5 mr-1" /> Website
                      </Button>
                    </a>
                  )}
                  {job.sponsor_metadata.career_portal && (
                    <a href={job.sponsor_metadata.career_portal} target="_blank" rel="noreferrer" className="flex-1">
                      <Button variant="outline" size="sm" className="w-full text-xs border-blue-900/40 text-blue-300 hover:text-blue-200">
                        <ExternalLink className="w-3.5 h-3.5 mr-1" /> Careers
                      </Button>
                    </a>
                  )}
                  {job.sponsor_metadata.linkedin_account && (
                    <a href={job.sponsor_metadata.linkedin_account} target="_blank" rel="noreferrer" title="Company LinkedIn">
                      <Button variant="outline" size="sm" className="border-sky-900/40 text-sky-400 hover:text-sky-300 px-2">
                        <svg className="w-4 h-4 fill-current" viewBox="0 0 24 24">
                          <path d="M19 0h-14c-2.761 0-5 2.239-5 5v14c0 2.761 2.239 5 5 5h14c2.762 0 5-2.239 5-5v-14c0-2.761-2.238-5-5-5zm-11 19h-3v-11h3v11zm-1.5-12.268c-.966 0-1.75-.79-1.75-1.764s.784-1.764 1.75-1.764 1.75.79 1.75 1.764-.783 1.764-1.75 1.764zm13.5 12.268h-3v-5.604c0-3.368-4-3.113-4 0v5.604h-3v-11h3v1.765c1.396-2.586 7-2.777 7 2.476v6.759z" />
                        </svg>
                      </Button>
                    </a>
                  )}
                </div>
              </div>
            ) : (
              <div className="flex items-center space-x-2 text-xs text-blue-200/70">
                <span className="w-1.5 h-1.5 bg-blue-500 rounded-full animate-pulse shrink-0" />
                <span>Historically sponsored H-1B visas. No detailed OPT metadata profile loaded.</span>
              </div>
            )}
          </div>
        )}

        {/* ── Meta grid ──────────────────────────────────────── */}
        <div
          className={cn('mt-3 grid gap-3 text-xs p-2.5 border rounded-lg', job.salary_text ? 'grid-cols-5' : 'grid-cols-4')}
          style={{ background: 'rgba(5,7,20,0.6)', borderColor: 'var(--t3)' }}
        >
          {[
            { label: 'Location',       value: job.location_work_type, copy: job.location_work_type },
            { label: 'Requirement ID', value: job.requirement_id || 'N/A', copy: job.requirement_id, mono: true },
            { label: 'Scraped At',     value: job.scraped_at ? formatScrapedDate(job.scraped_at) : 'N/A', copy: job.scraped_at },
            { label: 'Posted At',      value: job.posted_at ? formatScrapedDate(job.posted_at) : 'N/A', copy: job.posted_at },
            ...(job.salary_text ? [{ label: 'Salary Range', value: job.salary_text, copy: job.salary_text, salary: true }] : []),
          ].map(({ label, value, copy, mono, salary }) => (
            <div key={label}>
              <div className="flex items-center justify-between">
                <span className="font-bold text-slate-500 uppercase text-[9px] tracking-wider block">{label}</span>
                {copy && <CopyButton text={copy} />}
              </div>
              <span
                className={cn('mt-0.5 block truncate font-medium', mono && 'font-mono', salary ? 'text-emerald-400 font-semibold' : 'text-slate-300')}
                title={value}
              >
                {value}
              </span>
            </div>
          ))}
        </div>

        {/* ── Red Flags ──────────────────────────────────────── */}
        {job.red_flags && job.red_flags.length > 0 && (
          <div className="mt-3 p-2.5 bg-rose-950/30 border border-rose-900/30 rounded-xl flex items-start space-x-2">
            <AlertTriangle className="w-3.5 h-3.5 text-rose-400 shrink-0 mt-0.5" />
            <div>
              <span className="text-[10px] font-bold text-rose-400 uppercase tracking-wider block">Flags Triggered</span>
              <div className="flex flex-wrap gap-1 mt-1">
                {job.red_flags.map((flag, i) => (
                  <Badge key={i} variant="destructive" className="text-[9px] bg-rose-900/40 text-rose-300 border-rose-800/30">
                    {flag}
                  </Badge>
                ))}
              </div>
            </div>
          </div>
        )}

        {/* ── Confidence Score ───────────────────────────────── */}
        {job.confidence_score !== undefined && (
          <div className="mt-3.5 flex items-center justify-between text-xs">
            <span className="text-slate-400 font-medium">Policy Confidence Score:</span>
            <div className="flex items-center gap-1.5 font-bold">
              <Badge variant="outline" className={cn('text-[10px] uppercase tracking-wide', band.bg, band.color, 'border-0')}>
                {band.label}
              </Badge>
              <span className={band.color}>{job.confidence_score}%</span>
              <Progress value={job.confidence_score} className="w-20 h-1.5 bg-slate-800" />
            </div>
          </div>
        )}

        {/* ── Semantic Match Score ───────────────────────────── */}
        {job.match_score !== undefined && (
          <div className="mt-2 flex items-center justify-between text-xs">
            <span className="text-purple-300 font-medium">Semantic Match Score:</span>
            <div className="flex items-center gap-1.5 font-bold">
              <span className={job.match_score >= 80 ? 'text-purple-400' : job.match_score >= 60 ? 'text-indigo-400' : 'text-slate-400'}>
                {job.match_score}%
              </span>
              <Progress value={job.match_score} className="w-20 h-1.5 bg-slate-800" />
            </div>
          </div>
        )}

        {/* ── Classifier output ──────────────────────────────── */}
        {(() => {
          const d = job.apply_decision_payload as DecisionPayload | undefined;
          if (!d || (!d.recommendation && d.fit_score == null && !d.ownership_strength && !d.review_reason)) return null;
          return (
            <div className="mt-3 text-xs bg-violet-950/20 p-3 rounded-xl border border-violet-900/30 space-y-1.5">
              <span className="font-bold text-violet-400 uppercase text-[9px] tracking-wider block">Classifier output</span>
              <div className="flex flex-wrap gap-x-3 gap-y-1 text-slate-300">
                {d.recommendation && <span><span className="text-slate-500">Recommendation:</span> <span className="font-semibold text-white">{String(d.recommendation)}</span></span>}
                {d.fit_score != null && <span><span className="text-slate-500">Fit:</span> <span className="font-semibold text-white">{d.fit_score}</span></span>}
                {d.ownership_strength && <span><span className="text-slate-500">Ownership:</span> <span className="font-semibold text-white">{String(d.ownership_strength)}</span></span>}
              </div>
              {d.review_reason && String(d.review_reason).trim() && (
                <p className="text-slate-400 leading-relaxed"><span className="text-slate-500">Review reason:</span> {String(d.review_reason)}</p>
              )}
            </div>
          );
        })()}

        {/* ── Decision Rationale ─────────────────────────────── */}
        {job.rationale && (
          <div className="mt-3 text-xs bg-slate-950/30 p-3 rounded-xl border border-slate-800">
            <span className="font-bold text-slate-500 uppercase text-[9px] tracking-wider block mb-1">Decision Rationale</span>
            <p className="text-slate-300 line-clamp-3 leading-relaxed">{job.rationale}</p>
          </div>
        )}
      </div>

      {/* ── Action Footer ──────────────────────────────────────── */}
      <div className="mt-4 pt-3 border-t border-[var(--t3)] flex items-center justify-between gap-2 flex-wrap">

        <a
          href={browserOpenJobUrl(job.job_url)}
          target="_blank"
          rel="noreferrer"
          className="btn-mission btn-mission-cyan inline-flex items-center"
        >
          VIEW ↗ <ExternalLink className="w-3 h-3 ml-1 shrink-0" />
        </a>

        <div className="flex items-center gap-1.5 flex-wrap">
          {activeTab === 'approved' && authRole === 'admin' && (
            <>
              <Button
                size="sm"
                variant="outline"
                onClick={() => onGenerateTailoring(job.job_url)}
                className="border-emerald-800/50 text-emerald-300 hover:bg-emerald-950/40 h-7 px-2"
                title="AI Tailor Application"
              >
                <FileText className="w-3.5 h-3.5" />
              </Button>
              <ResumeGenerator
                jd={job.job_description}
                jobTitle={job.job_title}
                companyName={job.company_name}
                compact={true}
              />
            </>
          )}

          {/* Pipeline Stage */}
          {activeTab === 'approved' && (
            authRole === 'admin' ? (
              <Select
                value={job.pipeline_stage || 'Approved'}
                onValueChange={(v) => v && onUpdatePipelineStage(job.job_url, v)}
              >
                <SelectTrigger className="h-7 text-[11px] font-bold w-auto min-w-[110px] bg-[var(--navy2)] border-[var(--t3)] text-[var(--t1)]">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent className="bg-[var(--navy2)] border-[var(--t2)] text-[var(--t1)]">
                  {PIPELINE_STAGES.map(s => (
                    <SelectItem key={s} value={s} className="text-xs focus:bg-[var(--navy3)] focus:text-[var(--cyan)]">{s}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            ) : (
              <Badge variant="outline" className="border-violet-700 text-violet-300 bg-violet-950/40">
                {job.pipeline_stage || 'Approved'}
              </Badge>
            )
          )}

          {activeTab === 'human_review' && (
            <Button size="sm" variant="outline" onClick={() => onSubmitClassifierFeedback(job)}
              className="h-7 border-cyan-800/50 text-cyan-300 hover:bg-cyan-950/40">
              Log feedback
            </Button>
          )}

          <Button size="sm" variant="ghost" onClick={() => onOpenModal(job)}
            className="h-7 text-slate-300 hover:text-white hover:bg-slate-800/60">
            <Edit3 className="w-3 h-3 mr-1" />
            {authRole === 'admin' ? 'Inspect & Edit' : 'Inspect'}
          </Button>

          {activeTab !== 'approved' && authRole === 'admin' && (
            <Button size="sm" variant="outline" onClick={() => onApproveOverride(job)}
              className="h-7 border-emerald-800/50 text-emerald-300 hover:bg-emerald-950/40">
              ▲ Approve
            </Button>
          )}

          {/* Application Status — DropdownMenu replaces the fragile CSS hover trick */}
          <DropdownMenu>
            <DropdownMenuTrigger
              className={cn(
                'btn-mission h-7 text-[11px] inline-flex items-center gap-1',
                job.application_status ? 'btn-mission-cyan' : 'btn-mission-ghost',
              )}
              title="Track application status"
            >
              {job.application_status
                ? { applied: '📨', phone_screen: '📞', interview: '🎯', offer: '🎉', rejected: '❌' }[job.application_status]
                : '📋'
              }{' '}
              {job.application_status
                ? { applied: 'Applied', phone_screen: 'Screen', interview: 'Interview', offer: 'Offer', rejected: 'Rej' }[job.application_status]
                : 'Track'
              }
              <ChevronDown className="w-3 h-3 opacity-60" />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="bg-[var(--navy2)] border-[var(--t2)] text-[var(--t1)] min-w-[140px]">
              {Object.entries(APP_STATUS_LABELS).map(([s, label]) => (
                <DropdownMenuItem
                  key={s}
                  onClick={() => onUpdateApplicationStatus(job.job_url, s)}
                  className={cn(
                    'text-xs cursor-pointer focus:bg-[var(--navy3)]',
                    job.application_status === s && 'text-[var(--cyan)]',
                  )}
                >
                  {label}
                </DropdownMenuItem>
              ))}
              {job.application_status && (
                <>
                  <DropdownMenuSeparator className="bg-[var(--t3)]" />
                  <DropdownMenuItem
                    onClick={() => onUpdateApplicationStatus(job.job_url, null)}
                    className="text-xs text-[var(--red)] cursor-pointer focus:bg-[var(--navy3)] focus:text-[var(--red)]"
                  >
                    ✕ Clear
                  </DropdownMenuItem>
                </>
              )}
            </DropdownMenuContent>
          </DropdownMenu>

          {authRole === 'admin' && (
            <Button
              size="sm"
              variant="ghost"
              onClick={() => onDeleteJob(job.job_url)}
              className="h-7 text-rose-400 hover:text-rose-300 hover:bg-rose-950/40 px-2"
              title="Delete / Archive"
            >
              <XCircle className="w-3.5 h-3.5" />
            </Button>
          )}
        </div>
      </div>
    </Card>
  );
}
