export type TabId =
  | 'approved'
  | 'new_today'
  | 'applications'
  | 'pending'
  | 'rejected'
  | 'human_review'
  | 'settings'
  | 'analytics'
  | 'policy'
  | 'resume';

export interface DecisionPayload {
  apply_decision?: string;
  strongest_label?: string;
  red_flags?: string[];
  confidence_score?: number;
  rationale?: string;
  recommendation?: string;
  fit_score?: number;
  ownership_strength?: string;
  review_reason?: string;
  cloud?: {
    primary_cloud?: string;
  };
  [key: string]: unknown;
}

export interface Job {
  job_title: string;
  company_name: string;
  job_url: string;
  requirement_id: string;
  job_description: string;
  location_work_type: string;
  apply_decision: string;
  strongest_label: string;
  confidence_score: number;
  match_score?: number;
  rationale: string;
  red_flags?: string[];
  apply_decision_payload?: DecisionPayload;
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
  visa_sponsor?: boolean;
  sponsor_metadata?: SponsorMetadata;
  salary_text?: string;
  job_id?: string;
  description_hash?: string;
  id?: string;
  /** Set by near_dedup.group_and_flag_duplicates on the backend; the original is kept. */
  is_duplicate?: boolean;
  duplicate_of?: string | null;
  /** Last on-demand HTTP probe from /api/job/check-live */
  listing_health?: {
    uncertain: boolean;
    reason?: string;
    checked_at: string;
    http_status?: number | null;
  };
  application_status?: 'applied' | 'phone_screen' | 'interview' | 'offer' | 'rejected' | null;
  applied_at?: string | null;
  application_notes?: string | null;
}

export interface SponsorMetadata {
  id?: string;
  company_name: string;
  company_type?: string;
  w2_contractor?: string;
  employee_count?: number;
  linkedin_account?: string;
  career_portal?: string;
  website?: string;
  sponsor_status?: string;
  recommended_action?: string;
  opt_friendly_score?: number;
  cases_2024?: number;
  cases_2025?: number;
  cases_2026?: number;
  recent_cases?: number;
  recent_approvals?: number;
  trend_label?: string;
  top_state?: string;
}

export interface AnalyticsData {
  total_sourced: number;
  approved: number;
  rejected: number;
  approval_rate: number;
  labels_distribution: Record<string, number>;
  sources_distribution: Record<string, number>;
  rejection_reasons: Record<string, number>;
}

export interface PolicyConfig {
  max_experience_years: number;
  min_salary_annual: number;
  min_salary_hourly: number;
  enforce_visa_sponsorship: boolean;
  enforce_no_clearance: boolean;
  custom_red_flag_keywords: string[];
}

export interface Config {
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
    jooble_api_key?: string;
    official_career_job_urls_only?: boolean;
  };
}

export interface ScraperStatus {
  status: string;
  message: string;
  last_error: string | null;
  last_run: string | null;
  last_metrics: Record<string, number>;
}

export interface StaleCheckStatus {
  status: string;
  progress: number;
  total: number;
  completed: number;
  stale_found: number;
}

export interface SalaryInsights {
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
}
