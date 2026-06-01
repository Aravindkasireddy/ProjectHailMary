'use client';

import { useState, useEffect } from 'react';
import {
  Briefcase,
  Settings as SettingsIcon,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  RefreshCw,
  Search,
  ExternalLink,
  Edit3,
  Database,
  Check,
  Sliders,
  ChevronRight,
  BellRing,
  BarChart3,
  Shield,
  Copy,
  Undo,
  Redo,
  Bold,
  Italic,
  Underline,
  List,
  ListOrdered,
  Link2,
  Type,
  FileText,
  Lock,
  LogOut
} from 'lucide-react';
import ResumeGenerator from '../../components/ResumeGenerator';

const API_BASE = 'http://100.124.212.55:8080';

interface DecisionPayload {
  apply_decision?: string;
  strongest_label?: string;
  red_flags?: string[];
  confidence_score?: number;
  rationale?: string;
  cloud?: {
    primary_cloud?: string;
  };
  [key: string]: unknown;
}

interface Job {
  job_title: string;
  company_name: string;
  job_url: string;
  requirement_id: string;
  job_description: string;
  location_work_type: string;
  apply_decision: string;
  strongest_label: string;
  confidence_score: number;
  rationale: string;
  red_flags?: string[];
  apply_decision_payload?: DecisionPayload;
  synced?: boolean;
  synced_data?: unknown;
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
  salary_text?: string;
}

interface AnalyticsData {
  total_sourced: number;
  approved: number;
  rejected: number;
  approval_rate: number;
  labels_distribution: Record<string, number>;
  sources_distribution: Record<string, number>;
  rejection_reasons: Record<string, number>;
}

interface PolicyConfig {
  max_experience_years: number;
  min_salary_annual: number;
  min_salary_hourly: number;
  enforce_visa_sponsorship: boolean;
  enforce_no_clearance: boolean;
  custom_red_flag_keywords: string[];
}

interface Config {
  target_titles: string[];
  scheduler: {
    enabled: boolean;
    run_at_hour: number;
    run_at_minute: number;
  };
  webhook_url: string;
  webhook_source?: string;
  search?: {
    country_phrase?: string;
    include_remote_primary_boards?: boolean;
    merge_previous_scrape?: boolean;
    send_digest_only?: boolean;
    max_digest_items?: number;
  };
}

const CATEGORIES = [
  "DevOps Engineer",
  "Cloud Automation Engineer",
  "Platform Engineering",
  "Cloud Infrastructure Engineer",
  "Cloud Security Engineer",
  "DevSecOps",
  "Site Reliability Engineer (SRE)",
  "Continuous Integration (CI/CD)",
  "System Engineer",
  "Cloud Network Engineer",
  "Data Platform Engineer",
  "Machine Learning Engineer (MLOps)",
  "AI Platform Engineer (AIOps)",
  "OutOfScope"
];

const copyToClipboard = (text: string): boolean => {
  if (typeof window === 'undefined') return false;
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(text);
    return true;
  }
  // Fallback for insecure contexts (HTTP over IP address)
  const textArea = document.createElement("textarea");
  textArea.value = text;
  textArea.style.top = "0";
  textArea.style.left = "0";
  textArea.style.position = "fixed";
  document.body.appendChild(textArea);
  textArea.focus();
  textArea.select();
  let success = false;
  try {
    success = document.execCommand('copy');
  } catch (err) {
    console.error('Fallback copy failed', err);
  }
  document.body.removeChild(textArea);
  return success;
};

const CopyButton = ({ text }: { text: string }) => {
  const [copied, setCopied] = useState(false);
  const handleCopy = () => {
    const success = copyToClipboard(text);
    if (success) {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    }
  };
  return (
    <button
      onClick={handleCopy}
      type="button"
      className="p-1 text-slate-400 hover:text-white hover:bg-slate-800 rounded-lg transition-colors flex items-center"
      title="Copy to clipboard"
    >
      {copied ? (
        <Check className="w-3.5 h-3.5 text-emerald-400 animate-in zoom-in-50 duration-150" />
      ) : (
        <Copy className="w-3.5 h-3.5" />
      )}
    </button>
  );
};

export default function Dashboard() {
  const [jobs, setJobs] = useState<Job[]>([]);

  // Authentication States
  const [authToken, setAuthToken] = useState<string | null>(null);
  const [authRole, setAuthRole] = useState<'admin' | 'user' | null>(null);
  const [authEmail, setAuthEmail] = useState<string | null>(null);
  const [isAuthChecking, setIsAuthChecking] = useState<boolean>(true);
  const [loginEmail, setLoginEmail] = useState<string>('');
  const [loginPassword, setLoginPassword] = useState<string>('');
  const [loginError, setLoginError] = useState<string>('');
  const [loginLoading, setLoginLoading] = useState<boolean>(false);
  const [authMode, setAuthMode] = useState<'login' | 'register'>('login');

  // Analytics and Policy States
  const [analyticsData, setAnalyticsData] = useState<AnalyticsData | null>(null);
  const [analyticsLoading, setAnalyticsLoading] = useState(false);
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
    last_metrics: {} as Record<string, number>,
  });
  const [notionConnection, setNotionConnection] = useState({ connected: false, message: 'Checking...', dbName: '' });
  const [searchTerm, setSearchTerm] = useState('');
  const [activeTab, setActiveTab] = useState<'approved' | 'pending' | 'rejected' | 'settings' | 'analytics' | 'policy' | 'resume'>('approved');
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
  const [scrapedTimeframe, setScrapedTimeframe] = useState<'all' | 'today' | 'week' | 'month'>('all');
  const [staleCheckStatus, setStaleCheckStatus] = useState({ status: 'idle', progress: 0, total: 0, completed: 0, stale_found: 0 });
  const [showActiveOnly, setShowActiveOnly] = useState(true);

  // Custom States for Advanced Sourcing, Notion Sync, and Live Logs Console
  const [selectedSourceFilter, setSelectedSourceFilter] = useState<string | null>(null);
  const [scraperLogs, setScraperLogs] = useState<string[]>([]);
  const [isLogsExpanded, setIsLogsExpanded] = useState(false);
  const [notionSyncLoading, setNotionSyncLoading] = useState(false);
  const [notionStatusSyncLoading, setNotionStatusSyncLoading] = useState(false);

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
  const [salaryInsightsLoading, setSalaryInsightsLoading] = useState(false);
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

  // General Loading & Notification UI States
  const [syncingJobUrl, setSyncingJobUrl] = useState<string | null>(null);
  const [testingWebhook, setTestingWebhook] = useState(false);
  const [statusMessage, setStatusMessage] = useState<{ text: string; type: 'success' | 'error' | 'info' } | null>(null);

  // Core helpers (hoisted to prevent temporal dead zone)
  const showStatus = (text: string, type: 'success' | 'error' | 'info') => {
    setStatusMessage({ text, type });
    setTimeout(() => setStatusMessage(null), 5000);
  };

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoginError('');
    setLoginLoading(true);
    try {
      const endpoint = authMode === 'login' ? '/api/login' : '/api/register';
      const bodyPayload = { email: loginEmail, password: loginPassword };
      
      const res = await fetch(`${API_BASE}${endpoint}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(bodyPayload),
      });
      const data = await res.json();
      if (res.ok && data.success) {
        if (authMode === 'login') {
          localStorage.setItem('maas_auth_token', data.token);
          localStorage.setItem('maas_auth_role', data.role);
          localStorage.setItem('maas_auth_email', data.email || loginEmail);
          setAuthToken(data.token);
          setAuthRole(data.role as 'admin' | 'user');
          setAuthEmail(data.email || loginEmail);
          setLoginPassword('');
          setLoginEmail('');
          showStatus(`Welcome, logged in as ${data.role === 'admin' ? 'Admin' : 'Read-Only User'}.`, 'success');
        } else {
          setAuthMode('login');
          showStatus('Account created successfully! Please log in.', 'success');
        }
      } else {
        setLoginError(data.message || (authMode === 'login' ? 'Invalid credentials.' : 'Registration failed.'));
      }
    } catch (err) {
      setLoginError('Error connecting to authentication server.');
    } finally {
      setLoginLoading(false);
    }
  };

  const handleLogout = () => {
    localStorage.removeItem('maas_auth_token');
    localStorage.removeItem('maas_auth_role');
    localStorage.removeItem('maas_auth_email');
    setAuthToken(null);
    setAuthRole(null);
    setAuthEmail(null);
    showStatus('Logged out successfully.', 'info');
  };

  // Restore session from localStorage on mount & intercept fetch
  useEffect(() => {
    if (typeof window !== 'undefined') {
      const savedToken = localStorage.getItem('maas_auth_token');
      const savedRole = localStorage.getItem('maas_auth_role');
      const savedEmail = localStorage.getItem('maas_auth_email');
      if (savedToken && savedRole) {
        setAuthToken(savedToken);
        setAuthRole(savedRole as 'admin' | 'user');
        setAuthEmail(savedEmail || 'user@hailmary.ai');
      }
      setIsAuthChecking(false);
    }
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
            handleLogout();
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

  const checkNotionStatus = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/test-notion`);
      if (res.ok) {
        const data = await res.json();
        if (data.success) {
          setNotionConnection({ connected: true, message: 'Connected', dbName: data.db_name });
        } else {
          setNotionConnection({ connected: false, message: data.message, dbName: '' });
        }
      }
    } catch {
      setNotionConnection({ connected: false, message: 'Offline', dbName: '' });
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

  // Fetch API Functions
  const fetchAnalytics = async () => {
    setAnalyticsLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/analytics`);
      if (res.ok) {
        const data = await res.json();
        setAnalyticsData(data);
      }
    } catch {
      showStatus('Failed to load analytics data.', 'error');
    } finally {
      setAnalyticsLoading(false);
    }
  };

  const fetchPolicy = async () => {
    setPolicyLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/policy`);
      if (res.ok) {
        const data = await res.json();
        setPolicyConfig(data);
      }
    } catch {
      showStatus('Failed to load policy config.', 'error');
    } finally {
      setPolicyLoading(false);
    }
  };

  const fetchSalaryInsights = async () => {
    setSalaryInsightsLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/salary-insights`);
      if (res.ok) {
        const data = await res.json();
        setSalaryInsights(data);
      }
    } catch {
      showStatus('Failed to load salary insights.', 'error');
    } finally {
      setSalaryInsightsLoading(false);
    }
  };

  const fetchResume = async () => {
    setResumeLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/resume`);
      if (res.ok) {
        const data = await res.json();
        setResume(data.resume || '');
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
      const res = await fetch(`${API_BASE}/api/resume`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ resume }),
      });
      if (res.ok) {
        const data = await res.json();
        if (data.success) {
          showStatus(data.message, 'success');
        } else {
          showStatus(data.message || 'Failed to save resume.', 'error');
        }
      } else {
        showStatus('Failed to save resume.', 'error');
      }
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
      const res = await fetch(`${API_BASE}/api/update-pipeline-stage`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ job_url: jobUrl, pipeline_stage: newStage })
      });
      if (res.ok) {
        const data = await res.json();
        if (data.success) {
          showStatus(data.message, 'success');
          setJobs(prev => prev.map(j => j.job_url === jobUrl ? { ...j, pipeline_stage: newStage } : j));
        } else {
          showStatus(data.message, 'error');
        }
      }
    } catch {
      showStatus('Failed to update pipeline stage.', 'error');
    }
  };

  // Sync approved, unsynced jobs to Notion in bulk
  const syncAllToNotion = async () => {
    setNotionSyncLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/sync-notion`, { method: 'POST' });
      const data = await res.json();
      if (data.success) {
        showStatus(data.message, 'success');
        fetchData();
        fetchAnalytics();
      } else {
        showStatus(data.message || 'Batch Notion Sync failed.', 'error');
      }
    } catch {
      showStatus('Failed to connect to backend for Notion sync.', 'error');
    } finally {
      setNotionSyncLoading(false);
    }
  };

  // Sync statuses from Notion back to local SQLite/JSON databases
  const syncStatusFromNotion = async () => {
    setNotionStatusSyncLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/sync-notion-status`, { method: 'POST' });
      const data = await res.json();
      if (data.success) {
        showStatus(data.message, 'success');
        fetchData();
        fetchAnalytics();
      } else {
        showStatus(data.message || 'Two-way Notion status sync failed.', 'error');
      }
    } catch {
      showStatus('Failed to connect to backend for status check.', 'error');
    } finally {
      setNotionStatusSyncLoading(false);
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
  }, [isLogsExpanded]);

  const savePolicyConfig = async (updatedPolicy: PolicyConfig) => {
    try {
      const res = await fetch(`${API_BASE}/api/policy`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(updatedPolicy)
      });
      if (res.ok) {
        const data = await res.json();
        if (data.success) {
          showStatus(data.message, 'success');
          setPolicyConfig(updatedPolicy);
        } else {
          showStatus(data.message, 'error');
        }
      }
    } catch {
      showStatus('Failed to save policy configuration.', 'error');
    }
  };

  const fetchData = async () => {
    try {
      // 1. Fetch Jobs
      const resJobs = await fetch(`${API_BASE}/api/jobs`);
      if (resJobs.ok) {
        const jobsData = await resJobs.json();
        setJobs(jobsData);
      }

      // 2. Fetch Config
      const resConfig = await fetch(`${API_BASE}/api/config`);
      if (resConfig.ok) {
        const configData: Config = await resConfig.json();
        setConfig(configData);
        setTitlesInput(configData.target_titles.join('\n'));
        setWebhookUrlInput(configData.webhook_url);
        setSchedulerHour(configData.scheduler?.run_at_hour ?? 8);
        setSchedulerMinute(configData.scheduler?.run_at_minute ?? 0);
        setSchedulerEnabled(configData.scheduler?.enabled ?? true);
        setSendDigestOnly(configData.search?.send_digest_only ?? true);
      }

      // Check Notion status
      checkNotionStatus();
      // Check scraper status
      checkScraperStatus();
      // Check stale status
      checkStaleStatus();
    } catch {
      showStatus('Failed to communicate with local dashboard API.', 'error');
    }
  };

  // Tab change handler replacing side-effect useEffect
  const handleTabChange = (tab: 'approved' | 'pending' | 'rejected' | 'settings' | 'analytics' | 'policy' | 'resume') => {
    if (authRole !== 'admin' && ['policy', 'resume', 'settings'].includes(tab)) {
      showStatus('Admin role required to access this tab.', 'error');
      return;
    }
    setActiveTab(tab);
    setSelectedRoleFilter('all');
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
          .then(res => res.ok && res.json())
          .then(data => {
            if (data) setJobs(data);
          })
          .catch(() => {
            // Silence
          });
      }, 2000);
    }
    return () => clearInterval(interval);
  }, [scraperStatus.status, authToken]);

  // Initial load
  /* eslint-disable react-hooks/exhaustive-deps */
  useEffect(() => {
    if (!isAuthChecking && authToken) {
      fetchData();
    }
  }, [isAuthChecking, authToken]);
  /* eslint-enable react-hooks/exhaustive-deps */

  // Start scraper
  const triggerScrape = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/scrape`, { method: 'POST' });
      if (res.ok) {
        const data = await res.json();
        if (data.success) {
          showStatus('Scraper agent successfully launched in background!', 'success');
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

  // Poll stale check status when it is running
  useEffect(() => {
    let interval: NodeJS.Timeout;
    if (staleCheckStatus.status === 'running' && authToken) {
      interval = setInterval(() => {
        checkStaleStatus();
        // Periodically refresh jobs list too
        fetch(`${API_BASE}/api/jobs`)
          .then(res => res.ok && res.json())
          .then(data => {
            if (data) setJobs(data);
          })
          .catch(() => {
            // Silence
          });
      }, 2000);
    }
    return () => clearInterval(interval);
  }, [staleCheckStatus.status, authToken]);

  // Delete / Archive Job
  const deleteJob = async (job_url: string) => {
    if (!confirm('Are you sure you want to archive this job posting? It will be hidden from the dashboard.')) return;
    try {
      const res = await fetch(`${API_BASE}/api/delete`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ job_url })
      });
      if (res.ok) {
        const data = await res.json();
        if (data.success) {
          showStatus('Job archived successfully!', 'success');
          setJobs(prev => prev.map(j => j.job_url === job_url ? { ...j, archived: true } : j));
        } else {
          showStatus(data.message, 'error');
        }
      }
    } catch {
      showStatus('Failed to archive job.', 'error');
    }
  };

  // Sync Job to Notion
  const syncJob = async (job: Job) => {
    setSyncingJobUrl(job.job_url);
    try {
      const res = await fetch(`${API_BASE}/api/sync`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ job_url: job.job_url })
      });
      if (res.ok) {
        const data = await res.json();
        if (data.success) {
          showStatus(`Synced "${job.job_title}" successfully!`, 'success');
          // Update status locally
          setJobs(prev => prev.map(j => j.job_url === job.job_url ? { ...j, synced: true } : j));
        } else {
          showStatus(data.message, 'error');
        }
      }
    } catch {
      showStatus('Notion sync request failed.', 'error');
    } finally {
      setSyncingJobUrl(null);
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
        send_digest_only: sendDigestOnly
      }
    };

    try {
      const res = await fetch(`${API_BASE}/api/config`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(updatedConfig)
      });
      if (res.ok) {
        const data = await res.json();
        if (data.success) {
          showStatus('Configuration settings saved successfully!', 'success');
          setConfig(updatedConfig);
        } else {
          showStatus('Failed to save settings.', 'error');
        }
      }
    } catch {
      showStatus('Failed to reach settings API.', 'error');
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

  // Open inspection / override modal
  const openModal = (job: Job) => {
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
      job_url: editUrl.trim(),
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
      apply_decision_payload: parsedPayload
    };

    try {
      const res = await fetch(`${API_BASE}/api/override`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      if (res.ok) {
        const data = await res.json();
        if (data.success) {
          showStatus('Manual classification override applied successfully!', 'success');
          setIsModalOpen(false);
          // Refresh list
          fetch(`${API_BASE}/api/jobs`)
            .then(res => res.ok && res.json())
            .then(data => data && setJobs(data));
        } else {
          showStatus(data.message, 'error');
        }
      }
    } catch {
      showStatus('Failed to send classification override.', 'error');
    }
  };

  // Categorize jobs
  const approvedJobs = jobs.filter(j => !j.archived && j.apply_decision === 'APPLY' && (!j.red_flags || j.red_flags.length === 0));
  const rejectedJobs = jobs.filter(j => !j.archived && (j.apply_decision === 'DO_NOT_APPLY' || (j.red_flags && j.red_flags.length > 0)));
  const pendingJobs = jobs.filter(j => !j.archived && j.apply_decision !== 'APPLY' && j.apply_decision !== 'DO_NOT_APPLY');

  const getJobSource = (url: string) => {
    if (!url) return 'Other';
    const lUrl = url.toLowerCase();
    if (lUrl.includes('greenhouse.io')) return 'Greenhouse';
    if (lUrl.includes('lever.co')) return 'Lever';
    if (lUrl.includes('myworkdayjobs.com')) return 'Workday';
    if (lUrl.includes('ashbyhq.com')) return 'Ashby';
    if (lUrl.includes('workable.com')) return 'Workable';
    if (lUrl.includes('smartrecruiters.com')) return 'SmartRecruiters';
    if (lUrl.includes('weworkremotely.com')) return 'We Work Remotely';
    if (lUrl.includes('remote.co')) return 'Remote.co';
    if (lUrl.includes('linkedin.com')) return 'LinkedIn';
    if (lUrl.includes('workatastartup.com') || lUrl.includes('ycombinator.com')) return 'Y Combinator';
    return 'Other';
  };

  const filteredJobs = () => {
    let list = activeTab === 'approved' ? approvedJobs : activeTab === 'rejected' ? rejectedJobs : pendingJobs;

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

    if (searchTerm.trim()) {
      const term = searchTerm.toLowerCase();
      list = list.filter(j =>
        j.job_title.toLowerCase().includes(term) ||
        j.company_name.toLowerCase().includes(term) ||
        j.requirement_id.toLowerCase().includes(term)
      );
    }

    // Filter by scraped timeframe
    if (scrapedTimeframe !== 'all') {
      const now = new Date().getTime();
      const oneDay = 24 * 60 * 60 * 1000;
      list = list.filter(j => {
        if (!j.scraped_at) return false;
        const scrapedTime = new Date(j.scraped_at).getTime();
        const diff = now - scrapedTime;
        if (scrapedTimeframe === 'today') {
          return diff <= oneDay;
        } else if (scrapedTimeframe === 'week') {
          return diff <= 7 * oneDay;
        } else if (scrapedTimeframe === 'month') {
          return diff <= 30 * oneDay;
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
  };

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
        {/* Background gradients */}
        <div className="absolute top-0 left-1/4 w-96 h-96 bg-violet-600/10 rounded-full filter blur-[80px] pointer-events-none" />
        <div className="absolute top-1/3 right-1/4 w-96 h-96 bg-indigo-600/10 rounded-full filter blur-[80px] pointer-events-none" />

        <div className="w-full max-w-md bg-slate-900/60 backdrop-blur-xl border border-slate-800/80 rounded-2xl p-8 shadow-2xl relative z-10 animate-in fade-in zoom-in-95 duration-300">
          <div className="flex flex-col items-center space-y-6">
            <div className="p-4 bg-gradient-to-tr from-violet-600 to-indigo-600 rounded-2xl shadow-xl shadow-violet-500/10 flex items-center justify-center">
              <Lock className="w-8 h-8 text-white" />
            </div>
            
            <div className="text-center space-y-2">
              <h2 className="text-2xl font-bold tracking-tight bg-gradient-to-r from-white via-slate-200 to-slate-400 bg-clip-text text-transparent">
                MAAS Sourcing Agent
              </h2>
              <p className="text-sm text-slate-400">Master Classifier Policy Dashboard</p>
            </div>

            <form onSubmit={handleLogin} className="w-full space-y-4">
              <div className="space-y-2">
                <label className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
                  Email Address
                </label>
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
                <label className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
                  Password
                </label>
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
                  <>
                    <span>{authMode === 'login' ? 'Authenticate' : 'Create Account'}</span>
                    <ChevronRight className="w-4 h-4 group-hover:translate-x-0.5 transition-transform" />
                  </>
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
              Tailscale compatibility mode enabled. Secure endpoint authorization.
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1 min-h-screen bg-slate-950 text-slate-100 flex flex-col font-sans selection:bg-violet-600/30">

      {/* Background gradients */}
      <div className="absolute top-0 left-1/4 w-96 h-96 bg-violet-600/10 rounded-full filter blur-[80px] pointer-events-none" />
      <div className="absolute top-1/3 right-1/4 w-96 h-96 bg-indigo-600/10 rounded-full filter blur-[80px] pointer-events-none" />

      {/* Top Navbar */}
      <header className="sticky top-0 z-40 bg-slate-950/80 backdrop-blur-md border-b border-slate-800/80 px-6 py-4 flex items-center justify-between">
        <div className="flex items-center space-x-3">
          <div className="p-2 bg-gradient-to-tr from-violet-600 to-indigo-600 rounded-xl shadow-lg shadow-violet-500/20">
            <Briefcase className="w-6 h-6 text-white" />
          </div>
          <div>
            <h1 className="text-xl font-bold tracking-tight bg-gradient-to-r from-white via-slate-200 to-slate-400 bg-clip-text text-transparent">
              MAAS Sourcing Agent
            </h1>
            <p className="text-xs text-slate-400">Master Classifier Policy Dashboard</p>
          </div>
        </div>

        {/* Integration Status Badges */}
        <div className="flex items-center space-x-4">

          {/* Role Status Pill */}
          <div className="flex items-center space-x-2 bg-slate-900/80 border border-slate-800 rounded-full px-3 py-1.5 shadow-inner">
            <Shield className={`w-3.5 h-3.5 ${authRole === 'admin' ? 'text-violet-400' : 'text-slate-400'}`} />
            <span className="text-xs font-medium text-slate-300">Role:</span>
            <span className={`inline-flex items-center text-xs font-semibold px-2 py-0.5 rounded-full border ${
              authRole === 'admin' 
                ? 'text-violet-400 bg-violet-950/40 border-violet-800/50' 
                : 'text-slate-400 bg-slate-950/40 border-slate-800/50'
            }`}>
              {authRole === 'admin' ? 'Admin' : 'Read-Only'}{authEmail ? ` (${authEmail})` : ''}
            </span>
          </div>

          {/* Logout Button */}
          <button
            onClick={handleLogout}
            className="inline-flex items-center text-xs font-semibold text-slate-400 hover:text-white bg-slate-900 hover:bg-slate-800 border border-slate-800 hover:border-slate-700 px-3 py-1.5 rounded-full transition-colors active:scale-95"
            title="Log out"
          >
            <LogOut className="w-3.5 h-3.5 mr-1.5" />
            Logout
          </button>

          {/* Notion Status */}
          <div className="flex items-center space-x-2 bg-slate-900/80 border border-slate-800 rounded-full px-3 py-1.5 shadow-inner">
            <Database className="w-3.5 h-3.5 text-slate-400" />
            <span className="text-xs font-medium text-slate-300">Notion DB:</span>
            {notionConnection.connected ? (
              <span className="inline-flex items-center text-xs font-semibold text-emerald-400 bg-emerald-950/40 px-2 py-0.5 rounded-full border border-emerald-800/50">
                <Check className="w-3 h-3 mr-1" />
                {notionConnection.dbName || 'Connected'}
              </span>
            ) : (
              <button
                onClick={checkNotionStatus}
                className="inline-flex items-center text-xs font-semibold text-rose-400 bg-rose-950/40 px-2 py-0.5 rounded-full border border-rose-800/50 hover:bg-rose-900/30 transition-colors"
              >
                <XCircle className="w-3 h-3 mr-1" />
                Disconnected
              </button>
            )}
          </div>

          {/* Webhook Status indicator */}
          {(config.webhook_url || config.webhook_source === 'environment') && (
            <div className="flex items-center space-x-1.5 bg-slate-900/80 border border-slate-800 rounded-full px-3 py-1.5 text-xs text-indigo-300">
              <BellRing className="w-3.5 h-3.5" />
              <span>Discord {config.webhook_source === 'environment' ? '(env)' : ''}</span>
            </div>
          )}

          {/* Scraper Status */}
          <div className="flex items-center space-x-2 bg-slate-900/80 border border-slate-800 rounded-full px-3 py-1.5">
            <span className="relative flex h-2 w-2">
              <span className={`animate-ping absolute inline-flex h-full w-full rounded-full opacity-75 ${scraperStatus.status === 'running' ? 'bg-amber-400' : 'bg-slate-400'}`}></span>
              <span className={`relative inline-flex rounded-full h-2 w-2 ${scraperStatus.status === 'running' ? 'bg-amber-500' : 'bg-slate-500'}`}></span>
            </span>
            <span className="text-xs text-slate-300 capitalize">
              {scraperStatus.status === 'running'
                ? 'Sourcing...'
                : scraperStatus.status === 'failed'
                  ? 'Failed'
                  : scraperStatus.status === 'completed'
                    ? 'Ready'
                    : 'Idle'}
            </span>
          </div>

          {/* Stale Check Status */}
          {staleCheckStatus.status === 'running' && (
            <div className="flex items-center space-x-2 bg-indigo-950/40 border border-indigo-900/60 rounded-full px-3 py-1.5">
              <span className="relative flex h-2 w-2">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full opacity-75 bg-indigo-400"></span>
                <span className="relative inline-flex rounded-full h-2 w-2 bg-indigo-500"></span>
              </span>
              <span className="text-xs text-indigo-300">
                Checking Closed: {staleCheckStatus.progress}% ({staleCheckStatus.completed}/{staleCheckStatus.total})
              </span>
            </div>
          )}

          {/* Stale Check button */}
          {authRole === 'admin' && (
            <button
              onClick={triggerStaleCheck}
              disabled={staleCheckStatus.status === 'running'}
              className={`inline-flex items-center px-4 py-1.5 rounded-xl text-xs font-semibold shadow-md transition-all ${staleCheckStatus.status === 'running'
                  ? 'bg-slate-800 text-slate-500 border border-slate-700 cursor-not-allowed'
                  : 'bg-slate-900/90 hover:bg-slate-800 text-slate-200 border border-slate-700 hover:border-slate-600 active:scale-95'
                }`}
            >
              <RefreshCw className={`w-3.5 h-3.5 mr-1.5 ${staleCheckStatus.status === 'running' ? 'animate-spin' : ''}`} />
              Check Closed Jobs
            </button>
          )}

          {/* Manual Run button */}
          {authRole === 'admin' && (
            <button
              onClick={triggerScrape}
              disabled={scraperStatus.status === 'running'}
              className={`inline-flex items-center px-4 py-1.5 rounded-xl text-xs font-semibold shadow-md transition-all ${scraperStatus.status === 'running'
                  ? 'bg-slate-800 text-slate-500 border border-slate-700 cursor-not-allowed'
                  : 'bg-gradient-to-r from-violet-600 to-indigo-600 hover:from-violet-500 hover:to-indigo-500 text-white shadow-violet-600/10 border border-violet-500/20 active:scale-95'
                }`}
            >
              <RefreshCw className={`w-3.5 h-3.5 mr-1.5 ${scraperStatus.status === 'running' ? 'animate-spin' : ''}`} />
              Run Sourcing Agent
            </button>
          )}
        </div>
      </header>

      {/* Floating Status Message */}
      {statusMessage && (
        <div className={`fixed bottom-6 right-6 z-50 flex items-center space-x-2 px-4 py-3 rounded-xl border shadow-xl animate-bounce ${statusMessage.type === 'success'
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
      <main className="flex-1 max-w-7xl w-full mx-auto p-6 space-y-6 flex flex-col">

        {scraperStatus.status === 'failed' && scraperStatus.last_error && (
          <div className="bg-rose-500/10 border border-rose-500/30 p-4 rounded-2xl text-rose-200 text-xs font-mono whitespace-pre-wrap max-h-40 overflow-y-auto">
            <p className="font-semibold text-rose-300 mb-1">Last pipeline error</p>
            {scraperStatus.last_error}
          </div>
        )}

        {scraperStatus.last_metrics && Object.keys(scraperStatus.last_metrics || {}).length > 0 && scraperStatus.status !== 'running' && (
          <div className="bg-slate-900/50 border border-slate-800 p-3 rounded-xl text-xs text-slate-400">
            Last run counts:{' '}
            {Object.entries(scraperStatus.last_metrics)
              .map(([k, v]) => `${k}: ${v}`)
              .join(' · ')}
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
        <section className="grid grid-cols-1 md:grid-cols-3 gap-6">

          <div className="bg-slate-900/40 backdrop-blur-md border border-slate-800/85 p-6 rounded-2xl flex items-center justify-between shadow-xl">
            <div>
              <p className="text-sm text-slate-400 font-medium">Approved Jobs</p>
              <h3 className="text-3xl font-extrabold text-white mt-1">{approvedJobs.length}</h3>
              <p className="text-xs text-emerald-400 mt-1 flex items-center">
                <CheckCircle2 className="w-3.5 h-3.5 mr-1" /> Match policy guidelines
              </p>
            </div>
            <div className="p-3 bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 rounded-2xl">
              <CheckCircle2 className="w-6 h-6" />
            </div>
          </div>

          <div className="bg-slate-900/40 backdrop-blur-md border border-slate-800/85 p-6 rounded-2xl flex items-center justify-between shadow-xl">
            <div>
              <p className="text-sm text-slate-400 font-medium">Unreviewed Candidates</p>
              <h3 className="text-3xl font-extrabold text-white mt-1">{pendingJobs.length}</h3>
              <p className="text-xs text-amber-400 mt-1 flex items-center">
                <Sliders className="w-3.5 h-3.5 mr-1" /> Pending override decision
              </p>
            </div>
            <div className="p-3 bg-amber-500/10 text-amber-400 border border-amber-500/20 rounded-2xl">
              <Sliders className="w-6 h-6" />
            </div>
          </div>

          <div className="bg-slate-900/40 backdrop-blur-md border border-slate-800/85 p-6 rounded-2xl flex items-center justify-between shadow-xl">
            <div>
              <p className="text-sm text-slate-400 font-medium">Filtered / Rejected</p>
              <h3 className="text-3xl font-extrabold text-white mt-1">{rejectedJobs.length}</h3>
              <p className="text-xs text-rose-400 mt-1 flex items-center">
                <XCircle className="w-3.5 h-3.5 mr-1" /> Failed policy filters
              </p>
            </div>
            <div className="p-3 bg-rose-500/10 text-rose-400 border border-rose-500/20 rounded-2xl">
              <XCircle className="w-6 h-6" />
            </div>
          </div>

        </section>

        {/* Toolbar & Filter Tabs */}
        <section className="flex flex-col bg-slate-900/30 backdrop-blur-md border border-slate-800/80 p-4 rounded-2xl gap-4 shadow-xl">

          {/* Top Row: Navigation Tabs & Notion Buttons */}
          <div className="flex flex-col lg:flex-row items-stretch lg:items-center justify-between gap-4">
            {/* Navigation Tabs */}
            <div className="flex bg-slate-950 p-1.5 rounded-xl border border-slate-800/50 flex-wrap gap-1">
              <button
                onClick={() => handleTabChange('approved')}
                className={`flex items-center px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${activeTab === 'approved'
                    ? 'bg-gradient-to-r from-violet-600 to-indigo-600 text-white shadow-md'
                    : 'text-slate-400 hover:text-slate-200'
                  }`}
              >
                Approved ({approvedJobs.length})
              </button>
              <button
                onClick={() => handleTabChange('pending')}
                className={`flex items-center px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${activeTab === 'pending'
                    ? 'bg-gradient-to-r from-violet-600 to-indigo-600 text-white shadow-md'
                    : 'text-slate-400 hover:text-slate-200'
                  }`}
              >
                Unreviewed ({pendingJobs.length})
              </button>
              <button
                onClick={() => handleTabChange('rejected')}
                className={`flex items-center px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${activeTab === 'rejected'
                    ? 'bg-gradient-to-r from-violet-600 to-indigo-600 text-white shadow-md'
                    : 'text-slate-400 hover:text-slate-200'
                  }`}
              >
                Filtered ({rejectedJobs.length})
              </button>
              <button
                onClick={() => handleTabChange('analytics')}
                className={`flex items-center px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${activeTab === 'analytics'
                    ? 'bg-gradient-to-r from-violet-600 to-indigo-600 text-white shadow-md'
                    : 'text-slate-400 hover:text-slate-200'
                  }`}
              >
                <BarChart3 className="w-3.5 h-3.5 mr-1" />
                Analytics
              </button>
              {authRole === 'admin' && (
                <>
                  <button
                    onClick={() => handleTabChange('policy')}
                    className={`flex items-center px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${activeTab === 'policy'
                        ? 'bg-gradient-to-r from-violet-600 to-indigo-600 text-white shadow-md'
                        : 'text-slate-400 hover:text-slate-200'
                      }`}
                  >
                    <Shield className="w-3.5 h-3.5 mr-1" />
                    Classifier Policy
                  </button>
                  <button
                    onClick={() => handleTabChange('resume')}
                    className={`flex items-center px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${activeTab === 'resume'
                        ? 'bg-gradient-to-r from-violet-600 to-indigo-600 text-white shadow-md'
                        : 'text-slate-400 hover:text-slate-200'
                      }`}
                  >
                    <FileText className="w-3.5 h-3.5 mr-1" />
                    Base Resume
                  </button>
                  <button
                    onClick={() => handleTabChange('settings')}
                    className={`flex items-center px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${activeTab === 'settings'
                        ? 'bg-gradient-to-r from-violet-600 to-indigo-600 text-white shadow-md'
                        : 'text-slate-400 hover:text-slate-200'
                      }`}
                  >
                    <SettingsIcon className="w-3.5 h-3.5 mr-1" />
                    Settings
                  </button>
                </>
              )}
            </div>

            {/* Notion Sync Actions */}
            {authRole === 'admin' && (
              <div className="flex items-center gap-2 self-start lg:self-auto">
                <button
                  type="button"
                  onClick={syncAllToNotion}
                  disabled={notionSyncLoading || !notionConnection.connected}
                  className={`inline-flex items-center px-3 py-1.5 border rounded-xl text-xs font-semibold transition-all shadow-inner active:scale-95 ${
                    notionSyncLoading
                      ? 'bg-slate-800 text-slate-500 border-slate-700 cursor-not-allowed'
                      : !notionConnection.connected
                      ? 'bg-slate-900/40 border-slate-850 text-slate-500 cursor-not-allowed'
                      : 'bg-gradient-to-r from-violet-600 to-indigo-600 hover:from-violet-500 hover:to-indigo-500 border-violet-500/20 text-white shadow-md shadow-violet-500/10'
                  }`}
                >
                  <Database className={`w-3.5 h-3.5 mr-1.5 ${notionSyncLoading ? 'animate-spin' : ''}`} />
                  {notionSyncLoading ? 'Syncing...' : 'Sync to Notion'}
                </button>
                <button
                  type="button"
                  onClick={syncStatusFromNotion}
                  disabled={notionStatusSyncLoading || !notionConnection.connected}
                  className={`inline-flex items-center px-3 py-1.5 border rounded-xl text-xs font-semibold transition-all shadow-inner active:scale-95 ${
                    notionStatusSyncLoading
                      ? 'bg-slate-800 text-slate-500 border-slate-700 cursor-not-allowed'
                      : !notionConnection.connected
                      ? 'bg-slate-900/40 border-slate-850 text-slate-500 cursor-not-allowed'
                      : 'bg-slate-900/90 hover:bg-slate-800 border-slate-700 hover:border-slate-600 text-slate-200'
                  }`}
                >
                  <RefreshCw className={`w-3.5 h-3.5 mr-1.5 ${notionStatusSyncLoading ? 'animate-spin' : ''}`} />
                  {notionStatusSyncLoading ? 'Pulling...' : 'Pull Notion Status'}
                </button>
              </div>
            )}
          </div>

          {/* Bottom Row: Search bar & Category filter */}
          {activeTab !== 'settings' && (
            <div className="flex flex-col lg:flex-row items-stretch lg:items-center gap-3 w-full justify-between border-t border-slate-800/40 pt-3 flex-wrap">
              {activeTab === 'approved' && (
                <div className="relative shrink-0">
                  <span className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none text-slate-400">
                    <Sliders className="w-4 h-4 text-violet-400" />
                  </span>
                  <select
                    value={selectedRoleFilter}
                    onChange={e => setSelectedRoleFilter(e.target.value)}
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

              {/* Sort By Dropdown */}
              <div className="relative shrink-0">
                <span className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none text-slate-400">
                  <Sliders className="w-4 h-4 text-violet-400" />
                </span>
                <select
                  value={sortBy}
                  onChange={e => setSortBy(e.target.value as 'newest' | 'oldest')}
                  className="bg-slate-950/80 border border-slate-800 rounded-xl pl-9 pr-10 py-2 text-sm text-slate-200 focus:outline-none focus:border-violet-600/70 transition-colors shadow-inner appearance-none cursor-pointer w-full sm:w-auto min-w-[150px]"
                >
                  <option value="newest">Newest Scrape</option>
                  <option value="oldest">Oldest Scrape</option>
                </select>
                <span className="absolute inset-y-0 right-0 pr-3 flex items-center pointer-events-none text-slate-500">
                  <ChevronRight className="w-4 h-4 rotate-90" />
                </span>
              </div>

              {/* Show Active Only Toggle */}
              {activeTab === 'approved' && (
                <button
                  type="button"
                  onClick={() => setShowActiveOnly(prev => !prev)}
                  className={`inline-flex items-center px-4 py-2 border rounded-xl text-sm font-semibold transition-colors shrink-0 shadow-inner ${showActiveOnly
                      ? 'bg-violet-950/40 border-violet-850 text-violet-300'
                      : 'bg-slate-950/80 border-slate-800 text-slate-400 hover:text-slate-200'
                    }`}
                >
                  <Sliders className="w-4 h-4 mr-2 text-violet-400" />
                  {showActiveOnly ? 'Active Only' : 'Include Closed'}
                </button>
              )}

              {/* Scraped Timeframe Filter */}
              <div className="relative shrink-0">
                <span className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none text-slate-400">
                  <Sliders className="w-4 h-4 text-violet-400" />
                </span>
                <select
                  value={scrapedTimeframe}
                  onChange={e => setScrapedTimeframe(e.target.value as 'all' | 'today' | 'week' | 'month')}
                  className="bg-slate-950/80 border border-slate-800 rounded-xl pl-9 pr-10 py-2 text-sm text-slate-200 focus:outline-none focus:border-violet-600/70 transition-colors shadow-inner appearance-none cursor-pointer w-full sm:w-auto min-w-[170px]"
                >
                  <option value="all">All Scrape Times</option>
                  <option value="today">Scraped Today (24h)</option>
                  <option value="week">Scraped Last 7 Days</option>
                  <option value="month">Scraped Last 30 Days</option>
                </select>
                <span className="absolute inset-y-0 right-0 pr-3 flex items-center pointer-events-none text-slate-500">
                  <ChevronRight className="w-4 h-4 rotate-90" />
                </span>
              </div>

              <div className="relative flex-1">
                <span className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none text-slate-400">
                  <Search className="w-4 h-4" />
                </span>
                <input
                  type="text"
                  placeholder="Fuzzy search by job, company, or requirement id..."
                  value={searchTerm}
                  onChange={e => setSearchTerm(e.target.value)}
                  className="w-full bg-slate-950/80 border border-slate-800 rounded-xl pl-10 pr-4 py-2 text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:border-violet-600/70 transition-colors shadow-inner"
                />
              </div>
            </div>
          )}

        </section>

        {/* Tab Content Panels */}
        <section className="flex-1 flex flex-col">          {activeTab === 'analytics' ? (
            <div className="space-y-6">
              {analyticsLoading || !analyticsData ? (
                <div className="flex-1 flex flex-col items-center justify-center p-12 text-center border border-slate-800 rounded-2xl bg-slate-900/10">
                  <RefreshCw className="w-10 h-10 text-violet-500 animate-spin mb-3" />
                  <p className="text-sm text-slate-400 font-medium">Computing sourcing metrics & analytics...</p>
                </div>
              ) : (() => {
                const getSourceGradient = (srcName: string) => {
                  const s = srcName.toLowerCase();
                  if (s.includes('greenhouse')) return 'from-emerald-400 to-teal-500';
                  if (s.includes('lever')) return 'from-orange-400 to-amber-500';
                  if (s.includes('ashby')) return 'from-violet-400 to-fuchsia-500';
                  if (s.includes('workable')) return 'from-blue-400 to-indigo-500';
                  if (s.includes('remotely') || s.includes('remote.co') || s.includes('remote')) return 'from-rose-400 to-pink-500';
                  if (s.includes('linkedin')) return 'from-sky-400 to-blue-500';
                  if (s.includes('y combinator') || s.includes('workatastartup')) return 'from-yellow-400 to-orange-500';
                  return 'from-indigo-400 to-violet-500';
                };
                const getSourceDotColor = (srcName: string) => {
                  const s = srcName.toLowerCase();
                  if (s.includes('greenhouse')) return 'bg-emerald-400';
                  if (s.includes('lever')) return 'bg-orange-400';
                  if (s.includes('ashby')) return 'bg-violet-400';
                  if (s.includes('workable')) return 'bg-blue-400';
                  if (s.includes('remotely') || s.includes('remote.co') || s.includes('remote')) return 'bg-rose-400';
                  if (s.includes('linkedin')) return 'bg-sky-400';
                  if (s.includes('y combinator') || s.includes('workatastartup')) return 'bg-yellow-400';
                  return 'bg-indigo-400';
                };
                return (
                  <div className="space-y-6 animate-in fade-in duration-300">

                    {/* Cards Row */}
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
                        <h3 className="text-3xl font-extrabold text-violet-400 mt-2 tracking-tight">{analyticsData.approval_rate}%</h3>
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
                          <span className="text-[10px] text-slate-400 font-mono bg-slate-850 px-2 py-0.5 rounded-md">
                            By Title
                          </span>
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
                          <span className="text-[10px] text-slate-400 font-mono bg-slate-850 px-2 py-0.5 rounded-md">
                            By Platform
                          </span>
                        </div>

                        <div className="flex items-end justify-between h-56 pt-8 pb-3 px-6 gap-3 bg-slate-950/50 rounded-2xl border border-slate-800/50 relative overflow-hidden">
                          {/* Grid Background Lines */}
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
                              const grad = getSourceGradient(src);
                              return (
                                <div 
                                  key={src} 
                                  className="flex-1 flex flex-col items-center group relative h-full justify-end z-10 cursor-pointer"
                                  onClick={() => {
                                    setSelectedSourceFilter(src);
                                    setActiveTab('approved');
                                  }}
                                >
                                  {/* Custom Tooltip */}
                                  <div className="absolute bottom-full mb-2 opacity-0 group-hover:opacity-100 transition-opacity bg-slate-900 border border-slate-700 text-slate-100 text-[10px] font-bold py-1.5 px-2.5 rounded-lg shadow-xl pointer-events-none z-25 whitespace-nowrap flex flex-col items-center gap-0.5">
                                    <span className="text-white">{src}</span>
                                    <span className="text-violet-400 font-mono">{count} jobs ({pctOfTotal}%)</span>
                                  </div>
                                  <div 
                                    className={`w-full bg-gradient-to-t ${grad} rounded-t-md hover:brightness-110 shadow-lg shadow-black/20 group-hover:-translate-y-1 transition-all duration-500 ease-out`} 
                                    style={{ height: `${Math.max(heightPct, 6)}%` }}
                                  />
                                  <span className="text-[9px] text-slate-400 font-bold uppercase tracking-wider mt-2 truncate w-full text-center group-hover:text-white transition-colors">
                                    {src.replace("We Work Remotely", "WWR").split(' ')[0]}
                                  </span>
                                </div>
                              );
                            })
                          )}
                        </div>
                      </div>

                      {/* Sourcing Channel Mix Breakdown Table */}
                      <div className="bg-slate-900/40 backdrop-blur-md border border-slate-800/80 p-6 rounded-3xl shadow-xl space-y-4 lg:col-span-2">
                        <div className="flex items-center justify-between border-b border-slate-800 pb-3">
                          <div className="flex items-center space-x-2">
                            <BarChart3 className="w-5 h-5 text-emerald-400" />
                            <h3 className="text-sm font-bold text-white">Sourcing Mix & Performance Details</h3>
                          </div>
                          <span className="text-[10px] text-slate-400 bg-slate-800/60 px-2.5 py-1 rounded-full font-semibold">
                            Active Sourcing Channels
                          </span>
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
                                    <tr 
                                      key={src} 
                                      className="hover:bg-slate-800/10 transition-colors group cursor-pointer"
                                      onClick={() => {
                                        setSelectedSourceFilter(src);
                                        setActiveTab('approved');
                                      }}
                                    >
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

                      {/* Salary Analytics Insights */}
                      <div className="bg-slate-900/40 backdrop-blur-md border border-slate-800/80 p-6 rounded-3xl shadow-xl space-y-6 lg:col-span-2">
                        <div className="flex items-center justify-between border-b border-slate-800 pb-3">
                          <div className="flex items-center space-x-2">
                            <Database className="w-5 h-5 text-indigo-400" />
                            <h3 className="text-sm font-bold text-white">Sourced Salary & Compensation Metrics</h3>
                          </div>
                          <span className="text-[10px] text-slate-400 bg-slate-800/60 px-2.5 py-1 rounded-full font-semibold">
                            Salary Analytics
                          </span>
                        </div>

                        {salaryInsightsLoading || !salaryInsights ? (
                          <div className="flex flex-col items-center justify-center py-12 text-center text-slate-500">
                            <RefreshCw className="w-8 h-8 text-violet-500 animate-spin mb-3" />
                            <p className="text-xs font-semibold">Computing market salary trends...</p>
                          </div>
                        ) : (
                          <div className="grid grid-cols-1 md:grid-cols-2 gap-6 animate-in fade-in duration-300">
                            
                            {/* Salary Metric Stats */}
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
                            
                            {/* Salary Bands/insights detail */}
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

                  </div>
                );
              })()}
            </div>
          ) : activeTab === 'policy' ? (
            <div className="bg-slate-900/20 backdrop-blur-md border border-slate-800 p-6 rounded-2xl space-y-6 max-w-3xl shadow-xl">
              {policyLoading || !policyConfig ? (
                <div className="flex-1 flex flex-col items-center justify-center p-12 text-center border border-slate-800 rounded-2xl bg-slate-900/10">
                  <RefreshCw className="w-10 h-10 text-violet-500 animate-spin mb-3" />
                  <p className="text-sm text-slate-400 font-medium">Loading classifier policy guidelines...</p>
                </div>
              ) : (
                <div className="space-y-6 animate-in fade-in duration-300">
                  <div className="flex items-center justify-between pb-4 border-b border-slate-800">
                    <div className="flex items-center space-x-2">
                      <Shield className="w-5 h-5 text-violet-400" />
                      <h2 className="text-lg font-bold text-white">Classifier Policy & Experience Rules</h2>
                    </div>
                    <span className="text-[10px] bg-violet-950/60 text-violet-400 px-2 py-0.5 rounded border border-violet-850 font-bold uppercase tracking-wider">
                      Gemini Policy Gating
                    </span>
                  </div>

                  {/* Max Experience Input */}
                  <div className="space-y-2">
                    <div className="flex justify-between items-center">
                      <label className="block text-xs font-bold uppercase tracking-wider text-slate-400">
                        Max Allowed Experience Cap
                      </label>
                      <span className="text-xs font-bold text-violet-400">{policyConfig.max_experience_years} Years</span>
                    </div>
                    <div className="flex items-center space-x-4">
                      <input
                        type="range"
                        min="3"
                        max="15"
                        value={policyConfig.max_experience_years}
                        onChange={e => setPolicyConfig({ ...policyConfig, max_experience_years: Number(e.target.value) })}
                        className="flex-1 accent-violet-600 bg-slate-950 h-2 rounded-lg appearance-none cursor-pointer"
                      />
                      <input
                        type="number"
                        min="3"
                        max="15"
                        value={policyConfig.max_experience_years}
                        onChange={e => setPolicyConfig({ ...policyConfig, max_experience_years: Number(e.target.value) })}
                        className="w-16 bg-slate-950 border border-slate-800 rounded-xl px-2 py-1.5 text-center text-xs text-slate-200 focus:outline-none focus:border-violet-600/70"
                      />
                    </div>
                    <p className="text-[10px] text-slate-500">Jobs requesting experience years at or above this threshold will be flagged as R2 and automatically rejected.</p>
                  </div>

                  {/* Salary Threshold inputs */}
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-6 pt-4 border-t border-slate-800">
                    <div className="space-y-2">
                      <label className="block text-xs font-bold uppercase tracking-wider text-slate-400">
                        Min Annual Salary
                      </label>
                      <div className="relative">
                        <span className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none text-slate-500 text-xs">$</span>
                        <input
                          type="number"
                          value={policyConfig.min_salary_annual}
                          onChange={e => setPolicyConfig({ ...policyConfig, min_salary_annual: Number(e.target.value) })}
                          className="w-full bg-slate-950 border border-slate-800 rounded-xl pl-6 pr-4 py-2 text-sm text-slate-200 focus:outline-none focus:border-violet-600/70 shadow-inner"
                        />
                      </div>
                      <p className="text-[10px] text-slate-500">Block salaried positions offering below this annual rate (e.g. $80,000).</p>
                    </div>

                    <div className="space-y-2">
                      <label className="block text-xs font-bold uppercase tracking-wider text-slate-400">
                        Min Hourly Rate
                      </label>
                      <div className="relative">
                        <span className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none text-slate-500 text-xs">$</span>
                        <input
                          type="number"
                          value={policyConfig.min_salary_hourly}
                          onChange={e => setPolicyConfig({ ...policyConfig, min_salary_hourly: Number(e.target.value) })}
                          className="w-full bg-slate-950 border border-slate-800 rounded-xl pl-6 pr-4 py-2 text-sm text-slate-200 focus:outline-none focus:border-violet-600/70 shadow-inner"
                        />
                      </div>
                      <p className="text-[10px] text-slate-500">Block hourly contracts offering at or below this hourly rate (e.g. $50/hr).</p>
                    </div>
                  </div>

                  {/* Checkbox Gating Rules */}
                  <div className="space-y-3 pt-4 border-t border-slate-800">
                    <label className="block text-xs font-bold uppercase tracking-wider text-slate-400">
                      Standard Security Restrictions
                    </label>
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">

                      {/* Visa sponsorship toggle */}
                      <label className="flex items-center space-x-3 bg-slate-950/40 p-3 rounded-xl border border-slate-800 cursor-pointer hover:border-slate-700 transition-colors">
                        <input
                          type="checkbox"
                          checked={policyConfig.enforce_visa_sponsorship}
                          onChange={e => setPolicyConfig({ ...policyConfig, enforce_visa_sponsorship: e.target.checked })}
                          className="w-4 h-4 text-violet-600 bg-slate-900 border-slate-800 rounded focus:ring-violet-600 focus:ring-offset-slate-900"
                        />
                        <div>
                          <span className="text-xs font-bold text-slate-200 block">Block Visa Sponsorship Limits</span>
                          <span className="text-[9px] text-slate-500 block mt-0.5">{'Reject jobs that explicitly state "no sponsorship" or "cannot sponsor"'}</span>
                        </div>
                      </label>

                      {/* Security clearance toggle */}
                      <label className="flex items-center space-x-3 bg-slate-950/40 p-3 rounded-xl border border-slate-800 cursor-pointer hover:border-slate-700 transition-colors">
                        <input
                          type="checkbox"
                          checked={policyConfig.enforce_no_clearance}
                          onChange={e => setPolicyConfig({ ...policyConfig, enforce_no_clearance: e.target.checked })}
                          className="w-4 h-4 text-violet-600 bg-slate-900 border-slate-800 rounded focus:ring-violet-600 focus:ring-offset-slate-900"
                        />
                        <div>
                          <span className="text-xs font-bold text-slate-200 block">Block Security Clearance Roles</span>
                          <span className="text-[9px] text-slate-500 block mt-0.5">{'Reject roles requesting "Active Secret/TS Clearance" or government eligibility'}</span>
                        </div>
                      </label>

                    </div>
                  </div>

                  {/* Custom Red Flag Keywords */}
                  <div className="space-y-2 pt-4 border-t border-slate-800">
                    <label className="block text-xs font-bold uppercase tracking-wider text-slate-400">
                      Custom Red Flag Keywords (Comma separated)
                    </label>
                    <input
                      type="text"
                      placeholder="clearance, visa limit, federal, internship"
                      value={policyConfig.custom_red_flag_keywords.join(', ')}
                      onChange={e => setPolicyConfig({
                        ...policyConfig,
                        custom_red_flag_keywords: e.target.value.split(',').map(s => s.trim()).filter(s => s)
                      })}
                      className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-2.5 text-sm text-slate-200 placeholder-slate-650 focus:outline-none focus:border-violet-600/70 shadow-inner"
                    />
                    <p className="text-[10px] text-slate-500">Any exact keyword or phrase match will instantly flag the job as rejected.</p>
                  </div>

                  {/* Save panel */}
                  <div className="pt-6 border-t border-slate-850 flex justify-end">
                    <button
                      onClick={() => savePolicyConfig(policyConfig)}
                      className="inline-flex items-center px-6 py-2.5 bg-gradient-to-r from-violet-600 to-indigo-600 hover:from-violet-500 hover:to-indigo-500 text-white rounded-xl text-sm font-semibold shadow-md shadow-violet-500/10 border border-violet-500/20 active:scale-95 transition-all"
                    >
                      <Check className="w-4 h-4 mr-2" />
                      Apply Policy Rules
                    </button>
                  </div>

                </div>
              )}
            </div>
          ) : activeTab === 'settings' ? (

            /* Settings Tab */
            <div className="bg-slate-900/20 backdrop-blur-md border border-slate-850 p-6 rounded-2xl space-y-6 max-w-3xl shadow-xl">
              <div className="flex items-center space-x-2 pb-4 border-b border-slate-800">
                <SettingsIcon className="w-5 h-5 text-violet-400" />
                <h2 className="text-lg font-bold text-white">Sourcing & Webhook Settings</h2>
              </div>

              {/* Webhook URLs */}
              <div className="space-y-3">
                <label className="block text-xs font-bold uppercase tracking-wider text-slate-400">
                  Discord Notification Webhook
                </label>
                <div className="flex space-x-3">
                  <input
                    type="text"
                    placeholder="https://discord.com/api/webhooks/..."
                    value={webhookUrlInput}
                    onChange={e => setWebhookUrlInput(e.target.value)}
                    className="flex-1 bg-slate-950 border border-slate-800 rounded-xl px-4 py-2.5 text-sm text-slate-200 placeholder-slate-600 focus:outline-none focus:border-violet-600/70 shadow-inner"
                  />
                  <button
                    onClick={testWebhook}
                    disabled={testingWebhook}
                    className="inline-flex items-center px-4 py-2 bg-slate-800 hover:bg-slate-750 text-slate-300 hover:text-white rounded-xl text-xs font-semibold border border-slate-700 transition-colors"
                  >
                    {testingWebhook ? 'Testing...' : 'Test Webhook'}
                  </button>
                </div>

                {/* Webhook Delivery Preference Toggle */}
                <div className="bg-slate-950/40 border border-slate-850 p-3 rounded-xl flex items-center justify-between">
                  <div className="space-y-0.5">
                    <span className="text-xs font-bold text-slate-300">Delivery Preference</span>
                    <p className="text-[11px] text-slate-500">
                      Consolidated digest groups all new approved jobs into a single summary card instead of individual alerts.
                    </p>
                  </div>
                  <label className="inline-flex items-center cursor-pointer">
                    <input
                      type="checkbox"
                      checked={sendDigestOnly}
                      onChange={e => setSendDigestOnly(e.target.checked)}
                      className="sr-only peer"
                    />
                    <div className="relative w-9 h-5 bg-slate-800 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full rtl:peer-checked:after:-translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:start-[2px] after:bg-slate-400 after:border-slate-300 after:border after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:bg-violet-600 peer-checked:after:bg-white"></div>
                    <span className="ms-2 text-xs font-semibold text-slate-300">Digest</span>
                  </label>
                </div>

                <p className="text-xs text-slate-500">Sends alerts when new approved jobs are synced to Notion.</p>
              </div>

              {/* Target titles */}
              <div className="space-y-2">
                <label className="block text-xs font-bold uppercase tracking-wider text-slate-400">
                  Target Job Titles Sourcing List (One per line)
                </label>
                <textarea
                  rows={8}
                  placeholder="DevOps Engineer&#10;Platform Engineer"
                  value={titlesInput}
                  onChange={e => setTitlesInput(e.target.value)}
                  className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-3 text-sm text-slate-200 placeholder-slate-600 focus:outline-none focus:border-violet-600/70 shadow-inner"
                />
              </div>

              {/* Scheduler Settings */}
              <div className="space-y-4 pt-4 border-t border-slate-850">
                <label className="block text-xs font-bold uppercase tracking-wider text-slate-400">
                  Background Scheduler Configuration
                </label>
                <div className="flex flex-col sm:flex-row sm:items-center gap-6">
                  <label className="inline-flex items-center cursor-pointer">
                    <input
                      type="checkbox"
                      checked={schedulerEnabled}
                      onChange={e => setSchedulerEnabled(e.target.checked)}
                      className="sr-only peer"
                    />
                    <div className="relative w-11 h-6 bg-slate-800 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full rtl:peer-checked:after:-translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:start-[2px] after:bg-slate-400 after:border-slate-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-violet-600 peer-checked:after:bg-white"></div>
                    <span className="ms-3 text-sm font-medium text-slate-300">Run automatically every day</span>
                  </label>

                  {schedulerEnabled && (
                    <div className="flex items-center space-x-2">
                      <span className="text-sm text-slate-400">at</span>
                      <input
                        type="number"
                        min="0"
                        max="23"
                        value={schedulerHour}
                        onChange={e => setSchedulerHour(Number(e.target.value))}
                        className="w-16 bg-slate-950 border border-slate-800 rounded-xl px-3 py-1.5 text-center text-sm text-slate-200 focus:outline-none focus:border-violet-600/70"
                      />
                      <span className="text-sm text-slate-400">:</span>
                      <input
                        type="number"
                        min="0"
                        max="59"
                        value={schedulerMinute}
                        onChange={e => setSchedulerMinute(Number(e.target.value))}
                        className="w-16 bg-slate-950 border border-slate-800 rounded-xl px-3 py-1.5 text-center text-sm text-slate-200 focus:outline-none focus:border-violet-600/70"
                      />
                    </div>
                  )}
                </div>
              </div>

              {/* Submit panel */}
              <div className="pt-6 border-t border-slate-800 flex justify-end">
                <button
                  onClick={saveSettings}
                  className="inline-flex items-center px-6 py-2.5 bg-gradient-to-r from-violet-600 to-indigo-600 hover:from-violet-500 hover:to-indigo-500 text-white rounded-xl text-sm font-semibold shadow-md shadow-violet-500/10 border border-violet-500/20 active:scale-95 transition-all"
                >
                  <Check className="w-4 h-4 mr-2" />
                  Save Settings
                </button>
              </div>

            </div>
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
                    {activeTab === 'approved' ? 'Approved Postings' : activeTab === 'rejected' ? 'Filtered Postings' : 'Pending Review'}
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

              {filteredJobs().length === 0 ? (
                <div className="flex-1 flex flex-col items-center justify-center border border-dashed border-slate-800 rounded-2xl p-12 text-center bg-slate-900/10">
                  <Briefcase className="w-12 h-12 text-slate-600 mb-3" />
                  <h3 className="text-sm font-bold text-slate-400">No Job Postings Found</h3>
                  <p className="text-xs text-slate-500 max-w-sm mt-1">
                    {searchTerm ? 'No results matched your search term.' : 'Try running the sourcing agent to scrape jobs or override filter settings.'}
                  </p>
                </div>
              ) : isKanbanView ? (
                /* Kanban Board Columns */
                <div className="flex space-x-4 overflow-x-auto pb-4 custom-scrollbar items-start select-none">
                  {['Approved', 'Applied', 'Phone Screen', 'Technical Interview', 'Offer', 'Rejected'].map(stage => {
                    const stageJobs = filteredJobs().filter(j => (j.pipeline_stage || 'Approved') === stage || (stage === 'Rejected' && (j.pipeline_stage === 'Rejected' || j.pipeline_stage === 'Closed')));
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
                                <span className="text-[10px] font-mono text-slate-500 shrink-0" title={`Posted: ${job.posted_at ? formatScrapedDate(job.posted_at) : 'N/A'}\nScraped: ${formatScrapedDate(job.scraped_at || '')}`}>
                                  {job.posted_at ? formatScrapedDate(job.posted_at) : formatScrapedDate(job.scraped_at || '')}
                                </span>
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
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                  {filteredJobs().map((job, idx) => (

                    /* Job Card */
                    <div
                      key={job.job_url + idx}
                      className={`relative bg-slate-900/30 backdrop-blur-md rounded-2xl p-5 border flex flex-col justify-between shadow-lg hover:shadow-2xl transition-all duration-300 group ${activeTab === 'approved'
                          ? 'border-emerald-500/20 hover:border-emerald-500/50 hover:bg-emerald-950/5'
                          : activeTab === 'rejected'
                            ? 'border-rose-500/20 hover:border-rose-500/50 hover:bg-rose-950/5'
                            : 'border-amber-500/20 hover:border-amber-500/50 hover:bg-amber-950/5'
                        }`}
                    >
                      {/* Top Job Headers */}
                      <div>
                        <div className="flex items-start justify-between">
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center space-x-1.5 mr-2">
                              <h3 className="text-base font-bold text-white group-hover:text-violet-400 transition-colors truncate">
                                {job.job_title}
                              </h3>
                              <CopyButton text={job.job_title} />
                            </div>
                            <p className="text-xs font-semibold text-slate-400 mt-0.5">{job.company_name}</p>
                          </div>

                          <div className="flex flex-col items-end space-y-1.5 shrink-0">
                            {/* Label Badge */}
                            <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wider ${activeTab === 'approved'
                                ? 'bg-emerald-950/60 text-emerald-400 border border-emerald-800/40'
                                : activeTab === 'rejected'
                                  ? 'bg-rose-950/60 text-rose-400 border border-rose-800/40'
                                  : 'bg-amber-950/60 text-amber-400 border border-amber-800/40'
                              }`}>
                              {job.strongest_label}
                            </span>

                            {/* Stale Badge */}
                            {job.stale && (
                              <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-[9px] font-extrabold uppercase tracking-wider bg-rose-950/80 text-rose-300 border border-rose-850 animate-pulse">
                                Closed / Stale
                              </span>
                            )}
                          </div>
                        </div>

                        {/* Location / Req ID details */}
                        <div className={`mt-3 grid ${job.salary_text ? 'grid-cols-5' : 'grid-cols-4'} gap-3 text-xs text-slate-400 bg-slate-950/50 p-2.5 rounded-xl border border-slate-800/40`}>
                          <div>
                            <div className="flex items-center justify-between">
                              <span className="font-bold text-slate-500 uppercase text-[9px] tracking-wider block">Location</span>
                              <CopyButton text={job.location_work_type} />
                            </div>
                            <span className="mt-0.5 block truncate text-slate-300 font-medium" title={job.location_work_type}>
                              {job.location_work_type}
                            </span>
                          </div>
                          <div>
                            <div className="flex items-center justify-between">
                              <span className="font-bold text-slate-500 uppercase text-[9px] tracking-wider block">Requirement ID</span>
                              {job.requirement_id && <CopyButton text={job.requirement_id} />}
                            </div>
                            <span className="mt-0.5 block truncate text-slate-300 font-mono font-medium" title={job.requirement_id}>
                              {job.requirement_id || 'N/A'}
                            </span>
                          </div>
                          <div>
                            <div className="flex items-center justify-between">
                              <span className="font-bold text-slate-500 uppercase text-[9px] tracking-wider block">Scraped At</span>
                              {job.scraped_at && <CopyButton text={job.scraped_at} />}
                            </div>
                            <span className="mt-0.5 block truncate text-slate-300 font-medium" title={job.scraped_at}>
                              {job.scraped_at ? formatScrapedDate(job.scraped_at) : 'N/A'}
                            </span>
                          </div>
                          <div>
                            <div className="flex items-center justify-between">
                              <span className="font-bold text-slate-500 uppercase text-[9px] tracking-wider block">Posted At</span>
                              {job.posted_at && <CopyButton text={job.posted_at} />}
                            </div>
                            <span className="mt-0.5 block truncate text-slate-300 font-medium" title={job.posted_at}>
                              {job.posted_at ? formatScrapedDate(job.posted_at) : 'N/A'}
                            </span>
                          </div>
                          {job.salary_text && (
                            <div>
                              <div className="flex items-center justify-between">
                                <span className="font-bold text-slate-500 uppercase text-[9px] tracking-wider block">Salary Range</span>
                                <CopyButton text={job.salary_text} />
                              </div>
                              <span className="mt-0.5 block truncate text-emerald-400 font-semibold" title={job.salary_text}>
                                {job.salary_text}
                              </span>
                            </div>
                          )}
                        </div>

                        {/* Red Flags warning if rejected */}
                        {job.red_flags && job.red_flags.length > 0 && (
                          <div className="mt-3 p-2.5 bg-rose-950/30 border border-rose-900/30 rounded-xl flex items-start space-x-2">
                            <AlertTriangle className="w-3.5 h-3.5 text-rose-400 shrink-0 mt-0.5" />
                            <div>
                              <span className="text-[10px] font-bold text-rose-400 uppercase tracking-wider block">Flags Triggered</span>
                              <div className="flex flex-wrap gap-1 mt-1">
                                {job.red_flags.map((flag, fIdx) => (
                                  <span key={fIdx} className="bg-rose-900/40 text-rose-300 px-2 py-0.5 rounded text-[9px] border border-rose-800/30 font-medium">
                                    {flag}
                                  </span>
                                ))}
                              </div>
                            </div>
                          </div>
                        )}

                        {/* Confidence Scorer */}
                        {job.confidence_score !== undefined && (
                          <div className="mt-3.5 flex items-center justify-between text-xs">
                            <span className="text-slate-400 font-medium">Policy Confidence Score:</span>
                            <div className="flex items-center space-x-1.5 font-bold">
                              <span className={
                                job.confidence_score >= 90 ? 'text-emerald-400' : job.confidence_score >= 70 ? 'text-amber-400' : 'text-rose-400'
                              }>
                                {job.confidence_score}%
                              </span>
                              <div className="w-20 bg-slate-800 rounded-full h-1.5 overflow-hidden">
                                <div
                                  className={`h-full rounded-full ${job.confidence_score >= 90 ? 'bg-emerald-500' : job.confidence_score >= 70 ? 'bg-amber-500' : 'bg-rose-500'
                                    }`}
                                  style={{ width: `${job.confidence_score}%` }}
                                />
                              </div>
                            </div>
                          </div>
                        )}

                        {/* Decision Rationale */}
                        {job.rationale && (
                          <div className="mt-3 text-xs bg-slate-950/30 p-3 rounded-xl border border-slate-850">
                            <span className="font-bold text-slate-500 uppercase text-[9px] tracking-wider block mb-1">Decision Rationale</span>
                            <p className="text-slate-300 line-clamp-3 leading-relaxed">{job.rationale}</p>
                          </div>
                        )}
                      </div>

                      {/* Card Actions Bottom */}
                      <div className="mt-5 pt-3.5 border-t border-slate-850 flex items-center justify-between">

                        {/* URL click */}
                        <a
                          href={job.job_url}
                          target="_blank"
                          rel="noreferrer"
                          className="inline-flex items-center text-xs text-violet-400 hover:text-violet-300 font-semibold group/link"
                        >
                          View Site
                          <ExternalLink className="w-3 h-3 ml-1 group-hover/link:translate-x-0.5 group-hover/link:-translate-y-0.5 transition-transform" />
                        </a>

                        <div className="flex items-center space-x-2">
                          {activeTab === 'approved' && authRole === 'admin' && (
                            <>
                              <button
                                type="button"
                                onClick={() => generateTailoring(job.job_url)}
                                className="p-1.5 bg-emerald-950/40 hover:bg-emerald-900/60 text-emerald-400 hover:text-emerald-300 border border-emerald-800/40 rounded-xl transition-all"
                                title="AI Tailor Application"
                              >
                                <FileText className="w-4 h-4" />
                              </button>
                              <ResumeGenerator
                                jd={job.job_description}
                                jobTitle={job.job_title}
                                companyName={job.company_name}
                                compact={true}
                              />
                            </>
                          )}
                          {activeTab === 'approved' && (
                            authRole === 'admin' ? (
                              <select
                                value={job.pipeline_stage || 'Approved'}
                                onChange={e => updatePipelineStage(job.job_url, e.target.value)}
                                className="bg-slate-900 border border-slate-800 rounded-xl px-2 py-1.5 text-xs text-slate-300 focus:outline-none cursor-pointer hover:border-slate-700 transition-colors"
                              >
                                {['Approved', 'Applied', 'Phone Screen', 'Technical Interview', 'Offer', 'Rejected'].map(s => (
                                  <option key={s} value={s}>{s}</option>
                                ))}
                              </select>
                            ) : (
                              <span className="inline-flex items-center text-xs font-semibold text-violet-400 bg-violet-950/40 px-2.5 py-1.5 rounded-xl border border-violet-900/30">
                                {job.pipeline_stage || 'Approved'}
                              </span>
                            )
                          )}

                          {/* Inspect details button */}
                          <button
                            onClick={() => openModal(job)}
                            className="inline-flex items-center px-3 py-1.5 bg-slate-800 hover:bg-slate-750 text-slate-300 hover:text-white rounded-xl text-xs font-semibold border border-slate-700 transition-colors"
                          >
                            <Edit3 className="w-3 h-3 mr-1" />
                            {authRole === 'admin' ? 'Inspect & Edit' : 'Inspect'}
                          </button>

                          {/* Action specific buttons */}
                          {activeTab === 'approved' ? (
                            authRole === 'admin' && (
                              <button
                                onClick={() => syncJob(job)}
                                disabled={job.synced || syncingJobUrl === job.job_url}
                                className={`inline-flex items-center px-3 py-1.5 rounded-xl text-xs font-bold shadow-md transition-all ${job.synced
                                    ? 'bg-emerald-950/20 text-emerald-400 border border-emerald-800/40 cursor-not-allowed'
                                    : syncingJobUrl === job.job_url
                                      ? 'bg-slate-800 text-slate-500 border border-slate-700 cursor-not-allowed'
                                      : 'bg-gradient-to-r from-emerald-600 to-teal-600 hover:from-emerald-500 hover:to-teal-500 text-white shadow-emerald-600/10 border border-emerald-500/20 active:scale-95'
                                  }`}
                              >
                                {job.synced ? (
                                  <>
                                    <Check className="w-3 h-3 mr-1.5" />
                                    Synced
                                  </>
                                ) : syncingJobUrl === job.job_url ? (
                                  'Syncing...'
                                ) : (
                                  <>
                                    <Database className="w-3 h-3 mr-1.5" />
                                    Sync Notion
                                  </>
                                )}
                              </button>
                            )
                          ) : (
                            /* If rejected or candidate, show quick Approve Override */
                            authRole === 'admin' && (
                              <button
                                onClick={() => {
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
                                }}
                                className="inline-flex items-center px-3 py-1.5 bg-gradient-to-r from-violet-600 to-indigo-600 hover:from-violet-500 hover:to-indigo-500 text-white rounded-xl text-xs font-bold border border-violet-500/20 active:scale-95 shadow-md shadow-violet-500/10 transition-all"
                              >
                                Approve Override
                              </button>
                            )
                          )}

                          {/* Delete/Archive Button */}
                          {authRole === 'admin' && (
                            <button
                              onClick={() => deleteJob(job.job_url)}
                              className="inline-flex items-center p-1.5 bg-rose-950/40 hover:bg-rose-900/60 text-rose-400 hover:text-rose-200 rounded-xl text-xs font-semibold border border-rose-800/40 transition-colors shrink-0"
                              title="Delete / Archive job posting"
                            >
                              <XCircle className="w-4 h-4" />
                            </button>
                          )}
                        </div>
                      </div>

                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </section>

        {/* Live Scraper Log Console */}
        <section className="bg-slate-900/40 backdrop-blur-md border border-slate-800/80 rounded-2xl shadow-xl overflow-hidden mt-6">
          <button
            type="button"
            onClick={() => setIsLogsExpanded(prev => !prev)}
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

      </main>

      {/* Footer */}
      <footer className="mt-12 bg-slate-950 border-t border-slate-800/80 px-6 py-4 flex flex-col sm:flex-row items-center justify-between text-xs text-slate-500 gap-2">
        <p>© 2026 MAAS Job Sourcing Agent Dashboard. Powered by Next.js & TailwindCSS.</p>
        <p>Current Workspace: /Users/aravind/Documents/Gemini-jobsearch</p>
      </footer>

      {/* Inspect & Override Modal */}
      {isModalOpen && selectedJob && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/70 backdrop-blur-sm p-4 overflow-y-auto">
          <div className="bg-slate-900 border border-slate-800 w-full max-w-4xl rounded-3xl shadow-2xl flex flex-col max-h-[90vh] overflow-hidden animate-in fade-in zoom-in-95 duration-200">

            {/* Modal Header */}
            <div className="px-6 py-4 border-b border-slate-800 flex items-center justify-between bg-slate-950/50">
              <div className="flex items-center space-x-2">
                <Sliders className="w-5 h-5 text-violet-400" />
                <h3 className="text-base font-bold text-white">
                  {authRole === 'admin' ? 'Inspect Candidate & Apply Manual Override' : 'Inspect Candidate'}
                </h3>
              </div>
              <button
                onClick={() => setIsModalOpen(false)}
                className="p-1 text-slate-400 hover:text-white bg-slate-800 hover:bg-slate-750 rounded-lg transition-colors text-xs font-bold px-2.5"
              >
                Close
              </button>
            </div>

            {/* Modal Body */}
            <div className="p-6 overflow-y-auto space-y-5 flex-1 select-text bg-slate-900">

              {/* Job Title */}
              <div className="space-y-1.5">
                <div className="flex items-center justify-between">
                  <label className="block text-xs font-bold text-slate-400">
                    Job Title <span className="text-red-500">*</span>
                  </label>
                  <CopyButton text={editTitle} />
                </div>
                <input
                  type="text"
                  placeholder="Role title"
                  value={editTitle}
                  onChange={e => setEditTitle(e.target.value)}
                  readOnly={authRole !== 'admin'}
                  className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3 py-2.5 text-sm text-slate-200 focus:outline-none focus:border-violet-600/70 placeholder-slate-700 read-only:text-slate-400"
                />
              </div>

              {/* Requirement ID */}
              <div className="space-y-1.5">
                <div className="flex items-center justify-between">
                  <label className="block text-xs font-bold text-slate-400">
                    Requirement ID <span className="text-red-500">*</span>
                  </label>
                  <CopyButton text={editReqId} />
                </div>
                <input
                  type="text"
                  placeholder="e.g., REQ-12345"
                  value={editReqId}
                  onChange={e => setEditReqId(e.target.value)}
                  readOnly={authRole !== 'admin'}
                  className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3 py-2.5 text-sm text-slate-200 focus:outline-none focus:border-violet-600/70 placeholder-slate-700 font-mono read-only:text-slate-400"
                />
              </div>

              {/* URL for Original Posting */}
              <div className="space-y-1.5">
                <div className="flex items-center justify-between">
                  <label className="block text-xs font-bold text-slate-400">
                    URL for Original Posting <span className="text-red-500">*</span>
                  </label>
                  <CopyButton text={editUrl} />
                </div>
                <input
                  type="text"
                  placeholder="https://careers.example.com/job/123"
                  value={editUrl}
                  onChange={e => setEditUrl(e.target.value)}
                  readOnly={authRole !== 'admin'}
                  className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3 py-2.5 text-sm text-slate-200 focus:outline-none focus:border-violet-600/70 placeholder-slate-700 read-only:text-slate-400"
                />
              </div>

              {/* Company Name */}
              <div className="space-y-1.5">
                <div className="flex items-center justify-between">
                  <label className="block text-xs font-bold text-slate-400">
                    Company Name <span className="text-red-500">*</span>
                  </label>
                  <CopyButton text={editCompany} />
                </div>
                <input
                  type="text"
                  placeholder="Company name"
                  value={editCompany}
                  onChange={e => setEditCompany(e.target.value)}
                  readOnly={authRole !== 'admin'}
                  className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3 py-2.5 text-sm text-slate-200 focus:outline-none focus:border-violet-600/70 placeholder-slate-700 read-only:text-slate-400"
                />
              </div>

              {/* Location + Work Type */}
              <div className="space-y-1.5">
                <div className="flex items-center justify-between">
                  <label className="block text-xs font-bold text-slate-400">
                    Location + Work Type <span className="text-red-500">*</span>
                  </label>
                  <CopyButton text={editLocation} />
                </div>
                <input
                  type="text"
                  placeholder="e.g., Dallas, TX — Hybrid"
                  value={editLocation}
                  onChange={e => setEditLocation(e.target.value)}
                  readOnly={authRole !== 'admin'}
                  className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3 py-2.5 text-sm text-slate-200 focus:outline-none focus:border-violet-600/70 placeholder-slate-700 read-only:text-slate-400"
                />
              </div>

              {/* Cloud, Seniority, Source Row */}
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4 pt-1">
                {/* Cloud Dropdown */}
                <div className="space-y-1.5">
                  <div className="flex items-center justify-between">
                    <label className="block text-xs font-bold text-slate-400">Cloud</label>
                    <CopyButton text={editCloud} />
                  </div>
                  <select
                    value={editCloud}
                    onChange={e => setEditCloud(e.target.value)}
                    disabled={authRole !== 'admin'}
                    className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3 py-2.5 text-sm text-slate-200 focus:outline-none focus:border-violet-600/70 cursor-pointer disabled:text-slate-400 disabled:cursor-not-allowed"
                  >
                    <option value="Not specified">Not specified</option>
                    <option value="AWS">AWS</option>
                    <option value="GCP">GCP</option>
                    <option value="Azure">Azure</option>
                    <option value="Multiple">Multiple</option>
                    <option value="Other">Other</option>
                  </select>
                </div>

                {/* Seniority Dropdown */}
                <div className="space-y-1.5">
                  <div className="flex items-center justify-between">
                    <label className="block text-xs font-bold text-slate-400">Seniority</label>
                    <CopyButton text={editSeniority} />
                  </div>
                  <select
                    value={editSeniority}
                    onChange={e => setEditSeniority(e.target.value)}
                    disabled={authRole !== 'admin'}
                    className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3 py-2.5 text-sm text-slate-200 focus:outline-none focus:border-violet-600/70 cursor-pointer disabled:text-slate-400 disabled:cursor-not-allowed"
                  >
                    <option value="Not specified">Not specified</option>
                    <option value="Junior">Junior</option>
                    <option value="Mid">Mid</option>
                    <option value="Senior">Senior</option>
                    <option value="Lead">Lead</option>
                    <option value="Staff">Staff</option>
                    <option value="Principal">Principal</option>
                    <option value="Manager/Director">Manager/Director</option>
                  </select>
                </div>

                {/* Source Dropdown */}
                <div className="space-y-1.5">
                  <div className="flex items-center justify-between">
                    <label className="block text-xs font-bold text-slate-400">Source</label>
                    <CopyButton text={editSource} />
                  </div>
                  <select
                    value={editSource}
                    onChange={e => setEditSource(e.target.value)}
                    disabled={authRole !== 'admin'}
                    className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3 py-2.5 text-sm text-slate-200 focus:outline-none focus:border-violet-600/70 cursor-pointer disabled:text-slate-400 disabled:cursor-not-allowed"
                  >
                    <option value="Not specified">Not specified</option>
                    <option value="Yahoo Sourced">Yahoo Sourced</option>
                    <option value="ATS Direct">ATS Direct</option>
                    <option value="Manual Sourced">Manual Sourced</option>
                    <option value="Lever">Lever</option>
                    <option value="Greenhouse">Greenhouse</option>
                    <option value="Ashby">Ashby</option>
                    <option value="Other">Other</option>
                  </select>
                </div>
              </div>

              {/* Job Description with Toolbar */}
              <div className="space-y-1.5">
                <div className="flex items-center justify-between">
                  <label className="block text-xs font-bold text-slate-400">
                    Job Description <span className="text-red-500">*</span>
                  </label>
                  <CopyButton text={editDesc} />
                </div>

                {/* Editor Container */}
                <div className="border border-slate-800 rounded-2xl overflow-hidden bg-slate-950 flex flex-col focus-within:border-violet-600/70 transition-colors">

                  {/* Toolbar */}
                  {authRole === 'admin' && (
                    <div className="flex flex-wrap items-center gap-1 p-2 bg-slate-900 border-b border-slate-800">
                      <button
                        type="button"
                        onClick={handleUndo}
                        disabled={historyIndex <= 0}
                        className="p-1.5 text-slate-400 hover:text-white disabled:opacity-30 disabled:hover:text-slate-400 rounded transition-colors"
                        title="Undo"
                      >
                        <Undo className="w-4 h-4" />
                      </button>
                      <button
                        type="button"
                        onClick={handleRedo}
                        disabled={historyIndex >= descHistory.length - 1}
                        className="p-1.5 text-slate-400 hover:text-white disabled:opacity-30 disabled:hover:text-slate-400 rounded transition-colors"
                        title="Redo"
                      >
                        <Redo className="w-4 h-4" />
                      </button>
                      <div className="w-px h-4 bg-slate-800 mx-1" />

                      <button
                        type="button"
                        onClick={() => handleToolbarClick('bold')}
                        className="p-1.5 text-slate-400 hover:text-white font-bold rounded transition-colors"
                        title="Bold"
                      >
                        <Bold className="w-4 h-4" />
                      </button>
                      <button
                        type="button"
                        onClick={() => handleToolbarClick('italic')}
                        className="p-1.5 text-slate-400 hover:text-white italic rounded transition-colors"
                        title="Italic"
                      >
                        <Italic className="w-4 h-4" />
                      </button>
                      <button
                        type="button"
                        onClick={() => handleToolbarClick('underline')}
                        className="p-1.5 text-slate-400 hover:text-white underline rounded transition-colors"
                        title="Underline"
                      >
                        <Underline className="w-4 h-4" />
                      </button>
                      <div className="w-px h-4 bg-slate-800 mx-1" />

                      <button
                        type="button"
                        onClick={() => handleToolbarClick('bullet')}
                        className="p-1.5 text-slate-400 hover:text-white rounded transition-colors"
                        title="Bullet List"
                      >
                        <List className="w-4 h-4" />
                      </button>
                      <button
                        type="button"
                        onClick={() => handleToolbarClick('number')}
                        className="p-1.5 text-slate-400 hover:text-white rounded transition-colors"
                        title="Numbered List"
                      >
                        <ListOrdered className="w-4 h-4" />
                      </button>
                      <button
                        type="button"
                        onClick={() => handleToolbarClick('link')}
                        className="p-1.5 text-slate-400 hover:text-white rounded transition-colors"
                        title="Insert Link"
                      >
                        <Link2 className="w-4 h-4" />
                      </button>
                      <button
                        type="button"
                        onClick={() => handleToolbarClick('clear')}
                        className="p-1.5 text-slate-400 hover:text-white rounded transition-colors"
                        title="Clear Formatting"
                      >
                        <Type className="w-4 h-4" />
                      </button>
                    </div>
                  )}

                  {/* Textarea */}
                  <textarea
                    id="job-desc-textarea"
                    rows={8}
                    placeholder="Paste full job description here..."
                    value={editDesc}
                    onChange={e => setEditDesc(e.target.value)}
                    onBlur={e => updateDescWithHistory(e.target.value)}
                    readOnly={authRole !== 'admin'}
                    className="w-full bg-transparent px-4 py-3 text-sm text-slate-300 focus:outline-none resize-y placeholder-slate-700 min-h-[180px] leading-relaxed read-only:text-slate-400"
                  />

                  {/* Status Bar */}
                  <div className="px-4 py-1.5 bg-slate-900 border-t border-slate-800 text-[10px] text-slate-500 font-mono">
                    p
                  </div>
                </div>
              </div>

              {/* Optional details and review payload Accordion */}
              <div className="border border-slate-800 rounded-2xl overflow-hidden bg-slate-950/20">
                <button
                  type="button"
                  onClick={() => setIsPayloadExpanded(!isPayloadExpanded)}
                  className="w-full px-4 py-3 flex items-center justify-between text-xs font-bold text-slate-400 hover:bg-slate-850 hover:text-slate-200 transition-all bg-slate-900/30"
                >
                  <span className="flex items-center">
                    <ChevronRight className={`w-4 h-4 mr-2 transition-transform duration-200 ${isPayloadExpanded ? 'rotate-90 text-violet-400' : 'text-slate-500'}`} />
                    Optional details and review payload
                  </span>
                </button>

                {isPayloadExpanded && (
                  <div className="p-4 border-t border-slate-850 space-y-4 bg-slate-950/40 animate-in fade-in duration-200">
                    <div>
                      <div className="flex items-center justify-between pb-1">
                        <h4 className="text-xs font-bold uppercase tracking-wider text-slate-300">
                          DECISION PAYLOAD
                        </h4>
                        <CopyButton text={editPayload} />
                      </div>
                      <p className="text-[11px] text-slate-500 mb-2 leading-relaxed">
                        Optional: paste the master classifier payload (apply_decision, labels, rationale, etc.). If it says APPLY, MAAS will trust it unless a real duplicate or policy conflict exists.
                      </p>
                      <textarea
                        rows={8}
                        value={editPayload}
                        onChange={e => setEditPayload(e.target.value)}
                        readOnly={authRole !== 'admin'}
                        className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3 py-2 text-xs text-slate-300 focus:outline-none focus:border-violet-600/70 font-mono leading-relaxed placeholder-slate-700 read-only:text-slate-400"
                        placeholder='{ "apply_decision": "APPLY", "strongest_label": "...", ... }'
                      />
                    </div>
                  </div>
                )}
              </div>

              {/* Override Decision Section */}
              <div className="border border-slate-800/80 rounded-2xl p-4 bg-slate-950/20 space-y-4">
                <h4 className="text-xs font-bold uppercase tracking-wider text-slate-400 pb-1.5 border-b border-slate-850">
                  Manual Decision Override
                </h4>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div className="space-y-1.5">
                    <label className="block text-[10px] font-bold uppercase text-slate-500">Apply Decision</label>
                    <select
                      value={editDecision}
                      onChange={e => setEditDecision(e.target.value)}
                      disabled={authRole !== 'admin'}
                      className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-violet-600/70 disabled:text-slate-400 disabled:cursor-not-allowed"
                    >
                      <option value="APPLY">APPLY (Approve)</option>
                      <option value="DO_NOT_APPLY">DO_NOT_APPLY (Reject)</option>
                    </select>
                  </div>

                  <div className="space-y-1.5">
                    <label className="block text-[10px] font-bold uppercase text-slate-500">Policy Label</label>
                    <select
                      value={editLabel}
                      onChange={e => setEditLabel(e.target.value)}
                      disabled={authRole !== 'admin'}
                      className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-violet-600/70 disabled:text-slate-400 disabled:cursor-not-allowed"
                    >
                      {CATEGORIES.map(cat => (
                        <option key={cat} value={cat}>{cat}</option>
                      ))}
                    </select>
                  </div>

                  <div className="space-y-1.5 md:col-span-2">
                    <div className="flex justify-between items-center text-[10px] font-bold uppercase text-slate-500">
                      <span>Confidence Score</span>
                      <span className="text-violet-400 font-bold">{editScore}%</span>
                    </div>
                    <div className="flex items-center space-x-4">
                      <input
                        type="range"
                        min="0"
                        max="100"
                        value={editScore}
                        onChange={e => setEditScore(Number(e.target.value))}
                        disabled={authRole !== 'admin'}
                        className="flex-1 accent-violet-600 bg-slate-950 h-2 rounded-lg appearance-none cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
                      />
                      <input
                        type="number"
                        min="0"
                        max="100"
                        value={editScore}
                        onChange={e => setEditScore(Number(e.target.value))}
                        readOnly={authRole !== 'admin'}
                        className="w-16 bg-slate-950 border border-slate-800 rounded-xl px-2 py-1 text-center text-xs text-slate-200 focus:outline-none focus:border-violet-600/70 read-only:text-slate-400"
                      />
                    </div>
                  </div>

                  <div className="space-y-1.5 md:col-span-2">
                    <label className="block text-[10px] font-bold uppercase text-slate-500">Override Rationale</label>
                    <textarea
                      rows={3}
                      value={editRationale}
                      onChange={e => setEditRationale(e.target.value)}
                      readOnly={authRole !== 'admin'}
                      className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-violet-600/70 placeholder-slate-700 read-only:text-slate-400"
                      placeholder="Write details explaining the manual approval or classification adjustments..."
                    />
                  </div>
                </div>
              </div>

            </div>

            {/* Modal Footer */}
            <div className="px-6 py-4 border-t border-slate-800 flex justify-end items-center space-x-3 bg-slate-950/50">
              {selectedJob.apply_decision === 'APPLY' && authRole === 'admin' && (
                <div className="mr-auto flex items-center space-x-2">
                  <button
                    type="button"
                    onClick={() => {
                      setIsModalOpen(false);
                      generateTailoring(selectedJob.job_url);
                    }}
                    className="inline-flex items-center px-4 py-2 bg-gradient-to-r from-emerald-600 to-teal-600 hover:from-emerald-500 hover:to-teal-500 text-white rounded-xl text-xs font-bold border border-emerald-500/20 active:scale-95 shadow-md transition-all"
                  >
                    <FileText className="w-4 h-4 mr-2" />
                    AI Tailor Application
                  </button>
                  <ResumeGenerator
                    jd={selectedJob.job_description}
                    jobTitle={selectedJob.job_title}
                    companyName={selectedJob.company_name}
                    compact={false}
                  />
                </div>
              )}
              <button
                onClick={() => setIsModalOpen(false)}
                className="px-4 py-2 bg-slate-800 hover:bg-slate-750 text-slate-300 hover:text-white rounded-xl text-xs font-semibold border border-slate-700 transition-all"
              >
                {authRole === 'admin' ? 'Cancel' : 'Close'}
              </button>
              {authRole === 'admin' && (
                <button
                  onClick={submitOverride}
                  className="inline-flex items-center px-6 py-2 bg-gradient-to-r from-violet-600 to-indigo-600 hover:from-violet-500 hover:to-indigo-500 text-white rounded-xl text-xs font-bold border border-violet-500/20 active:scale-95 shadow-md shadow-violet-500/10 transition-all"
                >
                  <Check className="w-4 h-4 mr-2" />
                  Apply Override Changes
                </button>
              )}
            </div>

          </div>
        </div>
      )}

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
                          copyToClipboard(tailoredCoverLetter);
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
                                    copyToClipboard(s.suggested_bullet);
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

    </div>
  );
}
