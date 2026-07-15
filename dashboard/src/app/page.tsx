'use client';

import Link from 'next/link';
import { useState, useEffect, useRef, useMemo } from 'react';
import { useRouter } from 'next/navigation';
import {
  Briefcase,
  Settings as SettingsIcon,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  RefreshCw,
  Search,
  Database,
  Check,
  Sliders,
  ChevronRight,
  BellRing,
  BarChart3,
  Shield,
  Copy,
  FileText,
  Activity,
} from 'lucide-react';
import ResumeGenerator from '../../components/ResumeGenerator';
import CopyButton from '../../components/CopyButton';
import LogConsole from '../../components/LogConsole';
import SettingsPanel from '../../components/SettingsPanel';
import PolicyPanel from '../../components/PolicyPanel';
import JobCard from '../../components/JobCard';
import AppNav from '../../components/AppNav';
import { supabase } from '../supabaseClient';
import { dedupeJobsByCanonicalUrl, browserOpenJobUrl } from '../lib/jobUrl';
import { isOfficialCompanyCareersJobUrl } from '../lib/employerJobUrl';
import { fetchAllSupabaseJobs } from '../lib/fetchAllSupabaseJobs';
import {
  type TabId,
  type DecisionPayload,
  type Job,
  type SponsorMetadata,
  type AnalyticsData,
  type PolicyConfig,
  type Config,
  type ScraperStatus,
  type StaleCheckStatus,
  type SalaryInsights,
} from './home/types';
import { type ScrapedTimeframe, CATEGORIES } from './home/constants';
import {
  filterJobsOfficialCareersOnly,
  jobListPollUnchanged,
  isUsLocation,
  computeAnalytics,
  computeSalaryInsights,
  getJobSource,
} from './home/utils';
import HomeJobsToolbar from './home/HomeJobsToolbar';
import AnalyticsPanel from './home/AnalyticsPanel';
import ApplicationsKanban from './home/ApplicationsKanban';
import JobDetailModal from './home/JobDetailModal';

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8082';

// Types, constants, and pure helpers live in ./home/{types,constants,utils}.ts

export default function Dashboard() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [newJobsCount, setNewJobsCount] = useState<number>(0);

  // Authentication States
  const [authToken, setAuthToken] = useState<string | null>(null);
  const [authRole, setAuthRole] = useState<'admin' | 'user' | null>(null);
  const [authEmail, setAuthEmail] = useState<string | null>(null);
  const [isAuthChecking, setIsAuthChecking] = useState<boolean>(true);
  const router = useRouter();

  // Analytics and Policy States
  const [analyticsData, setAnalyticsData] = useState<AnalyticsData | null>(null);
  const [analyticsLoading] = useState(false);
  const [policyConfig, setPolicyConfig] = useState<PolicyConfig | null>(null);
  const [policyLoading, setPolicyLoading] = useState(false);

  // States
  const [config, setConfig] = useState<Config>({
    target_titles: [],
    scheduler: { enabled: true, run_at_hour: 8, run_at_minute: 0 },
    webhook_url: ''
  });
  const [scraperStatus, setScraperStatus] = useState({
    status: 'idle',
    message: 'Ready.',
    last_error: null as string | null,
    last_run: null as string | null,
    last_metrics: {} as Record<string, number>,
  });
  const [searchTerm, setSearchTerm] = useState('');
  // Debounced separately from searchTerm so the input feels instant while
  // typing, but the (potentially expensive) job-list filter only re-runs
  // ~250ms after the user pauses, not on every keystroke.
  const [debouncedSearchTerm, setDebouncedSearchTerm] = useState('');
  const searchInputRef = useRef<HTMLInputElement>(null);
  const modalRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const t = setTimeout(() => setDebouncedSearchTerm(searchTerm), 250);
    return () => clearTimeout(t);
  }, [searchTerm]);
  const [activeTab, setActiveTab] = useState<TabId>('approved');
  const [resume, setResume] = useState<string>('');
  const [resumeLoading, setResumeLoading] = useState<boolean>(false);
  const [resumeSaving, setResumeSaving] = useState<boolean>(false);
  
  // Custom states for AI tailoring
  const [tailoringLoading, setTailoringLoading] = useState<boolean>(false);
  const [tailoredCoverLetter, setTailoredCoverLetter] = useState<string>('');
  const [tailoredResumeBullets, setTailoredResumeBullets] = useState<Array<{original_bullet: string, suggested_bullet: string, rationale: string}>>([]);
  const [isTailorModalOpen, setIsTailorModalOpen] = useState<boolean>(false);
  const [selectedRoleFilter, setSelectedRoleFilter] = useState('all');
  const [sortBy, setSortBy] = useState<'newest' | 'oldest'>('newest');
  const [scrapedTimeframe, setScrapedTimeframe] = useState<'all' | 'recent' | 'today' | 'week' | 'month' | 'posted_today' | 'posted_week'>('all');
  const [staleCheckStatus, setStaleCheckStatus] = useState({ status: 'idle', progress: 0, total: 0, completed: 0, stale_found: 0 });
  const [showActiveOnly, setShowActiveOnly] = useState(true);
  const [past24hOnly, setPast24hOnly] = useState(false);
  const [officialCareerUrlsOnly, setOfficialCareerUrlsOnly] = useState(false);
  const officialCareerUrlsOnlyRef = useRef(false);

  useEffect(() => {
    officialCareerUrlsOnlyRef.current = officialCareerUrlsOnly;
  }, [officialCareerUrlsOnly]);

  const handleLogoutRef = useRef<() => Promise<void>>(async () => {});
  const handling401Ref = useRef(false);
  const jobsForPollRef = useRef<Job[]>([]);

  // Custom States for Advanced Sourcing and Live Logs Console
  const [selectedSourceFilter, setSelectedSourceFilter] = useState<string | null>(null);
  // Saved filter presets (High-fit / Fresh jobs / Remote-first / Needs review)
  const [confidenceBandFilter, setConfidenceBandFilter] = useState<'all' | 'high' | 'borderline'>('all');
  const [remoteOnlyFilter, setRemoteOnlyFilter] = useState(false);
  const [activeFilterPreset, setActiveFilterPreset] = useState<string | null>(null);
  // Bulk selection/actions on the approved feed
  const [selectedJobUrls, setSelectedJobUrls] = useState<Set<string>>(new Set());
  const [bulkActionBusy, setBulkActionBusy] = useState(false);
  const [scraperLogs, setScraperLogs] = useState<string[]>([]);
  const [isLogsExpanded, setIsLogsExpanded] = useState(false);

  // Custom States for Salary Insights and Kanban Board
  const [salaryInsights, setSalaryInsights] = useState<{
    yearly_count: number;
    yearly_avg: number;
    yearly_min: number;
    yearly_max: number;
    hourly_count: number;
    hourly_avg: number;
    hourly_min: number;
    hourly_max: number;
    yearly_distribution: number[];
    hourly_distribution: number[];
  } | null>(null);
  const [salaryInsightsLoading] = useState(false);
  const [isKanbanView, setIsKanbanView] = useState(false);

  // Selection / Editing Modal States
  const [selectedJob, setSelectedJob] = useState<Job | null>(null);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [editTitle, setEditTitle] = useState('');
  const [editCompany, setEditCompany] = useState('');
  const [editReqId, setEditReqId] = useState('');
  const [editLocation, setEditLocation] = useState('');
  const [editDecision, setEditDecision] = useState('APPLY');
  const [editLabel, setEditLabel] = useState('DevOps Engineer');
  const [editScore, setEditScore] = useState(85);
  const [editRationale, setEditRationale] = useState('');
  const [editDesc, setEditDesc] = useState('');
  const [editCloud, setEditCloud] = useState('Not specified');
  const [editSeniority, setEditSeniority] = useState('Not specified');
  const [editSource, setEditSource] = useState('Not specified');
  const [editUrl, setEditUrl] = useState('');
  const [editPayload, setEditPayload] = useState('');
  const [isPayloadExpanded, setIsPayloadExpanded] = useState(false);
  const [descHistory, setDescHistory] = useState<string[]>([]);
  const [historyIndex, setHistoryIndex] = useState(-1);

  // Settings Panel States
  const [titlesInput, setTitlesInput] = useState('');
  const [webhookUrlInput, setWebhookUrlInput] = useState('');
  const [schedulerHour, setSchedulerHour] = useState(8);
  const [schedulerMinute, setSchedulerMinute] = useState(0);
  const [schedulerEnabled, setSchedulerEnabled] = useState(true);
  const [sendDigestOnly, setSendDigestOnly] = useState(true);
  const [joobleApiKeyInput, setJoobleApiKeyInput] = useState('');

  // General Loading & Notification UI States
  const [checkingLiveJobUrl, setCheckingLiveJobUrl] = useState<string | null>(null);
  const [testingWebhook, setTestingWebhook] = useState(false);
  const [resettingTitles, setResettingTitles] = useState(false);
  const [statusMessage, setStatusMessage] = useState<{ text: string; type: 'success' | 'error' | 'info' } | null>(null);

  // Core helpers (hoisted to prevent temporal dead zone)
  const showStatus = (text: string, type: 'success' | 'error' | 'info') => {
    setStatusMessage({ text, type });
    setTimeout(() => setStatusMessage(null), 5000);
  };

  const handleLogout = async () => {
    await supabase.auth.signOut();
    localStorage.removeItem('maas_auth_token');
    localStorage.removeItem('maas_auth_role');
    localStorage.removeItem('maas_auth_email');
    setAuthToken(null);
    setAuthRole(null);
    setAuthEmail(null);
    router.push('/login');
  };

  useEffect(() => {
    handleLogoutRef.current = handleLogout;
  });

  // Restore session from Supabase on mount & listen to changes
  useEffect(() => {
    supabase.auth.getSession().then(({ data: { session } }) => {
      if (session) {
        const token = session.access_token;
        const userEmail = session.user.email || 'user@hailmary.ai';
        const role = userEmail === 'admin@hailmary.ai' ? 'admin' : 'user';
        if (typeof window !== 'undefined') {
          localStorage.setItem('maas_auth_token', token);
          localStorage.setItem('maas_auth_email', userEmail);
          localStorage.setItem('maas_auth_role', role);
        }
        setAuthToken(token);
        setAuthEmail(userEmail);
        setAuthRole(role);
      } else {
        if (typeof window !== 'undefined') {
          localStorage.removeItem('maas_auth_token');
          localStorage.removeItem('maas_auth_email');
          localStorage.removeItem('maas_auth_role');
        }
        setAuthToken(null);
        setAuthEmail(null);
        setAuthRole(null);
      }
      setIsAuthChecking(false);
    });

    const { data: { subscription } } = supabase.auth.onAuthStateChange((_event, session) => {
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
    if (typeof window !== 'undefined') {
      const originalFetch = window.fetch;
      window.fetch = async (input, init) => {
        const urlStr = typeof input === 'string' ? input : input instanceof URL ? input.toString() : '';
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
    }
  }, []);

  const checkStaleStatus = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/stale-status`);
      if (res.ok) {
        const data = await res.json();
        setStaleCheckStatus(data);
      }
    } catch {
      // Silence is golden
    }
  };

  const checkScraperStatus = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/scraper-status`);
      if (res.ok) {
        const data = await res.json();
        setScraperStatus((prev) => ({
          ...prev,
          ...data,
          last_error: data.last_error ?? prev.last_error ?? null,
          last_metrics: data.last_metrics ?? prev.last_metrics ?? {},
        }));
      }
    } catch {
      // Silence is golden
    }
  };

  // Trigger analytics + salary calculations whenever jobs list changes
  useEffect(() => {
    if (jobs.length > 0) {
      setTimeout(() => {
        setAnalyticsData(computeAnalytics(jobs));
        setSalaryInsights(computeSalaryInsights(jobs));
      }, 0);
    }
  }, [jobs]);

  // Fetch API Functions
  const fetchAnalytics = async () => {
    if (jobs.length > 0) setAnalyticsData(computeAnalytics(jobs));
  };

  const fetchPolicy = async () => {
    setPolicyLoading(true);
    try {
      const { data, error } = await supabase
        .from('user_configs')
        .select('policy_max_experience_years, policy_min_salary_annual, policy_min_salary_hourly, policy_enforce_visa_sponsorship, policy_enforce_no_clearance, policy_custom_red_flag_keywords')
        .maybeSingle();

      if (error) throw error;
      if (data) {
        setPolicyConfig({
          max_experience_years: data.policy_max_experience_years ?? 8,
          min_salary_annual: data.policy_min_salary_annual ?? 80000,
          min_salary_hourly: data.policy_min_salary_hourly ?? 50,
          enforce_visa_sponsorship: data.policy_enforce_visa_sponsorship ?? true,
          enforce_no_clearance: data.policy_enforce_no_clearance ?? true,
          custom_red_flag_keywords: data.policy_custom_red_flag_keywords || []
        });
      }
    } catch {
      showStatus('Failed to load policy config.', 'error');
    } finally {
      setPolicyLoading(false);
    }
  };

  const fetchSalaryInsights = async () => {
    if (jobs.length > 0) setSalaryInsights(computeSalaryInsights(jobs));
  };

  const fetchResume = async () => {
    setResumeLoading(true);
    try {
      const { data, error } = await supabase
        .from('user_configs')
        .select('base_resume')
        .maybeSingle();

      if (error) throw error;
      if (data) {
        setResume(data.base_resume || '');
      }
    } catch {
      showStatus('Failed to load base resume.', 'error');
    } finally {
      setResumeLoading(false);
    }
  };

  const saveResume = async () => {
    setResumeSaving(true);
    try {
      const { data: { user } } = await supabase.auth.getUser();
      if (!user) throw new Error('Not authenticated');

      const { error } = await supabase
        .from('user_configs')
        .upsert({
          user_id: user.id,
          base_resume: resume,
          updated_at: new Date().toISOString()
        });

      if (error) throw error;
      showStatus('Base resume saved successfully!', 'success');
    } catch {
      showStatus('Error saving resume.', 'error');
    } finally {
      setResumeSaving(false);
    }
  };

  const generateTailoring = async (jobUrl: string) => {
    setTailoringLoading(true);
    setTailoredCoverLetter('');
    setTailoredResumeBullets([]);
    setIsTailorModalOpen(true);
    try {
      const res = await fetch(`${API_BASE}/api/generate-tailoring`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ job_url: jobUrl }),
      });
      if (res.ok) {
        const data = await res.json();
        if (data.success) {
          setTailoredCoverLetter(data.cover_letter || '');
          setTailoredResumeBullets(data.resume_suggestions || []);
          showStatus('Tailored materials generated successfully!', 'success');
        } else {
          showStatus(data.message || 'Failed to generate tailored materials.', 'error');
          setIsTailorModalOpen(false);
        }
      } else {
        showStatus('Failed to generate tailored materials.', 'error');
        setIsTailorModalOpen(false);
      }
    } catch {
      showStatus('Error communicating with backend server.', 'error');
      setIsTailorModalOpen(false);
    } finally {
      setTailoringLoading(false);
    }
  };

  const updatePipelineStage = async (jobUrl: string, newStage: string) => {
    try {
      const { error } = await supabase
        .from('jobs')
        .update({ pipeline_stage: newStage })
        .eq('job_url', jobUrl);

      if (error) throw error;
      showStatus('Job pipeline stage updated successfully!', 'success');
      setJobs(prev => prev.map(j => j.job_url === jobUrl ? { ...j, pipeline_stage: newStage } : j));
    } catch {
      showStatus('Failed to update pipeline stage.', 'error');
    }
  };

  const toggleJobSelection = (jobUrl: string) => {
    setSelectedJobUrls(prev => {
      const next = new Set(prev);
      if (next.has(jobUrl)) next.delete(jobUrl);
      else next.add(jobUrl);
      return next;
    });
  };

  const selectAllVisible = (urls: string[]) => setSelectedJobUrls(new Set(urls));
  const clearSelection = () => setSelectedJobUrls(new Set());

  const bulkUpdatePipelineStage = async (newStage: string) => {
    const urls = Array.from(selectedJobUrls);
    if (urls.length === 0) return;
    setBulkActionBusy(true);
    try {
      const { error } = await supabase.from('jobs').update({ pipeline_stage: newStage }).in('job_url', urls);
      if (error) throw error;
      setJobs(prev => prev.map(j => urls.includes(j.job_url) ? { ...j, pipeline_stage: newStage } : j));
      showStatus(`Updated ${urls.length} job(s) to "${newStage}".`, 'success');
      clearSelection();
    } catch {
      showStatus('Bulk update failed.', 'error');
    } finally {
      setBulkActionBusy(false);
    }
  };

  const bulkReject = async () => {
    const urls = Array.from(selectedJobUrls);
    if (urls.length === 0) return;
    setBulkActionBusy(true);
    try {
      const { error } = await supabase
        .from('jobs')
        .update({ apply_decision: 'DO_NOT_APPLY', pipeline_stage: 'Rejected' })
        .in('job_url', urls);
      if (error) throw error;
      setJobs(prev => prev.map(j => urls.includes(j.job_url) ? { ...j, apply_decision: 'DO_NOT_APPLY', pipeline_stage: 'Rejected' } : j));
      showStatus(`Rejected ${urls.length} job(s).`, 'success');
      clearSelection();
    } catch {
      showStatus('Bulk reject failed.', 'error');
    } finally {
      setBulkActionBusy(false);
    }
  };

  // Poll scraper console logs when logs drawer is expanded
  useEffect(() => {
    let interval: NodeJS.Timeout | null = null;
    const fetchLogs = async () => {
      try {
        const res = await fetch(`${API_BASE}/api/logs`);
        if (res.ok) {
          const data = await res.json();
          setScraperLogs(data.logs || []);
        }
      } catch (err) {
        console.error('Error fetching logs:', err);
      }
    };

    if (isLogsExpanded && authToken) {
      fetchLogs();
      interval = setInterval(fetchLogs, 3000);
    }

    return () => {
      if (interval) clearInterval(interval);
    };
  }, [isLogsExpanded, authToken]);

  const savePolicyConfig = async (updatedPolicy: PolicyConfig) => {
    try {
      const { data: { user } } = await supabase.auth.getUser();
      if (!user) throw new Error('Not authenticated');

      const { error } = await supabase
        .from('user_configs')
        .upsert({
          user_id: user.id,
          policy_max_experience_years: updatedPolicy.max_experience_years,
          policy_min_salary_annual: updatedPolicy.min_salary_annual,
          policy_min_salary_hourly: updatedPolicy.min_salary_hourly,
          policy_enforce_visa_sponsorship: updatedPolicy.enforce_visa_sponsorship,
          policy_enforce_no_clearance: updatedPolicy.enforce_no_clearance,
          policy_custom_red_flag_keywords: updatedPolicy.custom_red_flag_keywords,
          updated_at: new Date().toISOString()
        });

      if (error) throw error;
      showStatus('Policy configuration saved successfully!', 'success');
      setPolicyConfig(updatedPolicy);
    } catch {
      showStatus('Failed to save policy configuration.', 'error');
    }
  };

  const fetchData = async () => {
    try {
      // Must paginate: Supabase/PostgREST silently caps unpaginated selects at 1000 rows.
      const [{ data: jobsData, error: jobsError }, { data: configData, error: configError }] = await Promise.all([
        fetchAllSupabaseJobs<Job>(supabase),
        supabase.from('user_configs').select('*').maybeSingle(),
      ]);

      let officialOnly = false;

      if (configError) {
        console.error('Error fetching config:', configError);
      } else if (configData) {
        const dbJoobleKey = configData.jooble_api_key || '';
        const fallbackJoobleKey =
          configData.target_companies && typeof configData.target_companies === 'object'
            ? (configData.target_companies as Record<string, unknown>).jooble_api_key || ''
            : '';
        const joobleKey = (dbJoobleKey || fallbackJoobleKey) as string;

        officialOnly = Boolean(configData.search_official_career_job_urls_only);

        const mappedConfig: Config = {
          target_titles: configData.target_titles || [],
          scheduler: {
            enabled: configData.scheduler_enabled ?? true,
            run_at_hour: configData.scheduler_run_at_hour ?? 8,
            run_at_minute: configData.scheduler_run_at_minute ?? 0,
          },
          webhook_url: configData.webhook_url || '',
          search: {
            country_phrase: configData.search_country_phrase || 'United States',
            include_remote_primary_boards: configData.search_include_remote_primary_boards ?? true,
            merge_previous_scrape: configData.search_merge_previous_scrape ?? true,
            send_digest_only: configData.search_send_digest_only ?? true,
            max_digest_items: configData.search_max_digest_items ?? 10,
            jooble_api_key: joobleKey,
            official_career_job_urls_only: officialOnly,
          },
        };
        setConfig(mappedConfig);
        setTitlesInput((configData.target_titles || []).join('\n'));
        setWebhookUrlInput(configData.webhook_url || '');
        setSchedulerHour(configData.scheduler_run_at_hour ?? 8);
        setSchedulerMinute(configData.scheduler_run_at_minute ?? 0);
        setSchedulerEnabled(configData.scheduler_enabled ?? true);
        setSendDigestOnly(configData.search_send_digest_only ?? true);
        setOfficialCareerUrlsOnly(officialOnly);
        setJoobleApiKeyInput(joobleKey);
      } else {
        setOfficialCareerUrlsOnly(false);
        const { data: sessionData } = await supabase.auth.getSession();
        if (sessionData?.session?.user) {
          const defaultTitles = [
            'DevOps Engineer',
            'Cloud Automation Engineer',
            'Platform Engineering',
            'Cloud Infrastructure Engineer',
            'DevSecOps',
            'Site Reliability Engineer (SRE)',
            'Continuous Integration (CI/CD)',
            'System Engineer',
          ];
          await supabase.from('user_configs').insert({
            user_id: sessionData.session.user.id,
            target_titles: defaultTitles,
          });
        }
      }

      if (jobsError) {
        console.error('Error fetching jobs:', jobsError);
      } else if (jobsData) {
        const deduped = dedupeJobsByCanonicalUrl(jobsData as Job[]);
        setJobs(filterJobsOfficialCareersOnly(deduped, officialOnly));
      }

      checkScraperStatus();
      checkStaleStatus();
    } catch {
      showStatus('Failed to communicate with Supabase database.', 'error');
    }
  };

  // Fetch new jobs count for tab badge
  const fetchNewJobs = async () => {
    try {
      const { data, error } = await supabase
        .from('jobs')
        .select('*')
        .gt('scraped_at', new Date(Date.now() - 15 * 60 * 1000).toISOString())
        .order('scraped_at', { ascending: false });

      if (error) throw error;
      if (data) {
        const d = filterJobsOfficialCareersOnly(
          dedupeJobsByCanonicalUrl(data as Job[]),
          officialCareerUrlsOnlyRef.current
        );
        setNewJobsCount(d.length);
      }
    } catch (e) {
      console.error('Failed to fetch new jobs count', e);
    }
  };

  // Watch scraper status to trigger fetch of new jobs after scrape completes
  useEffect(() => {
    if (scraperStatus.status === 'completed') {
      setTimeout(() => {
        fetchNewJobs();
        fetchData();
      }, 0);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scraperStatus.status]);

  // Synchronize dynamic URL changes with pushState
  const updateUrl = (tab: string, jobId: string | null) => {
    if (typeof window === 'undefined') return;
    const params = new URLSearchParams(window.location.search);
    params.set('tab', tab);
    if (jobId) {
      params.set('job', jobId);
    } else {
      params.delete('job');
    }
    const newUrl = `${window.location.pathname}?${params.toString()}`;
    if (window.location.search !== `?${params.toString()}`) {
      window.history.pushState({ tab, jobId }, '', newUrl);
    }
  };

  const closeModal = (skipHistoryPush = false) => {
    setIsModalOpen(false);
    setSelectedJob(null);
    if (!skipHistoryPush) {
      updateUrl(activeTab, null);
    }
  };

  // Global "/" focuses the search box (ignored while typing in any field);
  // Escape closes the job detail modal, or blurs the search box if it's
  // focused. Declared after closeModal/isModalOpen so both are already
  // initialized when this effect's dependency array is evaluated.
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      const isTyping = !!target && ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName);
      if (e.key === '/' && !isTyping) {
        e.preventDefault();
        searchInputRef.current?.focus();
      } else if (e.key === 'Escape') {
        if (isModalOpen) {
          closeModal();
        } else if (target && target === searchInputRef.current) {
          target.blur();
        }
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- closeModal is a plain function recreated each render with an equivalent closure; adding it would only churn the dep array, not change behavior.
  }, [isModalOpen]);

  // Focus the modal on open (keyboard/screen-reader users land inside it,
  // not stuck on whatever was focused on the page behind it).
  useEffect(() => {
    if (isModalOpen) {
      modalRef.current?.focus();
    }
  }, [isModalOpen]);

  // Trap Tab/Shift+Tab inside the modal while it's open - without this, a
  // keyboard user could Tab straight out into the backdrop/page content
  // behind it, which is hidden but still in the DOM.
  const handleModalKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    if (e.key !== 'Tab' || !modalRef.current) return;
    const focusable = modalRef.current.querySelectorAll<HTMLElement>(
      'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
    );
    if (focusable.length === 0) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault();
      first.focus();
    }
  };

  // Open inspection / override modal
  const openModal = (job: Job, skipHistoryPush = false) => {
    setSelectedJob(job);
    setEditTitle(job.job_title || '');
    setEditCompany(job.company_name || '');
    setEditReqId(job.requirement_id || '');
    setEditLocation(job.location_work_type || '');
    setEditDecision(job.apply_decision || 'APPLY');
    setEditLabel(job.strongest_label || 'DevOps Engineer');
    setEditScore(job.confidence_score || 85);
    setEditRationale(job.rationale || '');
    setEditDesc(job.job_description || '');
    setEditUrl(job.job_url || '');

    // Initialize history for undo/redo
    const initialDesc = job.job_description || '';
    setDescHistory([initialDesc]);
    setHistoryIndex(0);

    // Parse cloud from payload or custom property
    const jobCloud = job.cloud || job.apply_decision_payload?.cloud?.primary_cloud || 'Not specified';
    setEditCloud(jobCloud);

    // Parse seniority from custom property or fallback
    const jobSeniority = job.seniority || 'Not specified';
    setEditSeniority(jobSeniority);

    // Determine source
    let defaultSource = job.source;
    if (!defaultSource) {
      if (job.job_url?.includes('lever.co')) defaultSource = 'Lever';
      else if (job.job_url?.includes('greenhouse.io')) defaultSource = 'Greenhouse';
      else if (job.job_url?.includes('ashbyhq.com')) defaultSource = 'Ashby';
      else defaultSource = 'Yahoo Sourced';
    }
    setEditSource(defaultSource || 'Not specified');

    // Decision payload string representation
    const payloadObj = job.apply_decision_payload || {
      apply_decision: job.apply_decision || 'APPLY',
      strongest_label: job.strongest_label || 'DevOps Engineer',
      red_flags: job.red_flags || [],
      confidence_score: job.confidence_score || 85,
      rationale: job.rationale || ''
    };
    setEditPayload(JSON.stringify(payloadObj, null, 2));

    setIsPayloadExpanded(false);
    setIsModalOpen(true);

    if (!skipHistoryPush && typeof window !== 'undefined') {
      const params = new URLSearchParams(window.location.search);
      if (job.id) {
        params.set('job', job.id);
        const newUrl = `${window.location.pathname}?${params.toString()}`;
        if (window.location.search !== `?${params.toString()}`) {
          window.history.pushState({ tab: activeTab, jobId: job.id }, '', newUrl);
        }
      }
    }
  };

  // Tab change handler replacing side-effect useEffect
  const handleTabChange = (tab: TabId) => {
    if (authRole === 'user' && ['policy', 'resume', 'settings'].includes(tab)) {
      showStatus('Admin role required to access this tab.', 'error');
      if (typeof window !== 'undefined') {
        const params = new URLSearchParams(window.location.search);
        params.set('tab', activeTab);
        window.history.replaceState({ tab: activeTab, jobId: params.get('job') }, '', `${window.location.pathname}?${params.toString()}`);
      }
      return;
    }
    setActiveTab(tab);
    setSelectedRoleFilter('all');
    updateUrl(tab, null);
    if (tab === 'analytics') {
      fetchAnalytics();
      fetchSalaryInsights();
    } else if (tab === 'policy') {
      fetchPolicy();
    } else if (tab === 'resume') {
      fetchResume();
    }
  };

  // Poll scraper status when it is running
  useEffect(() => {
    let interval: NodeJS.Timeout;
    if (scraperStatus.status === 'running' && authToken) {
      interval = setInterval(() => {
        checkScraperStatus();
        // Periodically refresh jobs list too
        fetch(`${API_BASE}/api/jobs`)
          .then((res) => res.ok && res.json())
          .then((data: Job[] | undefined) => {
            if (!data) return;
            const deduped = dedupeJobsByCanonicalUrl(data);
            const incoming = filterJobsOfficialCareersOnly(deduped, officialCareerUrlsOnlyRef.current);
            const prev = jobsForPollRef.current;
            if (jobListPollUnchanged(prev, incoming)) return;
            if (prev.length > 0) {
              const oldIds = new Set(prev.map((j) => j.job_url));
              const newlyAdded = incoming.filter((j) => !oldIds.has(j.job_url)).length;
              setNewJobsCount(newlyAdded);
            }
            setJobs(incoming);
          })
          .catch(() => {
            // Silence
          });
      }, 2000);
    }
    return () => clearInterval(interval);
  }, [scraperStatus.status, authToken]);

  // Initial load. fetchData is async (fetch-then-setState), the standard "synchronize with
  // an external system" effect pattern react-hooks/set-state-in-effect's static analysis
  // can't see past the await on — same false-positive class as the redirect effect below.
  /* eslint-disable react-hooks/exhaustive-deps */
  useEffect(() => {
    if (!isAuthChecking && authToken) {
      fetchData(); // eslint-disable-line react-hooks/set-state-in-effect
    }
  }, [isAuthChecking, authToken]);
  /* eslint-enable react-hooks/exhaustive-deps */

  useEffect(() => {
    jobsForPollRef.current = jobs;
  }, [jobs]);

  // Redirect non-admins if they somehow end up on admin tabs
  useEffect(() => {
    if (authRole === 'user' && ['policy', 'resume', 'settings'].includes(activeTab)) {
      // Intentional guard redirect: forces a non-admin user off an admin-only tab whenever
      // authRole/activeTab change to that combination. There's no parent-owned event to hook
      // into here (tab/role are local state), so this effect-driven redirect is correct.
      handleTabChange('approved'); // eslint-disable-line react-hooks/set-state-in-effect
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- handleTabChange is stable for this component's lifetime (recreated each render but with equivalent closures); adding it would not change behavior, only churn the dep array.
  }, [authRole, activeTab]);

  // Synchronize browser history / URL parameters with React state
  useEffect(() => {
    if (typeof window === 'undefined') return;

    const syncStateFromUrl = () => {
      const params = new URLSearchParams(window.location.search);
      const tabParam = params.get('tab');
      const jobParam = params.get('job');

      // 1. Sync active tab
      const validTabs: TabId[] = ['approved', 'new_today', 'applications', 'pending', 'rejected', 'human_review', 'settings', 'analytics', 'policy', 'resume'];
      if (tabParam && validTabs.includes(tabParam as TabId)) {
        if (tabParam !== activeTab) {
          handleTabChange(tabParam as TabId);
        }
      } else if (!tabParam) {
        const newParams = new URLSearchParams(window.location.search);
        newParams.set('tab', activeTab);
        window.history.replaceState({ tab: activeTab, jobId: jobParam }, '', `${window.location.pathname}?${newParams.toString()}`);
      }

      // 2. Sync modal open/close state based on ?job=<id>
      if (jobParam) {
        const matchedJob = jobs.find(j => j.id === jobParam);
        if (matchedJob) {
          if (!isModalOpen || !selectedJob || selectedJob.id !== jobParam) {
            openModal(matchedJob, true);
          }
        }
      } else {
        if (isModalOpen) {
          closeModal(true);
        }
      }
    };

    syncStateFromUrl();

    const handlePopState = () => {
      syncStateFromUrl();
    };

    window.addEventListener('popstate', handlePopState);
    return () => {
      window.removeEventListener('popstate', handlePopState);
    };
    // closeModal/handleTabChange/openModal are plain function values recreated every render (not
    // memoized); adding them here would make this effect (which also attaches the popstate
    // listener) re-run on every render instead of only on the listed state changes, a real
    // behavior change this refactor must avoid.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobs, activeTab, isModalOpen, selectedJob, authRole]);

  // Start scraper
  const triggerScrape = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/scrape`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ past_24h_only: past24hOnly })
      });
      if (res.ok) {
        const data = await res.json();
        if (data.success) {
          showStatus('Scraper agent successfully launched in background!', 'success');
          setNewJobsCount(0);
          setScraperStatus((prev) => ({
            ...prev,
            status: 'running',
            message: 'Sourcing jobs...',
          }));
        } else {
          showStatus(data.message, 'error');
        }
      }
    } catch {
      showStatus('Failed to trigger scraper run.', 'error');
    }
  };

  // Start stale check
  const triggerStaleCheck = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/check-stale`, { method: 'POST' });
      if (res.ok) {
        const data = await res.json();
        if (data.success) {
          showStatus('Stale job check successfully launched in background!', 'success');
          setStaleCheckStatus((prev) => ({
            ...prev,
            status: 'running',
          }));
        } else {
          showStatus(data.message, 'error');
        }
      }
    } catch {
      showStatus('Failed to trigger stale check.', 'error');
    }
  };

  /** Per-job HTTP probe: updates ``stale`` when ``persist`` is true (default) on server + Supabase. */
  const checkJobPostingLive = async (job: Job) => {
    if (!job.job_url) {
      showStatus('This job has no URL to check.', 'error');
      return;
    }
    if (!authToken) {
      showStatus('Log in to check whether a posting is still live.', 'error');
      return;
    }
    setCheckingLiveJobUrl(job.job_url);
    try {
      const res = await fetch(`${API_BASE}/api/job/check-live`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          job_url: job.job_url,
          job_id: job.id || job.job_id,
          persist: true,
        }),
      });
      const data = (await res.json().catch(() => ({}))) as Record<string, unknown>;
      if (!res.ok || data.success === false) {
        showStatus((typeof data.message === 'string' && data.message) || 'Could not verify posting.', 'error');
        return;
      }
      const checkedAt = new Date().toISOString();
      const uncertain = Boolean(data.uncertain);
      const stale = Boolean(data.stale);
      setJobs((prev) =>
        prev.map((j) =>
          j.job_url === job.job_url
            ? {
                ...j,
                stale,
                listing_health: {
                  uncertain,
                  reason: typeof data.reason === 'string' ? data.reason : undefined,
                  checked_at: checkedAt,
                  http_status: (data.http_status as number | null | undefined) ?? null,
                },
              }
            : j
        )
      );
      setSelectedJob((prev) =>
        prev && prev.job_url === job.job_url
          ? {
              ...prev,
              stale,
              listing_health: {
                uncertain,
                reason: typeof data.reason === 'string' ? data.reason : undefined,
                checked_at: checkedAt,
                http_status: (data.http_status as number | null | undefined) ?? null,
              },
            }
          : prev
      );
      if (uncertain) {
        showStatus(
          (typeof data.reason === 'string' && data.reason) ||
            'Could not fully verify this listing (network timeout or gated page).',
          'info'
        );
      } else if (stale) {
        showStatus('Listing appears closed or removed.', 'success');
      } else {
        showStatus('Listing looks active (no closed signals detected).', 'success');
      }
      if (Array.isArray(data.persist_notes) && data.persist_notes.length > 0) {
        console.info('check-live persist notes:', data.persist_notes);
      }
    } catch {
      showStatus('Failed to reach server for live check.', 'error');
    } finally {
      setCheckingLiveJobUrl(null);
    }
  };

  // Poll stale check status when it is running
  useEffect(() => {
    let interval: NodeJS.Timeout;
    if (staleCheckStatus.status === 'running' && authToken) {
      interval = setInterval(() => {
        checkStaleStatus();
        // Periodically refresh jobs list directly from Supabase (paginated — default cap is 1000).
        void fetchAllSupabaseJobs<Job>(supabase).then(({ data }) => {
          if (!data) return;
          const deduped = dedupeJobsByCanonicalUrl(data);
          const incoming = filterJobsOfficialCareersOnly(deduped, officialCareerUrlsOnlyRef.current);
          setJobs((prev) => (jobListPollUnchanged(prev, incoming) ? prev : incoming));
        });
      }, 2000);
    }
    return () => clearInterval(interval);
  }, [staleCheckStatus.status, authToken]);

  // Supabase Realtime changes listener
  useEffect(() => {
    if (!authToken) return;

    const channel = supabase
      .channel('public:jobs')
      .on(
        'postgres_changes',
        { event: '*', schema: 'public', table: 'jobs' },
        (payload) => {
          if (payload.eventType === 'INSERT') {
            const newJob = payload.new as Job;
            if (officialCareerUrlsOnlyRef.current && !isOfficialCompanyCareersJobUrl(newJob.job_url || '')) {
              return;
            }
            setJobs((prev) => {
              if (prev.some((j) => j.job_url === newJob.job_url)) return prev;
              return [newJob, ...prev];
            });
            setNewJobsCount((c) => c + 1);
          } else if (payload.eventType === 'UPDATE') {
            const updatedJob = payload.new as Job;
            setJobs((prev) => {
              const merged = prev.map((j) => (j.job_url === updatedJob.job_url ? { ...j, ...updatedJob } : j));
              if (officialCareerUrlsOnlyRef.current && !isOfficialCompanyCareersJobUrl(updatedJob.job_url || '')) {
                return merged.filter((j) => j.job_url !== updatedJob.job_url);
              }
              return merged;
            });
          } else if (payload.eventType === 'DELETE') {
            const deletedJob = payload.old as { job_url?: string };
            setJobs(prev => prev.filter(j => j.job_url !== deletedJob.job_url));
          }
        }
      )
      .subscribe();

    return () => {
      supabase.removeChannel(channel);
    };
  }, [authToken]);

  // Delete / Archive Job
  const deleteJob = async (job_url: string) => {
    if (!confirm('Are you sure you want to archive this job posting? It will be hidden from the dashboard.')) return;
    try {
      const { error } = await supabase
        .from('jobs')
        .update({ archived: true })
        .eq('job_url', job_url);
        
      if (error) throw error;
      showStatus('Job archived successfully!', 'success');
      setJobs(prev => prev.map(j => j.job_url === job_url ? { ...j, archived: true } : j));
    } catch {
      showStatus('Failed to archive job.', 'error');
    }
  };

  const APPLICATION_STATUS_LABELS: Record<string, string> = {
    applied: '📨 Applied',
    phone_screen: '📞 Phone Screen',
    interview: '🎯 Interview',
    offer: '🎉 Offer',
    rejected: '❌ Rejected',
  };

  const updateApplicationStatus = async (job_url: string, status: string | null) => {
    try {
      const update: Record<string, string | null> = { application_status: status };
      if (status === 'applied') update.applied_at = new Date().toISOString();
      if (status === null) update.applied_at = null;
      const { error } = await supabase.from('jobs').update(update).eq('job_url', job_url);
      if (error) throw error;
      setJobs(prev => prev.map(j => j.job_url === job_url ? {
        ...j,
        application_status: status as Job['application_status'],
        applied_at: update.applied_at !== undefined ? update.applied_at : j.applied_at,
      } : j));
      showStatus(status ? `Status updated: ${APPLICATION_STATUS_LABELS[status]}` : 'Status cleared', 'success');
    } catch {
      showStatus('Failed to update application status.', 'error');
    }
  };

  // Save Settings Config
  const saveSettings = async () => {
    const updatedConfig: Config = {
      ...config,
      target_titles: titlesInput.split('\n').map(t => t.trim()).filter(t => t),
      scheduler: {
        enabled: schedulerEnabled,
        run_at_hour: Number(schedulerHour),
        run_at_minute: Number(schedulerMinute)
      },
      webhook_url: webhookUrlInput.trim(),
      search: {
        ...(config.search || {}),
        send_digest_only: sendDigestOnly,
        jooble_api_key: joobleApiKeyInput.trim(),
        official_career_job_urls_only: officialCareerUrlsOnly,
      },
    };

    try {
      const { data: { user } } = await supabase.auth.getUser();
      if (!user) throw new Error('Not authenticated');

      // 1. Try to upsert directly with jooble_api_key column
      const { error } = await supabase
        .from('user_configs')
        .upsert({
          user_id: user.id,
          target_titles: updatedConfig.target_titles,
          scheduler_enabled: updatedConfig.scheduler.enabled,
          scheduler_run_at_hour: updatedConfig.scheduler.run_at_hour,
          scheduler_run_at_minute: updatedConfig.scheduler.run_at_minute,
          webhook_url: updatedConfig.webhook_url,
          search_send_digest_only: updatedConfig.search?.send_digest_only,
          search_official_career_job_urls_only: updatedConfig.search?.official_career_job_urls_only,
          jooble_api_key: joobleApiKeyInput.trim(),
          updated_at: new Date().toISOString()
        });

      if (error) {
        // If the database complains about a missing column, fallback to storing it in target_companies JSONB
        if (error.message && (error.message.includes('column') || error.message.includes('does not exist'))) {
          console.warn("jooble_api_key column does not exist in user_configs. Falling back to target_companies JSONB.");
          
          // Fetch current target_companies to preserve them
          const { data: currentCfg } = await supabase
            .from('user_configs')
            .select('target_companies')
            .maybeSingle();
            
          const currentCompanies = (currentCfg && currentCfg.target_companies && typeof currentCfg.target_companies === 'object')
            ? currentCfg.target_companies
            : {};
            
          const companiesWithJooble = {
            ...currentCompanies,
            jooble_api_key: joobleApiKeyInput.trim()
          };

          const { error: fallbackError } = await supabase
            .from('user_configs')
            .upsert({
              user_id: user.id,
              target_titles: updatedConfig.target_titles,
              scheduler_enabled: updatedConfig.scheduler.enabled,
              scheduler_run_at_hour: updatedConfig.scheduler.run_at_hour,
              scheduler_run_at_minute: updatedConfig.scheduler.run_at_minute,
              webhook_url: updatedConfig.webhook_url,
              search_send_digest_only: updatedConfig.search?.send_digest_only,
              search_official_career_job_urls_only: updatedConfig.search?.official_career_job_urls_only,
              target_companies: companiesWithJooble,
              updated_at: new Date().toISOString()
            });

          if (fallbackError) throw fallbackError;
        } else {
          throw error;
        }
      }

      showStatus('Configuration settings saved successfully!', 'success');
      setConfig(updatedConfig);
      void fetchData();
    } catch {
      showStatus('Failed to save settings to database.', 'error');
    }
  };

  const resetTargetTitles = async () => {
    setResettingTitles(true);
    try {
      const res = await fetch(`${API_BASE}/api/config/default-target-titles`);
      if (!res.ok) throw new Error('defaults');
      const data = await res.json();
      const target_titles: string[] = data.target_titles || [];

      const { data: { user } } = await supabase.auth.getUser();
      if (user) {
        const { error } = await supabase.from('user_configs').upsert({
          user_id: user.id,
          target_titles,
          updated_at: new Date().toISOString()
        });
        if (error) throw error;
      }

      const { data: sess } = await supabase.auth.getSession();
      const bearer = authToken || sess?.session?.access_token;
      if (bearer) {
        await fetch(`${API_BASE}/api/config/reset-target-titles`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${bearer}`
          },
          body: '{}'
        });
      }

      setTitlesInput(target_titles.join('\n'));
      setConfig(prev => ({ ...prev, target_titles }));
      showStatus('Target titles restored to defaults.', 'success');
    } catch {
      showStatus('Could not restore default target titles.', 'error');
    } finally {
      setResettingTitles(false);
    }
  };

  const submitClassifierFeedback = async (job: Job) => {
    const note = window.prompt('Optional note for classifier feedback (sent to server log only)');
    if (note === null) return;
    try {
      const { data: sess } = await supabase.auth.getSession();
      const bearer = authToken || sess?.session?.access_token;
      const headers: Record<string, string> = { 'Content-Type': 'application/json' };
      if (bearer) headers.Authorization = `Bearer ${bearer}`;
      const p = job.apply_decision_payload;
      const res = await fetch(`${API_BASE}/api/classifier-feedback`, {
        method: 'POST',
        headers,
        body: JSON.stringify({
          job_url: job.job_url,
          job_title: job.job_title,
          note,
          recommendation: p && typeof p === 'object' && 'recommendation' in p ? (p as { recommendation?: string }).recommendation : undefined
        })
      });
      if (!res.ok) throw new Error('bad status');
      showStatus('Classifier feedback recorded.', 'success');
    } catch {
      showStatus('Failed to record classifier feedback.', 'error');
    }
  };

  // Test Discord Webhook
  const testWebhook = async () => {
    if (!webhookUrlInput.trim()) {
      showStatus('Please specify a Webhook URL first.', 'error');
      return;
    }
    setTestingWebhook(true);
    try {
      const res = await fetch(`${API_BASE}/api/test-webhook`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ webhook_url: webhookUrlInput.trim() })
      });
      if (res.ok) {
        const data = await res.json();
        if (data.success) {
          showStatus(data.message, 'success');
        } else {
          showStatus(data.message, 'error');
        }
      }
    } catch {
      showStatus('Failed to execute webhook test request.', 'error');
    } finally {
      setTestingWebhook(false);
    }
  };

  // Undo/Redo tracking for job description
  const updateDescWithHistory = (newVal: string) => {
    setEditDesc(newVal);
    const cleanHistory = descHistory.slice(0, historyIndex + 1);
    const updatedHistory = [...cleanHistory, newVal];
    if (updatedHistory.length > 50) {
      updatedHistory.shift();
    }
    setDescHistory(updatedHistory);
    setHistoryIndex(updatedHistory.length - 1);
  };

  const handleUndo = () => {
    if (historyIndex > 0) {
      const prevIdx = historyIndex - 1;
      setHistoryIndex(prevIdx);
      setEditDesc(descHistory[prevIdx]);
    }
  };

  const handleRedo = () => {
    if (historyIndex < descHistory.length - 1) {
      const nextIdx = historyIndex + 1;
      setHistoryIndex(nextIdx);
      setEditDesc(descHistory[nextIdx]);
    }
  };

  const handleToolbarClick = (action: string) => {
    const textarea = document.getElementById('job-desc-textarea') as HTMLTextAreaElement;
    if (!textarea) return;
    const start = textarea.selectionStart;
    const end = textarea.selectionEnd;
    const text = textarea.value;
    const selectedText = text.substring(start, end);

    let replacement = '';
    switch (action) {
      case 'bold':
        replacement = `**${selectedText || 'bold'}**`;
        break;
      case 'italic':
        replacement = `*${selectedText || 'italic'}*`;
        break;
      case 'underline':
        replacement = `<u>${selectedText || 'underlined'}</u>`;
        break;
      case 'bullet':
        replacement = `\n- ${selectedText || 'list item'}`;
        break;
      case 'number':
        replacement = `\n1. ${selectedText || 'list item'}`;
        break;
      case 'link':
        replacement = `[${selectedText || 'link text'}](https://)`;
        break;
      case 'clear':
        replacement = selectedText
          .replace(/\*\*|\*|__/g, '')
          .replace(/<u>|<\/u>/g, '')
          .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1');
        break;
      default:
        return;
    }

    const newValue = text.substring(0, start) + replacement + text.substring(end);
    updateDescWithHistory(newValue);

    setTimeout(() => {
      textarea.focus();
      textarea.setSelectionRange(start, start + replacement.length);
    }, 10);
  };

  // Quick "Approve Override" action from a job card (rejected/pending/human_review tabs)
  const approveOverride = (job: Job) => {
    setSelectedJob(job);
    setEditTitle(job.job_title);
    setEditCompany(job.company_name);
    setEditReqId(job.requirement_id);
    setEditLocation(job.location_work_type);
    setEditDecision('APPLY');
    setEditLabel(job.strongest_label === 'OutOfScope' ? 'DevOps Engineer' : job.strongest_label);
    setEditScore(85);
    setEditRationale('Manual override approved by user.');
    setEditDesc(job.job_description);
    // Open modal to review before override
    openModal({
      ...job,
      apply_decision: 'APPLY',
      strongest_label: job.strongest_label === 'OutOfScope' ? 'DevOps Engineer' : job.strongest_label,
      rationale: 'Manual override approved by user.'
    });
  };

  // Submit manual review override
  const submitOverride = async () => {
    if (!selectedJob) return;

    let parsedPayload = null;
    try {
      if (editPayload.trim()) {
        parsedPayload = JSON.parse(editPayload);
      }
    } catch {
      showStatus('Invalid Decision Payload JSON formatting. Please check the JSON syntax.', 'error');
      return;
    }

    const payload = {
      job_title: editTitle.trim(),
      company_name: editCompany.trim(),
      requirement_id: editReqId.trim(),
      location_work_type: editLocation.trim(),
      apply_decision: editDecision,
      strongest_label: editLabel,
      confidence_score: Number(editScore),
      rationale: editRationale.trim(),
      job_description: editDesc.trim(),
      red_flags: editDecision === 'APPLY' ? [] : (selectedJob.red_flags || ['Manual Disapproval']),

      // Extended fields
      cloud: editCloud,
      seniority: editSeniority,
      source: editSource,
      apply_decision_payload: parsedPayload,
      pipeline_stage: editDecision === 'APPLY' ? 'Approved' : 'Rejected'
    };

    try {
      const { error } = await supabase
        .from('jobs')
        .update(payload)
        .eq('job_url', editUrl.trim());

      if (error) throw error;
      showStatus('Manual classification override applied successfully!', 'success');
      closeModal();
      
      // Update local state directly
      setJobs(prev => prev.map(j => j.job_url === editUrl.trim() ? { ...j, ...payload } : j));
    } catch {
      showStatus('Failed to send classification override.', 'error');
    }
  };

  // Categorize jobs. Backend flags near-duplicates (near_dedup.group_and_flag_duplicates)
  // but never removes them from the response, so the UI must filter is_duplicate itself.
  // Memoized (previously plain consts re-filtered on every render) so these
  // are stable references across renders - both a real perf win on its own
  // (these run the full jobs[] array through .filter() on every keystroke/
  // state change otherwise) and required for filteredJobs' own useMemo
  // below to be valid: the React Compiler's lint rule
  // (react-hooks/preserve-manual-memoization) refuses to trust a manual
  // useMemo whose dependencies aren't themselves provably stable.
  const dedupedJobs = useMemo(
    () => jobs.filter(j => !j.is_duplicate && isUsLocation(j.location_work_type)),
    [jobs]
  );
  // Show ALL jobs — Gemini label is informational only, not a gate.
  // User runs their own LLM classifier to make final apply decisions.
  const approvedJobs = useMemo(
    () => dedupedJobs.filter(j => !j.archived),
    [dedupedJobs]
  );
  const [sessionStartMs] = useState(() => Date.now());
  const newTodayJobs = useMemo(() => {
    const oneDayAgo = sessionStartMs - 24 * 60 * 60 * 1000;
    return dedupedJobs.filter(j => !j.archived && j.scraped_at && new Date(j.scraped_at).getTime() >= oneDayAgo);
  }, [dedupedJobs, sessionStartMs]);
  const applicationJobs = useMemo(
    () => dedupedJobs.filter(j => !j.archived && j.application_status != null),
    [dedupedJobs]
  );
  const rejectedJobs = useMemo(
    () => dedupedJobs.filter(j => !j.archived && j.apply_decision === 'DO_NOT_APPLY'),
    [dedupedJobs]
  );
  const pendingJobs = useMemo(
    () => dedupedJobs.filter(j => !j.archived && j.apply_decision !== 'APPLY' && j.apply_decision !== 'DO_NOT_APPLY'),
    [dedupedJobs]
  );
  const humanReviewJobs = useMemo(
    () => dedupedJobs.filter(j => {
      if (j.archived) return false;
      const p = j.apply_decision_payload;
      const rec =
        p && typeof p === 'object' && 'recommendation' in p
          ? String((p as { recommendation?: string }).recommendation || '').toUpperCase()
          : '';
      return rec === 'HUMAN_REVIEW';
    }),
    [dedupedJobs]
  );



  // Memoized (was a plain function re-run on every render, including every
  // keystroke before the debounce above existed) - this filter/sort chain
  // touches the full job list for the active tab, so recomputing it only
  // when an actual input changes (not on every unrelated re-render) matters
  // once the list grows into the hundreds/thousands.
  const filteredJobs = useMemo(() => {
    let list =
      activeTab === 'approved'
        ? approvedJobs
        : activeTab === 'new_today'
          ? newTodayJobs
          : activeTab === 'applications'
            ? applicationJobs
            : activeTab === 'rejected'
              ? rejectedJobs
              : activeTab === 'human_review'
                ? humanReviewJobs
                : pendingJobs;

    // Filter out stale/closed jobs if showActiveOnly is enabled
    if (activeTab === 'approved' && showActiveOnly) {
      list = list.filter(j => !j.stale);
    }

    // Filter by source if selected
    if (selectedSourceFilter) {
      list = list.filter(j => getJobSource(j.job_url) === selectedSourceFilter);
    }

    // Filter approved jobs by role category if selected
    if (activeTab === 'approved' && selectedRoleFilter !== 'all') {
      list = list.filter(j => j.strongest_label === selectedRoleFilter);
    }

    // Saved preset: confidence band (High-fit = 90+, Needs review = 50-89)
    if (confidenceBandFilter === 'high') {
      list = list.filter(j => (j.confidence_score ?? 0) >= 90);
    } else if (confidenceBandFilter === 'borderline') {
      list = list.filter(j => (j.confidence_score ?? 0) >= 50 && (j.confidence_score ?? 0) < 90);
    }

    // Saved preset: Remote-first
    if (remoteOnlyFilter) {
      list = list.filter(j => (j.location_work_type || '').toLowerCase().includes('remote'));
    }

    if (debouncedSearchTerm.trim()) {
      const term = debouncedSearchTerm.toLowerCase();
      list = list.filter(j =>
        j.job_title.toLowerCase().includes(term) ||
        j.company_name.toLowerCase().includes(term) ||
        j.requirement_id.toLowerCase().includes(term)
      );
    }

    // Filter by scraped timeframe or posting timeframe
    if (scrapedTimeframe !== 'all') {
      const now = new Date().getTime();
      const oneDay = 24 * 60 * 60 * 1000;
      list = list.filter(j => {
        if (scrapedTimeframe === 'recent' || scrapedTimeframe === 'today' || scrapedTimeframe === 'week' || scrapedTimeframe === 'month') {
          if (!j.scraped_at) return false;
          const scrapedTime = new Date(j.scraped_at).getTime();
          const diff = now - scrapedTime;
          if (scrapedTimeframe === 'recent') return diff <= 4 * 60 * 60 * 1000;
          if (scrapedTimeframe === 'today') return diff <= oneDay;
          if (scrapedTimeframe === 'week') return diff <= 7 * oneDay;
          if (scrapedTimeframe === 'month') return diff <= 30 * oneDay;
        } else if (scrapedTimeframe === 'posted_today' || scrapedTimeframe === 'posted_week') {
          if (!j.posted_at) return false;
          const postedTime = new Date(j.posted_at).getTime();
          const diff = now - postedTime;
          if (scrapedTimeframe === 'posted_today') return diff <= oneDay;
          if (scrapedTimeframe === 'posted_week') return diff <= 7 * oneDay;
        }
        return true;
      });
    }

    // Sort by scraped_at if available
    return [...list].sort((a, b) => {
      const dateA = a.scraped_at ? new Date(a.scraped_at).getTime() : 0;
      const dateB = b.scraped_at ? new Date(b.scraped_at).getTime() : 0;
      if (sortBy === 'newest') {
        return dateB - dateA;
      } else {
        return dateA - dateB;
      }
    });
  }, [
    activeTab, approvedJobs, newTodayJobs, applicationJobs, rejectedJobs, humanReviewJobs, pendingJobs,
    showActiveOnly, selectedSourceFilter, selectedRoleFilter,
    confidenceBandFilter, remoteOnlyFilter, debouncedSearchTerm,
    scrapedTimeframe, sortBy,
  ]);

  const formatScrapedDate = (dateStr: string) => {
    try {
      const date = new Date(dateStr);
      return date.toLocaleDateString(undefined, {
        month: 'short',
        day: 'numeric',
        hour: 'numeric',
        minute: '2-digit'
      });
    } catch {
      return dateStr;
    }
  };

  const getRelativeScrapedTime = (dateStr?: string) => {
    if (!dateStr) return null;
    try {
      const now = new Date().getTime();
      const scraped = new Date(dateStr).getTime();
      const diffMs = now - scraped;
      const diffMins = Math.floor(diffMs / (60 * 1000));
      const diffHours = Math.floor(diffMs / (60 * 60 * 1000));
      
      if (diffMins < 60) {
        return { text: `${diffMins}m ago`, isRecent: true };
      } else if (diffHours < 24) {
        return { text: `${diffHours}h ago`, isRecent: diffHours < 4 };
      } else {
        const days = Math.floor(diffHours / 24);
        return { text: `${days}d ago`, isRecent: false };
      }
    } catch {
      return null;
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
    if (!isAuthChecking) router.replace('/login');
    return null;
  }


  return (
    <div className="flex h-screen bg-slate-950 text-slate-100 font-sans selection:bg-violet-600/30 overflow-hidden">
      <AppNav
        authRole={authRole}
        authEmail={authEmail}
        activeTab={activeTab}
        onTabChange={(tab) => handleTabChange(tab as TabId)}
        onLogout={handleLogout}
        webhookActive={!!(config.webhook_url || config.webhook_source === 'environment')}
        webhookSource={config.webhook_source}
        scraperRunning={scraperStatus.status === 'running'}
        onScrape={triggerScrape}
      />
      <div className="flex-1 flex flex-col min-w-0 overflow-hidden">

      {/* Floating Status Message */}
      {statusMessage && (
        <div className={`fixed bottom-6 right-6 z-50 flex items-center space-x-2 px-4 py-3 rounded-xl border shadow-xl animate-in fade-in duration-300 ${statusMessage.type === 'success'
            ? 'bg-emerald-950/90 text-emerald-300 border-emerald-800/80 shadow-emerald-900/20'
            : statusMessage.type === 'error'
              ? 'bg-rose-950/90 text-rose-300 border-rose-800/80 shadow-rose-900/20'
              : 'bg-indigo-950/90 text-indigo-300 border-indigo-800/80 shadow-indigo-900/20'
          }`}>
          {statusMessage.type === 'success' ? <CheckCircle2 className="w-5 h-5" /> : <AlertTriangle className="w-5 h-5" />}
          <span className="text-sm font-medium">{statusMessage.text}</span>
        </div>
      )}

      {/* Main Layout Grid */}
      <main className="flex-1 overflow-y-auto w-full p-6 space-y-6 flex flex-col">

        {/* Bold, standalone search - the first thing in the content area so
            it's unmissable, not just another field inside the filter
            toolbar. "/" focuses it from anywhere (ignored while typing). */}
        {activeTab !== 'settings' && (
          <div className="rounded-2xl border-2 border-violet-700/60 bg-gradient-to-r from-violet-950/30 via-slate-900/60 to-slate-900/30 p-4 shadow-lg shadow-violet-950/30">
            <label htmlFor="job-search-input" className="flex items-center gap-2 text-xs font-bold text-violet-300 uppercase tracking-wider mb-2">
              <Search className="w-4 h-4" />
              Search Jobs
            </label>
            <div className="relative">
              <span className="absolute inset-y-0 left-0 pl-4 flex items-center pointer-events-none text-violet-400">
                <Search className="w-5 h-5" />
              </span>
              <input
                id="job-search-input"
                ref={searchInputRef}
                type="text"
                placeholder="Search by job title, company, or requirement id..."
                aria-label="Search jobs by title, company, or requirement ID"
                value={searchTerm}
                onChange={e => setSearchTerm(e.target.value)}
                className="w-full bg-slate-950 border-2 border-violet-800/50 rounded-xl pl-12 pr-20 py-3.5 text-base text-white placeholder-slate-500 focus:outline-none focus:border-violet-500 focus:ring-2 focus:ring-violet-500/30 transition-all shadow-inner"
              />
              <span className="absolute inset-y-0 right-4 flex items-center pointer-events-none text-slate-400">
                <span className="text-xs font-bold border border-slate-600 rounded-md px-2 py-1 bg-slate-800/80">/</span>
              </span>
            </div>
          </div>
        )}

        <div className="rounded-2xl border border-violet-800/40 bg-gradient-to-r from-violet-950/40 to-slate-900/40 px-4 py-3 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
          <p className="text-sm text-slate-200">
            <span className="font-semibold text-violet-200">Company scraper</span>
            <span className="text-slate-500"> — </span>
            <span className="text-slate-400">Watch employer career pages on a schedule, or run a one-off ATS scrape (admin).</span>
          </p>
          <Link
            href="/company-scraper"
            className="inline-flex shrink-0 items-center justify-center gap-1.5 self-start sm:self-auto px-4 py-2 rounded-xl text-xs font-bold bg-violet-600 hover:bg-violet-500 text-white border border-violet-500/30 transition-colors"
          >
            Open company scraper
            <ChevronRight className="w-4 h-4" />
          </Link>
        </div>

        {scraperStatus.status === 'failed' && scraperStatus.last_error && (
          <div className="bg-rose-500/10 border border-rose-500/30 p-4 rounded-2xl text-rose-200 text-xs font-mono overflow-y-auto max-h-40">
            <p className="font-semibold text-rose-300 mb-1">Last pipeline error</p>
            {scraperStatus.last_error}
          </div>
        )}

        {/* new-jobs flash card removed — count surfaced as tab badge instead */}

        {scraperStatus.last_metrics && Object.keys(scraperStatus.last_metrics || {}).length > 0 && scraperStatus.status !== 'running' && (
          <div className="bg-slate-900/20 backdrop-blur-md border border-slate-800/80 p-5 rounded-2xl shadow-xl flex flex-col md:flex-row md:items-center justify-between gap-4">
            <div className="space-y-1">
              <div className="flex items-center space-x-2">
                <span className="w-2.5 h-2.5 rounded-full bg-emerald-500 animate-pulse"></span>
                <h4 className="text-sm font-bold text-slate-200">Sourcing Agent Last Run Results <span className="text-slate-500 font-normal">(This Run Only)</span></h4>
              </div>
              <p className="text-xs text-slate-400">
                {scraperStatus.last_run ? `Completed: ${new Date(scraperStatus.last_run).toLocaleString(undefined, {
                  month: 'short',
                  day: 'numeric',
                  hour: 'numeric',
                  minute: '2-digit'
                })} (${getRelativeScrapedTime(scraperStatus.last_run)?.text || 'just now'})` : 'Last run details updated.'}
              </p>
            </div>
            
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 flex-1 md:flex-none max-w-xl w-full">
              <div className="bg-slate-950/60 border border-slate-900/60 p-3 rounded-xl text-center shadow-inner">
                <span className="text-[10px] font-bold text-slate-500 uppercase tracking-wider block">Scraped Jobs</span>
                <span className="text-lg font-bold text-violet-400 mt-1 block">{scraperStatus.last_metrics.scraped_jobs_count ?? 0}</span>
              </div>
              <div className="bg-slate-950/60 border border-slate-900/60 p-3 rounded-xl text-center shadow-inner">
                <span className="text-[10px] font-bold text-slate-500 uppercase tracking-wider block">Approved Match</span>
                <span className="text-lg font-bold text-emerald-400 mt-1 block">{scraperStatus.last_metrics.approved_jobs_count ?? 0}</span>
              </div>
              <div className="bg-slate-950/60 border border-slate-900/60 p-3 rounded-xl text-center shadow-inner">
                <span className="text-[10px] font-bold text-slate-500 uppercase tracking-wider block">Unreviewed</span>
                <span className="text-lg font-bold text-amber-400 mt-1 block">{scraperStatus.last_metrics.active_candidates_count ?? 0}</span>
              </div>
              <div className="bg-slate-950/60 border border-slate-900/60 p-3 rounded-xl text-center shadow-inner">
                <span className="text-[10px] font-bold text-slate-500 uppercase tracking-wider block">Rejected</span>
                <span className="text-lg font-bold text-rose-400 mt-1 block">{scraperStatus.last_metrics.failed_candidates_count ?? 0}</span>
              </div>
            </div>
          </div>
        )}

        {/* Live Scraper Log Banner */}
        {scraperStatus.status === 'running' && (
          <div className="bg-gradient-to-r from-amber-500/10 via-amber-600/10 to-transparent border border-amber-500/20 p-4 rounded-2xl flex items-center space-x-3 shadow-sm animate-pulse">
            <RefreshCw className="w-5 h-5 text-amber-400 animate-spin" />
            <div className="flex-1">
              <h4 className="text-sm font-semibold text-amber-300">Background Job Agent Active</h4>
              <p className="text-xs text-amber-400">{scraperStatus.message}</p>
            </div>
          </div>
        )}

        {/* Dashboard Stat Counters */}
        <section className="grid grid-cols-1 md:grid-cols-2 gap-6">

          <div className="bg-slate-900/40 backdrop-blur-md border border-slate-800/85 p-6 rounded-2xl flex items-center justify-between shadow-xl">
            <div>
              <p className="text-sm text-slate-400 font-medium">Approved Jobs <span className="text-slate-600 font-normal">(All-Time)</span></p>
              <h3 className="text-3xl font-extrabold text-white mt-1">{approvedJobs.length}</h3>
              <p className="text-xs text-emerald-400 mt-1 flex items-center">
                <CheckCircle2 className="w-3.5 h-3.5 mr-1" /> Total stored, match policy guidelines
              </p>
            </div>
            <div className="p-3 bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 rounded-2xl">
              <CheckCircle2 className="w-6 h-6" />
            </div>
          </div>

          <div className="bg-slate-900/40 backdrop-blur-md border border-slate-800/85 p-6 rounded-2xl flex items-center justify-between shadow-xl">
            <div>
              <p className="text-sm text-slate-400 font-medium">Rejected <span className="text-slate-600 font-normal">(All-Time)</span></p>
              <h3 className="text-3xl font-extrabold text-white mt-1">{rejectedJobs.length}</h3>
              <p className="text-xs text-rose-400 mt-1 flex items-center">
                <XCircle className="w-3.5 h-3.5 mr-1" /> Total stored, failed policy filters
              </p>
            </div>
            <div className="p-3 bg-rose-500/10 text-rose-400 border border-rose-500/20 rounded-2xl">
              <XCircle className="w-6 h-6" />
            </div>
          </div>

        </section>

        {/* Toolbar & Filter Tabs */}
        <HomeJobsToolbar
          activeTab={activeTab}
          authRole={authRole}
          approvedJobs={approvedJobs}
          newTodayJobs={newTodayJobs}
          applicationJobs={applicationJobs}
          humanReviewJobs={humanReviewJobs}
          rejectedJobs={rejectedJobs}
          newJobsCount={newJobsCount}
          searchTerm={searchTerm}
          selectedRoleFilter={selectedRoleFilter}
          sortBy={sortBy}
          scrapedTimeframe={scrapedTimeframe}
          showActiveOnly={showActiveOnly}
          remoteOnlyFilter={remoteOnlyFilter}
          confidenceBandFilter={confidenceBandFilter}
          activeFilterPreset={activeFilterPreset}
          onTabChange={handleTabChange}
          onSearchChange={setSearchTerm}
          onRoleFilterChange={setSelectedRoleFilter}
          onSortChange={setSortBy}
          onTimeframeChange={setScrapedTimeframe}
          onShowActiveOnlyToggle={() => setShowActiveOnly(prev => !prev)}
          onRemoteOnlyChange={setRemoteOnlyFilter}
          onConfidenceBandChange={setConfidenceBandFilter}
          onPresetToggle={v => setActiveFilterPreset(v || null)}
        />

        {/* Tab Content Panels */}
        <section className="flex-1 flex flex-col">          {activeTab === 'analytics' ? (
            <AnalyticsPanel
              analyticsLoading={analyticsLoading}
              analyticsData={analyticsData}
              salaryInsightsLoading={salaryInsightsLoading}
              salaryInsights={salaryInsights}
              approvedJobs={approvedJobs}
              dedupedJobs={dedupedJobs}
              onSourceClick={(src) => { setActiveTab('approved'); setSearchTerm(src); }}
            />
          ) : activeTab === 'applications' ? (
            <div className="flex-1 p-4 overflow-auto">
              <h2 className="text-lg font-bold text-white mb-4">📋 My Applications</h2>
              <ApplicationsKanban
                applicationJobs={applicationJobs}
                onUpdateStatus={updateApplicationStatus}
              />
            </div>
          ) : activeTab === 'policy' ? (
            <PolicyPanel
              policyLoading={policyLoading}
              policyConfig={policyConfig}
              setPolicyConfig={setPolicyConfig}
              savePolicyConfig={savePolicyConfig}
            />
          ) : activeTab === 'settings' ? (
            <SettingsPanel
              webhookUrlInput={webhookUrlInput}
              setWebhookUrlInput={setWebhookUrlInput}
              testWebhook={testWebhook}
              testingWebhook={testingWebhook}
              sendDigestOnly={sendDigestOnly}
              setSendDigestOnly={setSendDigestOnly}
              officialCareerUrlsOnly={officialCareerUrlsOnly}
              setOfficialCareerUrlsOnly={setOfficialCareerUrlsOnly}
              titlesInput={titlesInput}
              setTitlesInput={setTitlesInput}
              schedulerEnabled={schedulerEnabled}
              setSchedulerEnabled={setSchedulerEnabled}
              schedulerHour={schedulerHour}
              setSchedulerHour={setSchedulerHour}
              schedulerMinute={schedulerMinute}
              setSchedulerMinute={setSchedulerMinute}
              saveSettings={saveSettings}
              onResetTargetTitles={resetTargetTitles}
              resettingTitles={resettingTitles}
              joobleApiKeyInput={joobleApiKeyInput}
              setJoobleApiKeyInput={setJoobleApiKeyInput}
            />
          ) : activeTab === 'resume' ? (
            <div className="bg-slate-900/20 backdrop-blur-md border border-slate-850 p-6 rounded-2xl space-y-6 max-w-4xl shadow-xl flex flex-col h-[70vh]">
              <div className="flex items-center justify-between pb-4 border-b border-slate-800">
                <div className="flex items-center space-x-2">
                  <FileText className="w-5 h-5 text-violet-400" />
                  <h2 className="text-lg font-bold text-white">Master Resume (Markdown)</h2>
                </div>
                <button
                  type="button"
                  onClick={saveResume}
                  disabled={resumeSaving}
                  className="inline-flex items-center px-4 py-2 bg-gradient-to-r from-violet-600 to-indigo-600 hover:from-violet-500 hover:to-indigo-500 text-white rounded-xl text-xs font-semibold shadow-md active:scale-95 transition-all disabled:opacity-50"
                >
                  <Check className="w-3.5 h-3.5 mr-1.5" />
                  {resumeSaving ? 'Saving...' : 'Save Resume'}
                </button>
              </div>

              {resumeLoading ? (
                <div className="flex-1 flex flex-col items-center justify-center space-y-3">
                  <RefreshCw className="w-8 h-8 text-violet-500 animate-spin" />
                  <p className="text-sm text-slate-400">Loading master resume...</p>
                </div>
              ) : (
                <div className="flex-1 flex flex-col space-y-2">
                  <p className="text-xs text-slate-400">
                    This Markdown document is your base resume. The AI Tailor uses this document to align your bullets and experience with approved job descriptions.
                  </p>
                  <textarea
                    value={resume}
                    onChange={e => setResume(e.target.value)}
                    className="flex-1 bg-slate-950 border border-slate-800 rounded-xl p-4 text-sm font-mono text-slate-200 focus:outline-none focus:border-violet-600/70 shadow-inner resize-none h-[400px]"
                    placeholder="# Master Resume..."
                  />
                </div>
              )}
            </div>
          ) : (

            /* Jobs List Cards Grid */
            <div className="flex-1 flex flex-col space-y-4">
              
              {/* View toggle (List vs Kanban) */}
              <div className="flex items-center justify-between border-b border-slate-900 pb-3">
                <div className="flex items-center space-x-2">
                  <Sliders className="w-4 h-4 text-violet-400" />
                  <h2 className="text-sm font-bold text-white uppercase tracking-wider">
                    {activeTab === 'approved'
                      ? 'Approved Postings'
                      : activeTab === 'rejected'
                        ? 'Rejected Postings'
                        : 'Classifier: human review'}
                  </h2>
                </div>
                <div className="flex bg-slate-950 p-1 rounded-xl border border-slate-900">
                  <button
                    type="button"
                    onClick={() => setIsKanbanView(false)}
                    className={`px-3 py-1 rounded-lg text-xs font-semibold transition-all ${!isKanbanView ? 'bg-slate-800 text-white shadow-sm' : 'text-slate-400 hover:text-slate-200'}`}
                  >
                    List View
                  </button>
                  <button
                    type="button"
                    onClick={() => setIsKanbanView(true)}
                    className={`px-3 py-1 rounded-lg text-xs font-semibold transition-all ${isKanbanView ? 'bg-slate-800 text-white shadow-sm' : 'text-slate-400 hover:text-slate-200'}`}
                  >
                    Kanban Board
                  </button>
                </div>
              </div>

              {selectedSourceFilter && (
                <div className="flex items-center space-x-2 bg-slate-900/60 border border-slate-800/80 rounded-xl px-3 py-1.5 w-fit">
                  <span className="text-xs text-slate-400">Active Filter:</span>
                  <span className="text-xs font-semibold text-violet-400">{selectedSourceFilter}</span>
                  <button
                    onClick={() => setSelectedSourceFilter(null)}
                    className="p-0.5 hover:bg-slate-800 rounded-md text-slate-400 hover:text-white transition-colors"
                    title="Clear filter"
                  >
                    <XCircle className="w-3.5 h-3.5" />
                  </button>
                </div>
              )}

              {filteredJobs.length === 0 ? (
                <div className="flex-1 flex flex-col items-center justify-center border border-dashed border-slate-800 rounded-2xl p-12 text-center bg-slate-900/10">
                  <Briefcase className="w-12 h-12 text-slate-600 mb-3" />
                  <h3 className="text-sm font-bold text-slate-400">No Job Postings Found</h3>
                  <p className="text-xs text-slate-500 max-w-sm mt-1">
                    {searchTerm ? 'No results matched your search term.' : 'Try running the sourcing agent to scrape jobs or override filter settings.'}
                  </p>
                </div>
              ) : isKanbanView && activeTab !== 'human_review' ? (
                /* Kanban Board Columns */
                <div className="flex space-x-4 overflow-x-auto pb-4 custom-scrollbar items-start select-none">
                  {['Approved', 'Applied', 'Phone Screen', 'Technical Interview', 'Offer', 'Rejected'].map(stage => {
                    const stageJobs = filteredJobs.filter(j => (j.pipeline_stage || 'Approved') === stage || (stage === 'Rejected' && (j.pipeline_stage === 'Rejected' || j.pipeline_stage === 'Closed')));
                    return (
                      <div key={stage} className="bg-slate-900/25 border border-slate-800/50 rounded-2xl p-4 w-72 shrink-0 flex flex-col max-h-[70vh] backdrop-blur-sm">
                        <div className="flex items-center justify-between pb-3 border-b border-slate-800/80 mb-3">
                          <span className="text-xs font-bold text-white uppercase tracking-wider">{stage}</span>
                          <span className="text-xs font-semibold bg-slate-950 px-2 py-0.5 rounded-full text-slate-400 border border-slate-800">{stageJobs.length}</span>
                        </div>
                        <div className="space-y-3 overflow-y-auto flex-1 custom-scrollbar pr-1 min-h-[300px]">
                          {stageJobs.map((job, idx) => (
                            <div 
                              key={job.job_url + idx}
                              className="bg-slate-950/80 border border-slate-900 hover:border-violet-500/50 rounded-xl p-3.5 space-y-3 transition-colors hover:shadow-lg shadow-black/25 group cursor-pointer"
                              onClick={() => openModal(job)}
                            >
                              <div className="flex justify-between items-start">
                                <span className="text-[10px] font-bold text-violet-400 tracking-wider truncate max-w-[150px]">{job.company_name}</span>
                                {(() => {
                                  const rel = getRelativeScrapedTime(job.scraped_at);
                                  if (!rel) return null;
                                  return (
                                    <span 
                                      className={`inline-flex items-center px-1.5 py-0.5 rounded text-[8px] font-bold uppercase tracking-wider shrink-0 transition-all ${
                                        rel.isRecent 
                                          ? 'bg-emerald-950/60 text-emerald-400 border border-emerald-900/40' 
                                          : 'bg-slate-900/60 text-slate-500'
                                      }`}
                                      title={`Posted: ${job.posted_at ? formatScrapedDate(job.posted_at) : 'N/A'}\nScraped: ${formatScrapedDate(job.scraped_at || '')}`}
                                    >
                                      {rel.text}
                                    </span>
                                  );
                                })()}
                              </div>
                              <h4 className="text-xs font-bold text-slate-200 line-clamp-2 leading-snug group-hover:text-white transition-colors">{job.job_title}</h4>
                              
                              {/* Salary Badge */}
                              {job.salary_text && (
                                <span className="inline-block text-[9px] font-semibold text-emerald-400 bg-emerald-950/40 px-2 py-0.5 rounded border border-emerald-900/30">
                                  {job.salary_text}
                                </span>
                              )}
                              
                              <div className="flex items-center justify-between pt-2 border-t border-slate-900/60">
                                {authRole === 'admin' ? (
                                  <select
                                    value={job.pipeline_stage || 'Approved'}
                                    onClick={e => e.stopPropagation()}
                                    onChange={e => updatePipelineStage(job.job_url, e.target.value)}
                                    className="bg-slate-900 border border-slate-800 rounded-lg px-2 py-1 text-[9px] text-slate-300 focus:outline-none cursor-pointer"
                                  >
                                    {['Approved', 'Applied', 'Phone Screen', 'Technical Interview', 'Offer', 'Rejected'].map(s => (
                                      <option key={s} value={s}>{s}</option>
                                    ))}
                                  </select>
                                ) : (
                                  <span className="inline-flex items-center text-[9px] font-semibold text-violet-400 bg-violet-950/40 px-2 py-0.5 rounded border border-violet-900/30">
                                    {job.pipeline_stage || 'Approved'}
                                  </span>
                                )}
                                <span className="text-[9px] text-slate-500">{getJobSource(job.job_url)}</span>
                              </div>
                            </div>
                          ))}
                          {stageJobs.length === 0 && (
                            <div className="flex flex-col items-center justify-center py-12 text-center text-slate-600 border border-dashed border-slate-900/40 rounded-xl">
                              <span className="text-[10px] font-semibold">Column Empty</span>
                            </div>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
              ) : (
                <>
                  {activeTab === 'approved' && authRole === 'admin' && (
                    <div className="flex items-center justify-between gap-3 mb-4 flex-wrap">
                      <div className="flex items-center gap-2">
                        <button
                          type="button"
                          onClick={() => selectedJobUrls.size > 0 ? clearSelection() : selectAllVisible(filteredJobs.map(j => j.job_url))}
                          className="px-3 py-1.5 rounded-lg text-xs font-semibold border border-slate-700 bg-slate-900/60 text-slate-300 hover:border-violet-600/50 hover:text-violet-300 transition-colors"
                        >
                          {selectedJobUrls.size > 0 ? `Clear (${selectedJobUrls.size})` : `Select all ${filteredJobs.length} visible`}
                        </button>
                      </div>
                      {selectedJobUrls.size > 0 && (
                        <div className="flex items-center gap-2 flex-wrap">
                          <span className="text-xs text-slate-400">{selectedJobUrls.size} selected</span>
                          <button
                            type="button"
                            disabled={bulkActionBusy}
                            onClick={() => bulkUpdatePipelineStage('Applied')}
                            className="px-3 py-1.5 rounded-lg text-xs font-bold bg-emerald-600/90 hover:bg-emerald-500 text-white disabled:opacity-50 transition-colors"
                          >
                            Mark Applied
                          </button>
                          <button
                            type="button"
                            disabled={bulkActionBusy}
                            onClick={bulkReject}
                            className="px-3 py-1.5 rounded-lg text-xs font-bold bg-rose-600/90 hover:bg-rose-500 text-white disabled:opacity-50 transition-colors"
                          >
                            Reject Selected
                          </button>
                        </div>
                      )}
                    </div>
                  )}
                  <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                    {filteredJobs.map((job, idx) => (
                      <div key={job.job_url + idx} className="relative">
                        {activeTab === 'approved' && authRole === 'admin' && (
                          <button
                            type="button"
                            onClick={() => toggleJobSelection(job.job_url)}
                            className={`absolute top-3 left-3 z-10 w-5 h-5 rounded-md border-2 flex items-center justify-center transition-colors ${
                              selectedJobUrls.has(job.job_url)
                                ? 'bg-violet-600 border-violet-500'
                                : 'bg-slate-950/80 border-slate-700 hover:border-violet-500'
                            }`}
                            aria-label="Select job"
                          >
                            {selectedJobUrls.has(job.job_url) && <Check className="w-3 h-3 text-white" />}
                          </button>
                        )}
                        <JobCard
                          job={job}
                          activeTab={activeTab}
                          authRole={authRole}
                          authToken={authToken}
                          checkingLiveJobUrl={checkingLiveJobUrl}
                          browserOpenJobUrl={browserOpenJobUrl}
                          getRelativeScrapedTime={getRelativeScrapedTime}
                          formatScrapedDate={formatScrapedDate}
                          onCheckLive={checkJobPostingLive}
                          onGenerateTailoring={generateTailoring}
                          onUpdatePipelineStage={updatePipelineStage}
                          onSubmitClassifierFeedback={submitClassifierFeedback}
                          onOpenModal={openModal}
                          onApproveOverride={approveOverride}
                          onDeleteJob={deleteJob}
                          onUpdateApplicationStatus={updateApplicationStatus}
                        />
                      </div>
                    ))}
                  </div>
                </>
              )}
            </div>
          )}
        </section>

        <LogConsole
          isLogsExpanded={isLogsExpanded}
          setIsLogsExpanded={setIsLogsExpanded}
          scraperStatus={scraperStatus}
          scraperLogs={scraperLogs}
        />

      </main>

      {/* Footer */}
      <footer className="mt-12 bg-slate-950 border-t border-slate-800/80 px-6 py-4 flex flex-col sm:flex-row items-center justify-between text-xs text-slate-500 gap-2">
        <p>© 2026 MAAS Job Sourcing Agent Dashboard. Powered by Next.js & TailwindCSS.</p>
        <p>Current Workspace: /Users/aravind/Documents/Gemini-jobsearch</p>
      </footer>

      {/* Inspect & Override Modal */}
      <JobDetailModal
        isOpen={isModalOpen}
        selectedJob={selectedJob}
        authRole={authRole}
        checkingLiveJobUrl={checkingLiveJobUrl}
        modalRef={modalRef}
        edit={{
          title: editTitle,
          company: editCompany,
          reqId: editReqId,
          location: editLocation,
          decision: editDecision,
          label: editLabel,
          score: editScore,
          rationale: editRationale,
          desc: editDesc,
          cloud: editCloud,
          seniority: editSeniority,
          source: editSource,
          url: editUrl,
          payload: editPayload,
          isPayloadExpanded,
          descHistory,
          historyIndex,
        }}
        handlers={{
          setTitle: setEditTitle,
          setCompany: setEditCompany,
          setReqId: setEditReqId,
          setLocation: setEditLocation,
          setDecision: setEditDecision,
          setLabel: setEditLabel,
          setScore: setEditScore,
          setRationale: setEditRationale,
          setDesc: setEditDesc,
          setCloud: setEditCloud,
          setSeniority: setEditSeniority,
          setSource: setEditSource,
          setUrl: setEditUrl,
          setPayload: setEditPayload,
          setIsPayloadExpanded,
          updateDescWithHistory,
          handleUndo,
          handleRedo,
          handleToolbarClick,
          closeModal,
          submitOverride,
          checkJobPostingLive,
          generateTailoring,
          handleModalKeyDown,
        }}
      />


      {/* AI Tailoring Drawer/Modal */}
      {isTailorModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/70 backdrop-blur-sm p-4 overflow-y-auto">
          <div className="bg-slate-900 border border-slate-800 w-full max-w-5xl rounded-3xl shadow-2xl flex flex-col max-h-[90vh] overflow-hidden animate-in fade-in zoom-in-95 duration-200">
            
            {/* Modal Header */}
            <div className="px-6 py-4 border-b border-slate-800 flex items-center justify-between bg-slate-950/50">
              <div className="flex items-center space-x-2">
                <FileText className="w-5 h-5 text-emerald-400" />
                <div>
                  <h3 className="text-base font-bold text-white">AI Application Tailoring</h3>
                  <p className="text-xs text-slate-400">Customized using gemini-2.5-flash</p>
                </div>
              </div>
              <button
                type="button"
                onClick={() => setIsTailorModalOpen(false)}
                className="p-1 text-slate-400 hover:text-white bg-slate-800 hover:bg-slate-700 rounded-lg transition-colors text-xs font-bold px-2.5"
              >
                Close
              </button>
            </div>

            {/* Modal Body */}
            <div className="p-6 overflow-y-auto space-y-6 flex-1 bg-slate-900 text-slate-200">
              {tailoringLoading ? (
                <div className="flex flex-col items-center justify-center py-20 space-y-4">
                  <RefreshCw className="w-10 h-10 text-emerald-500 animate-spin" />
                  <div className="text-center space-y-1">
                    <p className="text-sm font-semibold text-white">Generating tailored application materials...</p>
                    <p className="text-xs text-slate-500">Retrieving job postings, evaluating resume relevance, and executing Gemini model prompts.</p>
                  </div>
                </div>
              ) : (
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 items-stretch">
                  
                  {/* Left Column: Cover Letter */}
                  <div className="flex flex-col space-y-3 bg-slate-950/30 p-5 rounded-2xl border border-slate-850">
                    <div className="flex items-center justify-between border-b border-slate-800 pb-2.5">
                      <h4 className="text-sm font-bold text-white uppercase tracking-wider">Tailored Cover Letter</h4>
                      <button
                        type="button"
                        onClick={() => {
                          navigator.clipboard.writeText(tailoredCoverLetter);
                          showStatus('Cover letter copied to clipboard!', 'success');
                        }}
                        className="inline-flex items-center px-3 py-1.5 bg-slate-850 hover:bg-slate-800 text-slate-300 hover:text-white rounded-lg text-xs font-semibold border border-slate-800 transition-colors"
                      >
                        <Copy className="w-3.5 h-3.5 mr-1.5" />
                        Copy Letter
                      </button>
                    </div>
                    <textarea
                      readOnly
                      value={tailoredCoverLetter}
                      className="flex-1 min-h-[350px] lg:min-h-[450px] bg-slate-950/80 border border-slate-850 rounded-xl p-4 text-xs font-mono text-slate-300 leading-relaxed focus:outline-none resize-none"
                    />
                  </div>

                  {/* Right Column: Resume Bullet Revisions */}
                  <div className="flex flex-col space-y-3 bg-slate-950/30 p-5 rounded-2xl border border-slate-850">
                    <div className="border-b border-slate-800 pb-2.5">
                      <h4 className="text-sm font-bold text-white uppercase tracking-wider">Resume Bullet Suggestions</h4>
                      <p className="text-[11px] text-slate-400 mt-0.5">Adapt your resume with these tailored bullet points</p>
                    </div>

                    <div className="flex-1 overflow-y-auto space-y-4 max-h-[350px] lg:max-h-[450px] pr-1">
                      {tailoredResumeBullets.length === 0 ? (
                        <div className="h-full flex flex-col items-center justify-center text-slate-500 py-10">
                          <p className="text-xs">No bullet points require adaptation for this role.</p>
                        </div>
                      ) : (
                        tailoredResumeBullets.map((s, idx) => (
                          <div key={idx} className="bg-slate-950/40 border border-slate-850 rounded-xl p-3.5 space-y-3 shadow-sm">
                            {/* Original bullet */}
                            <div>
                              <span className="text-[9px] font-bold text-rose-400/80 uppercase tracking-wide block">Original</span>
                              <p className="text-[11px] text-slate-400 line-through mt-0.5 leading-relaxed">{s.original_bullet}</p>
                            </div>
                            
                            {/* Suggested bullet */}
                            <div className="border-t border-slate-850/60 pt-2.5">
                              <div className="flex items-center justify-between">
                                <span className="text-[9px] font-bold text-emerald-400 uppercase tracking-wide">Suggested Edit</span>
                                <button
                                  type="button"
                                  onClick={() => {
                                    navigator.clipboard.writeText(s.suggested_bullet);
                                    showStatus(`Suggested bullet ${idx + 1} copied!`, 'success');
                                  }}
                                  className="p-1 text-slate-400 hover:text-white hover:bg-slate-800 rounded transition-all"
                                  title="Copy Bullet"
                                >
                                  <Copy className="w-3 h-3" />
                                </button>
                              </div>
                              <p className="text-xs text-emerald-300/90 font-medium mt-0.5 leading-relaxed">{s.suggested_bullet}</p>
                            </div>

                            {/* Rationale */}
                            <div className="bg-slate-900/50 p-2.5 rounded-lg text-[10px] text-slate-400 leading-relaxed border border-slate-850/40">
                              <span className="font-bold text-slate-500 uppercase text-[9px] block mb-0.5">Why this change?</span>
                              {s.rationale}
                            </div>
                          </div>
                        ))
                      )}
                    </div>
                  </div>

                </div>
              )}
            </div>
            
            {/* Modal Footer */}
            <div className="px-6 py-4 border-t border-slate-800 flex justify-end bg-slate-950/50">
              <button
                type="button"
                onClick={() => setIsTailorModalOpen(false)}
                className="px-5 py-2.5 bg-slate-800 hover:bg-slate-750 text-slate-300 hover:text-white rounded-xl text-xs font-semibold transition-all"
              >
                Close Drawer
              </button>
            </div>

          </div>
        </div>
      )}

      </div>{/* end flex-1 content column */}
    </div>
  );
}
