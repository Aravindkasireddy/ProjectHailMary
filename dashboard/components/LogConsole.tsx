'use client';

import { Database } from 'lucide-react';

interface LogConsoleProps {
  isLogsExpanded: boolean;
  setIsLogsExpanded: (val: boolean | ((prev: boolean) => boolean)) => void;
  scraperStatus: {
    status: string;
    message: string;
  };
  scraperLogs: string[];
}

export default function LogConsole({
  isLogsExpanded,
  setIsLogsExpanded,
  scraperStatus,
  scraperLogs,
}: LogConsoleProps) {
  return (
    <section className="bg-slate-900/40 backdrop-blur-md border border-slate-800/80 rounded-2xl shadow-xl overflow-hidden mt-6">
      <button
        type="button"
        onClick={() => setIsLogsExpanded((prev) => !prev)}
        className="w-full flex items-center justify-between px-5 py-4 hover:bg-slate-800/25 transition-colors"
      >
        <div className="flex items-center space-x-2.5">
          <Database className="w-5 h-5 text-indigo-400 animate-pulse" />
          <div className="text-left">
            <h3 className="text-sm font-bold text-white">Live Pipeline Logs Console</h3>
            <p className="text-[10px] text-slate-400">
              {scraperStatus.status === 'running'
                ? 'Scraper active - streaming logs'
                : 'Pipeline idle - click to view recent logs'}
            </p>
          </div>
        </div>
        <div className="flex items-center space-x-3">
          {scraperStatus.status === 'running' && (
            <span className="flex h-2 w-2 relative">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-amber-400 opacity-75"></span>
              <span className="relative inline-flex rounded-full h-2 w-2 bg-amber-500"></span>
            </span>
          )}
          <span className="text-xs text-indigo-400 hover:text-indigo-300 font-semibold">
            {isLogsExpanded ? 'Hide Console' : 'Show Console'}
          </span>
        </div>
      </button>

      {isLogsExpanded && (
        <div className="border-t border-slate-800 p-4 bg-slate-950/85">
          <div className="flex items-center justify-between mb-3 text-xs text-slate-400 font-mono">
            <span>logs/scrape.log · Last 100 lines</span>
            <span className="flex items-center gap-1.5">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
              Auto-refreshing (3s)
            </span>
          </div>
          <div className="h-64 overflow-y-auto bg-slate-950 font-mono text-xs text-slate-300 p-4 rounded-xl border border-slate-850/80 custom-scrollbar">
            <pre className="whitespace-pre-wrap leading-relaxed text-left">
              {scraperLogs.length > 0
                ? scraperLogs.join('')
                : 'No logs fetched yet or pipeline log is empty.'}
            </pre>
          </div>
        </div>
      )}
    </section>
  );
}
