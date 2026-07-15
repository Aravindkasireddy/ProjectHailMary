export const CATEGORIES = [
  'DevOps Engineer',
  'Cloud Automation Engineer',
  'Platform Engineering',
  'Cloud Infrastructure Engineer',
  'DevSecOps',
  'Site Reliability Engineer (SRE)',
  'Continuous Integration (CI/CD)',
  'System Engineer',
  'OutOfScope',
];

export const SCRAPE_TIMEFRAME_OPTIONS = [
  { value: 'all', label: 'All Times' },
  { value: 'recent', label: 'Sourced: Last 4 Hours' },
  { value: 'today', label: 'Sourced: Last 24 Hours' },
  { value: 'posted_today', label: 'Posted: Last 24 Hours' },
  { value: 'week', label: 'Sourced: Last 7 Days' },
  { value: 'posted_week', label: 'Posted: Last 7 Days' },
  { value: 'month', label: 'Sourced: Last 30 Days' },
] as const;

export type ScrapedTimeframe = (typeof SCRAPE_TIMEFRAME_OPTIONS)[number]['value'];

export const FILTER_PRESETS = [
  {
    id: 'high_fit',
    label: '⚡ High-Fit',
    tooltip: 'Confidence ≥ 85%',
    apply: () => ({ confidenceBandFilter: 'high' as const, remoteOnlyFilter: false, scrapedTimeframe: 'all' as const }),
  },
  {
    id: 'fresh',
    label: '🌱 Fresh Jobs',
    tooltip: 'Sourced in the last 24 h',
    apply: () => ({ confidenceBandFilter: 'all' as const, remoteOnlyFilter: false, scrapedTimeframe: 'today' as const }),
  },
  {
    id: 'remote',
    label: '🌐 Remote-First',
    tooltip: 'Remote location only',
    apply: () => ({ confidenceBandFilter: 'all' as const, remoteOnlyFilter: true, scrapedTimeframe: 'all' as const }),
  },
  {
    id: 'review',
    label: '🔍 Needs Review',
    tooltip: 'Borderline confidence — worth a second look',
    apply: () => ({ confidenceBandFilter: 'borderline' as const, remoteOnlyFilter: false, scrapedTimeframe: 'all' as const }),
  },
];

export const NON_US_TERMS = [
  'india', 'bangalore', 'bengaluru', 'hyderabad', 'pune', 'mumbai', 'delhi', 'chennai', 'gurugram', 'gurgaon', 'noida',
  'uk', 'london', 'united kingdom', 'england', 'scotland', 'wales',
  'canada', 'toronto', 'vancouver', 'montreal', 'ottawa', 'calgary',
  'germany', 'berlin', 'munich', 'frankfurt',
  'france', 'paris',
  'australia', 'sydney', 'melbourne', 'brisbane', 'perth',
  'singapore', 'japan', 'tokyo', 'china', 'beijing', 'shanghai',
  'ireland', 'dublin', 'netherlands', 'amsterdam', 'poland', 'warsaw', 'krakow',
  'brazil', 'sao paulo', 'mexico', 'colombia', 'argentina', 'chile',
  'emea', 'apac', 'latam', 'europe', 'asia', 'africa',
  'philippines', 'manila', 'indonesia', 'jakarta', 'malaysia', 'kuala lumpur',
  'ukraine', 'romania', 'bulgaria', 'serbia', 'croatia', 'czech',
  'sweden', 'norway', 'finland', 'denmark', 'switzerland', 'austria', 'belgium',
  'spain', 'madrid', 'barcelona', 'portugal', 'lisbon', 'italy', 'rome', 'milan',
  'israel', 'tel aviv', 'dubai', 'uae', 'saudi arabia', 'south africa', 'egypt',
  'new zealand', 'auckland',
];
