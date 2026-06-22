"""H1B sponsor company-name cleaning and fuzzy matching helpers.

Extracted verbatim from dashboard_server.py.
"""
import re
import time

# Module-level cache (was module-level globals in dashboard_server.py)
_cached_sponsors_cleaned = None
_cached_sponsors_time = 0.0


def clean_company_name(name: str) -> str:
    if not name:
        return ""
    name = name.lower()
    # Remove common punctuation
    name = re.sub(r'[,.\-\(\)]', ' ', name)
    # Remove common corporate suffixes
    suffixes = [
        r'\binc\b', r'\bllc\b', r'\bcorp\b', r'\bcorporation\b', r'\bincorporated\b',
        r'\bltd\b', r'\blimited\b', r'\bco\b', r'\bsystems\b', r'\btechnologies\b',
        r'\bsolutions\b', r'\bsoftware\b', r'\btechnology\b', r'\bsystem\b', r'\bsolution\b',
        r'\bai\b', r'\bca\b', r'\bus\b', r'\busa\b'
    ]
    for suffix in suffixes:
        name = re.sub(suffix, '', name)
    # Collapse spaces
    name = re.sub(r'\s+', ' ', name).strip()
    return name


def get_h1b_sponsors_cleaned():
    global _cached_sponsors_cleaned, _cached_sponsors_time
    now = time.time()
    # Cache for 1 hour
    if _cached_sponsors_cleaned is not None and now - _cached_sponsors_time < 3600:
        return _cached_sponsors_cleaned

    try:
        from supabase_client import get_supabase_client
        supabase = get_supabase_client()
        sponsors = {}
        offset = 0
        limit = 1000
        while True:
            # Query all metadata fields to attach to jobs
            fields = (
                "company_name, company_type, w2_contractor, employee_count, "
                "linkedin_account, career_portal, website, sponsor_status, "
                "recommended_action, opt_friendly_score, cases_2024, cases_2025, "
                "cases_2026, recent_cases, recent_approvals, trend_label, top_state"
            )
            res = supabase.table("h1b_sponsors").select(fields).eq("is_sponsor", True).range(offset, offset + limit - 1).execute()
            if not res.data:
                break
            for row in res.data:
                name = row.get("company_name")
                if not name:
                    continue
                cleaned = clean_company_name(name)
                if cleaned:
                    sponsors[cleaned] = row
            if len(res.data) < limit:
                break
            offset += limit

        _cached_sponsors_cleaned = sponsors
        _cached_sponsors_time = now
        print(f"Loaded {len(sponsors)} cleaned H1B sponsors with metadata into cache.")
        return _cached_sponsors_cleaned
    except Exception as e:
        print(f"Failed to fetch and cache H1B sponsors: {e}")
        return _cached_sponsors_cleaned or {}


def is_sponsor_match(job_company: str, sponsors_cleaned: dict):
    job_comp_clean = clean_company_name(job_company)
    if not job_comp_clean or len(job_comp_clean) < 2:
        return None

    # 1. Exact cleaned match
    if job_comp_clean in sponsors_cleaned:
        return sponsors_cleaned[job_comp_clean]

    # 2. Part match for longer names
    for clean_sp, sponsor_data in sponsors_cleaned.items():
        if job_comp_clean == clean_sp:
            return sponsor_data
        if len(job_comp_clean) >= 4:
            if job_comp_clean.startswith(clean_sp) or clean_sp.startswith(job_comp_clean):
                return sponsor_data
            if job_comp_clean in clean_sp.split() or clean_sp in job_comp_clean.split():
                return sponsor_data
    return None
