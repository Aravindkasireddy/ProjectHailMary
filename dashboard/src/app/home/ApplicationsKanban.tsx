'use client';

import { Job } from './types';

interface ApplicationsKanbanProps {
  applicationJobs: Job[];
  onUpdateStatus: (jobUrl: string, status: string | null) => void;
}

const STATUSES = ['applied', 'phone_screen', 'interview', 'offer', 'rejected'] as const;
type AppStatus = (typeof STATUSES)[number];

const LABELS: Record<AppStatus, string> = {
  applied: '📨 Applied',
  phone_screen: '📞 Phone Screen',
  interview: '🎯 Interview',
  offer: '🎉 Offer',
  rejected: '❌ Rejected',
};

const COLORS: Record<AppStatus, string> = {
  applied: 'border-blue-500',
  phone_screen: 'border-yellow-500',
  interview: 'border-purple-500',
  offer: 'border-green-500',
  rejected: 'border-red-500',
};

export default function ApplicationsKanban({ applicationJobs, onUpdateStatus }: ApplicationsKanbanProps) {
  if (applicationJobs.length === 0) {
    return (
      <div className="text-slate-400 text-sm text-center py-16">
        No applications tracked yet.<br />
        Click &quot;Track Application&quot; on any job to start tracking.
      </div>
    );
  }

  return (
    <div className="grid grid-cols-1 md:grid-cols-5 gap-4">
      {STATUSES.map(status => {
        const cols = applicationJobs.filter(j => j.application_status === status);
        return (
          <div key={status} className={`border-t-2 ${COLORS[status]} bg-slate-800/50 rounded-lg p-3`}>
            <div className="text-xs font-bold text-slate-300 mb-2">
              {LABELS[status]} <span className="text-slate-500">({cols.length})</span>
            </div>
            <div className="space-y-2">
              {cols.map(job => (
                <div key={job.job_url} className="bg-slate-700/70 rounded p-2 text-xs">
                  <div className="font-semibold text-white truncate">{job.job_title}</div>
                  <div className="text-slate-400 truncate">{job.company_name}</div>
                  {job.applied_at && (
                    <div className="text-slate-500 mt-1">
                      {new Date(job.applied_at).toLocaleDateString()}
                    </div>
                  )}
                  <div className="flex flex-wrap gap-1 mt-2">
                    {STATUSES.filter(s => s !== status).map(s => (
                      <button
                        key={s}
                        onClick={() => onUpdateStatus(job.job_url, s)}
                        className="px-1.5 py-0.5 rounded bg-slate-600 hover:bg-slate-500 text-slate-300 text-[10px] transition-colors"
                      >
                        → {LABELS[s].split(' ')[1]}
                      </button>
                    ))}
                    <button
                      onClick={() => onUpdateStatus(job.job_url, null)}
                      className="px-1.5 py-0.5 rounded bg-slate-600 hover:bg-red-700 text-slate-400 text-[10px] transition-colors"
                    >
                      ✕ Remove
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}
