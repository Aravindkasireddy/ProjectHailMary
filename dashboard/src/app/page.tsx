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
  Send, 
  Check, 
  Sliders, 
  ChevronRight, 
  FileText,
  BellRing,
  Info,
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
  Type
} from 'lucide-react';

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8080';

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
  apply_decision_payload?: any;
  synced?: boolean;
  synced_data?: any;
  scraped_at?: string;
  stale?: boolean;
  archived?: boolean;
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

const CopyButton = ({ text }: { text: string }) => {
  const [copied, setCopied] = useState(false);
  const handleCopy = () => {
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
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

  // Analytics and Policy States
  const [analyticsData, setAnalyticsData] = useState<any>(null);
  const [analyticsLoading, setAnalyticsLoading] = useState(false);
  const [policyConfig, setPolicyConfig] = useState<any>(null);
  const [policyLoading, setPolicyLoading] = useState(false);

  const fetchAnalytics = async () => {
    setAnalyticsLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/analytics`);
      if (res.ok) {
        const data = await res.json();
        setAnalyticsData(data);
      }
    } catch (e) {
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
    } catch (e) {
      showStatus('Failed to load policy config.', 'error');
    } finally {
      setPolicyLoading(false);
    }
  };

  const savePolicyConfig = async (updatedPolicy: any) => {
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
    } catch (e) {
      showStatus('Failed to save policy configuration.', 'error');
    }
  };
  const [config, setConfig] = useState<Config>({
    target_titles: [],
    scheduler: { enabled: true, run_at_hour: 8, run_at_minute: 0 },
    webhook_url: ''
  });
  const [syncedJobs, setSyncedJobs] = useState<Record<string, any>>({});
  const [scraperStatus, setScraperStatus] = useState({
    status: 'idle',
    message: 'Ready.',
    last_error: null as string | null,
    last_metrics: {} as Record<string, number>,
  });
  const [notionConnection, setNotionConnection] = useState({ connected: false, message: 'Checking...', dbName: '' });
  const [searchTerm, setSearchTerm] = useState('');
  const [activeTab, setActiveTab] = useState<'approved' | 'pending' | 'rejected' | 'settings' | 'analytics' | 'policy'>('approved');
  const [selectedRoleFilter, setSelectedRoleFilter] = useState('all');
  const [sortBy, setSortBy] = useState<'newest' | 'oldest'>('newest');
  const [scrapedTimeframe, setScrapedTimeframe] = useState<'all' | 'today' | 'week' | 'month'>('all');
  const [staleCheckStatus, setStaleCheckStatus] = useState({ status: 'idle', progress: 0, total: 0, completed: 0, stale_found: 0 });
  const [showActiveOnly, setShowActiveOnly] = useState(true);

  useEffect(() => {
    setSelectedRoleFilter('all');
    if (activeTab === 'analytics') {
      fetchAnalytics();
    } else if (activeTab === 'policy') {
      fetchPolicy();
    }
  }, [activeTab]);
  
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
  const [loading, setLoading] = useState(false);
  const [syncingJobUrl, setSyncingJobUrl] = useState<string | null>(null);
  const [testingWebhook, setTestingWebhook] = useState(false);
  const [statusMessage, setStatusMessage] = useState<{ text: string; type: 'success' | 'error' | 'info' } | null>(null);

  // Fetch Jobs & Config
  const fetchData = async () => {
    setLoading(true);
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
    } catch (error) {
      showStatus('Failed to communicate with local dashboard API.', 'error');
    } finally {
      setLoading(false);
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
    } catch (e) {
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
    } catch (e) {}
  };

  // Poll scraper status when it is running
  useEffect(() => {
    let interval: NodeJS.Timeout;
    if (scraperStatus.status === 'running') {
      interval = setInterval(() => {
        checkScraperStatus();
        // Periodically refresh jobs list too
        fetch(`${API_BASE}/api/jobs`)
          .then(res => res.ok && res.json())
          .then(data => data && setJobs(data));
      }, 2000);
    }
    return () => clearInterval(interval);
  }, [scraperStatus.status]);

  useEffect(() => {
    fetchData();
  }, []);

  const showStatus = (text: string, type: 'success' | 'error' | 'info') => {
    setStatusMessage({ text, type });
    setTimeout(() => setStatusMessage(null), 5000);
  };

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
    } catch (error) {
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
    } catch (error) {
      showStatus('Failed to trigger stale check.', 'error');
    }
  };

  const checkStaleStatus = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/stale-status`);
      if (res.ok) {
        const data = await res.json();
        setStaleCheckStatus(data);
      }
    } catch (e) {}
  };

  // Poll stale check status when it is running
  useEffect(() => {
    let interval: NodeJS.Timeout;
    if (staleCheckStatus.status === 'running') {
      interval = setInterval(() => {
        checkStaleStatus();
        // Periodically refresh jobs list too
        fetch(`${API_BASE}/api/jobs`)
          .then(res => res.ok && res.json())
          .then(data => data && setJobs(data));
      }, 2000);
    }
    return () => clearInterval(interval);
  }, [staleCheckStatus.status]);

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
    } catch (e) {
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
    } catch (e) {
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
    } catch (e) {
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
    } catch (e) {
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
    const jobCloud = (job as any).cloud || job.apply_decision_payload?.cloud?.primary_cloud || 'Not specified';
    setEditCloud(jobCloud);

    // Parse seniority from custom property or fallback
    const jobSeniority = (job as any).seniority || 'Not specified';
    setEditSeniority(jobSeniority);

    // Determine source
    let defaultSource = (job as any).source;
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
    } catch (e) {
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
    } catch (e) {
      showStatus('Failed to send classification override.', 'error');
    }
  };

  // Categorize jobs
  const approvedJobs = jobs.filter(j => !j.archived && j.apply_decision === 'APPLY' && (!j.red_flags || j.red_flags.length === 0));
  const rejectedJobs = jobs.filter(j => !j.archived && (j.apply_decision === 'DO_NOT_APPLY' || (j.red_flags && j.red_flags.length > 0)));
  const pendingJobs = jobs.filter(j => !j.archived && j.apply_decision !== 'APPLY' && j.apply_decision !== 'DO_NOT_APPLY');

  const filteredJobs = () => {
    let list = activeTab === 'approved' ? approvedJobs : activeTab === 'rejected' ? rejectedJobs : pendingJobs;
    
    // Filter out stale/closed jobs if showActiveOnly is enabled
    if (activeTab === 'approved' && showActiveOnly) {
      list = list.filter(j => !j.stale);
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
    } catch (e) {
      return dateStr;
    }
  };

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
          <button
            onClick={triggerStaleCheck}
            disabled={staleCheckStatus.status === 'running'}
            className={`inline-flex items-center px-4 py-1.5 rounded-xl text-xs font-semibold shadow-md transition-all ${
              staleCheckStatus.status === 'running'
                ? 'bg-slate-800 text-slate-500 border border-slate-700 cursor-not-allowed'
                : 'bg-slate-900/90 hover:bg-slate-800 text-slate-200 border border-slate-700 hover:border-slate-600 active:scale-95'
            }`}
          >
            <RefreshCw className={`w-3.5 h-3.5 mr-1.5 ${staleCheckStatus.status === 'running' ? 'animate-spin' : ''}`} />
            Check Closed Jobs
          </button>

          {/* Manual Run button */}
          <button
            onClick={triggerScrape}
            disabled={scraperStatus.status === 'running'}
            className={`inline-flex items-center px-4 py-1.5 rounded-xl text-xs font-semibold shadow-md transition-all ${
              scraperStatus.status === 'running'
                ? 'bg-slate-800 text-slate-500 border border-slate-700 cursor-not-allowed'
                : 'bg-gradient-to-r from-violet-600 to-indigo-600 hover:from-violet-500 hover:to-indigo-500 text-white shadow-violet-600/10 border border-violet-500/20 active:scale-95'
            }`}
          >
            <RefreshCw className={`w-3.5 h-3.5 mr-1.5 ${scraperStatus.status === 'running' ? 'animate-spin' : ''}`} />
            Run Sourcing Agent
          </button>
        </div>
      </header>

      {/* Floating Status Message */}
      {statusMessage && (
        <div className={`fixed bottom-6 right-6 z-50 flex items-center space-x-2 px-4 py-3 rounded-xl border shadow-xl animate-bounce ${
          statusMessage.type === 'success' 
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
        
        {scraperStatus.status === 'failed' && (scraperStatus as any).last_error && (
          <div className="bg-rose-500/10 border border-rose-500/30 p-4 rounded-2xl text-rose-200 text-xs font-mono whitespace-pre-wrap max-h-40 overflow-y-auto">
            <p className="font-semibold text-rose-300 mb-1">Last pipeline error</p>
            {(scraperStatus as any).last_error}
          </div>
        )}

        {(scraperStatus as any).last_metrics && Object.keys((scraperStatus as any).last_metrics || {}).length > 0 && scraperStatus.status !== 'running' && (
          <div className="bg-slate-900/50 border border-slate-800 p-3 rounded-xl text-xs text-slate-400">
            Last run counts:{' '}
            {Object.entries((scraperStatus as any).last_metrics)
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
        <section className="flex flex-col md:flex-row items-stretch md:items-center justify-between bg-slate-900/30 backdrop-blur-md border border-slate-800/80 p-3 rounded-2xl gap-4 shadow-xl">
          
          {/* Navigation Tabs */}
          <div className="flex bg-slate-950 p-1.5 rounded-xl border border-slate-800/50 flex-wrap gap-1">
            <button
              onClick={() => setActiveTab('approved')}
              className={`flex items-center px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${
                activeTab === 'approved' 
                  ? 'bg-gradient-to-r from-violet-600 to-indigo-600 text-white shadow-md' 
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              Approved ({approvedJobs.length})
            </button>
            <button
              onClick={() => setActiveTab('pending')}
              className={`flex items-center px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${
                activeTab === 'pending' 
                  ? 'bg-gradient-to-r from-violet-600 to-indigo-600 text-white shadow-md' 
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              Unreviewed ({pendingJobs.length})
            </button>
            <button
              onClick={() => setActiveTab('rejected')}
              className={`flex items-center px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${
                activeTab === 'rejected' 
                  ? 'bg-gradient-to-r from-violet-600 to-indigo-600 text-white shadow-md' 
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              Filtered ({rejectedJobs.length})
            </button>
            <button
              onClick={() => setActiveTab('analytics')}
              className={`flex items-center px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${
                activeTab === 'analytics' 
                  ? 'bg-gradient-to-r from-violet-600 to-indigo-600 text-white shadow-md' 
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              <BarChart3 className="w-3.5 h-3.5 mr-1" />
              Analytics
            </button>
            <button
              onClick={() => setActiveTab('policy')}
              className={`flex items-center px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${
                activeTab === 'policy' 
                  ? 'bg-gradient-to-r from-violet-600 to-indigo-600 text-white shadow-md' 
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              <Shield className="w-3.5 h-3.5 mr-1" />
              Classifier Policy
            </button>
            <button
              onClick={() => setActiveTab('settings')}
              className={`flex items-center px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${
                activeTab === 'settings' 
                  ? 'bg-gradient-to-r from-violet-600 to-indigo-600 text-white shadow-md' 
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              <SettingsIcon className="w-3.5 h-3.5 mr-1" />
              Settings
            </button>
          </div>

          {/* Search bar & Category filter */}
          {activeTab !== 'settings' && (
            <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-3 flex-1 md:max-w-2xl">
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
                  className={`inline-flex items-center px-4 py-2 border rounded-xl text-sm font-semibold transition-colors shrink-0 shadow-inner ${
                    showActiveOnly 
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
        <section className="flex-1 flex flex-col">
          {activeTab === 'analytics' ? (
            <div className="space-y-6">
              {analyticsLoading || !analyticsData ? (
                <div className="flex-1 flex flex-col items-center justify-center p-12 text-center border border-slate-800 rounded-2xl bg-slate-900/10">
                  <RefreshCw className="w-10 h-10 text-violet-500 animate-spin mb-3" />
                  <p className="text-sm text-slate-400 font-medium">Computing sourcing metrics & analytics...</p>
                </div>
              ) : (
                <div className="space-y-6 animate-in fade-in duration-300">
                  
                  {/* Cards Row */}
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                    <div className="bg-slate-900/30 border border-slate-800 p-5 rounded-2xl shadow-lg">
                      <p className="text-xs text-slate-400 font-medium uppercase tracking-wider">Total Sourced</p>
                      <h3 className="text-2xl font-extrabold text-white mt-1">{analyticsData.total_sourced}</h3>
                      <p className="text-[10px] text-slate-500 mt-1">Jobs parsed by platform</p>
                    </div>
                    <div className="bg-slate-900/30 border border-slate-800 p-5 rounded-2xl shadow-lg">
                      <p className="text-xs text-slate-400 font-medium uppercase tracking-wider">Approved Jobs</p>
                      <h3 className="text-2xl font-extrabold text-emerald-400 mt-1">{analyticsData.approved}</h3>
                      <p className="text-[10px] text-slate-500 mt-1">Passed all policy filters</p>
                    </div>
                    <div className="bg-slate-900/30 border border-slate-800 p-5 rounded-2xl shadow-lg">
                      <p className="text-xs text-slate-400 font-medium uppercase tracking-wider">Rejected Jobs</p>
                      <h3 className="text-2xl font-extrabold text-rose-400 mt-1">{analyticsData.rejected}</h3>
                      <p className="text-[10px] text-slate-500 mt-1">Failed experience/auth checks</p>
                    </div>
                    <div className="bg-slate-900/30 border border-slate-800 p-5 rounded-2xl shadow-lg">
                      <p className="text-xs text-slate-400 font-medium uppercase tracking-wider">Approval Rate</p>
                      <h3 className="text-2xl font-extrabold text-violet-400 mt-1">{analyticsData.approval_rate}%</h3>
                      <p className="text-[10px] text-slate-500 mt-1">Sourcing qualification yield</p>
                    </div>
                  </div>

                  {/* Charts Grid */}
                  <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                    
                    {/* Role Labels Distribution */}
                    <div className="bg-slate-900/30 border border-slate-800 p-6 rounded-3xl shadow-xl space-y-4">
                      <div className="flex items-center space-x-2 border-b border-slate-800 pb-3">
                        <Briefcase className="w-5 h-5 text-violet-400" />
                        <h3 className="text-sm font-bold text-white">Approved Job Labels Distribution</h3>
                      </div>
                      <div className="space-y-3.5 max-h-[300px] overflow-y-auto pr-2">
                        {Object.entries(analyticsData.labels_distribution).length === 0 ? (
                          <p className="text-xs text-slate-500 text-center py-6">No approved jobs available for distribution.</p>
                        ) : (
                          Object.entries(analyticsData.labels_distribution)
                            .sort((a: any, b: any) => b[1] - a[1])
                            .map(([label, count]: any) => {
                              const pct = analyticsData.approved > 0 ? (count / analyticsData.approved * 100).toFixed(1) : 0;
                              return (
                                <div key={label} className="space-y-1">
                                  <div className="flex justify-between text-xs font-medium">
                                    <span className="text-slate-300">{label}</span>
                                    <span className="text-slate-400">{count} jobs ({pct}%)</span>
                                  </div>
                                  <div className="h-2 w-full bg-slate-950 rounded-full overflow-hidden border border-slate-800/40">
                                    <div className="h-full bg-gradient-to-r from-violet-600 to-indigo-600 rounded-full" style={{ width: `${pct}%` }} />
                                  </div>
                                </div>
                              );
                            })
                        )}
                      </div>
                    </div>

                    {/* Scraper Sources Distribution */}
                    <div className="bg-slate-900/30 border border-slate-800 p-6 rounded-3xl shadow-xl space-y-4">
                      <div className="flex items-center space-x-2 border-b border-slate-800 pb-3">
                        <Database className="w-5 h-5 text-violet-400" />
                        <h3 className="text-sm font-bold text-white">Scraper Sources Yield</h3>
                      </div>
                      
                      <div className="flex items-end justify-between h-48 pt-6 pb-2 px-4 gap-2 bg-slate-950/40 rounded-2xl border border-slate-800/40">
                        {Object.entries(analyticsData.sources_distribution).length === 0 ? (
                          <p className="text-xs text-slate-500 text-center w-full py-16">No sourced listings available.</p>
                        ) : (
                          Object.entries(analyticsData.sources_distribution).map(([src, count]: any) => {
                            const maxVal = Math.max(...(Object.values(analyticsData.sources_distribution) as number[]));
                            const heightPct = maxVal > 0 ? (count / maxVal * 100) : 0;
                            return (
                              <div key={src} className="flex-1 flex flex-col items-center group relative h-full justify-end">
                                <div className="absolute bottom-full mb-1 opacity-0 group-hover:opacity-100 transition-opacity bg-slate-900 border border-slate-700 text-slate-100 text-[10px] font-bold py-1 px-2 rounded shadow-xl pointer-events-none z-10 whitespace-nowrap">
                                  {count} jobs
                                </div>
                                <div 
                                  className="w-full bg-gradient-to-t from-violet-600 to-indigo-500 rounded-t-lg group-hover:from-violet-500 group-hover:to-indigo-400 transition-all duration-500" 
                                  style={{ height: `${Math.max(heightPct, 5)}%` }}
                                />
                                <span className="text-[9px] text-slate-500 font-bold uppercase tracking-wider mt-2 truncate w-full text-center">
                                  {src.split(' ')[0]}
                                </span>
                              </div>
                            );
                          })
                        )}
                      </div>
                    </div>

                    {/* Rejection Reasons */}
                    <div className="bg-slate-900/30 border border-slate-800 p-6 rounded-3xl shadow-xl space-y-4 lg:col-span-2">
                      <div className="flex items-center space-x-2 border-b border-slate-800 pb-3">
                        <AlertTriangle className="w-5 h-5 text-rose-400" />
                        <h3 className="text-sm font-bold text-white">Rejection Policy Failures Breakdown</h3>
                      </div>
                      
                      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                        {Object.entries(analyticsData.rejection_reasons)
                          .filter(([_, count]: any) => count > 0)
                          .sort((a: any, b: any) => b[1] - a[1])
                          .map(([reason, count]: any) => {
                            const maxVal = Math.max(...(Object.values(analyticsData.rejection_reasons) as number[]));
                            const pct = maxVal > 0 ? (count / maxVal * 100).toFixed(1) : 0;
                            return (
                              <div key={reason} className="bg-slate-950/30 border border-slate-800/40 p-3 rounded-xl space-y-2">
                                <div className="flex justify-between text-xs font-semibold">
                                  <span className="text-slate-300 truncate max-w-[220px]">{reason}</span>
                                  <span className="text-rose-400 font-bold">{count} flags ({pct}%)</span>
                                </div>
                                <div className="h-1.5 w-full bg-slate-950 rounded-full overflow-hidden">
                                  <div className="h-full bg-rose-600 rounded-full" style={{ width: `${pct}%` }} />
                                </div>
                              </div>
                            );
                          })}
                        
                        {Object.values(analyticsData.rejection_reasons).every(v => v === 0) && (
                          <p className="text-xs text-slate-500 text-center py-6 w-full col-span-2">No rejected jobs logged yet.</p>
                        )}
                      </div>
                    </div>

                  </div>

                </div>
              )}
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
                          <span className="text-[9px] text-slate-500 block mt-0.5">Reject jobs that explicitly state "no sponsorship" or "cannot sponsor"</span>
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
                          <span className="text-[9px] text-slate-500 block mt-0.5">Reject roles requesting "Active Secret/TS Clearance" or government eligibility</span>
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
          ) : (
            
            /* Jobs List Cards Grid */
            <div className="flex-1 flex flex-col">
              {filteredJobs().length === 0 ? (
                <div className="flex-1 flex flex-col items-center justify-center border border-dashed border-slate-800 rounded-2xl p-12 text-center bg-slate-900/10">
                  <Briefcase className="w-12 h-12 text-slate-600 mb-3" />
                  <h3 className="text-sm font-bold text-slate-400">No Job Postings Found</h3>
                  <p className="text-xs text-slate-500 max-w-sm mt-1">
                    {searchTerm ? 'No results matched your search term.' : 'Try running the sourcing agent to scrape jobs or override filter settings.'}
                  </p>
                </div>
              ) : (
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                  {filteredJobs().map((job, idx) => (
                    
                    /* Job Card */
                    <div 
                      key={job.job_url + idx}
                      className={`relative bg-slate-900/30 backdrop-blur-md rounded-2xl p-5 border flex flex-col justify-between shadow-lg hover:shadow-2xl transition-all duration-300 group ${
                        activeTab === 'approved' 
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
                            <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wider ${
                              activeTab === 'approved'
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
                        <div className="mt-3 grid grid-cols-3 gap-3 text-xs text-slate-400 bg-slate-950/50 p-2.5 rounded-xl border border-slate-800/40">
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
                                  className={`h-full rounded-full ${
                                    job.confidence_score >= 90 ? 'bg-emerald-500' : job.confidence_score >= 70 ? 'bg-amber-500' : 'bg-rose-500'
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
                          {/* Inspect details button */}
                          <button
                            onClick={() => openModal(job)}
                            className="inline-flex items-center px-3 py-1.5 bg-slate-800 hover:bg-slate-750 text-slate-300 hover:text-white rounded-xl text-xs font-semibold border border-slate-700 transition-colors"
                          >
                            <Edit3 className="w-3 h-3 mr-1" />
                            Inspect & Edit
                          </button>

                          {/* Action specific buttons */}
                          {activeTab === 'approved' ? (
                            <button
                              onClick={() => syncJob(job)}
                              disabled={job.synced || syncingJobUrl === job.job_url}
                              className={`inline-flex items-center px-3 py-1.5 rounded-xl text-xs font-bold shadow-md transition-all ${
                                job.synced
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
                          ) : (
                            /* If rejected or candidate, show quick Approve Override */
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
                          )}

                          {/* Delete/Archive Button */}
                          <button
                            onClick={() => deleteJob(job.job_url)}
                            className="inline-flex items-center p-1.5 bg-rose-950/40 hover:bg-rose-900/60 text-rose-400 hover:text-rose-200 rounded-xl text-xs font-semibold border border-rose-800/40 transition-colors shrink-0"
                            title="Delete / Archive job posting"
                          >
                            <XCircle className="w-4 h-4" />
                          </button>
                        </div>
                      </div>

                    </div>
                  ))}
                </div>
              )}
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
                <h3 className="text-base font-bold text-white">Inspect Candidate & Apply Manual Override</h3>
              </div>
              <button
                onClick={() => setIsModalOpen(false)}
                className="p-1 text-slate-400 hover:text-white bg-slate-800 hover:bg-slate-700 rounded-lg transition-colors text-xs font-bold px-2.5"
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
                  className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3 py-2.5 text-sm text-slate-200 focus:outline-none focus:border-violet-600/70 placeholder-slate-700"
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
                  className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3 py-2.5 text-sm text-slate-200 focus:outline-none focus:border-violet-600/70 placeholder-slate-700 font-mono"
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
                  className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3 py-2.5 text-sm text-slate-200 focus:outline-none focus:border-violet-600/70 placeholder-slate-700"
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
                  className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3 py-2.5 text-sm text-slate-200 focus:outline-none focus:border-violet-600/70 placeholder-slate-700"
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
                  className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3 py-2.5 text-sm text-slate-200 focus:outline-none focus:border-violet-600/70 placeholder-slate-700"
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
                    className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3 py-2.5 text-sm text-slate-200 focus:outline-none focus:border-violet-600/70 cursor-pointer"
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
                    className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3 py-2.5 text-sm text-slate-200 focus:outline-none focus:border-violet-600/70 cursor-pointer"
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
                    className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3 py-2.5 text-sm text-slate-200 focus:outline-none focus:border-violet-600/70 cursor-pointer"
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
                  
                  {/* Textarea */}
                  <textarea
                    id="job-desc-textarea"
                    rows={8}
                    placeholder="Paste full job description here..."
                    value={editDesc}
                    onChange={e => setEditDesc(e.target.value)}
                    onBlur={e => updateDescWithHistory(e.target.value)}
                    className="w-full bg-transparent px-4 py-3 text-sm text-slate-300 focus:outline-none resize-y placeholder-slate-700 min-h-[180px] leading-relaxed"
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
                        className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3 py-2 text-xs text-slate-300 focus:outline-none focus:border-violet-600/70 font-mono leading-relaxed placeholder-slate-700"
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
                      className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-violet-600/70"
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
                      className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-violet-600/70"
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
                        className="flex-1 accent-violet-600 bg-slate-950 h-2 rounded-lg appearance-none cursor-pointer"
                      />
                      <input
                        type="number"
                        min="0"
                        max="100"
                        value={editScore}
                        onChange={e => setEditScore(Number(e.target.value))}
                        className="w-16 bg-slate-950 border border-slate-800 rounded-xl px-2 py-1 text-center text-xs text-slate-200 focus:outline-none focus:border-violet-600/70"
                      />
                    </div>
                  </div>

                  <div className="space-y-1.5 md:col-span-2">
                    <label className="block text-[10px] font-bold uppercase text-slate-500">Override Rationale</label>
                    <textarea
                      rows={3}
                      value={editRationale}
                      onChange={e => setEditRationale(e.target.value)}
                      className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-violet-600/70 placeholder-slate-700"
                      placeholder="Write details explaining the manual approval or classification adjustments..."
                    />
                  </div>
                </div>
              </div>

            </div>

            {/* Modal Footer */}
            <div className="px-6 py-4 border-t border-slate-800 flex justify-end space-x-3 bg-slate-950/50">
              <button
                onClick={() => setIsModalOpen(false)}
                className="px-4 py-2 bg-slate-800 hover:bg-slate-750 text-slate-300 hover:text-white rounded-xl text-xs font-semibold border border-slate-700 transition-all"
              >
                Cancel
              </button>
              <button
                onClick={submitOverride}
                className="inline-flex items-center px-6 py-2 bg-gradient-to-r from-violet-600 to-indigo-600 hover:from-violet-500 hover:to-indigo-500 text-white rounded-xl text-xs font-bold border border-violet-500/20 active:scale-95 shadow-md shadow-violet-500/10 transition-all"
              >
                <Check className="w-4 h-4 mr-2" />
                Apply Override Changes
              </button>
            </div>

          </div>
        </div>
      )}

    </div>
  );
}
