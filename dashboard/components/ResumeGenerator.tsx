'use client';

import React, { useState } from 'react';
import { FileText, RefreshCw, Copy, Download, X } from 'lucide-react';

export interface ResumeGeneratorProps {
  jd: string;
  jobTitle: string;
  companyName: string;
}

export default function ResumeGenerator({ jd, jobTitle, companyName }: ResumeGeneratorProps) {
  const [loading, setLoading] = useState<boolean>(false);
  const [resume, setResume] = useState<string | null>(null);
  const [stats, setStats] = useState<{ words: number; bullets: number; tokens_used: number } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState<boolean>(false);
  const [isOpen, setIsOpen] = useState<boolean>(false);

  const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8080';

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
    } catch (err: any) {
      setError(err.message || 'An unexpected error occurred.');
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
        className="bg-white/10 border border-white/20 text-white hover:bg-white/20 disabled:opacity-50 disabled:cursor-not-allowed transition-all flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-semibold backdrop-blur-md shadow-lg"
      >
        {loading ? (
          <>
            <RefreshCw className="w-3.5 h-3.5 animate-spin text-violet-400" />
            <span>GPT-4o generating...</span>
          </>
        ) : (
          <>
            <FileText className="w-3.5 h-3.5 text-emerald-400" />
            <span>Generate ATS Resume (V5)</span>
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
