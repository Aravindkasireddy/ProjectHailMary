'use client';

import React, { useState } from 'react';
import { FileText, RefreshCw, Copy, Download, X } from 'lucide-react';

export interface ResumeGeneratorProps {
  jd: string;
  jobTitle: string;
  companyName: string;
  compact?: boolean;
}

interface ResumeStats {
  words: number;
  bullets: number;
  tokens_used: number;
  long_bullets: { bullet: string; words: number }[];
  warnings: string[];
  signals_detected: {
    primary_platform: string | null;
    dominant_cloud: string;
    cicd_tools: string[];
    monitoring_tools: string[];
    compliance: string[];
  };
}

export default function ResumeGenerator({ jd, jobTitle, companyName, compact = false }: ResumeGeneratorProps) {
  const [loading, setLoading] = useState<boolean>(false);
  const [resume, setResume] = useState<string | null>(null);
  const [stats, setStats] = useState<ResumeStats | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState<boolean>(false);
  const [isOpen, setIsOpen] = useState<boolean>(false);

  const API_BASE = 'http://100.124.212.55:8080';

  const handleGenerate = async () => {
    setLoading(true);
    setError(null);
    setResume(null);
    setStats(null);
    try {
      const res = await fetch(`${API_BASE}/api/resume/generate`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ jd }),
      });

      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.error || 'Failed to generate resume.');
      }

      setResume(data.resume);
      setStats(data.stats);
      setIsOpen(true);
    } catch (err: unknown) {
      const errMsg = err instanceof Error ? err.message : 'An unexpected error occurred.';
      setError(errMsg);
    } finally {
      setLoading(false);
    }
  };

  const handleCopy = () => {
    if (!resume) return;
    navigator.clipboard.writeText(resume);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleDownload = () => {
    if (!resume) return;
    const blob = new Blob([resume], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    
    const formattedCompany = companyName.replace(/\s+/g, '_');
    const formattedTitle = jobTitle.replace(/\s+/g, '_');
    link.download = `ARK_Resume_${formattedCompany}_${formattedTitle}.txt`;
    
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  };

  return (
    <div className="inline-block">
      <button
        type="button"
        onClick={handleGenerate}
        disabled={loading}
        title="Generate ATS Resume (V5)"
        className={
          compact
            ? "p-1.5 bg-violet-950/40 hover:bg-violet-900/60 text-violet-400 hover:text-violet-300 border border-violet-800/40 rounded-xl transition-all disabled:opacity-50"
            : "bg-white/10 border border-white/20 text-white hover:bg-white/20 disabled:opacity-50 disabled:cursor-not-allowed transition-all flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-semibold backdrop-blur-md shadow-lg"
        }
      >
        {loading ? (
          <>
            <RefreshCw className="w-3.5 h-3.5 animate-spin text-violet-400" />
            {!compact && <span>GPT-4o generating...</span>}
          </>
        ) : (
          <>
            <FileText className={compact ? "w-4 h-4" : "w-3.5 h-3.5 text-emerald-400"} />
            {!compact && <span>Generate ATS Resume (V5)</span>}
          </>
        )}
      </button>

      {error && (
        <p className="mt-2 text-xs text-rose-400 font-medium">{error}</p>
      )}

      {/* Dark Glassmorphic Modal */}
      {isOpen && resume && (
        <div className="fixed inset-0 bg-black/70 backdrop-blur-sm z-50 flex items-center justify-center p-4 overflow-y-auto">
          <div className="bg-slate-900/90 border border-slate-800/80 w-full max-w-4xl rounded-3xl shadow-2xl flex flex-col max-h-[90vh] overflow-hidden backdrop-blur-lg animate-in fade-in zoom-in-95 duration-200">
            
            {/* Modal Header */}
            <div className="px-6 py-4 border-b border-slate-800/60 flex items-center justify-between bg-slate-950/40">
              <div className="flex items-center space-x-2">
                <FileText className="w-5 h-5 text-emerald-400" />
                <div>
                  <h3 className="text-base font-bold text-white">
                    ARK Resume — {jobTitle} @ {companyName}
                  </h3>
                  <p className="text-[11px] text-slate-400">Tailored using GPT-4o ATS V5 Prompt Engine</p>
                </div>
              </div>
              <button
                type="button"
                onClick={() => setIsOpen(false)}
                className="p-1 text-slate-400 hover:text-white bg-slate-800 hover:bg-slate-700/80 rounded-lg transition-colors text-xs font-bold px-2 flex items-center justify-center"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            {/* Modal Body */}
            <div className="p-6 overflow-y-auto space-y-4 flex-1 bg-slate-900/50">
              
              {/* Stats Row */}
              {stats && (
                <div className="flex flex-wrap gap-3">
                  <div className="bg-slate-950/60 border border-slate-850 px-3.5 py-1.5 rounded-xl flex items-center space-x-2 shadow-inner">
                    <span className="text-[10px] font-bold text-slate-500 uppercase tracking-wider">Words:</span>
                    <span className="text-xs font-bold text-violet-400">{stats.words}</span>
                  </div>
                  <div className="bg-slate-950/60 border border-slate-850 px-3.5 py-1.5 rounded-xl flex items-center space-x-2 shadow-inner">
                    <span className="text-[10px] font-bold text-slate-500 uppercase tracking-wider">Bullets:</span>
                    <span className="text-xs font-bold text-emerald-400">{stats.bullets}</span>
                  </div>
                  <div className="bg-slate-950/60 border border-slate-850 px-3.5 py-1.5 rounded-xl flex items-center space-x-2 shadow-inner">
                    <span className="text-[10px] font-bold text-slate-500 uppercase tracking-wider">Tokens:</span>
                    <span className="text-xs font-bold text-blue-400">{stats.tokens_used}</span>
                  </div>
                </div>
              )}

              {stats?.signals_detected && (
                <div style={{ marginBottom: '12px' }}>
                  <p style={{ fontSize: '11px', color: '#6b7280', textTransform: 'uppercase', 
                              letterSpacing: '0.06em', marginBottom: '8px' }}>
                    JD signals detected
                  </p>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
                    {stats.signals_detected.primary_platform && (
                      <span style={{ fontSize: '11px', padding: '3px 8px', borderRadius: '20px',
                                     background: 'rgba(16,185,129,0.15)', color: '#10b981',
                                     fontFamily: 'monospace' }}>
                        platform: {stats.signals_detected.primary_platform}
                      </span>
                    )}
                    {stats.signals_detected.dominant_cloud && (
                      <span style={{ fontSize: '11px', padding: '3px 8px', borderRadius: '20px',
                                     background: 'rgba(59,130,246,0.15)', color: '#60a5fa',
                                     fontFamily: 'monospace' }}>
                        cloud: {stats.signals_detected.dominant_cloud}
                      </span>
                    )}
                    {stats.signals_detected.cicd_tools?.map((t: string) => (
                      <span key={t} style={{ fontSize: '11px', padding: '3px 8px', borderRadius: '20px',
                                             background: 'rgba(139,92,246,0.15)', color: '#a78bfa',
                                             fontFamily: 'monospace' }}>
                        {t}
                      </span>
                    ))}
                    {stats.signals_detected.monitoring_tools?.map((t: string) => (
                      <span key={t} style={{ fontSize: '11px', padding: '3px 8px', borderRadius: '20px',
                                             background: 'rgba(245,158,11,0.15)', color: '#fbbf24',
                                             fontFamily: 'monospace' }}>
                        {t}
                      </span>
                    ))}
                  </div>

                  {stats.warnings?.length > 0 && (
                    <div style={{ marginTop: '8px', padding: '8px 12px', background: 'rgba(239,68,68,0.1)',
                                  borderRadius: '8px', border: '1px solid rgba(239,68,68,0.2)' }}>
                      {stats.warnings.map((w: string, i: number) => (
                        <p key={i} style={{ fontSize: '12px', color: '#f87171', margin: 0 }}>{w}</p>
                      ))}
                    </div>
                  )}

                  {stats.long_bullets?.length > 0 && (
                    <div style={{ marginTop: '8px', padding: '8px 12px', background: 'rgba(245,158,11,0.1)',
                                  borderRadius: '8px', border: '1px solid rgba(245,158,11,0.2)' }}>
                      <p style={{ fontSize: '12px', color: '#fbbf24', margin: '0 0 4px 0', fontWeight: 500 }}>
                        {stats.long_bullets.length} bullet(s) over 24 words — Workday will truncate these
                      </p>
                      {stats.long_bullets.map((b: { bullet: string; words: number }, i: number) => (
                        <p key={i} style={{ fontSize: '11px', color: '#f59e0b', margin: '2px 0',
                                            fontFamily: 'monospace' }}>
                          [{b.words}w] {b.bullet}...
                        </p>
                      ))}
                    </div>
                  )}
                </div>
              )}

              {/* Textarea for Plain Text Resume */}
              <div className="flex flex-col space-y-1">
                <label className="text-[10px] font-bold uppercase text-slate-400 tracking-wider">ATS Plain Text Resume Content</label>
                <textarea
                  readOnly
                  value={resume}
                  className="w-full min-h-[420px] bg-black/40 border border-slate-800/80 rounded-2xl p-4 text-xs font-mono text-slate-200 select-text focus:outline-none resize-none leading-relaxed shadow-inner"
                />
              </div>
            </div>

            {/* Modal Footer */}
            <div className="px-6 py-4 border-t border-slate-800/60 flex items-center justify-end gap-3 bg-slate-950/40">
              <button
                type="button"
                onClick={handleCopy}
                className={`inline-flex items-center px-4 py-2 rounded-xl text-xs font-semibold shadow-md active:scale-95 transition-all border ${
                  copied
                    ? 'bg-emerald-600/20 border-emerald-500/35 text-emerald-400'
                    : 'bg-slate-850 hover:bg-slate-800 text-slate-300 hover:text-white border-slate-800'
                }`}
              >
                <Copy className="w-3.5 h-3.5 mr-1.5" />
                {copied ? 'Copied ✓' : 'Copy Resume'}
              </button>
              <button
                type="button"
                onClick={handleDownload}
                className="inline-flex items-center px-4 py-2 bg-gradient-to-r from-violet-600 to-indigo-600 hover:from-violet-500 hover:to-indigo-500 text-white border border-violet-500/20 rounded-xl text-xs font-semibold shadow-md active:scale-95 transition-all"
              >
                <Download className="w-3.5 h-3.5 mr-1.5" />
                Download .txt
              </button>
              <button
                type="button"
                onClick={() => setIsOpen(false)}
                className="px-4 py-2 bg-slate-800 hover:bg-slate-750 text-slate-300 hover:text-white rounded-xl text-xs font-semibold border border-slate-700/60 transition-all"
              >
                Close
              </button>
            </div>

          </div>
        </div>
      )}
    </div>
  );
}
