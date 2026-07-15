'use client';

import {
  AlertTriangle,
  BarChart3,
  Briefcase,
  Database,
  RefreshCw,
  Shield,
  XCircle,
  CheckCircle2,
} from 'lucide-react';
import { AnalyticsData, Job, SalaryInsights } from './types';

interface AnalyticsPanelProps {
  analyticsLoading: boolean;
  analyticsData: AnalyticsData | null;
  salaryInsightsLoading: boolean;
  salaryInsights: SalaryInsights | null;
  approvedJobs: Job[];
  dedupedJobs: Job[];
  onSourceClick: (src: string) => void;
}

function getSourceGradient(srcName: string): string {
  const s = srcName.toLowerCase();
  if (s.includes('greenhouse')) return 'from-emerald-400 to-teal-500';
  if (s.includes('lever')) return 'from-orange-400 to-amber-500';
  if (s.includes('ashby')) return 'from-violet-400 to-fuchsia-500';
  if (s.includes('workable')) return 'from-blue-400 to-indigo-500';
  if (s.includes('remotely') || s.includes('remote.co') || s.includes('remote')) return 'from-rose-400 to-pink-500';
  if (s.includes('linkedin')) return 'from-sky-400 to-blue-500';
  if (s.includes('y combinator') || s.includes('workatastartup')) return 'from-yellow-400 to-orange-500';
  return 'from-indigo-400 to-violet-500';
}

function getSourceDotColor(srcName: string): string {
  const s = srcName.toLowerCase();
  if (s.includes('greenhouse')) return 'bg-emerald-400';
  if (s.includes('lever')) return 'bg-orange-400';
  if (s.includes('ashby')) return 'bg-violet-400';
  if (s.includes('workable')) return 'bg-blue-400';
  if (s.includes('remotely') || s.includes('remote.co') || s.includes('remote')) return 'bg-rose-400';
  if (s.includes('linkedin')) return 'bg-sky-400';
  if (s.includes('y combinator') || s.includes('workatastartup')) return 'bg-yellow-400';
  return 'bg-indigo-400';
}

export default function AnalyticsPanel({
  analyticsLoading,
  analyticsData,
  salaryInsightsLoading,
  salaryInsights,
  approvedJobs,
  dedupedJobs,
  onSourceClick,
}: AnalyticsPanelProps) {
  if (analyticsLoading || !analyticsData) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center p-12 text-center border border-slate-800 rounded-2xl bg-slate-900/10">
        <RefreshCw className="w-10 h-10 text-violet-500 animate-spin mb-3" />
        <p className="text-sm text-slate-400 font-medium">Computing sourcing metrics & analytics...</p>
      </div>
    );
  }

  const approvedWithConf = dedupedJobs.filter(j => j.apply_decision === 'APPLY' && j.confidence_score !== undefined);
  const bands = {
    veryStrong: approvedWithConf.filter(j => (j.confidence_score ?? 0) >= 90).length,
    strong: approvedWithConf.filter(j => (j.confidence_score ?? 0) >= 70 && (j.confidence_score ?? 0) < 90).length,
    borderline: approvedWithConf.filter(j => (j.confidence_score ?? 0) >= 50 && (j.confidence_score ?? 0) < 70).length,
    reviewNeeded: approvedWithConf.filter(j => (j.confidence_score ?? 0) < 50).length,
  };
  const totalConf = approvedWithConf.length || 1;
  const recentOutOfScope = dedupedJobs
    .filter(j => j.strongest_label === 'OutOfScope' || j.apply_decision === 'DO_NOT_APPLY')
    .sort((a, b) => new Date(b.scraped_at || 0).getTime() - new Date(a.scraped_at || 0).getTime())
    .slice(0, 8);

  return (
    <div className="space-y-6 animate-in fade-in duration-300">

      {/* Summary Cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <div className="bg-slate-900/40 backdrop-blur-md border border-slate-800/80 p-5 rounded-2xl shadow-[0_4px_20px_rgba(0,0,0,0.3)] hover:-translate-y-0.5 hover:border-slate-700/80 transition-all duration-300 group">
          <div className="flex justify-between items-start">
            <p className="text-xs text-slate-400 font-semibold uppercase tracking-wider">Total Sourced</p>
            <Database className="w-4 h-4 text-slate-400 group-hover:text-white transition-colors" />
          </div>
          <h3 className="text-3xl font-extrabold text-white mt-2 tracking-tight">{analyticsData.total_sourced}</h3>
          <p className="text-[10px] text-slate-500 mt-1">Jobs scanned across platforms</p>
        </div>
        <div className="bg-slate-900/40 backdrop-blur-md border border-emerald-950/60 p-5 rounded-2xl shadow-[0_4px_20px_rgba(0,0,0,0.3)] hover:-translate-y-0.5 hover:border-emerald-800/50 transition-all duration-300 group">
          <div className="flex justify-between items-start">
            <p className="text-xs text-slate-400 font-semibold uppercase tracking-wider">Approved Jobs</p>
            <CheckCircle2 className="w-4 h-4 text-emerald-400 group-hover:text-emerald-300 transition-colors" />
          </div>
          <h3 className="text-3xl font-extrabold text-emerald-400 mt-2 tracking-tight">{analyticsData.approved}</h3>
          <p className="text-[10px] text-slate-500 mt-1">Passed automated pre-screening</p>
        </div>
        <div className="bg-slate-900/40 backdrop-blur-md border border-rose-950/60 p-5 rounded-2xl shadow-[0_4px_20px_rgba(0,0,0,0.3)] hover:-translate-y-0.5 hover:border-rose-800/50 transition-all duration-300 group">
          <div className="flex justify-between items-start">
            <p className="text-xs text-slate-400 font-semibold uppercase tracking-wider">Rejected Jobs</p>
            <XCircle className="w-4 h-4 text-rose-400 group-hover:text-rose-300 transition-colors" />
          </div>
          <h3 className="text-3xl font-extrabold text-rose-400 mt-2 tracking-tight">{analyticsData.rejected}</h3>
          <p className="text-[10px] text-slate-500 mt-1">Failed experience/auth constraints</p>
        </div>
        <div className="bg-slate-900/40 backdrop-blur-md border border-violet-950/60 p-5 rounded-2xl shadow-[0_4px_20px_rgba(0,0,0,0.3)] hover:-translate-y-0.5 hover:border-violet-800/50 transition-all duration-300 group">
          <div className="flex justify-between items-start">
            <p className="text-xs text-slate-400 font-semibold uppercase tracking-wider">Approval Rate</p>
            <BarChart3 className="w-4 h-4 text-violet-400 group-hover:text-violet-300 transition-colors" />
          </div>
          <h3 className="text-3xl font-extrabold text-violet-400 mt-2 tracking-tight">{analyticsData.approval_rate.toFixed(1)}%</h3>
          <p className="text-[10px] text-slate-500 mt-1">Sourcing qualification yield</p>
        </div>
      </div>

      {/* Charts Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">

        {/* Role Labels Distribution */}
        <div className="bg-slate-900/40 backdrop-blur-md border border-slate-800/80 p-6 rounded-3xl shadow-xl space-y-4">
          <div className="flex items-center justify-between border-b border-slate-800 pb-3">
            <div className="flex items-center space-x-2">
              <Briefcase className="w-5 h-5 text-violet-400" />
              <h3 className="text-sm font-bold text-white">Approved Job Labels Distribution</h3>
            </div>
            <span className="text-[10px] text-slate-400 font-mono bg-slate-850 px-2 py-0.5 rounded-md">By Title</span>
          </div>
          <div className="space-y-4 max-h-[300px] overflow-y-auto pr-2 custom-scrollbar">
            {Object.entries(analyticsData.labels_distribution).length === 0 ? (
              <p className="text-xs text-slate-500 text-center py-12">No approved jobs available for distribution.</p>
            ) : (
              Object.entries(analyticsData.labels_distribution)
                .sort((a, b) => b[1] - a[1])
                .map(([label, count]) => {
                  const pct = analyticsData.approved > 0 ? (count / analyticsData.approved * 100).toFixed(1) : 0;
                  return (
                    <div key={label} className="space-y-1.5 group">
                      <div className="flex justify-between text-xs font-semibold">
                        <span className="text-slate-300 group-hover:text-white transition-colors">{label}</span>
                        <span className="text-slate-400 font-mono">{count} jobs ({pct}%)</span>
                      </div>
                      <div className="h-2.5 w-full bg-slate-950 rounded-full overflow-hidden border border-slate-800/60 p-[1px]">
                        <div className="h-full bg-gradient-to-r from-violet-500 via-indigo-500 to-sky-400 rounded-full transition-all duration-1000" style={{ width: `${pct}%` }} />
                      </div>
                    </div>
                  );
                })
            )}
          </div>
        </div>

        {/* Scraper Sources Distribution */}
        <div className="bg-slate-900/40 backdrop-blur-md border border-slate-800/80 p-6 rounded-3xl shadow-xl space-y-4">
          <div className="flex items-center justify-between border-b border-slate-800 pb-3">
            <div className="flex items-center space-x-2">
              <Database className="w-5 h-5 text-indigo-400" />
              <h3 className="text-sm font-bold text-white">Scraper Sourcing Yield</h3>
            </div>
            <span className="text-[10px] text-slate-400 font-mono bg-slate-850 px-2 py-0.5 rounded-md">By Platform</span>
          </div>
          <div className="flex items-end justify-between h-56 pt-8 pb-3 px-6 gap-3 bg-slate-950/50 rounded-2xl border border-slate-800/50 relative overflow-hidden">
            <div className="absolute inset-0 flex flex-col justify-between pointer-events-none p-6 pb-12 opacity-10">
              <div className="border-b border-dashed border-slate-400 w-full" />
              <div className="border-b border-dashed border-slate-400 w-full" />
              <div className="border-b border-dashed border-slate-400 w-full" />
            </div>
            {Object.entries(analyticsData.sources_distribution).length === 0 ? (
              <p className="text-xs text-slate-500 text-center w-full py-20 z-10">No sourced listings available.</p>
            ) : (
              Object.entries(analyticsData.sources_distribution).map(([src, count]) => {
                const maxVal = Math.max(...(Object.values(analyticsData.sources_distribution) as number[]));
                const heightPct = maxVal > 0 ? (count / maxVal * 100) : 0;
                const pctOfTotal = analyticsData.total_sourced > 0 ? (count / analyticsData.total_sourced * 100).toFixed(1) : 0;
                return (
                  <div
                    key={src}
                    className="flex-1 flex flex-col items-center group relative h-full justify-end z-10 cursor-pointer"
                    onClick={() => onSourceClick(src)}
                  >
                    <div className="absolute bottom-full mb-2 opacity-0 group-hover:opacity-100 transition-opacity bg-slate-900 border border-slate-700 text-slate-100 text-[10px] font-bold py-1.5 px-2.5 rounded-lg shadow-xl pointer-events-none z-25 whitespace-nowrap flex flex-col items-center gap-0.5">
                      <span className="text-white">{src}</span>
                      <span className="text-violet-400 font-mono">{count} jobs ({pctOfTotal}%)</span>
                    </div>
                    <div
                      className={`w-full bg-gradient-to-t ${getSourceGradient(src)} rounded-t-md hover:brightness-110 shadow-lg shadow-black/20 group-hover:-translate-y-1 transition-all duration-500 ease-out`}
                      style={{ height: `${Math.max(heightPct, 6)}%` }}
                    />
                    <span className="text-[9px] text-slate-400 font-bold uppercase tracking-wider mt-2 truncate w-full text-center group-hover:text-white transition-colors">
                      {src.replace('We Work Remotely', 'WWR').split(' ')[0]}
                    </span>
                  </div>
                );
              })
            )}
          </div>
        </div>

        {/* Sourcing Channel Mix Table */}
        <div className="bg-slate-900/40 backdrop-blur-md border border-slate-800/80 p-6 rounded-3xl shadow-xl space-y-4 lg:col-span-2">
          <div className="flex items-center justify-between border-b border-slate-800 pb-3">
            <div className="flex items-center space-x-2">
              <BarChart3 className="w-5 h-5 text-emerald-400" />
              <h3 className="text-sm font-bold text-white">Sourcing Mix & Performance Details</h3>
            </div>
            <span className="text-[10px] text-slate-400 bg-slate-800/60 px-2.5 py-1 rounded-full font-semibold">Active Sourcing Channels</span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs text-slate-300">
              <thead>
                <tr className="border-b border-slate-850 text-[10px] uppercase tracking-wider text-slate-400 font-bold">
                  <th className="py-3 px-4">Sourcing Channel</th>
                  <th className="py-3 px-4 text-right">Job Count</th>
                  <th className="py-3 px-4 text-right">Percentage Mix</th>
                  <th className="py-3 px-4 text-center">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-850">
                {Object.entries(analyticsData.sources_distribution)
                  .sort((a, b) => b[1] - a[1])
                  .map(([src, count]) => {
                    const pct = analyticsData.total_sourced > 0 ? (count / analyticsData.total_sourced * 100).toFixed(1) : 0;
                    const dot = getSourceDotColor(src);
                    return (
                      <tr key={src} className="hover:bg-slate-800/10 transition-colors group cursor-pointer" onClick={() => onSourceClick(src)}>
                        <td className="py-3 px-4 flex items-center space-x-2 font-medium text-slate-300 group-hover:text-white transition-colors">
                          <span className={`w-2.5 h-2.5 rounded-full ${dot} shadow-sm shadow-black`} />
                          <span>{src}</span>
                        </td>
                        <td className="py-3 px-4 text-right font-semibold text-white font-mono">{count}</td>
                        <td className="py-3 px-4 text-right">
                          <div className="flex items-center justify-end space-x-3">
                            <span className="text-slate-300 font-medium font-mono">{pct}%</span>
                            <div className="w-16 h-1.5 bg-slate-950 rounded-full overflow-hidden border border-slate-800/40">
                              <div className={`h-full ${dot} rounded-full`} style={{ width: `${pct}%` }} />
                            </div>
                          </div>
                        </td>
                        <td className="py-3 px-4 text-center">
                          <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[9px] font-bold bg-emerald-950/40 text-emerald-400 border border-emerald-900/30">
                            Operational
                          </span>
                        </td>
                      </tr>
                    );
                  })}
              </tbody>
            </table>
          </div>
        </div>

        {/* Rejection Reasons */}
        <div className="bg-slate-900/40 backdrop-blur-md border border-slate-800/80 p-6 rounded-3xl shadow-xl space-y-4 lg:col-span-2">
          <div className="flex items-center space-x-2 border-b border-slate-800 pb-3">
            <AlertTriangle className="w-5 h-5 text-rose-400" />
            <h3 className="text-sm font-bold text-white">Rejection Policy Failures Breakdown</h3>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {Object.entries(analyticsData.rejection_reasons)
              .filter(([, count]) => count > 0)
              .sort((a, b) => b[1] - a[1])
              .map(([reason, count]) => {
                const maxVal = Math.max(...(Object.values(analyticsData.rejection_reasons) as number[]));
                const pct = maxVal > 0 ? (count / maxVal * 100).toFixed(1) : 0;
                return (
                  <div key={reason} className="bg-slate-950/40 border border-slate-850 p-4 rounded-2xl space-y-2.5 hover:border-slate-800 transition-colors">
                    <div className="flex justify-between text-xs font-semibold">
                      <span className="text-slate-300 truncate max-w-[200px]" title={reason}>{reason}</span>
                      <span className="text-rose-400 font-bold font-mono">{count} flags ({pct}%)</span>
                    </div>
                    <div className="h-2 w-full bg-slate-950 rounded-full overflow-hidden border border-slate-900">
                      <div className="h-full bg-gradient-to-r from-rose-600 to-pink-500 rounded-full" style={{ width: `${pct}%` }} />
                    </div>
                  </div>
                );
              })}
            {Object.values(analyticsData.rejection_reasons).every(v => v === 0) && (
              <p className="text-xs text-slate-500 text-center py-12 w-full col-span-2">No rejected jobs logged yet.</p>
            )}
          </div>
        </div>

        {/* Salary Insights */}
        <div className="bg-slate-900/40 backdrop-blur-md border border-slate-800/80 p-6 rounded-3xl shadow-xl space-y-6 lg:col-span-2">
          <div className="flex items-center justify-between border-b border-slate-800 pb-3">
            <div className="flex items-center space-x-2">
              <Database className="w-5 h-5 text-indigo-400" />
              <h3 className="text-sm font-bold text-white">Sourced Salary & Compensation Metrics</h3>
            </div>
            <span className="text-[10px] text-slate-400 bg-slate-800/60 px-2.5 py-1 rounded-full font-semibold">Salary Analytics</span>
          </div>
          {salaryInsightsLoading || !salaryInsights ? (
            <div className="flex flex-col items-center justify-center py-12 text-center text-slate-500">
              <RefreshCw className="w-8 h-8 text-violet-500 animate-spin mb-3" />
              <p className="text-xs font-semibold">Computing market salary trends...</p>
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6 animate-in fade-in duration-300">
              <div className="space-y-4">
                <h4 className="text-xs font-bold text-slate-400 uppercase tracking-wider">Compensation Summary</h4>
                <div className="grid grid-cols-2 gap-4">
                  <div className="bg-slate-950/60 border border-slate-850 p-4 rounded-2xl flex flex-col justify-between">
                    <span className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider">Average Annual Base</span>
                    <span className="text-xl font-extrabold text-white mt-1.5 font-mono">
                      {salaryInsights.yearly_avg > 0 ? `$${(salaryInsights.yearly_avg / 1000).toFixed(0)}k` : '$0'}
                    </span>
                    <span className="text-[9px] text-slate-500 mt-1">Based on {salaryInsights.yearly_count} salaried positions</span>
                  </div>
                  <div className="bg-slate-950/60 border border-slate-850 p-4 rounded-2xl flex flex-col justify-between">
                    <span className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider">Salaried Range</span>
                    <span className="text-sm font-bold text-emerald-400 mt-2 font-mono truncate">
                      {salaryInsights.yearly_min > 0 ? `$${(salaryInsights.yearly_min / 1000).toFixed(0)}k - $${(salaryInsights.yearly_max / 1000).toFixed(0)}k` : 'N/A'}
                    </span>
                    <span className="text-[9px] text-slate-500 mt-1">Min/Max limits found</span>
                  </div>
                  <div className="bg-slate-950/60 border border-slate-850 p-4 rounded-2xl flex flex-col justify-between">
                    <span className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider">Average Hourly Rate</span>
                    <span className="text-xl font-extrabold text-white mt-1.5 font-mono">
                      {salaryInsights.hourly_avg > 0 ? `$${salaryInsights.hourly_avg.toFixed(2)}/hr` : '$0'}
                    </span>
                    <span className="text-[9px] text-slate-500 mt-1">Based on {salaryInsights.hourly_count} hourly positions</span>
                  </div>
                  <div className="bg-slate-950/60 border border-slate-850 p-4 rounded-2xl flex flex-col justify-between">
                    <span className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider">Hourly Range</span>
                    <span className="text-sm font-bold text-emerald-400 mt-2 font-mono truncate">
                      {salaryInsights.hourly_min > 0 ? `$${salaryInsights.hourly_min.toFixed(0)} - $${salaryInsights.hourly_max.toFixed(0)}/hr` : 'N/A'}
                    </span>
                    <span className="text-[9px] text-slate-500 mt-1">Min/Max hourly limits</span>
                  </div>
                </div>
              </div>
              <div className="space-y-4 bg-slate-950/40 border border-slate-850 p-5 rounded-2xl">
                <h4 className="text-xs font-bold text-slate-400 uppercase tracking-wider">Sourcing Intelligence</h4>
                <div className="space-y-3.5 text-xs">
                  <div className="flex justify-between items-center py-2 border-b border-slate-900/60">
                    <span className="text-slate-400">Total Postings Checked</span>
                    <span className="font-bold text-white font-mono">{approvedJobs.length}</span>
                  </div>
                  <div className="flex justify-between items-center py-2 border-b border-slate-900/60">
                    <span className="text-slate-400">Postings with Salary Info</span>
                    <span className="font-bold text-violet-400 font-mono">
                      {salaryInsights.yearly_count + salaryInsights.hourly_count} ({approvedJobs.length > 0 ? (((salaryInsights.yearly_count + salaryInsights.hourly_count) / approvedJobs.length) * 100).toFixed(0) : 0}%)
                    </span>
                  </div>
                  <p className="text-[10px] text-slate-500 leading-relaxed pt-2">
                    Market intelligence extracts salary bands directly from the scraped text descriptions using customized regular expressions. Rates below $500/hr are categorized as hourly wages, while larger rates are calculated as annual salaries.
                  </p>
                </div>
              </div>
            </div>
          )}
        </div>

      </div>

      {/* Classifier QA */}
      <div className="bg-slate-900/30 backdrop-blur-md border border-slate-800/80 rounded-2xl p-6 shadow-xl">
        <div className="flex items-center justify-between mb-5">
          <div className="flex items-center space-x-2">
            <Shield className="w-4 h-4 text-violet-400" />
            <h3 className="text-sm font-bold text-white">Classifier QA</h3>
          </div>
          <span className="text-[10px] text-slate-400 bg-slate-800/60 px-2.5 py-1 rounded-full font-semibold">
            Precision &amp; Drift Review
          </span>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <div className="space-y-3">
            <h4 className="text-xs font-bold text-slate-400 uppercase tracking-wider">Approved Confidence Distribution</h4>
            {([
              { label: 'Very Strong (90-100)', count: bands.veryStrong, color: 'bg-emerald-500' },
              { label: 'Strong (70-89)', count: bands.strong, color: 'bg-amber-500' },
              { label: 'Borderline (50-69)', count: bands.borderline, color: 'bg-orange-500' },
              { label: 'Review Needed (<50)', count: bands.reviewNeeded, color: 'bg-rose-500' },
            ] as const).map(b => (
              <div key={b.label} className="space-y-1">
                <div className="flex justify-between text-[11px] text-slate-400">
                  <span>{b.label}</span>
                  <span className="font-mono font-bold text-slate-200">{b.count} ({((b.count / totalConf) * 100).toFixed(0)}%)</span>
                </div>
                <div className="w-full bg-slate-950/60 rounded-full h-1.5 overflow-hidden">
                  <div className={`h-full rounded-full ${b.color}`} style={{ width: `${(b.count / totalConf) * 100}%` }} />
                </div>
              </div>
            ))}
            {(bands.borderline + bands.reviewNeeded) > 0 && (
              <p className="text-[10px] text-amber-400/80 pt-1">
                {bands.borderline + bands.reviewNeeded} approved job(s) scored below 70% confidence — worth a manual spot-check via Inspect &amp; Edit.
              </p>
            )}
          </div>
          <div className="space-y-2 bg-slate-950/40 border border-slate-850 p-4 rounded-2xl">
            <h4 className="text-xs font-bold text-slate-400 uppercase tracking-wider">Recently Rejected (OutOfScope)</h4>
            <p className="text-[10px] text-slate-500 mb-2">Sample for reviewing policy drift — are these correctly excluded?</p>
            <div className="space-y-1.5 max-h-64 overflow-y-auto">
              {recentOutOfScope.length === 0 ? (
                <p className="text-[11px] text-slate-600 italic">No OutOfScope rejections found.</p>
              ) : recentOutOfScope.map((j, i) => (
                <div key={j.job_url + i} className="flex items-center justify-between text-[11px] py-1.5 border-b border-slate-900/60 last:border-0">
                  <span className="text-slate-300 truncate pr-2">{j.job_title} <span className="text-slate-500">@ {j.company_name}</span></span>
                  <span className="text-rose-400/80 shrink-0 text-[10px] uppercase font-semibold">{(j.red_flags && j.red_flags[0]) || 'OutOfScope'}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

    </div>
  );
}
