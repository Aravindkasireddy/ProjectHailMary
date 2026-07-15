'use client';

import {
  BarChart3,
  ChevronRight,
  FileText,
  Settings as SettingsIcon,
  Shield,
  Sliders,
} from 'lucide-react';
import { TabId, Job } from './types';
import { ScrapedTimeframe } from './constants';

interface HomeJobsToolbarProps {
  activeTab: TabId;
  authRole: 'admin' | 'user' | null;

  // tab counts
  approvedJobs: Job[];
  newTodayJobs: Job[];
  applicationJobs: Job[];
  humanReviewJobs: Job[];
  rejectedJobs: Job[];
  newJobsCount: number;

  // filter state
  searchTerm: string;
  selectedRoleFilter: string;
  sortBy: 'newest' | 'oldest';
  scrapedTimeframe: ScrapedTimeframe;
  showActiveOnly: boolean;
  remoteOnlyFilter: boolean;
  confidenceBandFilter: 'all' | 'high' | 'borderline';
  activeFilterPreset: string | null;

  // callbacks
  onTabChange: (tab: TabId) => void;
  onSearchChange: (v: string) => void;
  onRoleFilterChange: (v: string) => void;
  onSortChange: (v: 'newest' | 'oldest') => void;
  onTimeframeChange: (v: ScrapedTimeframe) => void;
  onShowActiveOnlyToggle: () => void;
  onRemoteOnlyChange: (v: boolean) => void;
  onConfidenceBandChange: (v: 'all' | 'high' | 'borderline') => void;
  onPresetToggle: (key: string) => void;
}

const TAB_PRESETS = [
  {
    key: 'high_fit' as const,
    label: 'High-fit',
    set: (cb: HomeJobsToolbarProps) => {
      cb.onConfidenceBandChange('high');
      cb.onRemoteOnlyChange(false);
      cb.onTimeframeChange('all');
    },
  },
  {
    key: 'fresh' as const,
    label: 'Fresh jobs',
    set: (cb: HomeJobsToolbarProps) => {
      cb.onTimeframeChange('today');
      cb.onConfidenceBandChange('all');
      cb.onRemoteOnlyChange(false);
    },
  },
  {
    key: 'remote' as const,
    label: 'Remote-first',
    set: (cb: HomeJobsToolbarProps) => {
      cb.onRemoteOnlyChange(true);
      cb.onConfidenceBandChange('all');
      cb.onTimeframeChange('all');
    },
  },
  {
    key: 'needs_review' as const,
    label: 'Needs review',
    set: (cb: HomeJobsToolbarProps) => {
      cb.onConfidenceBandChange('borderline');
      cb.onRemoteOnlyChange(false);
      cb.onTimeframeChange('all');
    },
  },
];

export default function HomeJobsToolbar(props: HomeJobsToolbarProps) {
  const {
    activeTab, authRole,
    approvedJobs, newTodayJobs, applicationJobs, humanReviewJobs, rejectedJobs, newJobsCount,
    searchTerm, selectedRoleFilter, sortBy, scrapedTimeframe, showActiveOnly,
    activeFilterPreset,
    onTabChange, onSearchChange, onRoleFilterChange, onSortChange,
    onTimeframeChange, onShowActiveOnlyToggle, onPresetToggle,
    onRemoteOnlyChange, onConfidenceBandChange,
  } = props;

  const tabCls = (id: TabId, gradient = 'from-violet-600 to-indigo-600') =>
    `flex items-center px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${
      activeTab === id
        ? `bg-gradient-to-r ${gradient} text-white shadow-md`
        : 'text-slate-400 hover:text-slate-200'
    }`;

  return (
    <section className="flex flex-col bg-slate-900/30 backdrop-blur-md border border-slate-800/80 p-4 rounded-2xl gap-4 shadow-xl">

      {/* Navigation Tabs row */}
      <div className="flex flex-col lg:flex-row items-stretch lg:items-center justify-between gap-4">
        <div className="flex bg-slate-950 p-1.5 rounded-xl border border-slate-800/50 flex-wrap gap-1">

          <button onClick={() => onTabChange('approved')} className={tabCls('approved')}>
            All Jobs ({approvedJobs.length})
          </button>

          <button onClick={() => onTabChange('new_today')} className={tabCls('new_today', 'from-emerald-600 to-teal-600')}>
            🆕 New Today ({newTodayJobs.length})
            {newJobsCount > 0 && (
              <span
                className="ml-1 inline-flex items-center justify-center px-1.5 py-0.5 text-[9px] font-extrabold leading-none rounded-full animate-pulse"
                style={{ background: 'var(--cyan)', color: 'var(--void)', minWidth: '16px' }}
              >
                +{newJobsCount}
              </span>
            )}
          </button>

          <button onClick={() => onTabChange('applications')} className={tabCls('applications', 'from-blue-600 to-cyan-600')}>
            📋 My Applications ({applicationJobs.length})
          </button>

          <button onClick={() => onTabChange('human_review')} className={tabCls('human_review')}>
            Human review ({humanReviewJobs.length})
          </button>

          <button onClick={() => onTabChange('rejected')} className={tabCls('rejected')}>
            Rejected ({rejectedJobs.length})
          </button>

          <button onClick={() => onTabChange('analytics')} className={tabCls('analytics')}>
            <BarChart3 className="w-3.5 h-3.5 mr-1" />
            Analytics
          </button>

          {authRole === 'admin' && (
            <>
              <button onClick={() => onTabChange('policy')} className={tabCls('policy')}>
                <Shield className="w-3.5 h-3.5 mr-1" />
                Classifier Policy
              </button>
              <button onClick={() => onTabChange('resume')} className={tabCls('resume')}>
                <FileText className="w-3.5 h-3.5 mr-1" />
                Base Resume
              </button>
              <button onClick={() => onTabChange('settings')} className={tabCls('settings')}>
                <SettingsIcon className="w-3.5 h-3.5 mr-1" />
                Settings
              </button>
            </>
          )}
        </div>
      </div>

      {/* Quick filter presets — approved tab only */}
      {activeTab === 'approved' && (
        <div className="flex items-center gap-2 flex-wrap border-t border-slate-800/40 pt-3">
          <span className="text-[10px] font-bold text-slate-500 uppercase tracking-wider shrink-0">Quick filters:</span>
          {TAB_PRESETS.map(preset => (
            <button
              key={preset.key}
              type="button"
              onClick={() => {
                if (activeFilterPreset === preset.key) {
                  onPresetToggle('');
                  onConfidenceBandChange('all');
                  onRemoteOnlyChange(false);
                  onTimeframeChange('all');
                } else {
                  onPresetToggle(preset.key);
                  preset.set(props);
                }
              }}
              className={`px-3 py-1 rounded-lg text-[11px] font-semibold border transition-colors ${
                activeFilterPreset === preset.key
                  ? 'bg-violet-600/90 text-white border-violet-500'
                  : 'bg-slate-900/60 text-slate-300 border-slate-700 hover:border-violet-600/50 hover:text-violet-300'
              }`}
            >
              {preset.label}
            </button>
          ))}
        </div>
      )}

      {/* Filter row — hidden on settings tab */}
      {activeTab !== 'settings' && (
        <div className="flex flex-col lg:flex-row items-stretch lg:items-center gap-3 w-full justify-between border-t border-slate-800/40 pt-3 flex-wrap">

          {/* Search box */}
          <div className="relative flex-1 min-w-[200px]">
            <input
              type="text"
              value={searchTerm}
              onChange={e => onSearchChange(e.target.value)}
              placeholder="Search jobs, companies…"
              className="w-full bg-slate-950/80 border border-slate-800 rounded-xl pl-4 pr-4 py-2 text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:border-violet-600/70 transition-colors shadow-inner"
            />
          </div>

          {/* Role filter — approved tab only */}
          {activeTab === 'approved' && (
            <div className="relative shrink-0">
              <span className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
                <Sliders className="w-4 h-4 text-violet-400" />
              </span>
              <select
                value={selectedRoleFilter}
                onChange={e => onRoleFilterChange(e.target.value)}
                className="bg-slate-950/80 border border-slate-800 rounded-xl pl-9 pr-10 py-2 text-sm text-slate-200 focus:outline-none focus:border-violet-600/70 transition-colors shadow-inner appearance-none cursor-pointer w-full sm:w-auto min-w-[180px]"
              >
                <option value="all">All Roles</option>
                {Array.from(new Set(approvedJobs.map(j => j.strongest_label).filter(Boolean))).map(role => (
                  <option key={role} value={role}>{role}</option>
                ))}
              </select>
              <span className="absolute inset-y-0 right-0 pr-3 flex items-center pointer-events-none text-slate-500">
                <ChevronRight className="w-4 h-4 rotate-90" />
              </span>
            </div>
          )}

          {/* Sort */}
          <div className="relative shrink-0">
            <span className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
              <Sliders className="w-4 h-4 text-violet-400" />
            </span>
            <select
              value={sortBy}
              onChange={e => onSortChange(e.target.value as 'newest' | 'oldest')}
              className="bg-slate-950/80 border border-slate-800 rounded-xl pl-9 pr-10 py-2 text-sm text-slate-200 focus:outline-none focus:border-violet-600/70 transition-colors shadow-inner appearance-none cursor-pointer w-full sm:w-auto min-w-[150px]"
            >
              <option value="newest">Newest Scrape</option>
              <option value="oldest">Oldest Scrape</option>
            </select>
            <span className="absolute inset-y-0 right-0 pr-3 flex items-center pointer-events-none text-slate-500">
              <ChevronRight className="w-4 h-4 rotate-90" />
            </span>
          </div>

          {/* Active only toggle — approved tab only */}
          {activeTab === 'approved' && (
            <button
              type="button"
              onClick={onShowActiveOnlyToggle}
              className={`inline-flex items-center px-4 py-2 border rounded-xl text-sm font-semibold transition-colors shrink-0 shadow-inner ${
                showActiveOnly
                  ? 'bg-violet-950/40 border-violet-800 text-violet-300'
                  : 'bg-slate-950/80 border-slate-800 text-slate-400 hover:text-slate-200'
              }`}
            >
              <Sliders className="w-4 h-4 mr-2 text-violet-400" />
              {showActiveOnly ? 'Active Only' : 'Include Closed'}
            </button>
          )}

          {/* Timeframe */}
          <div className="relative shrink-0">
            <span className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
              <Sliders className="w-4 h-4 text-violet-400" />
            </span>
            <select
              value={scrapedTimeframe}
              onChange={e => onTimeframeChange(e.target.value as ScrapedTimeframe)}
              className="bg-slate-950/80 border border-slate-800 rounded-xl pl-9 pr-10 py-2 text-sm text-slate-200 focus:outline-none focus:border-violet-600/70 transition-colors shadow-inner appearance-none cursor-pointer w-full sm:w-auto min-w-[170px]"
            >
              <option value="all">All Times</option>
              <option value="recent">Sourced: Last 4 Hours</option>
              <option value="today">Sourced: Last 24 Hours</option>
              <option value="posted_today">Posted: Last 24 Hours</option>
              <option value="week">Sourced: Last 7 Days</option>
              <option value="posted_week">Posted: Last 7 Days</option>
              <option value="month">Sourced: Last 30 Days</option>
            </select>
            <span className="absolute inset-y-0 right-0 pr-3 flex items-center pointer-events-none text-slate-500">
              <ChevronRight className="w-4 h-4 rotate-90" />
            </span>
          </div>

        </div>
      )}
    </section>
  );
}
