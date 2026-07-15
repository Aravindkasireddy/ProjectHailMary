'use client';

import { RefObject } from 'react';
import {
  Activity,
  Bold,
  Check,
  ChevronRight,
  FileText,
  Italic,
  Link2,
  List,
  ListOrdered,
  Redo,
  Sliders,
  Type,
  Underline,
  Undo,
} from 'lucide-react';
import CopyButton from '../../../components/CopyButton';
import ResumeGenerator from '../../../components/ResumeGenerator';
import { Job } from './types';
import { CATEGORIES } from './constants';

export interface EditState {
  title: string;
  company: string;
  reqId: string;
  location: string;
  decision: string;
  label: string;
  score: number;
  rationale: string;
  desc: string;
  cloud: string;
  seniority: string;
  source: string;
  url: string;
  payload: string;
  isPayloadExpanded: boolean;
  descHistory: string[];
  historyIndex: number;
}

export interface EditHandlers {
  setTitle: (v: string) => void;
  setCompany: (v: string) => void;
  setReqId: (v: string) => void;
  setLocation: (v: string) => void;
  setDecision: (v: string) => void;
  setLabel: (v: string) => void;
  setScore: (v: number) => void;
  setRationale: (v: string) => void;
  setDesc: (v: string) => void;
  setCloud: (v: string) => void;
  setSeniority: (v: string) => void;
  setSource: (v: string) => void;
  setUrl: (v: string) => void;
  setPayload: (v: string) => void;
  setIsPayloadExpanded: (v: boolean) => void;
  updateDescWithHistory: (v: string) => void;
  handleUndo: () => void;
  handleRedo: () => void;
  handleToolbarClick: (action: string) => void;
  closeModal: () => void;
  submitOverride: () => void;
  checkJobPostingLive: (job: Job) => Promise<void>;
  generateTailoring: (jobUrl: string) => void;
  handleModalKeyDown: (e: React.KeyboardEvent<HTMLDivElement>) => void;
}

interface JobDetailModalProps {
  isOpen: boolean;
  selectedJob: Job | null;
  authRole: 'admin' | 'user' | null;
  checkingLiveJobUrl: string | null;
  modalRef: RefObject<HTMLDivElement | null>;
  edit: EditState;
  handlers: EditHandlers;
}

export default function JobDetailModal({
  isOpen,
  selectedJob,
  authRole,
  checkingLiveJobUrl,
  modalRef,
  edit,
  handlers,
}: JobDetailModalProps) {
  if (!isOpen || !selectedJob) return null;

  const {
    title, company, reqId, location, decision, label, score, rationale,
    desc, cloud, seniority, source, url, payload, isPayloadExpanded,
    descHistory, historyIndex,
  } = edit;

  const {
    setTitle, setCompany, setReqId, setLocation, setDecision, setLabel,
    setScore, setRationale, setDesc, setCloud, setSeniority, setSource,
    setUrl, setPayload, setIsPayloadExpanded, updateDescWithHistory,
    handleUndo, handleRedo, handleToolbarClick,
    closeModal, submitOverride, checkJobPostingLive, generateTailoring,
    handleModalKeyDown,
  } = handlers;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/70 backdrop-blur-sm p-4 overflow-y-auto">
      <div
        ref={modalRef}
        role="dialog"
        aria-modal="true"
        aria-label={authRole === 'admin' ? 'Inspect Candidate & Apply Manual Override' : 'Inspect Candidate'}
        tabIndex={-1}
        onKeyDown={handleModalKeyDown}
        className="bg-slate-900 border border-slate-800 w-full max-w-4xl rounded-3xl shadow-2xl flex flex-col max-h-[90vh] overflow-hidden animate-in fade-in zoom-in-95 duration-200 focus:outline-none"
      >
        {/* Header */}
        <div className="px-6 py-4 border-b border-slate-800 flex items-center justify-between bg-slate-950/50">
          <div className="flex items-center space-x-2">
            <Sliders className="w-5 h-5 text-violet-400" />
            <h3 className="text-base font-bold text-white">
              {authRole === 'admin' ? 'Inspect Candidate & Apply Manual Override' : 'Inspect Candidate'}
            </h3>
          </div>
          <div className="flex items-center gap-2">
            {selectedJob.job_url && (
              <button
                type="button"
                onClick={() => void checkJobPostingLive(selectedJob)}
                disabled={checkingLiveJobUrl === selectedJob.job_url}
                className={`inline-flex items-center px-2.5 py-1.5 rounded-lg text-xs font-semibold border transition-colors ${
                  checkingLiveJobUrl === selectedJob.job_url
                    ? 'bg-slate-800 text-slate-500 border-slate-700 cursor-wait'
                    : 'bg-violet-950/50 hover:bg-violet-900/60 text-violet-200 border-violet-800/40'
                }`}
                title="Probe the posting URL for closed vs active signals"
              >
                <Activity className={`w-3.5 h-3.5 mr-1 ${checkingLiveJobUrl === selectedJob.job_url ? 'animate-spin' : ''}`} />
                {checkingLiveJobUrl === selectedJob.job_url ? 'Checking…' : 'Check live'}
              </button>
            )}
            <button
              onClick={() => closeModal()}
              className="p-1 text-slate-400 hover:text-white bg-slate-800 hover:bg-slate-750 rounded-lg transition-colors text-xs font-bold px-2.5"
            >
              Close
            </button>
          </div>
        </div>

        {/* Body */}
        <div className="p-6 overflow-y-auto space-y-5 flex-1 select-text bg-slate-900">

          {/* Job Title */}
          <div className="space-y-1.5">
            <div className="flex items-center justify-between">
              <label className="block text-xs font-bold text-slate-400">Job Title <span className="text-red-500">*</span></label>
              <CopyButton text={title} />
            </div>
            <input type="text" placeholder="Role title" value={title} onChange={e => setTitle(e.target.value)}
              readOnly={authRole !== 'admin'}
              className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3 py-2.5 text-sm text-slate-200 focus:outline-none focus:border-violet-600/70 placeholder-slate-700 read-only:text-slate-400" />
          </div>

          {/* Requirement ID */}
          <div className="space-y-1.5">
            <div className="flex items-center justify-between">
              <label className="block text-xs font-bold text-slate-400">Requirement ID <span className="text-red-500">*</span></label>
              <CopyButton text={reqId} />
            </div>
            <input type="text" placeholder="e.g., REQ-12345" value={reqId} onChange={e => setReqId(e.target.value)}
              readOnly={authRole !== 'admin'}
              className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3 py-2.5 text-sm text-slate-200 focus:outline-none focus:border-violet-600/70 placeholder-slate-700 font-mono read-only:text-slate-400" />
          </div>

          {/* URL */}
          <div className="space-y-1.5">
            <div className="flex items-center justify-between">
              <label className="block text-xs font-bold text-slate-400">URL for Original Posting <span className="text-red-500">*</span></label>
              <CopyButton text={url} />
            </div>
            <input type="text" placeholder="https://careers.example.com/job/123" value={url} onChange={e => setUrl(e.target.value)}
              readOnly={authRole !== 'admin'}
              className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3 py-2.5 text-sm text-slate-200 focus:outline-none focus:border-violet-600/70 placeholder-slate-700 read-only:text-slate-400" />
          </div>

          {/* Company */}
          <div className="space-y-1.5">
            <div className="flex items-center justify-between">
              <label className="block text-xs font-bold text-slate-400">Company Name <span className="text-red-500">*</span></label>
              <CopyButton text={company} />
            </div>
            <input type="text" placeholder="Company name" value={company} onChange={e => setCompany(e.target.value)}
              readOnly={authRole !== 'admin'}
              className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3 py-2.5 text-sm text-slate-200 focus:outline-none focus:border-violet-600/70 placeholder-slate-700 read-only:text-slate-400" />
          </div>

          {/* Location */}
          <div className="space-y-1.5">
            <div className="flex items-center justify-between">
              <label className="block text-xs font-bold text-slate-400">Location + Work Type <span className="text-red-500">*</span></label>
              <CopyButton text={location} />
            </div>
            <input type="text" placeholder="e.g., Dallas, TX — Hybrid" value={location} onChange={e => setLocation(e.target.value)}
              readOnly={authRole !== 'admin'}
              className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3 py-2.5 text-sm text-slate-200 focus:outline-none focus:border-violet-600/70 placeholder-slate-700 read-only:text-slate-400" />
          </div>

          {/* Cloud / Seniority / Source */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4 pt-1">
            <div className="space-y-1.5">
              <div className="flex items-center justify-between">
                <label className="block text-xs font-bold text-slate-400">Cloud</label>
                <CopyButton text={cloud} />
              </div>
              <select value={cloud} onChange={e => setCloud(e.target.value)} disabled={authRole !== 'admin'}
                className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3 py-2.5 text-sm text-slate-200 focus:outline-none focus:border-violet-600/70 cursor-pointer disabled:text-slate-400 disabled:cursor-not-allowed">
                {['Not specified','AWS','GCP','Azure','Multiple','Other'].map(o => <option key={o} value={o}>{o}</option>)}
              </select>
            </div>
            <div className="space-y-1.5">
              <div className="flex items-center justify-between">
                <label className="block text-xs font-bold text-slate-400">Seniority</label>
                <CopyButton text={seniority} />
              </div>
              <select value={seniority} onChange={e => setSeniority(e.target.value)} disabled={authRole !== 'admin'}
                className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3 py-2.5 text-sm text-slate-200 focus:outline-none focus:border-violet-600/70 cursor-pointer disabled:text-slate-400 disabled:cursor-not-allowed">
                {['Not specified','Junior','Mid','Senior','Lead','Staff','Principal','Manager/Director'].map(o => <option key={o} value={o}>{o}</option>)}
              </select>
            </div>
            <div className="space-y-1.5">
              <div className="flex items-center justify-between">
                <label className="block text-xs font-bold text-slate-400">Source</label>
                <CopyButton text={source} />
              </div>
              <select value={source} onChange={e => setSource(e.target.value)} disabled={authRole !== 'admin'}
                className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3 py-2.5 text-sm text-slate-200 focus:outline-none focus:border-violet-600/70 cursor-pointer disabled:text-slate-400 disabled:cursor-not-allowed">
                {['Not specified','Yahoo Sourced','ATS Direct','Manual Sourced','Lever','Greenhouse','Ashby','Other'].map(o => <option key={o} value={o}>{o}</option>)}
              </select>
            </div>
          </div>

          {/* Job Description */}
          <div className="space-y-1.5">
            <div className="flex items-center justify-between">
              <label className="block text-xs font-bold text-slate-400">Job Description <span className="text-red-500">*</span></label>
              <CopyButton text={desc} />
            </div>
            <div className="border border-slate-800 rounded-2xl overflow-hidden bg-slate-950 flex flex-col focus-within:border-violet-600/70 transition-colors">
              {authRole === 'admin' && (
                <div className="flex flex-wrap items-center gap-1 p-2 bg-slate-900 border-b border-slate-800">
                  <button type="button" onClick={handleUndo} disabled={historyIndex <= 0}
                    className="p-1.5 text-slate-400 hover:text-white disabled:opacity-30 rounded transition-colors" title="Undo">
                    <Undo className="w-4 h-4" />
                  </button>
                  <button type="button" onClick={handleRedo} disabled={historyIndex >= descHistory.length - 1}
                    className="p-1.5 text-slate-400 hover:text-white disabled:opacity-30 rounded transition-colors" title="Redo">
                    <Redo className="w-4 h-4" />
                  </button>
                  <div className="w-px h-4 bg-slate-800 mx-1" />
                  {([['bold', Bold], ['italic', Italic], ['underline', Underline]] as const).map(([action, Icon]) => (
                    <button key={action} type="button" onClick={() => handleToolbarClick(action)}
                      className="p-1.5 text-slate-400 hover:text-white rounded transition-colors">
                      <Icon className="w-4 h-4" />
                    </button>
                  ))}
                  <div className="w-px h-4 bg-slate-800 mx-1" />
                  {([['bullet', List], ['number', ListOrdered], ['link', Link2], ['clear', Type]] as const).map(([action, Icon]) => (
                    <button key={action} type="button" onClick={() => handleToolbarClick(action)}
                      className="p-1.5 text-slate-400 hover:text-white rounded transition-colors">
                      <Icon className="w-4 h-4" />
                    </button>
                  ))}
                </div>
              )}
              <textarea id="job-desc-textarea" rows={8}
                placeholder="Paste full job description here..."
                value={desc} onChange={e => setDesc(e.target.value)}
                onBlur={e => updateDescWithHistory(e.target.value)}
                readOnly={authRole !== 'admin'}
                className="w-full bg-transparent px-4 py-3 text-sm text-slate-300 focus:outline-none resize-y placeholder-slate-700 min-h-[180px] leading-relaxed read-only:text-slate-400" />
              <div className="px-4 py-1.5 bg-slate-900 border-t border-slate-800 text-[10px] text-slate-500 font-mono">
                {desc.length} chars
              </div>
            </div>
          </div>

          {/* Optional Details Accordion */}
          <div className="border border-slate-800 rounded-2xl overflow-hidden bg-slate-950/20">
            <button type="button" onClick={() => setIsPayloadExpanded(!isPayloadExpanded)}
              className="w-full px-4 py-3 flex items-center justify-between text-xs font-bold text-slate-400 hover:bg-slate-850 hover:text-slate-200 transition-all bg-slate-900/30">
              <span className="flex items-center">
                <ChevronRight className={`w-4 h-4 mr-2 transition-transform duration-200 ${isPayloadExpanded ? 'rotate-90 text-violet-400' : 'text-slate-500'}`} />
                Optional details and review payload
              </span>
            </button>
            {isPayloadExpanded && (
              <div className="p-4 border-t border-slate-850 space-y-4 bg-slate-950/40 animate-in fade-in duration-200">
                <div>
                  <div className="flex items-center justify-between pb-1">
                    <h4 className="text-xs font-bold uppercase tracking-wider text-slate-300">DECISION PAYLOAD</h4>
                    <CopyButton text={payload} />
                  </div>
                  <p className="text-[11px] text-slate-500 mb-2 leading-relaxed">
                    Optional: paste the master classifier payload. If it says APPLY, MAAS will trust it unless a real duplicate or policy conflict exists.
                  </p>
                  <textarea rows={8} value={payload} onChange={e => setPayload(e.target.value)}
                    readOnly={authRole !== 'admin'}
                    className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3 py-2 text-xs text-slate-300 focus:outline-none focus:border-violet-600/70 font-mono leading-relaxed placeholder-slate-700 read-only:text-slate-400"
                    placeholder='{ "apply_decision": "APPLY", "strongest_label": "...", ... }' />
                </div>
              </div>
            )}
          </div>

          {/* Override Decision */}
          <div className="border border-slate-800/80 rounded-2xl p-4 bg-slate-950/20 space-y-4">
            <h4 className="text-xs font-bold uppercase tracking-wider text-slate-400 pb-1.5 border-b border-slate-850">
              Manual Decision Override
            </h4>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div className="space-y-1.5">
                <label className="block text-[10px] font-bold uppercase text-slate-500">Apply Decision</label>
                <select value={decision} onChange={e => setDecision(e.target.value)} disabled={authRole !== 'admin'}
                  className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-violet-600/70 disabled:text-slate-400 disabled:cursor-not-allowed">
                  <option value="APPLY">APPLY (Approve)</option>
                  <option value="DO_NOT_APPLY">DO_NOT_APPLY (Reject)</option>
                </select>
              </div>
              <div className="space-y-1.5">
                <label className="block text-[10px] font-bold uppercase text-slate-500">Policy Label</label>
                <select value={label} onChange={e => setLabel(e.target.value)} disabled={authRole !== 'admin'}
                  className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-violet-600/70 disabled:text-slate-400 disabled:cursor-not-allowed">
                  {CATEGORIES.map(cat => <option key={cat} value={cat}>{cat}</option>)}
                </select>
              </div>
              <div className="space-y-1.5 md:col-span-2">
                <div className="flex justify-between items-center text-[10px] font-bold uppercase text-slate-500">
                  <span>Confidence Score</span>
                  <span className="text-violet-400 font-bold">{score}%</span>
                </div>
                <div className="flex items-center space-x-4">
                  <input type="range" min="0" max="100" value={score} onChange={e => setScore(Number(e.target.value))}
                    disabled={authRole !== 'admin'}
                    className="flex-1 accent-violet-600 bg-slate-950 h-2 rounded-lg appearance-none cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed" />
                  <input type="number" min="0" max="100" value={score} onChange={e => setScore(Number(e.target.value))}
                    readOnly={authRole !== 'admin'}
                    className="w-16 bg-slate-950 border border-slate-800 rounded-xl px-2 py-1 text-center text-xs text-slate-200 focus:outline-none focus:border-violet-600/70 read-only:text-slate-400" />
                </div>
              </div>
              <div className="space-y-1.5 md:col-span-2">
                <label className="block text-[10px] font-bold uppercase text-slate-500">Override Rationale</label>
                <textarea rows={3} value={rationale} onChange={e => setRationale(e.target.value)}
                  readOnly={authRole !== 'admin'}
                  className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-violet-600/70 placeholder-slate-700 read-only:text-slate-400"
                  placeholder="Write details explaining the manual approval or classification adjustments..." />
              </div>
            </div>
          </div>
        </div>

        {/* Footer */}
        <div className="px-6 py-4 border-t border-slate-800 flex justify-end items-center space-x-3 bg-slate-950/50">
          {selectedJob.apply_decision === 'APPLY' && authRole === 'admin' && (
            <div className="mr-auto flex items-center space-x-2">
              <button type="button"
                onClick={() => { closeModal(); generateTailoring(selectedJob.job_url); }}
                className="inline-flex items-center px-4 py-2 bg-gradient-to-r from-emerald-600 to-teal-600 hover:from-emerald-500 hover:to-teal-500 text-white rounded-xl text-xs font-bold border border-emerald-500/20 active:scale-95 shadow-md transition-all">
                <FileText className="w-4 h-4 mr-2" />
                AI Tailor Application
              </button>
              <ResumeGenerator jd={selectedJob.job_description} jobTitle={selectedJob.job_title} companyName={selectedJob.company_name} compact={false} />
            </div>
          )}
          <button onClick={() => closeModal()}
            className="px-4 py-2 bg-slate-800 hover:bg-slate-750 text-slate-300 hover:text-white rounded-xl text-xs font-semibold border border-slate-700 transition-all">
            {authRole === 'admin' ? 'Cancel' : 'Close'}
          </button>
          {authRole === 'admin' && (
            <button onClick={submitOverride}
              className="inline-flex items-center px-6 py-2 bg-gradient-to-r from-violet-600 to-indigo-600 hover:from-violet-500 hover:to-indigo-500 text-white rounded-xl text-xs font-bold border border-violet-500/20 active:scale-95 shadow-md shadow-violet-500/10 transition-all">
              <Check className="w-4 h-4 mr-2" />
              Apply Override Changes
            </button>
          )}
        </div>

      </div>
    </div>
  );
}
