'use client';

import Link from 'next/link';
import { useCallback, useEffect, useRef, useState } from 'react';
import { Briefcase, ChevronLeft, ExternalLink, Lock, LogOut, RefreshCw, Trash2, XCircle } from 'lucide-react';
import { supabase } from '../../supabaseClient';

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8082';

interface CompanyScrapeSummary {
  company?: string;
  careers_url?: string;
  ats_platform?: string;
  total_scraped?: number;
  it_jobs_found?: number;
  saved_to_db?: number;
  errors?: string[];
}

interface CompanyScrapeStatus {
  status: string;
  phase: string;
  phase_key?: string;
  started_at: string | null;
  finished_at: string | null;
  duration_seconds: number | null;
  summary: CompanyScrapeSummary | null;
  error: string | null;
  input: string | null;
}

interface WatchedCompany {
  id: string;
  input_value: string;
  company_name: string | null;
  careers_url: string | null;
  ats_platform: string | null;
  scrape_frequency: string | null;
  last_scraped_at: string | null;
  last_jobs_found: number | null;
interface CompanyJobRow {
  id?: string;
  job_title: string;
  company_name: string;
  job_url: string;
  location_work_type?: string | null;
  scraped_at?: string | null;
  posted_at?: string | null;
  apply_decision_payload?: { ats_platform?: string; is_company_targeted?: boolean } | null;
}

const idleStatus: CompanyScrapeStatus = {
  status: 'idle',
  phase: 'Idle',
  phase_key: 'idle',
  started_at: null,
  finished_at: null,
  duration_seconds: null,
  summary: null,
  error: null,
  input: null,
};

function formatRelativeScraped(iso: string | null | undefined): string {
  if (!iso) return 'Never';
  try {
    const t = new Date(iso).getTime();
    if (Number.isNaN(t)) return '—';
    const diff = Date.now() - t;
    const s = Math.floor(diff / 1000);
    if (s < 45) return 'Just now';
    const m = Math.floor(s / 60);
    if (m < 60) return `${m}m ago`;
    const h = Math.floor(m / 60);
    if (h < 48) return `${h}h ago`;
    const d = Math.floor(h / 24);
    if (d < 14) return `${d}d ago`;
    const w = Math.floor(d / 7);
    return `${w}w ago`;
  } catch {
    return '—';
  }
}

export default function CompanyScraperPage() {
  const [authToken, setAuthToken] = useState<string | null>(null);
  const [authRole, setAuthRole] = useState<'admin' | 'user' | null>(null);
  const [authEmail, setAuthEmail] = useState<string | null>(null);
  const [isAuthChecking, setIsAuthChecking] = useState(true);
  const [loginEmail, setLoginEmail] = useState('');
  const [loginPassword, setLoginPassword] = useState('');
  const [loginError, setLoginError] = useState('');
  const [loginLoading, setLoginLoading] = useState(false);
  const [authMode, setAuthMode] = useState<'login' | 'register'>('login');

  const [input, setInput] = useState('');
  const [scrapeLoading, setScrapeLoading] = useState(false);
  const [scrapeError, setScrapeError] = useState<string | null>(null);
  const [companyStatus, setCompanyStatus] = useState<CompanyScrapeStatus>(idleStatus);
  const [resultsCleared, setResultsCleared] = useState(false);
  const [lastSummary, setLastSummary] = useState<CompanyScrapeSummary | null>(null);
  const [tableJobs, setTableJobs] = useState<CompanyJobRow[]>([]);
  const [tableLoading, setTableLoading] = useState(false);

  const [watchInput, setWatchInput] = useState('');
  const [watchLoading, setWatchLoading] = useState(false);
  const [watchError, setWatchError] = useState<string | null>(null);
  const [watchAddedBanner, setWatchAddedBanner] = useState<string | null>(null);
  const [watchedCompanies, setWatchedCompanies] = useState<WatchedCompany[]>([]);
  const [watchedListLoading, setWatchedListLoading] = useState(false);

  const handling401Ref = useRef(false);
  const handleLogoutRef = useRef<() => Promise<void>>(async () => {});
  const lastCompanyJobsLoadKey = useRef<string>('');

  const handleLogout = useCallback(async () => {
    await supabase.auth.signOut();
    setAuthToken(null);
    setAuthEmail(null);
    setAuthRole(null);
  }, []);

  useEffect(() => {
    handleLogoutRef.current = handleLogout;
  }, [handleLogout]);

  useEffect(() => {
    supabase.auth.getSession().then(({ data: { session } }) => {
      if (session) {
        const token = session.access_token;
        const userEmail = session.user.email || 'user@hailmary.ai';
        const role = userEmail === 'admin@hailmary.ai' ? 'admin' : 'user';
        setAuthToken(token);
        setAuthEmail(userEmail);
        setAuthRole(role);
      } else {
        setAuthToken(null);
        setAuthEmail(null);
        setAuthRole(null);
      }
      setIsAuthChecking(false);
    });

    const {
      data: { subscription },
    } = supabase.auth.onAuthStateChange((_event, session) => {
      if (session) {
        const token = session.access_token;
        const userEmail = session.user.email || 'user@hailmary.ai';
        const role = userEmail === 'admin@hailmary.ai' ? 'admin' : 'user';
        localStorage.setItem('maas_auth_token', token);
        localStorage.setItem('maas_auth_email', userEmail);
        localStorage.setItem('maas_auth_role', role);
        setAuthToken(token);
        setAuthEmail(userEmail);
        setAuthRole(role);
      } else {
        localStorage.removeItem('maas_auth_token');
        localStorage.removeItem('maas_auth_email');
        localStorage.removeItem('maas_auth_role');
        setAuthToken(null);
        setAuthEmail(null);
        setAuthRole(null);
      }
    });

    return () => {
      subscription.unsubscribe();
    };
  }, []);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    const originalFetch = window.fetch;
    window.fetch = async (input, init) => {
      const urlStr =
        typeof input === 'string' ? input : input instanceof URL ? input.toString() : '';
      if (urlStr.startsWith(API_BASE) && !urlStr.endsWith('/api/login')) {
        const token = localStorage.getItem('maas_auth_token');
        const headers = new Headers(init?.headers || {});
        if (token) {
          headers.set('Authorization', `Bearer ${token}`);
        }
        const res = await originalFetch(input, { ...init, headers });
        if (res.status === 401) {
          if (!handling401Ref.current) {
            handling401Ref.current = true;
            void Promise.resolve(handleLogoutRef.current()).finally(() => {
              window.setTimeout(() => {
                handling401Ref.current = false;
              }, 1500);
            });
          }
        }
        return res;
      }
      return originalFetch(input, init);
    };
    return () => {
      window.fetch = originalFetch;
    };
  }, []);

  const refreshStatus = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/scrape/company/status`);
      if (!res.ok) return;
      const data = (await res.json()) as CompanyScrapeStatus;
      setCompanyStatus(data);
    } catch {
      // ignore
    }
  }, []);

  const loadWatchedCompanies = useCallback(async (opts?: { silent?: boolean }) => {
    if (!authToken) return;
    if (!opts?.silent) setWatchedListLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/watched-companies`);
      if (!res.ok) return;
      const data = (await res.json()) as { companies?: WatchedCompany[] };
      setWatchedCompanies(data.companies || []);
    } catch {
      // ignore
    } finally {
      if (!opts?.silent) setWatchedListLoading(false);
    }
  }, [authToken]);

  useEffect(() => {
    if (!authToken) return;
    void loadWatchedCompanies();
    const id = window.setInterval(() => void loadWatchedCompanies({ silent: true }), 60_000);
    return () => clearInterval(id);
  }, [authToken, loadWatchedCompanies]);

  useEffect(() => {
    if (!authToken) return;
    void refreshStatus();
  }, [authToken, refreshStatus]);

  const isCompanyScrapeRunning = companyStatus.status === 'running';

  useEffect(() => {
    if (!authToken || !isCompanyScrapeRunning) return;
    void refreshStatus();
    const id = setInterval(() => {
      void refreshStatus();
    }, 3000);
    return () => clearInterval(id);
  }, [authToken, isCompanyScrapeRunning, refreshStatus]);

  const loadCompanyJobs = useCallback(async (companyName: string) => {
    if (!companyName.trim()) {
      setTableJobs([]);
      return;
    }
    setTableLoading(true);
    try {
      const { data, error } = await supabase
        .from('jobs')
        .select('*')
        .eq('company_name', companyName)
        .contains('apply_decision_payload', { is_company_targeted: true })
        .order('scraped_at', { ascending: false });
      if (error) {
        setTableJobs([]);
        return;
      }
      setTableJobs((data as CompanyJobRow[]) || []);
    } finally {
      setTableLoading(false);
    }
  }, []);

  useEffect(() => {
    if (resultsCleared) return;
    if (companyStatus.status !== 'completed') return;
    const company = companyStatus.summary?.company;
    if (!company) return;
    const key = `${company}|${companyStatus.finished_at || ''}`;
    if (lastCompanyJobsLoadKey.current === key) return;
    lastCompanyJobsLoadKey.current = key;
    setLastSummary(companyStatus.summary);
    void loadCompanyJobs(company);
  }, [
    companyStatus.status,
    companyStatus.summary?.company,
    companyStatus.finished_at,
    loadCompanyJobs,
    resultsCleared,
  ]);

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoginLoading(true);
    setLoginError('');
    try {
      if (authMode === 'register') {
        const { error } = await supabase.auth.signUp({ email: loginEmail, password: loginPassword });
        if (error) {
          setLoginError(error.message);
          return;
        }
        setLoginError('Check your email to confirm registration, then sign in.');
        return;
      }
      const { error } = await supabase.auth.signInWithPassword({
        email: loginEmail,
        password: loginPassword,
      });
      if (error) {
        setLoginError(error.message);
        return;
      }
    } finally {
      setLoginLoading(false);
    }
  };

  const trimmedInput = input.trim();
  const canSubmit = trimmedInput.length > 0 && !isCompanyScrapeRunning && !scrapeLoading;

  const startScrape = async () => {
    if (!trimmedInput) return;
    lastCompanyJobsLoadKey.current = '';
    setScrapeError(null);
    setScrapeLoading(true);
    setResultsCleared(false);
    try {
      const res = await fetch(`${API_BASE}/api/scrape/company`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ input: trimmedInput }),
      });
      const data = await res.json().catch(() => ({}));
      if (res.status === 403) {
        setScrapeError((data as { message?: string }).message || 'Admin access required.');
        return;
      }
      if (res.status === 409) {
        setScrapeError((data as { message?: string }).message || 'A scrape is already running.');
        return;
      }
      if (!res.ok || !(data as { success?: boolean }).success) {
        setScrapeError((data as { message?: string }).message || 'Failed to start company scrape.');
        return;
      }
      await refreshStatus();
    } catch {
      setScrapeError('Failed to start company scrape.');
    } finally {
      setScrapeLoading(false);
    }
  };

  const clearResults = () => {
    lastCompanyJobsLoadKey.current = '';
    setResultsCleared(true);
    setLastSummary(null);
    setTableJobs([]);
    setScrapeError(null);
  };

  const trimmedWatchInput = watchInput.trim();
  const addWatchedCompany = async () => {
    if (!trimmedWatchInput) return;
    setWatchLoading(true);
    setWatchError(null);
    setWatchAddedBanner(null);
    try {
      const res = await fetch(`${API_BASE}/api/watched-companies`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ input: trimmedWatchInput }),
      });
      const data = (await res.json().catch(() => ({}))) as {
        message?: string;
        id?: string;
        company_name?: string | null;
        ats_platform?: string | null;
      };
      if (!res.ok) {
        setWatchError(data.message || 'Failed to add watch');
        return;
      }
      const label = data.company_name || trimmedWatchInput;
      const ats = data.ats_platform ? ` · ${data.ats_platform}` : '';
      setWatchAddedBanner(`${label}${ats}`);
      window.setTimeout(() => setWatchAddedBanner(null), 6000);
      setWatchInput('');
      await loadWatchedCompanies({ silent: true });
    } catch {
      setWatchError('Failed to add watch');
    } finally {
      setWatchLoading(false);
    }
  };

  const patchWatchedFrequency = async (id: string, freq: 'daily' | 'weekly') => {
    try {
      const res = await fetch(`${API_BASE}/api/watched-companies/${id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ scrape_frequency: freq }),
      });
      if (!res.ok) return;
      await loadWatchedCompanies({ silent: true });
    } catch {
      // ignore
    }
  };

  const removeWatchedCompany = async (id: string) => {
    try {
      const res = await fetch(`${API_BASE}/api/watched-companies/${id}`, { method: 'DELETE' });
      if (!res.ok) return;
      await loadWatchedCompanies({ silent: true });
    } catch {
      // ignore
    }
  };

  const deriveJobType = (loc: string | null | undefined) => {
    if (!loc) return '—';
    const l = loc.toLowerCase();
    if (l.includes('hybrid')) return 'Hybrid';
    if (l.includes('remote')) return 'Remote';
    if (l.includes('onsite') || l.includes('on-site') || l.includes('in office')) return 'Onsite';
    return '—';
  };

  const displayPhase = () => {
    if (resultsCleared && !isCompanyScrapeRunning) return 'Idle';
    if (isCompanyScrapeRunning) return companyStatus.phase || 'Scraping jobs...';
    if (companyStatus.status === 'failed') return 'Failed';
    if (companyStatus.status === 'completed') return 'Completed';
    return companyStatus.phase || 'Idle';
  };

  const formatDatePosted = (row: CompanyJobRow) => {
    const raw = row.posted_at || row.scraped_at;
    if (!raw) return '—';
    try {
      return new Date(raw).toLocaleDateString(undefined, {
        month: 'short',
        day: 'numeric',
        year: 'numeric',
      });
    } catch {
      return raw;
    }
  };

  if (isAuthChecking) {
    return (
      <div className="min-h-screen bg-slate-950 flex flex-col items-center justify-center text-slate-100">
        <div className="absolute top-0 left-1/4 w-96 h-96 bg-violet-600/10 rounded-full filter blur-[80px] pointer-events-none animate-pulse" />
        <div className="absolute top-1/3 right-1/4 w-96 h-96 bg-indigo-600/10 rounded-full filter blur-[80px] pointer-events-none animate-pulse" />
        <div className="flex flex-col items-center space-y-4">
          <div className="p-3 bg-gradient-to-tr from-violet-600 to-indigo-600 rounded-2xl shadow-xl shadow-violet-500/20 animate-bounce">
            <Briefcase className="w-8 h-8 text-white" />
          </div>
          <p className="text-sm font-medium text-slate-400 animate-pulse">Initializing secure connection...</p>
        </div>
      </div>
    );
  }

  if (!authToken) {
    return (
      <div className="min-h-screen bg-slate-950 flex flex-col items-center justify-center text-slate-100 px-4 relative overflow-hidden">
        <div className="absolute top-0 left-1/4 w-96 h-96 bg-violet-600/10 rounded-full filter blur-[80px] pointer-events-none" />
        <div className="absolute top-1/3 right-1/4 w-96 h-96 bg-indigo-600/10 rounded-full filter blur-[80px] pointer-events-none" />

        <div className="w-full max-w-md bg-slate-900/60 backdrop-blur-xl border border-slate-800/80 rounded-2xl p-8 shadow-2xl relative z-10 animate-in fade-in zoom-in-95 duration-300">
          <div className="flex flex-col items-center space-y-6">
            <div className="p-4 bg-gradient-to-tr from-violet-600 to-indigo-600 rounded-2xl shadow-xl shadow-violet-500/10 flex items-center justify-center">
              <Lock className="w-8 h-8 text-white" />
            </div>

            <div className="text-center space-y-2">
              <h2 className="text-2xl font-bold tracking-tight bg-gradient-to-r from-white via-slate-200 to-slate-400 bg-clip-text text-transparent">
                Company Job Scraper
              </h2>
              <p className="text-sm text-slate-400">Sign in to scrape and save IT roles to your jobs table</p>
            </div>

            <form onSubmit={handleLogin} className="w-full space-y-4">
              <div className="space-y-2">
                <label className="text-xs font-semibold text-slate-400 uppercase tracking-wider">Email Address</label>
                <input
                  type="email"
                  placeholder="name@example.com"
                  value={loginEmail}
                  onChange={(e) => setLoginEmail(e.target.value)}
                  className="w-full bg-slate-950/80 border border-slate-800 rounded-xl px-4 py-3 text-slate-100 placeholder:text-slate-600 focus:outline-none focus:ring-2 focus:ring-violet-600/50 focus:border-violet-500 transition-all"
                  required
                />
              </div>

              <div className="space-y-2">
                <label className="text-xs font-semibold text-slate-400 uppercase tracking-wider">Password</label>
                <input
                  type="password"
                  placeholder="••••••••"
                  value={loginPassword}
                  onChange={(e) => setLoginPassword(e.target.value)}
                  className="w-full bg-slate-950/80 border border-slate-800 rounded-xl px-4 py-3 text-slate-100 placeholder:text-slate-600 focus:outline-none focus:ring-2 focus:ring-violet-600/50 focus:border-violet-500 transition-all"
                  required
                />
              </div>

              {loginError && (
                <div className="flex items-center space-x-2 bg-rose-950/30 border border-rose-800/50 rounded-xl p-3 text-rose-400 text-sm animate-in shake duration-200">
                  <XCircle className="w-4 h-4 shrink-0" />
                  <span>{loginError}</span>
                </div>
              )}

              <button
                type="submit"
                disabled={loginLoading}
                className="w-full bg-gradient-to-r from-violet-600 to-indigo-600 hover:from-violet-500 hover:to-indigo-500 text-white font-semibold py-3 px-4 rounded-xl shadow-lg shadow-violet-500/20 hover:shadow-violet-500/30 transition-all flex items-center justify-center space-x-2 disabled:opacity-50 disabled:cursor-not-allowed group"
              >
                {loginLoading ? (
                  <RefreshCw className="w-5 h-5 animate-spin" />
                ) : (
                  <span>{authMode === 'login' ? 'Authenticate' : 'Create Account'}</span>
                )}
              </button>

              <div className="text-center pt-2">
                <button
                  type="button"
                  onClick={() => {
                    setAuthMode(authMode === 'login' ? 'register' : 'login');
                    setLoginError('');
                  }}
                  className="text-xs text-violet-400 hover:text-violet-300 font-medium transition-colors"
                >
                  {authMode === 'login' ? "Don't have an account? Create one" : 'Already have an account? Sign in'}
                </button>
              </div>
            </form>

            <div className="text-xs text-slate-500 text-center border-t border-slate-800/60 pt-4 w-full">
              <Link href="/" className="text-violet-400 hover:text-violet-300 font-medium">
                ← Back to main dashboard
              </Link>
            </div>
          </div>
        </div>
      </div>
    );
  }

  const summary = !resultsCleared && lastSummary ? lastSummary : null;
  const showSummaryCard =
    !resultsCleared && companyStatus.status === 'completed' && summary && !isCompanyScrapeRunning;
  const foundCount = summary?.it_jobs_found ?? companyStatus.summary?.it_jobs_found;
  const savedCount = summary?.saved_to_db ?? companyStatus.summary?.saved_to_db;

  return (
    <div className="flex-1 min-h-screen bg-slate-950 text-slate-100 flex flex-col font-sans selection:bg-violet-600/30">
      <div className="absolute top-0 left-1/4 w-96 h-96 bg-violet-600/10 rounded-full filter blur-[80px] pointer-events-none" />
      <div className="absolute top-1/3 right-1/4 w-96 h-96 bg-indigo-600/10 rounded-full filter blur-[80px] pointer-events-none" />

      <header className="sticky top-0 z-40 bg-slate-950/80 backdrop-blur-md border-b border-slate-800/80 px-6 py-4 flex items-center justify-between">
        <div className="flex items-center space-x-3">
          <Link
            href="/"
            className="inline-flex items-center text-xs font-semibold text-slate-400 hover:text-white bg-slate-900 hover:bg-slate-800 border border-slate-800 hover:border-slate-700 px-3 py-1.5 rounded-full transition-colors"
          >
            <ChevronLeft className="w-3.5 h-3.5 mr-1" />
            Dashboard
          </Link>
          <div className="p-2 bg-gradient-to-tr from-violet-600 to-indigo-600 rounded-xl shadow-lg shadow-violet-500/20">
            <Briefcase className="w-6 h-6 text-white" />
          </div>
          <div>
            <h1 className="text-xl font-bold tracking-tight bg-gradient-to-r from-white via-slate-200 to-slate-400 bg-clip-text text-transparent">
              Company Job Scraper
            </h1>
            <p className="text-xs text-slate-400">On-demand ATS scrape → Supabase jobs</p>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <span className="text-xs text-slate-400 hidden sm:inline">{authEmail}</span>
          <button
            type="button"
            onClick={() => void handleLogout()}
            className="inline-flex items-center text-xs font-semibold text-slate-400 hover:text-white bg-slate-900 hover:bg-slate-800 border border-slate-800 hover:border-slate-700 px-3 py-1.5 rounded-full transition-colors active:scale-95"
          >
            <LogOut className="w-3.5 h-3.5 mr-1.5" />
            Logout
          </button>
        </div>
      </header>

      <main className="relative z-10 flex-1 max-w-5xl w-full mx-auto px-6 py-8 space-y-6">
        <section className="bg-slate-900/40 backdrop-blur-md border border-slate-800/80 p-6 rounded-2xl shadow-xl space-y-4">
          <h2 className="text-sm font-bold text-white tracking-tight">Target</h2>
          <p className="text-xs text-slate-400">
            Examples: &apos;Google&apos;, &apos;https://careers.usaa.com&apos;
          </p>
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            disabled={isCompanyScrapeRunning}
            placeholder="Enter company name or careers URL..."
            className="w-full bg-slate-950/80 border border-slate-800 rounded-xl px-4 py-3 text-slate-100 placeholder:text-slate-600 focus:outline-none focus:ring-2 focus:ring-violet-600/50 focus:border-violet-500 transition-all disabled:opacity-50"
          />
          {authRole === 'admin' ? (
            <button
              type="button"
              onClick={() => void startScrape()}
              disabled={!canSubmit}
              className={`inline-flex items-center px-4 py-2 rounded-xl text-xs font-semibold shadow-md transition-all ${
                !canSubmit
                  ? 'bg-slate-800 text-slate-500 border border-slate-700 cursor-not-allowed'
                  : 'bg-gradient-to-r from-violet-600 to-indigo-600 hover:from-violet-500 hover:to-indigo-500 text-white shadow-violet-600/10 border border-violet-500/20 active:scale-95'
              }`}
            >
              <RefreshCw className={`w-3.5 h-3.5 mr-2 ${scrapeLoading || isCompanyScrapeRunning ? 'animate-spin' : ''}`} />
              Scrape IT Jobs
            </button>
          ) : (
            <p className="text-xs text-amber-400/90">
              Company scrape is available to admin accounts only (same as the main sourcing agent).
            </p>
          )}
          {scrapeError && (
            <div className="flex items-center space-x-2 bg-rose-950/30 border border-rose-800/50 rounded-xl p-3 text-rose-400 text-sm">
              <XCircle className="w-4 h-4 shrink-0" />
              <span>{scrapeError}</span>
            </div>
          )}
        </section>

        <section className="bg-slate-900/40 backdrop-blur-md border border-slate-800/80 p-6 rounded-2xl shadow-xl space-y-4">
          <div className="flex items-center justify-between border-b border-slate-800 pb-3">
            <h2 className="text-sm font-bold text-white tracking-tight">Watched Companies</h2>
            {watchedListLoading && <RefreshCw className="w-4 h-4 text-violet-400 animate-spin" />}
          </div>
          <p className="text-xs text-slate-400">
            Scheduled scrapes run in the background (daily or weekly). Add a company name or careers URL to watch.
          </p>
          <div className="flex flex-col sm:flex-row gap-2">
            <input
              type="text"
              value={watchInput}
              onChange={(e) => setWatchInput(e.target.value)}
              placeholder="Company name or URL..."
              className="flex-1 bg-slate-950/80 border border-slate-800 rounded-xl px-4 py-3 text-slate-100 placeholder:text-slate-600 focus:outline-none focus:ring-2 focus:ring-violet-600/50 focus:border-violet-500 transition-all"
            />
            <button
              type="button"
              onClick={() => void addWatchedCompany()}
              disabled={watchLoading || !trimmedWatchInput}
              className={`inline-flex items-center justify-center px-4 py-3 rounded-xl text-xs font-semibold shadow-md transition-all shrink-0 ${
                watchLoading || !trimmedWatchInput
                  ? 'bg-slate-800 text-slate-500 border border-slate-700 cursor-not-allowed'
                  : 'bg-gradient-to-r from-violet-600 to-indigo-600 hover:from-violet-500 hover:to-indigo-500 text-white shadow-violet-600/10 border border-violet-500/20 active:scale-95'
              }`}
            >
              {watchLoading ? <RefreshCw className="w-4 h-4 animate-spin" /> : 'Watch'}
            </button>
          </div>
          {watchAddedBanner && (
            <div className="flex items-center space-x-2 bg-emerald-950/30 border border-emerald-800/50 rounded-xl p-3 text-emerald-300/90 text-sm">
              <span>
                Now watching: <span className="font-semibold text-white">{watchAddedBanner}</span>
              </span>
            </div>
          )}
          {watchError && (
            <div className="flex items-center space-x-2 bg-rose-950/30 border border-rose-800/50 rounded-xl p-3 text-rose-400 text-sm">
              <XCircle className="w-4 h-4 shrink-0" />
              <span>{watchError}</span>
            </div>
          )}

          <div className="border-t border-slate-800 pt-4 space-y-2">
            <h3 className="text-[10px] font-bold uppercase tracking-wider text-slate-500">Currently Watching</h3>
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs text-slate-300">
                <thead>
                  <tr className="border-b border-slate-850 text-[10px] uppercase tracking-wider text-slate-400 font-bold">
                    <th className="py-3 px-2">Company</th>
                    <th className="py-3 px-2">ATS</th>
                    <th className="py-3 px-2">Frequency</th>
                    <th className="py-3 px-2">Last scraped</th>
                    <th className="py-3 px-2 w-10" />
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-850">
                  {watchedCompanies.length === 0 ? (
                    <tr>
                      <td colSpan={5} className="py-8 px-2 text-center text-slate-500 text-xs">
                        No watched companies yet. Add one above.
                      </td>
                    </tr>
                  ) : (
                    watchedCompanies.map((row) => {
                      const name = row.company_name || row.input_value;
                      const freq = (row.scrape_frequency || 'daily').toLowerCase() === 'weekly' ? 'weekly' : 'daily';
                      return (
                        <tr key={row.id} className="hover:bg-slate-800/10 transition-colors">
                          <td className="py-3 px-2 font-medium text-slate-200 max-w-[140px] sm:max-w-[200px] truncate" title={name}>
                            {name}
                          </td>
                          <td className="py-3 px-2 capitalize text-slate-300 whitespace-nowrap">
                            {row.ats_platform || '—'}
                          </td>
                          <td className="py-3 px-2 whitespace-nowrap">
                            <div className="inline-flex rounded-lg border border-slate-800 overflow-hidden">
                              <button
                                type="button"
                                onClick={() => void patchWatchedFrequency(row.id, 'daily')}
                                className={`px-2 py-1 text-[10px] font-semibold transition-colors ${
                                  freq === 'daily'
                                    ? 'bg-violet-600/30 text-white'
                                    : 'bg-slate-950/50 text-slate-500 hover:text-slate-300'
                                }`}
                              >
                                Daily
                              </button>
                              <button
                                type="button"
                                onClick={() => void patchWatchedFrequency(row.id, 'weekly')}
                                className={`px-2 py-1 text-[10px] font-semibold border-l border-slate-800 transition-colors ${
                                  freq === 'weekly'
                                    ? 'bg-violet-600/30 text-white'
                                    : 'bg-slate-950/50 text-slate-500 hover:text-slate-300'
                                }`}
                              >
                                Weekly
                              </button>
                            </div>
                          </td>
                          <td className="py-3 px-2 text-slate-400 whitespace-nowrap">
                            {formatRelativeScraped(row.last_scraped_at)}
                          </td>
                          <td className="py-3 px-2">
                            <button
                              type="button"
                              onClick={() => void removeWatchedCompany(row.id)}
                              className="p-1.5 rounded-lg text-slate-500 hover:text-rose-400 hover:bg-rose-950/20 transition-colors"
                              title="Remove watch"
                              aria-label="Remove watch"
                            >
                              <Trash2 className="w-4 h-4" />
                            </button>
                          </td>
                        </tr>
                      );
                    })
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </section>

        <section className="bg-slate-900/40 backdrop-blur-md border border-slate-800/80 p-6 rounded-2xl shadow-xl space-y-4">
          <div className="flex items-center justify-between border-b border-slate-800 pb-3">
            <h2 className="text-sm font-bold text-white">Results</h2>
            <button
              type="button"
              onClick={clearResults}
              className="inline-flex items-center text-xs font-semibold text-slate-400 hover:text-white bg-slate-900 hover:bg-slate-800 border border-slate-800 hover:border-slate-700 px-3 py-1.5 rounded-full transition-colors active:scale-95"
            >
              Clear Results
            </button>
          </div>

          <div className="text-sm text-slate-300 space-y-1">
            <p>
              <span className="text-slate-500">Status:</span>{' '}
              <span className="font-semibold text-white">{displayPhase()}</span>
            </p>
            {!resultsCleared && isCompanyScrapeRunning && (
              <p className="text-xs text-slate-400">
                Found: <span className="text-slate-200 font-mono">—</span> IT jobs &nbsp;|&nbsp; Saved:{' '}
                <span className="text-slate-200 font-mono">—</span> to DB
              </p>
            )}
            {!resultsCleared && companyStatus.status === 'completed' && (
              <p className="text-xs text-slate-400">
                Found:{' '}
                <span className="text-slate-200 font-mono">{foundCount ?? '—'}</span> IT jobs &nbsp;|&nbsp; Saved:{' '}
                <span className="text-slate-200 font-mono">{savedCount ?? '—'}</span> to DB
              </p>
            )}
            {companyStatus.status === 'failed' && companyStatus.error && (
              <p className="text-xs text-rose-400 mt-2">{companyStatus.error}</p>
            )}
          </div>

          {showSummaryCard && summary && (
            <div className="bg-slate-950/50 border border-slate-800 rounded-xl p-4 space-y-2 text-xs text-slate-300">
              <p>
                <span className="text-slate-500">Company:</span>{' '}
                <span className="text-white font-semibold">{summary.company}</span>
              </p>
              <p>
                <span className="text-slate-500">ATS Platform:</span>{' '}
                <span className="text-white capitalize">{summary.ats_platform}</span>
              </p>
              <p>
                <span className="text-slate-500">Total Scraped:</span>{' '}
                <span className="font-mono text-slate-100">{summary.total_scraped ?? 0}</span>
              </p>
              <p>
                <span className="text-slate-500">IT Jobs Found:</span>{' '}
                <span className="font-mono text-slate-100">{summary.it_jobs_found ?? 0}</span>
              </p>
              <p>
                <span className="text-slate-500">Saved to DB:</span>{' '}
                <span className="font-mono text-slate-100">{summary.saved_to_db ?? 0}</span>
              </p>
              <p>
                <span className="text-slate-500">Duration:</span>{' '}
                <span className="font-mono text-slate-100">
                  {companyStatus.duration_seconds != null ? `${companyStatus.duration_seconds}s` : '—'}
                </span>
              </p>
            </div>
          )}
        </section>

        <section className="bg-slate-900/40 backdrop-blur-md border border-slate-800/80 p-6 rounded-2xl shadow-xl space-y-4">
          <div className="flex items-center justify-between border-b border-slate-800 pb-3">
            <h2 className="text-sm font-bold text-white">Saved jobs</h2>
            {tableLoading && <RefreshCw className="w-4 h-4 text-violet-400 animate-spin" />}
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs text-slate-300">
              <thead>
                <tr className="border-b border-slate-850 text-[10px] uppercase tracking-wider text-slate-400 font-bold">
                  <th className="py-3 px-4">Job Title</th>
                  <th className="py-3 px-4">Company</th>
                  <th className="py-3 px-4">Location</th>
                  <th className="py-3 px-4">Job Type</th>
                  <th className="py-3 px-4">ATS Platform</th>
                  <th className="py-3 px-4">Date Posted</th>
                  <th className="py-3 px-4">Link</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-850">
                {tableJobs.length === 0 ? (
                  <tr>
                    <td colSpan={7} className="py-8 px-4 text-center text-slate-500 text-xs">
                      {resultsCleared
                        ? 'Run a scrape or clear was used — no rows to show.'
                        : 'No matching rows yet. After a successful scrape, jobs appear here.'}
                    </td>
                  </tr>
                ) : (
                  tableJobs.map((row) => (
                    <tr key={row.id || row.job_url} className="hover:bg-slate-800/10 transition-colors">
                      <td className="py-3 px-4 font-medium text-slate-200 max-w-[200px] truncate" title={row.job_title}>
                        {row.job_title}
                      </td>
                      <td className="py-3 px-4 text-slate-300">{row.company_name}</td>
                      <td className="py-3 px-4 text-slate-400 max-w-[160px] truncate" title={row.location_work_type || ''}>
                        {row.location_work_type || '—'}
                      </td>
                      <td className="py-3 px-4 text-slate-400">{deriveJobType(row.location_work_type)}</td>
                      <td className="py-3 px-4 capitalize text-slate-300">
                        {row.apply_decision_payload?.ats_platform || '—'}
                      </td>
                      <td className="py-3 px-4 text-slate-400 whitespace-nowrap">{formatDatePosted(row)}</td>
                      <td className="py-3 px-4">
                        <a
                          href={row.job_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="inline-flex items-center text-violet-400 hover:text-violet-300 font-semibold"
                        >
                          Open
                          <ExternalLink className="w-3 h-3 ml-1" />
                        </a>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </section>
      </main>
    </div>
  );
}
