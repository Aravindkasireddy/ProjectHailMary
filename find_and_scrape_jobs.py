import os
import sys

if __name__ == "__main__" and sys.platform == "darwin" and not os.environ.get("OBJC_DISABLE_INITIALIZE_FORK_SAFETY"):
    # macOS-only crash fix (confirmed live 2026-06-24): this process makes HTTPS
    # requests from several ThreadPoolExecutor worker threads, then Playwright
    # forks a browser subprocess (sync_playwright -> subprocess.Popen -> fork()).
    # Apple's Network.framework fork-child handlers (nw_settings_child_has_forked
    # / NEFlowDirectorDestroy) are not safe to run after CFNetwork has been used
    # from multiple threads, and crash with EXC_BAD_ACCESS - confirmed via 30
    # crash reports in ~5 minutes, all with the identical fork()-time backtrace.
    # This never reproduces on the Linux production VM (no Network.framework
    # there). Setting this env var must happen before the ObjC runtime
    # initializes, so we re-exec the interpreter with it set rather than just
    # assigning os.environ (too late by the time this line runs).
    os.environ["OBJC_DISABLE_INITIALIZE_FORK_SAFETY"] = "YES"
    os.execve(sys.executable, [sys.executable] + sys.argv, os.environ)

import re
import json
import time
import logging
import argparse
import requests
import hashlib
import random
from concurrent.futures import ThreadPoolExecutor, as_completed
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from datetime import datetime, timezone, timedelta
from pathlib import Path
from bs4 import BeautifulSoup
from urllib.parse import urlparse, quote_plus, parse_qs, urljoin
from playwright.sync_api import sync_playwright
try:
    from playwright_stealth import stealth_sync
except ImportError:
    stealth_sync = None
from dotenv import load_dotenv

def resolve_path(base_path):
    email = os.environ.get("MAAS_USER_EMAIL")
    if not email:
        return base_path
    suffix = re.sub(r'[^a-zA-Z0-9_.-]', '_', email)
    p = Path(base_path)
    return p.parent / f"{p.stem}_{suffix}{p.suffix}"

def get_cdt_now_iso():
    # CDT is UTC-5
    cdt = timezone(timedelta(hours=-5))
    return datetime.now(cdt).isoformat()

def is_recent_date(val):
    if not val:
        return True
    try:
        import email.utils
        
        # Lever API createdAt is integer milliseconds
        if isinstance(val, (int, float)):
            dt = datetime.fromtimestamp(val / 1000.0, tz=timezone.utc)
            now = datetime.now(timezone.utc)
            return (now - dt).total_seconds() < 86400
            
        if isinstance(val, str):
            val = val.strip()
            # Try parsing RFC 2822 date (standard for RSS pubDate)
            try:
                dt = email.utils.parsedate_to_datetime(val)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                now = datetime.now(dt.tzinfo)
                return (now - dt).total_seconds() < 86400
            except Exception:
                pass
                
            # Try parsing ISO 8601 date
            iso_str = val.replace('Z', '+00:00')
            try:
                dt = datetime.fromisoformat(iso_str)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                now = datetime.now(dt.tzinfo)
                return (now - dt).total_seconds() < 86400
            except Exception:
                pass
                
            # Try parsing YYYY-MM-DD
            try:
                dt = datetime.strptime(val[:10], "%Y-%m-%d")
                dt = dt.replace(tzinfo=timezone.utc)
                now = datetime.now(timezone.utc)
                return (now - dt).total_seconds() < 86400
            except Exception:
                pass
    except Exception as e:
        print(f"Error parsing date {val}: {e}")
    return True

PAST_24H = False

SEARCH_STATE = {
    "consecutive_failures": 0,
    "consecutive_zero_yields": 0,
    "aborted": False
}


_ENGINE_REACHABLE_CACHE = {}


def _engine_reachable(name: str, probe_url: str) -> bool:
    """Cached per-process reachability probe for a search engine. search_for_job_url()
    (the per-job LinkedIn career-link resolution path) can be called hundreds of times
    in a single run; without caching, a persistent IP block (confirmed live 2026-06-24
    for both Yahoo and DuckDuckGo) gets independently re-discovered on every single job,
    burning 3 failed attempts + backoff per engine per job for nothing.
    """
    if name in _ENGINE_REACHABLE_CACHE:
        return _ENGINE_REACHABLE_CACHE[name]
    try:
        r = requests.get(probe_url, headers={"User-Agent": get_random_user_agent()}, timeout=8)
        ok = r.status_code < 500
    except Exception:
        ok = False
    _ENGINE_REACHABLE_CACHE[name] = ok
    return ok


def _duckduckgo_reachable() -> bool:
    return _engine_reachable("duckduckgo", "https://html.duckduckgo.com/html/?q=test")


def _yahoo_reachable() -> bool:
    """One cheap probe to confirm Yahoo search isn't currently blocking this IP
    outright, before spinning up the concurrent per-title search workers. Each
    worker has its own 5-consecutive-failure circuit breaker, so without this
    upfront check, a persistent block gets independently re-discovered by every
    concurrent worker (confirmed live 2026-06-23: 237 Yahoo errors / 119 abort
    triggers logged over a week of runs, most from this exact redundant pattern
    rather than genuinely intermittent failures).
    """
    return _engine_reachable("yahoo", "https://search.yahoo.com/search?p=test")

USER_AGENTS = [
    # Chrome on Windows/Mac/Linux
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    # Safari on Mac
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3 Safari/605.1.15",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Safari/605.1.15",
    # Firefox on Windows/Mac/Linux
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:124.0) Gecko/20100101 Firefox/124.0",
    "Mozilla/5.0 (X11; Linux x86_64; rv:124.0) Gecko/20100101 Firefox/124.0",
    # Edge on Windows/Mac
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0",
]

def get_random_user_agent():
    return random.choice(USER_AGENTS)

import threading

gemini_keys_lock = threading.Lock()
current_key_index = 0

FOUND_URLS_LOCK = threading.Lock()
DRY_URLS_LOCK = threading.Lock()

# Playwright's sync API is not safe to drive from multiple threads concurrently:
# one thread's browser crash corrupts the shared driver state for every other
# thread mid-call, surfacing as "'PlaywrightContextManager' object has no
# attribute '_playwright'" across all of them (confirmed live 2026-06-22 - a
# single crashed browser cascaded into every concurrent LinkedIn scrape thread
# falling back to the much slower/less reliable LLM parser). Serializing all
# sync_playwright() usage behind this lock trades concurrency for correctness;
# the ThreadPoolExecutor callers still parallelize the non-Playwright parts of
# each task (HTTP requests, parsing), just not the browser session itself.
PLAYWRIGHT_LOCK = threading.Lock()

def add_if_new_url(url, found_urls):
    with FOUND_URLS_LOCK:
        if url in found_urls:
            return False
        found_urls.add(url)
        return True

def append_dry_url(dry_url, dry_urls):
    with DRY_URLS_LOCK:
        dry_urls.append(dry_url)

def get_gemini_api_keys():
    keys = []
    gkey = os.environ.get("GEMINI_API_KEY")
    if gkey:
        for k in gkey.split(","):
            k_stripped = k.strip()
            if k_stripped and k_stripped not in keys:
                keys.append(k_stripped)
    idx = 1
    while True:
        key_i = os.environ.get(f"GEMINI_API_KEY_{idx}")
        if key_i:
            key_i = key_i.strip()
            if key_i and key_i not in keys:
                keys.append(key_i)
            idx += 1
        else:
            break
    return keys

def get_active_gemini_key():
    global current_key_index
    keys = get_gemini_api_keys()
    if not keys:
        return None
    with gemini_keys_lock:
        if current_key_index >= len(keys):
            return None
        return keys[current_key_index]

def rotate_gemini_key(failed_key=None):
    global current_key_index
    keys = get_gemini_api_keys()
    if not keys:
        return False
    with gemini_keys_lock:
        if failed_key and current_key_index < len(keys) and keys[current_key_index] != failed_key:
            return True # already rotated by another thread
        current_key_index += 1
        if current_key_index < len(keys):
            print(f"Rotating to Gemini API Key #{current_key_index + 1}...", flush=True)
            return True
        else:
            print("All Gemini API keys in the pool have been exhausted.", flush=True)
            return False

def get_random_proxy():
    try:
        # Try loading from env variable first
        env_proxies = os.environ.get("PROXIES")
        if env_proxies:
            proxies_list = [p.strip() for p in env_proxies.split(",") if p.strip()]
            if proxies_list:
                return random.choice(proxies_list)

        from jobsearch_paths import workspace_root
        config_path = resolve_path(workspace_root() / "config.json")
        if config_path.exists():
            cfg = json.loads(config_path.read_text(encoding="utf-8"))
            proxies = cfg.get("proxies", [])
            if proxies:
                return random.choice(proxies)
    except Exception:
        pass
    return None

def get_playwright_proxy(proxy_str):
    if not proxy_str:
        return None
    try:
        if not proxy_str.startswith("http://") and not proxy_str.startswith("https://"):
            proxy_str = "http://" + proxy_str
        parsed = urlparse(proxy_str)
        server = f"{parsed.scheme}://{parsed.hostname}"
        if parsed.port:
            server += f":{parsed.port}"
        res = {"server": server}
        if parsed.username:
            res["username"] = parsed.username
        if parsed.password:
            res["password"] = parsed.password
        return res
    except Exception:
        return None


def compute_description_hash(description):
    if not description:
        return ""
    normalized = "".join(description.lower().split())
    return hashlib.sha256(normalized.encode('utf-8')).hexdigest()

def filter_discovered_links(links):
    if not links:
        return []
    valid_links = []
    for link in links:
        try:
            parsed = urlparse(link)
            domain = parsed.netloc.lower()
            
            # 1. Blacklist search engines, social media, and reference sites
            if any(bad in domain for bad in [
                'duckduckgo.com', 'yahoo.com', 'google.com', 'bing.com', 'github.com', 
                'twitter.com', 'facebook.com', 'instagram.com', 'youtube.com', 'wikipedia.org', 
                'reddit.com', 'medium.com', 'stackoverflow.com', 'npmtrends.com', 'npmjs.com'
            ]):
                continue
                
            path_parts = [p for p in parsed.path.split('/') if p]
            if not path_parts:
                continue

            # 2. Check existing specific ATS platforms (for backward compatibility and strictness)
            if 'greenhouse.io' in domain:
                if len(path_parts) >= 3 and path_parts[1] == 'jobs':
                    valid_links.append(link)
                    continue
            elif 'lever.co' in domain:
                if len(path_parts) >= 2:
                    valid_links.append(link)
                    continue
            elif 'myworkdayjobs.com' in domain:
                if 'job' in path_parts:
                    valid_links.append(link)
                    continue
            elif 'ashbyhq.com' in domain:
                if len(path_parts) >= 2:
                    valid_links.append(link)
                    continue
            elif 'workable.com' in domain:
                if len(path_parts) >= 3 and path_parts[1] == 'j':
                    valid_links.append(link)
                    continue
            elif 'smartrecruiters.com' in domain:
                if len(path_parts) >= 2 and '-' in path_parts[1] and path_parts[1].split('-')[0].isdigit():
                    valid_links.append(link)
                    continue
            elif 'weworkremotely.com' in domain:
                if 'remote-jobs' in path_parts:
                    valid_links.append(link)
                    continue
            elif 'remote.co' in domain:
                if 'job-details' in path_parts or 'job' in path_parts:
                    valid_links.append(link)
                    continue
            elif 'linkedin.com' in domain:
                if 'view' in path_parts:
                    valid_links.append(link)
                    continue
            elif 'workatastartup.com' in domain:
                if 'jobs' in path_parts:
                    valid_links.append(link)
                    continue

            # 3. Check new targeted ATS platforms & job boards
            is_new_ats = False
            if any(tgt in domain for tgt in [
                'remoterocketship.com', 'pinpointhq.com', 'remotive.com', 'remotive.io', 
                'paylocity.com', 'keka.com', 'breezy.hr', 'wellfound.com', 'oraclecloud.com', 
                'recruitee.com', 'rippling-ats.com', 'rippling.com', 'gusto-ats.com', 
                'careerpuck.com', 'teamtailor.com', 'talentreef.com', 'homerun.co', 
                'gem.com', 'trakstar.com', 'catsone.com', 'jazzhr.com', 'jazz.co', 
                'jobvite.com', 'icims.com', 'dover.com', 'builtin', 'adp.com', 
                'glassdoor.com', 'factorialhr.com', 'trinethire.com', 'notion.so'
            ]):
                is_new_ats = True
            
            # 4. Check custom subdomains (jobs.*, careers.*, people.*, talent.*)
            elif any(domain.startswith(sub) for sub in ['jobs.', 'careers.', 'people.', 'talent.']):
                is_new_ats = True

            # 5. Check generic paths with careers/jobs keywords
            elif any(part in path_parts for part in ['careers', 'jobs', 'job', 'careers-portal', 'career', 'p', 'o', 'view']):
                is_new_ats = True

            if is_new_ats:
                # Require at least one path segment to avoid matching homepages
                if len(path_parts) >= 1:
                    valid_links.append(link)
                    
        except Exception:
            pass
    return list(set(valid_links))

def search_google_custom(query):
    api_key = os.environ.get("GOOGLE_SEARCH_API_KEY")
    cx = os.environ.get("GOOGLE_SEARCH_CX")
    if not api_key or not cx:
        return None
    url = "https://www.googleapis.com/customsearch/v1"
    params = {
        "key": api_key,
        "cx": cx,
        "q": query
    }
    if PAST_24H:
        params["dateRestrict"] = "d1"
    try:
        r = requests.get(url, params=params, timeout=10)
        if r.status_code == 200:
            data = r.json()
            items = data.get("items", [])
            return [item["link"] for item in items if "link" in item]
        else:
            log(f"Google Custom Search API returned status code {r.status_code}: {r.text}")
    except Exception as e:
        log(f"Google Custom Search API error: {e}")
    return None

def search_bing_api(query):
    api_key = os.environ.get("BING_SEARCH_API_KEY")
    if not api_key:
        return None
    url = "https://api.bing.microsoft.com/v7.0/search"
    headers = {"Ocp-Apim-Subscription-Key": api_key}
    params = {"q": query, "count": 10}
    if PAST_24H:
        params["freshness"] = "Day"
    try:
        r = requests.get(url, headers=headers, params=params, timeout=10)
        if r.status_code == 200:
            data = r.json()
            web_pages = data.get("webPages", {}).get("value", [])
            return [page["url"] for page in web_pages if "url" in page]
        else:
            log(f"Bing Search API returned status code {r.status_code}: {r.text}")
    except Exception as e:
        log(f"Bing Search API error: {e}")
    return None

def search_serper(query):
    api_key = os.environ.get("SERPER_API_KEY")
    if not api_key:
        return None
    url = "https://google.serper.dev/search"
    headers = {
        "X-API-KEY": api_key,
        "Content-Type": "application/json"
    }
    payload = {
        "q": query
    }
    if PAST_24H:
        payload["tbs"] = "qdr:d"
    try:
        r = requests.post(url, headers=headers, json=payload, timeout=10)
        if r.status_code == 200:
            data = r.json()
            organic = data.get("organic", [])
            return [item["link"] for item in organic if "link" in item]
        else:
            log(f"Serper API returned status code {r.status_code}: {r.text}")
    except Exception as e:
        log(f"Serper API error: {e}")
    return None

def search_serpapi(query):
    api_key = os.environ.get("SERPAPI_API_KEY")
    if not api_key:
        return None
    url = "https://serpapi.com/search"
    params = {
        "engine": "google",
        "q": query,
        "api_key": api_key
    }
    if PAST_24H:
        params["tbs"] = "qdr:d"
    try:
        r = requests.get(url, params=params, timeout=10)
        if r.status_code == 200:
            data = r.json()
            organic_results = data.get("organic_results", [])
            return [item["link"] for item in organic_results if "link" in item]
        else:
            log(f"SerpApi returned status code {r.status_code}: {r.text}")
    except Exception as e:
        log(f"SerpApi error: {e}")
    return None

def search_duckduckgo(query):
    if SEARCH_STATE["aborted"]:
        return []
    t0 = time.perf_counter()
    headers = {
        "User-Agent": get_random_user_agent(),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8"
    }
    time_filter = "&df=d" if PAST_24H else ""
    url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}{time_filter}"
    links = []
    try:
        r = http_get(url, headers=headers, timeout=10)
        if r.status_code == 200:
            SEARCH_STATE["consecutive_failures"] = 0
            soup = BeautifulSoup(r.text, 'html.parser')
            for a in soup.find_all('a', href=True):
                href = a['href']
                if 'uddg=' in href:
                    parsed_href = urlparse(href)
                    queries = parse_qs(parsed_href.query)
                    actual_url = queries.get('uddg', [None])[0]
                    if actual_url:
                        href = actual_url
                
                # Filter to ensure it belongs to one of our target job boards and isn't a search engine URL
                if any(tgt in href for tgt in ['boards.greenhouse.io', 'jobs.lever.co', 'myworkdayjobs.com', 'jobs.ashbyhq.com', 'apply.workable.com', 'jobs.smartrecruiters.com', 'weworkremotely.com', 'remote.co', 'linkedin.com/jobs/view', 'workatastartup.com/jobs']):
                    parsed_actual = urlparse(href)
                    domain_actual = parsed_actual.netloc.lower()
                    if not any(se in domain_actual for se in ['yahoo.com', 'yahoo.co', 'google.com', 'bing.com', 'duckduckgo.com']):
                        links.append(href)
        else:
            log(f"DuckDuckGo search error for '{query}': status code {r.status_code}")
            SEARCH_STATE["consecutive_failures"] += 1
    except Exception as e:
        log(f"DuckDuckGo search error for '{query}': {e}")
        SEARCH_STATE["consecutive_failures"] += 1

    _record_search_op("duckduckgo_search", time.perf_counter() - t0, query, len(links))
    if SEARCH_STATE["consecutive_failures"] >= 5:
        log("Aborting search discovery stage early: reached 5 consecutive connection/DNS/server failures.")
        SEARCH_STATE["aborted"] = True
    return links


def _record_search_op(operation_name, elapsed_s, query, result_count):
    try:
        from pipeline_metrics import append_pipeline_metric

        append_pipeline_metric(
            str(WORKSPACE),
            "operation",
            {
                "operation_name": operation_name,
                "stage": "discovery",
                "duration_ms": int(elapsed_s * 1000),
                "success": result_count > 0,
                "jobs_processed": result_count,
                "metadata": {"query": query},
            },
        )
    except Exception:
        pass

def extract_job_with_gemini(url, html, api_key):
    if not api_key:
        return None
    try:
        import google.generativeai as genai
        body_text = clean_text(html)
        body_text = body_text[:12000]
        
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(
            model_name="gemini-2.5-flash",
            generation_config={"response_mime_type": "application/json"}
        )
        prompt = f"""
You are an expert technical sourcing parser. Given a job posting webpage's text content, extract the job details.
URL: {url}

Page Content:
\"\"\"
{body_text}
\"\"\"

Extract the following fields and return ONLY a JSON object:
- "job_title": The official title of the job.
- "company_name": The hiring company's name.
- "requirement_id": A unique job ID, requisition number, or code found in the text or URL. If not found, look at the URL path segments. If still not found, return "Unknown".
- "job_description": The full text of the job description/requirements. Keep formatting clean.
- "location_work_type": The location and work type (e.g. Remote, Hybrid, or city/state).

Conform exactly to this JSON schema:
{{
  "job_title": "string",
  "company_name": "string",
  "requirement_id": "string",
  "job_description": "string",
  "location_work_type": "string"
}}
"""
        response = model.generate_content(prompt)
        text = response.text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines[-1].startswith("```"):
                lines = lines[:-1]
            text = "\n".join(lines).strip()
        data = json.loads(text)
        
        if data.get("job_title") and data.get("job_description"):
            data["job_url"] = url
            return data
    except Exception as e:
        print(f"Gemini fallback extraction failed for {url}: {e}", flush=True)
    return None

def extract_job_with_openai(url, html):
    openai_key = os.environ.get("OPENAI_API_KEY")
    if not openai_key:
        return None
    try:
        from openai import OpenAI
        body_text = clean_text(html)
        body_text = body_text[:12000]
        
        client = OpenAI(api_key=openai_key)
        prompt = f"""
You are an expert technical sourcing parser. Given a job posting webpage's text content, extract the job details.
URL: {url}

Page Content:
\"\"\"
{body_text}
\"\"\"

Extract the following fields and return ONLY a JSON object:
- "job_title": The official title of the job.
- "company_name": The hiring company's name.
- "requirement_id": A unique job ID, requisition number, or code found in the text or URL. If not found, look at the URL path segments. If still not found, return "Unknown".
- "job_description": The full text of the job description/requirements. Keep formatting clean.
- "location_work_type": The location and work type (e.g. Remote, Hybrid, or city/state).

Conform exactly to this JSON schema:
{{
  "job_title": "string",
  "company_name": "string",
  "requirement_id": "string",
  "job_description": "string",
  "location_work_type": "string"
}}
"""
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"}
        )
        text = response.choices[0].message.content.strip()
        data = json.loads(text)
        if data.get("job_title") and data.get("job_description"):
            data["job_url"] = url
            return data
    except Exception as e:
        print(f"OpenAI extraction fallback failed for {url}: {e}", flush=True)
    return None

def scrape_url_with_gemini_fallback(url, api_key=None):
    log(f"Triggering LLM fallback parser for: {url}")
    html = fetch_with_playwright(url)
    if not html:
        return None
    
    # Try Gemini first with key rotation support
    while True:
        active_key = get_active_gemini_key()
        if not active_key:
            break

        _t_llm = time.perf_counter()
        try:
            res = extract_job_with_gemini(url, html, active_key)
            _record_connector_substep("llm_extraction", time.perf_counter() - _t_llm, connector="generic", success=bool(res), model="gemini")
            if res:
                return res
            else:
                raise RuntimeError("Empty Gemini response")
        except Exception as e:
            err_msg = str(e).lower()
            if any(term in err_msg for term in ["429", "400", "403", "quota", "limit", "exhausted", "invalid", "blocked", "denied", "resourceexhausted"]):
                print(f"Gemini key rate-limited/exhausted/invalid during scrape: {active_key[:8]}... Rotating...", flush=True)
                if rotate_gemini_key(active_key):
                    continue
            break
            
    # Try OpenAI gpt-4o-mini fallback
    if os.environ.get("OPENAI_API_KEY"):
        log(f"Using OpenAI fallback parser for: {url}")
        _t_llm = time.perf_counter()
        res = extract_job_with_openai(url, html)
        _record_connector_substep("llm_extraction", time.perf_counter() - _t_llm, connector="generic", success=bool(res), model="gpt-4o-mini")
        if res:
            return res

    return None



from jobsearch_paths import workspace_root

WORKSPACE = workspace_root()
load_dotenv(dotenv_path=str(WORKSPACE / ".env"))
CONFIG_PATH = resolve_path(WORKSPACE / "config.json")
SCRAPED_OUTPUT = resolve_path(WORKSPACE / "scraped_jobs.json")
_scripts_path = str(WORKSPACE / "scripts")
if _scripts_path not in sys.path:
    sys.path.insert(0, _scripts_path)


def _ensure_log_dir():
    (WORKSPACE / "logs").mkdir(parents=True, exist_ok=True)


def _setup_run_logging():
    _ensure_log_dir()
    log_path = WORKSPACE / "logs" / "scrape.log"
    root = logging.getLogger("jobsearch")
    root.setLevel(logging.INFO)
    if root.handlers:
        return root
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setFormatter(fmt)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    root.addHandler(fh)
    root.addHandler(sh)
    return root


log = _setup_run_logging().info


def http_get(url, headers=None, timeout=10, attempts=3):
    """GET with automatic exponential backoff on connection errors and 429/50x codes, plus proxy and User-Agent rotation on each attempt."""
    t0 = time.perf_counter()
    used_attempts = 0
    final_status = None
    last_err = None
    last_response = None
    try:
        for attempt in range(1, attempts + 1):
            used_attempts = attempt
            h = (headers or {}).copy()
            if "User-Agent" not in h:
                h["User-Agent"] = get_random_user_agent()

            proxy_str = get_random_proxy()
            proxies = {"http": proxy_str, "https": proxy_str} if proxy_str else None
            if proxy_str:
                log(f"Routing http_get attempt {attempt}/{attempts} through proxy: {proxy_str}")

            try:
                r = requests.get(url, headers=h, proxies=proxies, timeout=timeout)
                last_response = r
                final_status = r.status_code
                if r.status_code in [200, 201, 204, 301, 302]:
                    return r
                log(f"http_get attempt {attempt}/{attempts} returned status code {r.status_code} for URL: {url}")
                last_err = f"Status code {r.status_code}"
            except Exception as e:
                log(f"http_get attempt {attempt}/{attempts} failed for URL: {url}: {e}")
                last_err = e

            if attempt < attempts:
                time.sleep(1.0 * (2 ** (attempt - 1)))

        if last_response is not None:
            return last_response
        if isinstance(last_err, Exception):
            raise last_err
        raise RuntimeError(f"All http_get attempts failed for {url}: {last_err}")
    finally:
        _record_http_get(url, time.perf_counter() - t0, used_attempts, final_status, success=final_status in (200, 201, 204, 301, 302))


def _record_http_get(url, elapsed_s, attempts_used, status_code, success):
    try:
        from pipeline_metrics import append_pipeline_metric

        append_pipeline_metric(
            str(WORKSPACE),
            "operation",
            {
                "operation_name": "http_request",
                "stage": "discovery",
                "duration_ms": int(elapsed_s * 1000),
                "success": bool(success),
                "metadata": {"url": url, "attempts_used": attempts_used, "status_code": status_code, "retry": attempts_used > 1},
            },
        )
    except Exception:
        pass


def clean_text(html_content):
    if not html_content:
        return ""
    soup = BeautifulSoup(html_content, 'html.parser')
    for script in soup(["script", "style"]):
        script.extract()
    # Replace multiple newlines with single ones
    text = soup.get_text(separator="\n")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return "\n".join(lines)

def _log_playwright_timing(url, elapsed_s, attempt, success):
    """Best-effort telemetry (Phase 10 of the 2026-06-27 perf audit). Records
    per-call Playwright timing so future optimization attempts can be
    measured against real numbers instead of estimates.

    Real incident from this same audit: an earlier version of this change
    also tried to reuse a single shared browser instance across calls to
    avoid the per-call Chromium cold-start. That was reverted - confirmed
    live (logs/scrape.log) it caused "Cannot switch to a different thread"
    failures on 219 of 262 calls (83.6%), because Playwright's sync API
    binds a browser to whichever thread launched it, and this function is
    called from multiple different ThreadPoolExecutor worker threads
    (PLAYWRIGHT_LOCK serializes access but does not change which thread is
    calling). Per-call sync_playwright()/browser.launch() below is
    intentional, not yet-unoptimized - any future attempt at browser reuse
    must keep the browser pinned to one thread (e.g. a dedicated worker
    thread + queue), not a shared global like the first attempt.
    """
    try:
        from pipeline_metrics import append_pipeline_metric

        append_pipeline_metric(
            str(WORKSPACE),
            "playwright_fetch",
            {
                "url": url,
                "duration_ms": int(elapsed_s * 1000),
                "attempt": attempt,
                "success": success,
            },
        )
    except Exception:
        pass


def _record_substep(operation_name, elapsed_s, success=True, metadata=None):
    try:
        from pipeline_metrics import append_pipeline_metric

        append_pipeline_metric(
            str(WORKSPACE),
            "operation",
            {
                "operation_name": operation_name,
                "stage": "discovery",
                "duration_ms": int(elapsed_s * 1000),
                "success": success,
                "metadata": metadata or {},
            },
        )
    except Exception:
        pass


def fetch_with_playwright(url):
    last_err = None
    for attempt in range(1, 4):
        t0 = time.perf_counter()
        try:
            # Randomized pre-navigation delay (1-3s)
            time.sleep(random.uniform(1.0, 3.0))
            with PLAYWRIGHT_LOCK, sync_playwright() as p:
                proxy_str = get_random_proxy()
                proxy_obj = get_playwright_proxy(proxy_str)
                
                # Chromium arguments for advanced evasion and container stability
                launch_args = [
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-infobars",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--disable-web-security"
                ]
                launch_kwargs = {
                    "headless": True,
                    "args": launch_args
                }
                if proxy_obj:
                    launch_kwargs["proxy"] = proxy_obj
                    log(f"Routing Playwright attempt {attempt} through proxy: {proxy_str}")
                
                # Try Chromium first, fallback to WebKit
                _t_launch = time.perf_counter()
                browser = None
                browser_type = "chromium"
                try:
                    browser = p.chromium.launch(**launch_kwargs)
                except Exception as chromium_err:
                    log(f"Playwright Chromium launch failed, falling back to WebKit: {chromium_err}")
                    # Launch webkit as fallback
                    launch_kwargs_fallback = {"headless": True}
                    if proxy_obj:
                        launch_kwargs_fallback["proxy"] = proxy_obj
                    browser = p.webkit.launch(**launch_kwargs_fallback)
                    browser_type = "webkit"
                _record_substep("browser_launch", time.perf_counter() - _t_launch, metadata={"browser_type": browser_type})

                # Rotate viewport sizes
                viewports = [
                    {"width": 1920, "height": 1080},
                    {"width": 1440, "height": 900},
                    {"width": 1366, "height": 768},
                    {"width": 1536, "height": 864}
                ]
                viewport = random.choice(viewports)
                
                # Rotate languages
                locales = ["en-US", "en-GB", "en-CA"]
                locale = random.choice(locales)
                
                _t_context = time.perf_counter()
                context = browser.new_context(
                    user_agent=get_random_user_agent(),
                    viewport=viewport,
                    locale=locale,
                    timezone_id="America/Chicago",
                    geolocation={"latitude": 37.7749, "longitude": -122.4194},
                    permissions=["geolocation"]
                )

                page = context.new_page()

                # Apply stealth mode if library is available (stealth_sync is designed for chromium)
                if stealth_sync and browser_type == "chromium":
                    stealth_sync(page)
                _record_substep("browser_context_create", time.perf_counter() - _t_context)

                # Navigate with a generous timeout
                _t_nav = time.perf_counter()
                page.goto(url, wait_until="commit", timeout=30000)
                _record_substep("page_navigation", time.perf_counter() - _t_nav)

                # 1. Cloudflare / Bot Verification Wait Loop
                for cf_attempt in range(5):
                    title = page.title().lower()
                    content = page.content().lower()
                    if any(term in title for term in ["cloudflare", "just a moment", "attention required"]) or "checking your browser" in content:
                        log(f"Playwright detected Cloudflare or checking page for {url}. Waiting 2s (attempt {cf_attempt + 1}/5)...")
                        time.sleep(2.0)
                    else:
                        break
                
                # 2. Simulate Human Interaction (Scroll)
                try:
                    # Scroll down to trigger lazy loading of assets and text
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight * 0.35)")
                    time.sleep(random.uniform(0.5, 1.2))
                    page.evaluate("window.scrollTo(0, 0)")
                except Exception:
                    pass
                
                # 3. Dynamic Selector/Network Wait
                try:
                    # Common selectors for job descriptions (Greenhouse, Lever, Ashby, Workday, etc.)
                    selectors = [
                        '[data-automation-id="jobPostingDescription"]',
                        '[data-qa="job-description"]',
                        '.job-description',
                        '#job-description',
                        '.job-body',
                        '.jobDescription',
                        'article',
                        'main'
                    ]
                    # Wait for any of these selectors to be visible
                    _t_sel = time.perf_counter()
                    page.wait_for_selector(", ".join(selectors), timeout=6000)
                    _record_substep("wait_for_selector", time.perf_counter() - _t_sel, success=True)
                except Exception:
                    _record_substep("wait_for_selector", time.perf_counter() - _t_sel, success=False)
                    # Fallback sleep to let SPA routers finish loading
                    time.sleep(random.uniform(2.5, 4.0))

                html = page.content()
                browser.close()
                _log_playwright_timing(url, time.perf_counter() - t0, attempt, success=True)
                return html
        except Exception as e:
            last_err = e
            log(f"Playwright attempt {attempt} failed for {url}: {e}")
            _log_playwright_timing(url, time.perf_counter() - t0, attempt, success=False)
            time.sleep(min(2 ** attempt, 8))
            
    print(f"Playwright error for {url}: {last_err}", flush=True)
    return None




def scrape_weworkremotely(url):
    try:
        html = fetch_with_playwright(url)
        if not html:
            return None
        soup = BeautifulSoup(html, 'html.parser')
        
        title_elem = soup.find('h1')
        title = title_elem.get_text().strip() if title_elem else "Unknown Title"
        if "categories" in url or not title or title == "Unknown Title":
            return None
            
        company_div = soup.find(class_='lis-container__job__sidebar__companyDetails__info__title')
        company = company_div.get_text().strip() if company_div else "Unknown"
        
        loc_span = soup.find(class_='box--region') or soup.find(class_='box--multi')
        location = loc_span.get_text().strip() if loc_span else "Remote"
        
        parsed = urlparse(url)
        path_parts = [p for p in parsed.path.split('/') if p]
        req_id = path_parts[-1] if path_parts else "Unknown"
        
        jd_div = soup.find(class_='lis-container__job__content__description') or soup.find(class_='lis-container__job__content') or soup.find(class_='content')
        jd_text = clean_text(str(jd_div)) if jd_div else clean_text(html)
        
        return {
            "job_title": title,
            "company_name": company,
            "job_url": url,
            "requirement_id": req_id,
            "job_description": jd_text.strip(),
            "location_work_type": f"{location} (Remote/Hybrid)"
        }
    except Exception as e:
        print(f"Failed to scrape We Work Remotely URL {url}: {e}")
        return None

def scrape_remoteco(url):
    try:
        html = fetch_with_playwright(url)
        if not html:
            return None
        soup = BeautifulSoup(html, 'html.parser')
        
        s = soup.find('script', id='__NEXT_DATA__')
        if not s:
            title_elem = soup.find('h1')
            title = title_elem.get_text().strip() if title_elem else "Unknown Title"
            return {
                "job_title": title,
                "company_name": "Remote.co",
                "job_url": url,
                "requirement_id": "Unknown",
                "job_description": clean_text(html),
                "location_work_type": "Remote"
            }
            
        data = json.loads(s.string)
        job_details = data.get('props', {}).get('pageProps', {}).get('jobDetails', {})
        if not job_details:
            return None
            
        title = job_details.get("title", "Unknown Title")
        req_id = job_details.get("id") or job_details.get("slug")
        if not req_id:
            parsed = urlparse(url)
            path_parts = [p for p in parsed.path.split('/') if p]
            req_id = path_parts[-1] if path_parts else "Unknown"
            
        uuid_match = re.search(r'([a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})', req_id)
        if uuid_match:
            req_id = uuid_match.group(1)
            
        company_data = job_details.get("company")
        company_name = "Remote.co"
        if company_data and isinstance(company_data, dict):
            company_name = company_data.get("name") or "Remote.co"
            
        if company_name == "Remote.co" and " - " in title:
            title_parts = title.split(" - ")
            if len(title_parts) >= 2:
                p0 = title_parts[0].strip()
                p1 = title_parts[1].strip()
                if not any(w in p0.lower() for w in ["engineer", "developer", "architect", "lead", "manager", "senior", "junior", "remote"]):
                    company_name = p0
                    title = p1
                    
        desc = job_details.get("description")
        if not desc:
            parts = []
            summary = job_details.get("jobSummary")
            if summary:
                parts.append(f"Job Summary:\n{summary}")
            salary = job_details.get("salaryRange")
            if salary:
                parts.append(f"Salary Range: {salary}")
            schedules = job_details.get("jobSchedules")
            if schedules:
                parts.append(f"Job Schedule: {', '.join(schedules) if isinstance(schedules, list) else schedules}")
            types = job_details.get("jobTypes")
            if types:
                parts.append(f"Job Type: {', '.join(types) if isinstance(types, list) else types}")
            benefits = job_details.get("jobBenefits")
            if benefits:
                parts.append(f"Benefits:\n" + "\n".join([f"- {b}" for b in benefits]))
            desc = "\n\n".join(parts)
            
        locs = job_details.get("displayLocations") or job_details.get("remoteOptions")
        location = "Remote"
        if locs:
            location = ", ".join(locs) if isinstance(locs, list) else locs
            
        source_url = job_details.get("sourceUrl")
        if source_url and isinstance(source_url, str):
            source_url = source_url.strip().replace('"', '').replace("'", "")
            if source_url.startswith("http://") or source_url.startswith("https://"):
                url = source_url
            else:
                log(f"Skipping Remote.co URL {url} because sourceUrl is not a valid HTTP link.")
                return None
        else:
            log(f"Skipping Remote.co URL {url} because sourceUrl is paywalled or missing.")
            return None
            
        return {
            "job_title": title,
            "company_name": company_name,
            "job_url": url,
            "requirement_id": req_id,
            "job_description": desc.strip(),
            "location_work_type": f"{location} (Remote/Hybrid)"
        }
    except Exception as e:
        print(f"Failed to scrape Remote.co URL {url}: {e}")
        return None

def scrape_greenhouse(url):
    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
    try:
        response = http_get(url, headers=headers, timeout=10)
        if response.status_code != 200:
            return None
        # Timer starts after http_get returns - http_request has its own
        # separate telemetry, this should only measure parsing/extraction.
        _t_parse = time.perf_counter()
        soup = BeautifulSoup(response.text, 'html.parser')

        # Extract title
        title_elem = soup.find('h1')
        title = title_elem.get_text().strip() if title_elem else "Unknown Title"
        
        # Extract company from path
        parsed = urlparse(url)
        path_parts = [p for p in parsed.path.split('/') if p]
        company = path_parts[0].capitalize() if path_parts else "Unknown"
        
        # Extract location
        loc_elem = soup.find(class_='location')
        location = loc_elem.get_text().strip() if loc_elem else "Remote"
        
        # Get requisition ID
        req_id = path_parts[-1] if path_parts else "Unknown"
        text = soup.get_text()
        req_match = re.search(r'(?:Req(?:uisition)?\s*(?:ID|Code|#)|Job\s*(?:ID|Code|#)|Requisition\s*(?:ID|Code|#))[:\-\s#]+([a-zA-Z0-9\-_]+)', text, re.IGNORECASE)
        if req_match:
            req_id = req_match.group(1).strip()
            
        jd_div = soup.find(id='content') or soup.find(class_='job-post') or soup.find(class_='job__description')
        jd_text = clean_text(str(jd_div)) if jd_div else clean_text(response.text)
        _record_connector_substep("html_parsing", time.perf_counter() - _t_parse, connector="greenhouse", company=company)
        return {
            "job_title": title,
            "company_name": company,
            "job_url": url,
            "requirement_id": req_id,
            "job_description": jd_text.strip(),
            "location_work_type": f"{location} (Remote/Hybrid)"
        }
    except Exception as e:
        print(f"Failed to scrape Greenhouse URL {url}: {e}")
        return None

def scrape_lever(url):
    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
    try:
        response = http_get(url, headers=headers, timeout=10)
        if response.status_code != 200:
            return None
        _t_parse = time.perf_counter()
        soup = BeautifulSoup(response.text, 'html.parser')

        title_elem = soup.find('h2') or soup.find('h1')
        title = title_elem.get_text().strip() if title_elem else "Unknown Title"
        
        parsed = urlparse(url)
        path_parts = [p for p in parsed.path.split('/') if p]
        company = path_parts[0].capitalize() if path_parts else "Unknown"
        
        loc_elem = soup.find(class_='location') or soup.find(class_='posting-categories')
        location = loc_elem.get_text().strip() if loc_elem else "Remote"
        location = re.sub(r'\s+', ' ', location)
        
        req_id = path_parts[-1] if len(path_parts) > 1 else "Unknown"
        text = soup.get_text()
        req_match = re.search(r'(?:Req(?:uisition)?\s*(?:ID|Code|#)|Job\s*(?:ID|Code|#)|Requisition\s*(?:ID|Code|#))[:\-\s#]+([a-zA-Z0-9\-_]+)', text, re.IGNORECASE)
        if req_match:
            req_id = req_match.group(1).strip()
            
        jd_div = soup.find(class_='posting-sections') or soup.find(class_='job-post')
        jd_text = clean_text(str(jd_div)) if jd_div else clean_text(response.text)
        _record_connector_substep("html_parsing", time.perf_counter() - _t_parse, connector="lever", company=company)
        return {
            "job_title": title,
            "company_name": company,
            "job_url": url,
            "requirement_id": req_id,
            "job_description": jd_text.strip(),
            "location_work_type": f"{location} (Remote/Hybrid)"
        }
    except Exception as e:
        print(f"Failed to scrape Lever URL {url}: {e}")
        return None

def scrape_workday(url):
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json",
        "Content-Type": "application/json"
    }
    
    # 1. Attempt REST API scraping (faster, cleaner, handles client-side dynamic rendering)
    _t_json = time.perf_counter()
    try:
        parsed = urlparse(url)
        tenant = parsed.netloc.split('.')[0]
        path_parts = [p for p in parsed.path.split('/') if p]
        
        if 'job' in path_parts:
            job_idx = path_parts.index('job')
            if job_idx > 0:
                board = path_parts[job_idx - 1]
                # Extract the job slug (handle trailing /apply)
                if path_parts[-1].lower() == 'apply':
                    job_slug = path_parts[-2]
                else:
                    job_slug = path_parts[-1]
                    
                api_url = f"https://{parsed.netloc}/wday/cxs/{tenant}/{board}/job/{job_slug}"
                api_response = http_get(api_url, headers=headers, timeout=10, attempts=2)
                
                if api_response.status_code == 200:
                    api_data = api_response.json()
                    job_info = api_data.get("jobPostingInfo", {})
                    if job_info:
                        title = job_info.get("title", "Unknown Title")
                        company = parsed.netloc.split('.')[0].capitalize()
                        req_id = job_info.get("jobReqId") or job_info.get("id") or "Unknown"
                        description = clean_text(job_info.get("jobDescription", ""))
                        location = job_info.get("location", "Remote")

                        _record_connector_substep("json_parsing", time.perf_counter() - _t_json, connector="workday", company=company)
                        return {
                            "job_title": title,
                            "company_name": company,
                            "job_url": url,
                            "requirement_id": req_id,
                            "job_description": description.strip(),
                            "location_work_type": f"{location} (Remote/Hybrid)"
                        }
                    else:
                        print(f"Workday REST API payload missing jobPostingInfo for {url}")
                elif api_response.status_code == 403:
                    # 403 indicates expired/inactive postings
                    print(f"Workday REST API returned 403 (likely inactive/expired) for {url}")
                    return {"inactive": True}
                else:
                    print(f"Workday REST API returned status {api_response.status_code} for {url}")
        else:
            print(f"Could not extract REST API details from Workday URL path structure: {url}")
    except Exception as api_err:
        print(f"Workday REST API scraping attempt failed for {url}: {api_err}")

    # 2. HTML / JSON-LD Fallback (for older/custom Workday setups)
    _t_html = time.perf_counter()
    try:
        html_headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
        response = http_get(url, headers=html_headers, timeout=10)
        if response.status_code != 200:
            return None
        soup = BeautifulSoup(response.text, 'html.parser')
        parsed = urlparse(url)
        company = parsed.netloc.split('.')[0].capitalize()
        
        json_ld_script = soup.find('script', type='application/ld+json')
        if json_ld_script:
            try:
                data = json.loads(json_ld_script.string)
                title = data.get("title", "Unknown Title")
                description = clean_text(data.get("description", ""))
                identifier = data.get("identifier", {})
                req_id = identifier.get("value", "") if isinstance(identifier, dict) else ""
                if not req_id:
                    url_match = re.search(r'_([a-zA-Z0-9\-]+)$', url)
                    req_id = url_match.group(1) if url_match else "Unknown"
                location_data = data.get("jobLocation", {})
                address = location_data.get("address", {}) if isinstance(location_data, dict) else {}
                locality = address.get("addressLocality", "Remote") if isinstance(address, dict) else "Remote"
                country = address.get("addressCountry", "US") if isinstance(address, dict) else "US"
                _record_connector_substep("html_parsing", time.perf_counter() - _t_html, connector="workday", company=company, source="json_ld")
                return {
                    "job_title": title,
                    "company_name": company,
                    "job_url": url,
                    "requirement_id": req_id,
                    "job_description": description.strip(),
                    "location_work_type": f"{locality}, {country} (Remote/Hybrid)"
                }
            except Exception:
                pass

        title_elem = soup.find('title')
        title = title_elem.get_text().strip() if title_elem else "Unknown Title"
        url_match = re.search(r'_([a-zA-Z0-9\-]+)$', url)
        req_id = url_match.group(1) if url_match else "Unknown"
        body = soup.find('body')
        jd_text = clean_text(str(body)) if body else ""
        _record_connector_substep("html_parsing", time.perf_counter() - _t_html, connector="workday", company=company, source="raw_html")
        return {
            "job_title": title,
            "company_name": company,
            "job_url": url,
            "requirement_id": req_id,
            "job_description": jd_text.strip(),
            "location_work_type": "Remote"
        }
    except Exception as e:
        print(f"Failed to scrape Workday URL fallback {url}: {e}")
        return None

def scrape_ashby(url):
    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
    try:
        response = http_get(url, headers=headers, timeout=10)
        # Handle redirects or inactive job postings
        if response.status_code != 200:
            return None

        _t_parse = time.perf_counter()
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Check if it redirected away from the job ID path segment
        parsed = urlparse(url)
        path_parts = [p for p in parsed.path.split('/') if p]
        final_parsed = urlparse(response.url)
        final_path_parts = [p for p in final_parsed.path.split('/') if p]
        
        # If the path segments decreased significantly, it redirected to company board
        if len(final_path_parts) < len(path_parts) and len(final_path_parts) <= 1:
            print(f"  Inactive: Ashby page redirected to company board.", flush=True)
            return {"inactive": True}
            
        json_ld_script = soup.find('script', type='application/ld+json')
        if json_ld_script:
            try:
                data = json.loads(json_ld_script.string)
                title = data.get("title", "Unknown Title")
                description = clean_text(data.get("description", ""))
                org = data.get("hiringOrganization", {})
                company = org.get("name", "Unknown") if isinstance(org, dict) else "Unknown"
                identifier = data.get("identifier", {})
                req_id = identifier.get("value", "") if isinstance(identifier, dict) else ""
                
                if not req_id:
                    req_id = path_parts[-1] if path_parts else "Unknown"
                    
                loc_data = data.get("jobLocation", {})
                address = loc_data.get("address", {}) if isinstance(loc_data, dict) else {}
                locality = address.get("addressLocality", "") if isinstance(address, dict) else ""
                country = address.get("addressCountry", "") if isinstance(address, dict) else ""
                if isinstance(country, dict):
                    country = country.get("name", "US")
                
                loc_str = ""
                if locality:
                    loc_str += locality
                if country:
                    if loc_str:
                        loc_str += f", {country}"
                    else:
                        loc_str = country
                if not loc_str:
                    loc_str = "Remote"

                _record_connector_substep("json_parsing", time.perf_counter() - _t_parse, connector="ashby", company=company, source="json_ld")
                return {
                    "job_title": title,
                    "company_name": company,
                    "job_url": url,
                    "requirement_id": req_id,
                    "job_description": description.strip(),
                    "location_work_type": f"{loc_str} (Remote/Hybrid)"
                }
            except Exception as e:
                print(f"Failed parsing Ashby JSON-LD: {e}")
                
        # HTML Fallback
        title_elem = soup.find('title') or soup.find('h1') or soup.find('h2')
        title_text = title_elem.text.strip() if title_elem else "Unknown Title"
        # Cleanup "DevOps Engineer @ Company"
        if " @ " in title_text:
            title_text = title_text.split(" @ ")[0].strip()
            
        company = path_parts[0].capitalize() if path_parts else "Unknown"
        req_id = path_parts[-1] if path_parts else "Unknown"
        description = clean_text(str(soup.find('body')))

        _record_connector_substep("html_parsing", time.perf_counter() - _t_parse, connector="ashby", company=company, source="raw_html")
        return {
            "job_title": title_text,
            "company_name": company,
            "job_url": url,
            "requirement_id": req_id,
            "job_description": description.strip(),
            "location_work_type": "Remote"
        }
    except Exception as e:
        print(f"Failed to scrape Ashby URL {url}: {e}")
        return None

def scrape_workable(url):
    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
    try:
        parsed = urlparse(url)
        path_parts = [p for p in parsed.path.split('/') if p]
        
        if len(path_parts) >= 3 and path_parts[1] == 'j':
            company_slug = path_parts[0]
            job_id = path_parts[2]
        else:
            if len(path_parts) >= 2 and path_parts[0] == 'j':
                company_slug = "unknown"
                job_id = path_parts[1]
            else:
                return None
                
        company_name = company_slug.replace('-', ' ').title()
        if company_slug != "unknown":
            try:
                acct_url = f"https://apply.workable.com/api/v1/accounts/{company_slug}"
                acct_res = http_get(acct_url, headers=headers, timeout=5)
                if acct_res.status_code == 200:
                    company_name = acct_res.json().get("name", company_name)
            except Exception:
                pass
                
        api_url = f"https://apply.workable.com/api/v2/accounts/{company_slug}/jobs/{job_id}"
        response = http_get(api_url, headers=headers, timeout=10)
        if response.status_code != 200:
            return None
            
        data = response.json()
        title = data.get("title", "Unknown Title")
        req_id = data.get("shortcode", job_id)
        
        desc_html = data.get("description", "")
        reqs_html = data.get("requirements", "")
        benefits_html = data.get("benefits", "")
        
        combined_html = f"<div>{desc_html}</div>"
        if reqs_html:
            combined_html += f"<div><h3>Requirements</h3>{reqs_html}</div>"
        if benefits_html:
            combined_html += f"<div><h3>Benefits</h3>{benefits_html}</div>"
            
        description = clean_text(combined_html)
        
        loc_data = data.get("location", {})
        city = loc_data.get("city", "")
        country = loc_data.get("country", "")
        workplace = data.get("workplace", "remote")
        
        loc_str = ""
        if city:
            loc_str += city
        if country:
            if loc_str:
                loc_str += f", {country}"
            else:
                loc_str = country
        if not loc_str:
            loc_str = "Remote"
            
        return {
            "job_title": title,
            "company_name": company_name,
            "job_url": url,
            "requirement_id": req_id,
            "job_description": description.strip(),
            "location_work_type": f"{loc_str} ({workplace.capitalize()})"
        }
    except Exception as e:
        print(f"Failed to scrape Workable URL {url}: {e}")
        return None

def scrape_smartrecruiters(url):
    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
    try:
        parsed = urlparse(url)
        path_parts = [p for p in parsed.path.split('/') if p]
        
        if len(path_parts) >= 2:
            company_slug = path_parts[0]
            last_part = path_parts[1]
            posting_id = last_part.split('-')[0]
        else:
            return None
            
        api_url = f"https://api.smartrecruiters.com/v1/companies/{company_slug}/postings/{posting_id}"
        response = http_get(api_url, headers=headers, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            # If the job is inactive, filter it out
            if not data.get("active", True):
                print(f"  Inactive: SmartRecruiters REST API reports active=False.", flush=True)
                return {"inactive": True}
                
            title = data.get("name", "Unknown Title")
            company_name = data.get("company", {}).get("name") if isinstance(data.get("company"), dict) else company_slug.replace('-', ' ').title()
            req_id = data.get("id", posting_id)
            
            job_ad = data.get("jobAd", {})
            sections = job_ad.get("sections", {})
            combined_html = ""
            for sec_key in ['companyDescription', 'jobDescription', 'qualifications', 'additionalInformation']:
                sec = sections.get(sec_key, {})
                if sec and sec.get("text"):
                    title_sec = sec.get("title", sec_key.replace('Description', ' Description').title())
                    combined_html += f"<div><h3>{title_sec}</h3>{sec['text']}</div>"
                    
            description = clean_text(combined_html)
            loc_data = data.get("location", {})
            loc_str = loc_data.get("fullLocation") or loc_data.get("address") or "Remote"
            
            return {
                "job_title": title,
                "company_name": company_name,
                "job_url": url,
                "requirement_id": req_id,
                "job_description": description.strip(),
                "location_work_type": f"{loc_str} (Remote/Hybrid)"
            }
            
        # Fallback to HTML scraping
        response = http_get(url, headers=headers, timeout=10)
        if response.status_code != 200:
            return None
            
        # Check for inactive job indicators
        if "This job is no longer available" in response.text or "no longer available" in response.text:
            print(f"  Inactive: SmartRecruiters HTML says job no longer available.", flush=True)
            return {"inactive": True}
            
        soup = BeautifulSoup(response.text, 'html.parser')
        
        json_ld_script = soup.find('script', type='application/ld+json')
        if json_ld_script:
            try:
                data = json.loads(json_ld_script.string)
                title = data.get("title", "Unknown Title")
                description = clean_text(data.get("description", ""))
                org = data.get("hiringOrganization", {})
                company = org.get("name", company_slug.replace('-', ' ').title()) if isinstance(org, dict) else company_slug.replace('-', ' ').title()
                
                return {
                    "job_title": title,
                    "company_name": company,
                    "job_url": url,
                    "requirement_id": posting_id,
                    "job_description": description.strip(),
                    "location_work_type": "Remote"
                }
            except Exception:
                pass
                
        title_elem = soup.find(itemprop="title") or soup.find('h1')
        title = title_elem.get_text().strip() if title_elem else "Unknown Title"
        
        desc_div = soup.find(itemprop="description")
        resp_div = soup.find(itemprop="responsibilities")
        qual_div = soup.find(itemprop="qualifications")
        inc_div = soup.find(itemprop="incentives")
        
        combined_text = ""
        if desc_div:
            combined_text += f"\nCompany Description:\n{desc_div.get_text().strip()}"
        if resp_div:
            combined_text += f"\nResponsibilities:\n{resp_div.get_text().strip()}"
        if qual_div:
            combined_text += f"\nQualifications:\n{qual_div.get_text().strip()}"
        if inc_div:
            combined_text += f"\nIncentives:\n{inc_div.get_text().strip()}"
            
        if not combined_text:
            combined_text = response.text
            
        description = clean_text(combined_text)
        
        org_elem = soup.find(itemprop="hiringOrganization")
        company = company_slug.replace('-', ' ').title()
        if org_elem:
            meta_name = org_elem.find(itemprop="name")
            if meta_name:
                company = meta_name.get("content", company)
                
        return {
            "job_title": title,
            "company_name": company,
            "job_url": url,
            "requirement_id": posting_id,
            "job_description": description.strip(),
            "location_work_type": "Remote"
        }
    except Exception as e:
        print(f"Failed to scrape SmartRecruiters URL {url}: {e}")
        return None

ATS_DOMAINS = [
    'greenhouse.io',
    'lever.co',
    'ashbyhq.com',
    'myworkdayjobs.com',
    'workdayjobs.com',
    'smartrecruiters.com',
    'workable.com',
    'breezy.hr',
    'rippling.com',
    'rippling-ats.com',
    'recruitee.com',
    'pinpointhq.com',
    'jazzhr.com',
    'jazz.co',
    'jobvite.com',
    'icims.com',
    'teamtailor.com',
    'applytojob.com',
    'recruitingbypaycor.com',
    'ultipro.com',
    'brassring.com',
    'taleo.net'
]

def clean_company_name(name):
    if not name:
        return ""
    name = name.lower()
    # remove common suffixes
    name = re.sub(r'\b(inc|llc|corp|co|corporation|incorporated|limited|ltd|gmbh|fzco)\b', '', name)
    name = re.sub(r'[^a-z0-9]', '', name)
    return name.strip()

def get_company_tokens(name):
    if not name:
        return []
    name = name.lower()
    # Replace non-alphanumeric with spaces
    name = re.sub(r'[^a-z0-9\s]', ' ', name)
    words = name.split()
    ignore_words = {
        'inc', 'llc', 'corp', 'co', 'corporation', 'incorporated', 'limited', 'ltd', 'gmbh', 'fzco',
        'technologies', 'technology', 'systems', 'solutions', 'services', 'group', 'partners', 
        'associates', 'consulting', 'software', 'lab', 'labs', 'ai', 'and', 'the', 'company', 'of', 'us', 'usa', 'global'
    }
    tokens = [w for w in words if w not in ignore_words and len(w) > 1]
    if not tokens:
        tokens = [w for w in words if w not in {'inc', 'llc', 'corp', 'co', 'ltd', 'limited'}]
    return tokens

def extract_ats_links(text, html=None):
    found_links = []
    if html:
        try:
            soup = BeautifulSoup(html, 'html.parser')
            for a in soup.find_all('a', href=True):
                found_links.append(a['href'])
        except Exception:
            pass
            
    url_pattern = r'(https?://[^\s"\'()<>#]+)'
    found_links.extend(re.findall(url_pattern, text))
    
    valid_links = []
    for link in found_links:
        try:
            parsed = urlparse(link)
            domain = parsed.netloc.lower()
            if not domain:
                continue
            
            if any(bad in domain for bad in [
                'linkedin.com', 'licdn.com', 'licdn.net', 'google.com', 'gstatic.com',
                'yahoo.com', 'bing.com', 'duckduckgo.com', 'twitter.com', 'facebook.com',
                'instagram.com', 'youtube.com', 'wikipedia.org', 'reddit.com', 'medium.com',
                'stackoverflow.com'
            ]):
                continue
                
            if any(ats in domain for ats in ATS_DOMAINS):
                valid_links.append(link)
                continue
                
            path_parts = [p for p in parsed.path.split('/') if p]
            if any(part in path_parts for part in ['careers', 'jobs', 'job', 'careers-portal', 'career', 'apply']):
                valid_links.append(link)
        except Exception:
            pass
            
    seen = set()
    unique_links = []
    for l in valid_links:
        if l not in seen:
            seen.add(l)
            unique_links.append(l)
    return unique_links

def search_for_job_url(query):
    has_google = bool(os.environ.get("GOOGLE_SEARCH_API_KEY") and os.environ.get("GOOGLE_SEARCH_CX"))
    has_bing = bool(os.environ.get("BING_SEARCH_API_KEY"))
    has_serper = bool(os.environ.get("SERPER_API_KEY"))
    has_serpapi = bool(os.environ.get("SERPAPI_API_KEY"))
    
    urls = None
    if has_google:
        urls = search_google_custom(query)
    elif has_bing:
        urls = search_bing_api(query)
    elif has_serper:
        urls = search_serper(query)
    elif has_serpapi:
        urls = search_serpapi(query)
        
    if not urls and _yahoo_reachable():
        urls = search_yahoo(query)
    if not urls and _duckduckgo_reachable():
        urls = search_duckduckgo(query)

    return urls or []

def filter_and_score_urls(urls, clean_company, company_tokens):
    candidate_urls = []
    for url in urls:
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        
        if any(bad in domain for bad in [
            'linkedin.com', 'indeed.com', 'simplyhired.com', 'ziprecruiter.com', 'glassdoor.com',
            'google.com', 'yahoo.com', 'facebook.com', 'twitter.com', 'youtube.com', 'wikipedia.org',
            'reddit.com', 'medium.com', 'stackoverflow.com', 'upwork.com', 'fiverr.com', 'freelancer.com',
            'talent.com', 'jooble.org', 'monster.com', 'careerbuilder.com', 'salary.com', 'ziprecruiter.com'
        ]):
            continue
            
        is_ats = any(ats in domain for ats in ATS_DOMAINS)
        
        has_company_name = False
        if clean_company and clean_company in url.lower():
            has_company_name = True
        elif company_tokens:
            matched_tokens = [t for t in company_tokens if t in url.lower()]
            if len(matched_tokens) == len(company_tokens):
                has_company_name = True
            elif len(company_tokens) > 1 and len(matched_tokens) >= len(company_tokens) - 1:
                has_company_name = True
                
        path_parts = [p for p in parsed.path.split('/') if p]
        has_career_keyword = any(part in path_parts for part in ['careers', 'jobs', 'job', 'careers-portal', 'career', 'apply'])
        
        score = 0
        if has_company_name and is_ats:
            score = 10
        elif has_company_name and has_career_keyword:
            score = 8
        elif has_company_name:
            score = 5
            
        if score > 0:
            candidate_urls.append((score, url))
            
    return candidate_urls

def resolve_career_link_with_llm(job_title, company_name):
    # Try Gemini first with key rotation support
    while True:
        active_key = get_active_gemini_key()
        if not active_key:
            break
        try:
            import google.generativeai as genai
            genai.configure(api_key=active_key)
            model = genai.GenerativeModel(
                model_name="gemini-2.5-flash",
                generation_config={"response_mime_type": "application/json"}
            )
            prompt = f"""
You are an expert recruitment researcher. Your task is to find the official careers page, job board (e.g. Greenhouse, Lever, Workday, Ashby, or Workable), or direct job application URL for the following job:
Company: {company_name}
Job Title: {job_title}

Search your knowledge and the web to find the most accurate direct URL.
Conform exactly to this JSON schema:
{{
  "careers_url": "string"
}}
"""
            response = model.generate_content(prompt)
            text = response.text.strip()
            if text.startswith("```"):
                lines = text.split("\n")
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines[-1].startswith("```"):
                    lines = lines[:-1]
                text = "\n".join(lines).strip()
            data = json.loads(text)
            url = data.get("careers_url")
            if url and url.startswith("http"):
                log(f"Resolved company career link via Gemini fallback: {url}")
                return url
        except Exception as e:
            err_msg = str(e).lower()
            if any(term in err_msg for term in ["429", "400", "403", "quota", "limit", "exhausted", "invalid", "blocked", "denied", "resourceexhausted"]):
                print(f"Gemini key rate-limited/exhausted/invalid during resolution: {active_key[:8]}... Rotating...", flush=True)
                if rotate_gemini_key(active_key):
                    continue
            break

    # Try OpenAI fallback
    openai_key = os.environ.get("OPENAI_API_KEY")
    if openai_key:
        try:
            from openai import OpenAI
            client = OpenAI(api_key=openai_key)
            prompt = f"""
You are an expert recruitment researcher. Your task is to find the official careers page, job board (e.g. Greenhouse, Lever, Workday, Ashby, or Workable), or direct job application URL for the following job:
Company: {company_name}
Job Title: {job_title}

Search your knowledge and the web to find the most accurate direct URL.
Conform exactly to this JSON schema:
{{
  "careers_url": "string"
}}
"""
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"}
            )
            data = json.loads(response.choices[0].message.content.strip())
            url = data.get("careers_url")
            if url and url.startswith("http"):
                log(f"Resolved company career link via OpenAI fallback: {url}")
                return url
        except Exception as e:
            print(f"OpenAI career link resolution failed: {e}")
    return None

def _record_connector_substep(operation_name, elapsed_s, connector=None, company=None, success=True, **metadata):
    """Sub-step telemetry inside the connector_extract waterfall (2026-06-27
    instrumentation task: subdivide connector_extract, which the analyzer
    confirmed is ~60% of total pipeline time, into measurable steps). Pure
    observability - never changes control flow, retries, or concurrency.
    """
    try:
        from pipeline_metrics import append_pipeline_metric

        append_pipeline_metric(
            str(WORKSPACE),
            "operation",
            {
                "operation_name": operation_name,
                "stage": "discovery",
                "ats_source": connector,
                "company": company,
                "duration_ms": int(elapsed_s * 1000),
                "success": success,
                "metadata": metadata,
            },
        )
    except Exception:
        pass


def resolve_career_link(job_title, company_name, jd_text, html=None):
    try:
        # Step 1: Scan description & HTML for direct ATS links
        extracted = extract_ats_links(jd_text, html)
        if extracted:
            clean_company = clean_company_name(company_name)
            if clean_company:
                for link in extracted:
                    if clean_company in link.lower():
                        return link
            return extracted[0]
            
        # Step 2: Fallback to targeted search
        clean_company = clean_company_name(company_name)
        company_tokens = get_company_tokens(company_name)
        
        query = f'"{company_name}" "{job_title}" (site:greenhouse.io OR site:lever.co OR site:ashbyhq.com OR site:myworkdayjobs.com OR site:workdayjobs.com OR site:smartrecruiters.com OR site:workable.com OR site:careers OR site:jobs)'
        search_urls = search_for_job_url(query)
        
        candidate_urls = filter_and_score_urls(search_urls, clean_company, company_tokens)
        
        if not candidate_urls:
            query_broad = f'"{company_name}" "{job_title}" career OR jobs'
            search_urls_broad = search_for_job_url(query_broad)
            candidate_urls = filter_and_score_urls(search_urls_broad, clean_company, company_tokens)
            
        if candidate_urls:
            candidate_urls.sort(key=lambda x: x[0], reverse=True)
            return candidate_urls[0][1]
            
        # Step 3: Fallback to LLM-based resolution if search yields no valid company links
        _t_llm = time.perf_counter()
        llm_url = resolve_career_link_with_llm(job_title, company_name)
        _record_connector_substep("llm_fallback", time.perf_counter() - _t_llm, company=company_name, success=bool(llm_url))
        if llm_url:
            return llm_url

    except Exception as e:
        print(f"Error resolving career link for {company_name} - {job_title}: {e}")
    return None


def _resolved_career_url_is_live(url: str) -> bool:
    """Verify a resolved career URL (search result or LLM-suggested) actually resolves
    before trusting it as job_url. LLM resolution in particular can hallucinate
    plausible-looking but fake URLs (placeholder IDs, generic search pages) with no
    grounding — accepting those unverified is what caused dozens of duplicate rows
    per (company, title) pair, since each hallucinated guess becomes a new job_url.
    Conservative: any ambiguity (network error, 401/403/5xx) is treated as "not verified
    live" so we fall back to the real, stable LinkedIn URL instead of a guess.
    """
    try:
        from job_link_health import check_job_posting_live

        info = check_job_posting_live(url, timeout=8.0)
        return (
            not info.get("uncertain")
            and not info.get("stale")
            and isinstance(info.get("http_status"), int)
            and 200 <= info["http_status"] < 300
        )
    except Exception:
        return False


def linkedin_job_view_url(url: str) -> str:
    """
    LinkedIn /jobs/search?currentJobId=… is a search shell, not a stable job page.
    Normalize to https://www.linkedin.com/jobs/view/{id}/ so Playwright sees the job detail
    (better for extract_ats_links / resolve_career_link). Non-LinkedIn URLs unchanged.
    """
    u = (url or "").strip()
    if not u or "linkedin.com" not in u.lower():
        return u
    try:
        p = urlparse(u)
        if "jobs/search" not in (p.path or "").lower():
            return u
        q = parse_qs(p.query)
        jid = None
        for key, vals in q.items():
            if key.lower() == "currentjobid" and vals:
                cand = str(vals[0]).strip()
                if cand.isdigit():
                    jid = cand
                    break
        if jid:
            return f"https://www.linkedin.com/jobs/view/{jid}/"
    except Exception:
        pass
    return u


def scrape_linkedin(url):
    fetch_url = linkedin_job_view_url(url)
    try:
        html = fetch_with_playwright(fetch_url)
        if not html:
            return None
        # Real measurement bug caught while reviewing the analyzer's output
        # (2026-06-27): an earlier version started this timer BEFORE
        # fetch_with_playwright() above, so "html_parsing" was actually
        # measuring playwright_fetch_time + parsing_time combined - that's
        # why it showed an implausible ~4.8s average for what should be a
        # millisecond-scale BeautifulSoup parse. Started here instead, after
        # the fetch returns, so it only measures parsing/field-extraction.
        _t_parse = time.perf_counter()
        soup = BeautifulSoup(html, 'html.parser')
        title_elem = soup.find('h1', class_=re.compile('topcard__title|job-search-card__title|title')) or soup.find('h1')
        title = title_elem.get_text().strip() if title_elem else "Unknown Title"
        # LinkedIn's own SEO/search-aggregator landing pages (e.g. "54,000+
        # Migration Specialist Jobs in United States") render an <h1> in this
        # exact "<count>+ ... Jobs in <location>" shape - confirmed live,
        # these were being scraped and stored as if they were real individual
        # postings (company always "Unknown" on these). Reject before the
        # title check below even runs.
        if re.match(r'^[\d,]+\+?\s+.*\bjobs\s+in\b', title, re.I):
            return None
        if (
            "login" in fetch_url.lower()
            or not title
            or title in ("Sign Up", "Unknown Title", "Error", "Page Not Found", "403 Forbidden")
        ):
            return None
        company_elem = soup.find('a', class_=re.compile('topcard__org-name-link|company-name')) or soup.find('span', class_=re.compile('topcard__flavor'))
        company = company_elem.get_text().strip() if company_elem else "Unknown"
        if company == "Unknown":
            # A real LinkedIn posting always has an org-name element; a missing
            # one paired with a parsed title means we're on a block/error page
            # that slipped past the title check above, not a genuine job.
            return None

        # Skip LinkedIn Easy Apply postings (user instruction, 2026-06-24). The
        # earlier fix only checked this in fetch_linkedin_guest_jobs()'s search-
        # result card loop, but scrape_linkedin() is also called directly on any
        # LinkedIn URL surfaced via the bulk Yahoo-search discovery path
        # (search_and_scrape_for_keyword -> scrape_single_url dispatches on
        # domain) - that path never goes through the card loop at all, so Easy
        # Apply postings reached there were never filtered. Checking the apply
        # button specifically (not the whole page) to avoid a false match from
        # an unrelated "recommended jobs" sidebar widget elsewhere on the page.
        apply_btn = soup.find(class_=re.compile('jobs-apply-button'))
        apply_btn_text = apply_btn.get_text(" ", strip=True).lower() if apply_btn else ""
        if "easy apply" in apply_btn_text:
            return None
        loc_elem = soup.find('span', class_=re.compile('topcard__flavor--bullet')) or soup.find('span', class_=re.compile('topcard__flavor--bullet-location'))
        location = loc_elem.get_text().strip() if loc_elem else "Remote"
        jd_div = soup.find('div', class_=re.compile('description__text|show-more-less-html__markup|description'))
        jd_text = clean_text(str(jd_div)) if jd_div else clean_text(html)
        parsed = urlparse(fetch_url)
        path_parts = [p for p in parsed.path.split('/') if p]
        jv = re.search(r"/jobs/view/(\d+)", (parsed.path or ""), re.I)
        if jv:
            req_id = jv.group(1)
        else:
            req_id = path_parts[-1] if path_parts else "Unknown"
            id_match = re.search(r"(\d+)", str(req_id))
            if id_match:
                req_id = id_match.group(1)

        _record_connector_substep("html_parsing", time.perf_counter() - _t_parse, connector="linkedin", company=company)

        _t_resolve = time.perf_counter()
        resolved_url = resolve_career_link(title, company, jd_text, html)
        _record_connector_substep("career_url_resolution", time.perf_counter() - _t_resolve, connector="linkedin", company=company, success=bool(resolved_url))

        if resolved_url:
            _t_validate = time.perf_counter()
            is_live = _resolved_career_url_is_live(resolved_url)
            _record_connector_substep("live_url_validation", time.perf_counter() - _t_validate, connector="linkedin", company=company, success=is_live)
            if not is_live:
                log(f"Discarding unverified resolved career URL (not live): {resolved_url}")
                resolved_url = None
        final_url = resolved_url if resolved_url else fetch_url
        
        return {
            "job_title": title,
            "company_name": company,
            "job_url": final_url,
            "requirement_id": req_id,
            "job_description": jd_text.strip(),
            "location_work_type": f"{location} (Remote/Hybrid)"
        }
    except Exception as e:
        print(f"Failed to scrape LinkedIn URL {url}: {e}")
        return None

def scrape_yc(url):
    try:
        html = fetch_with_playwright(url)
        if not html:
            return None
        soup = BeautifulSoup(html, 'html.parser')
        title_elem = soup.find('h1') or soup.find('h2')
        title = title_elem.get_text().strip() if title_elem else "Unknown Title"
        company_elem = soup.find(class_=re.compile('company-name|startup-name|brand')) or soup.find('a', href=re.compile('/companies/'))
        company = company_elem.get_text().strip() if company_elem else "YC Startup"
        if company == "YC Startup" and " at " in title:
            parts = title.split(" at ")
            title = parts[0].strip()
            company = parts[1].strip()
        loc_elem = soup.find(class_=re.compile('location|job-location'))
        location = loc_elem.get_text().strip() if loc_elem else "Remote"
        jd_div = soup.find(class_=re.compile('job-description|description')) or soup.find('div', id='job-description')
        jd_text = clean_text(str(jd_div)) if jd_div else clean_text(html)
        parsed = urlparse(url)
        path_parts = [p for p in parsed.path.split('/') if p]
        req_id = path_parts[-1] if path_parts else "Unknown"
        id_match = re.search(r'(\d+)', req_id)
        if id_match:
            req_id = id_match.group(1)
        return {
            "job_title": title,
            "company_name": company,
            "job_url": url,
            "requirement_id": req_id,
            "job_description": jd_text.strip(),
            "location_work_type": f"{location} (Remote/Hybrid)"
        }
    except Exception as e:
        print(f"Failed to scrape YC Work at a Startup URL {url}: {e}")
        return None

def search_yahoo(query):
    if SEARCH_STATE["aborted"]:
        return []
    t0 = time.perf_counter()
    headers = {
        "User-Agent": get_random_user_agent(),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8"
    }
    time_filter = "&btf=d" if PAST_24H else ""
    url = f"https://search.yahoo.com/search?p={quote_plus(query)}{time_filter}"
    links = []
    try:
        r = http_get(url, headers=headers, timeout=10)
        if r.status_code == 200:
            SEARCH_STATE["consecutive_failures"] = 0
            soup = BeautifulSoup(r.text, 'html.parser')
            for a in soup.find_all('a', href=True):
                href = a['href']
                m = re.search(r'RU=([^/]+)', href)
                if m:
                    from urllib.parse import unquote
                    actual_url = unquote(m.group(1))
                    links.append(actual_url)
                else:
                    parsed = urlparse(href)
                    domain = parsed.netloc.lower()
                    if parsed.scheme.startswith('http') and not any(bad in domain for bad in ['yahoo.com', 'yimg.com']):
                        links.append(href)
        else:
            log(f"Yahoo search error for '{query}': status code {r.status_code}")
            SEARCH_STATE["consecutive_failures"] += 1
    except Exception as e:
        log(f"Yahoo search error for '{query}': {e}")
        SEARCH_STATE["consecutive_failures"] += 1

    _record_search_op("yahoo_search", time.perf_counter() - t0, query, len(links))
    if SEARCH_STATE["consecutive_failures"] >= 5:
        log("Aborting search discovery stage early: reached 5 consecutive connection/DNS/server failures.")
        SEARCH_STATE["aborted"] = True
    return links


def fetch_linkedin_guest_jobs(target_titles, search_cfg, found_urls, dry_run, dry_urls):
    log("Starting LinkedIn Guest API job discovery...")
    urls_to_scrape = []
    country = search_cfg.get("country_phrase", "United States")
    headers = {
        "User-Agent": get_random_user_agent(),
        "Accept-Language": "en-US,en;q=0.9",
        "Accept": "*/*"
    }

    for title in target_titles:
        if SEARCH_STATE["aborted"]:
            break
        url = f"https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?keywords={quote_plus(title)}&location={quote_plus(country)}&start=0"
        try:
            log(f"Querying LinkedIn guest API for title: '{title}'")
            r = http_get(url, headers=headers, timeout=12, attempts=3)
            if r.status_code != 200:
                log(f"  LinkedIn guest API for '{title}' returned status code {r.status_code}")
                continue
            
            soup = BeautifulSoup(r.text, 'html.parser')
            cards = soup.find_all('li')
            if not cards:
                log("  No job cards found.")
                continue
            
            log(f"  Found {len(cards)} raw cards for '{title}'")
            for card in cards:
                a_tag = card.find('a', href=True)
                if not a_tag:
                    continue
                href = (a_tag.get("href") or "").strip()
                if not href:
                    continue
                if href.startswith("/"):
                    job_url = urljoin("https://www.linkedin.com/", href)
                else:
                    job_url = href

                job_url = linkedin_job_view_url(job_url)

                nu = normalize_job_url(job_url)
                if not nu:
                    continue
                
                title_tag = card.find('h3', class_=re.compile('title|base-search-card__title')) or card.find('h3')
                job_title = title_tag.text.strip() if title_tag else ""

                # Skip LinkedIn Easy Apply postings per user instruction. Matching on
                # the card's visible text rather than a specific CSS class, since
                # LinkedIn's "Easy Apply" badge class names shift between markup
                # versions but the visible label text does not.
                if "easy apply" in card.get_text(" ", strip=True).lower():
                    continue

                if not is_target_job(job_title, [title]):
                    continue
                
                if not add_if_new_url(nu, found_urls):
                    continue
                
                if dry_run:
                    log(f"  [DRY RUN MATCH] LinkedIn guest: '{job_title}' - {job_url}")
                    append_dry_url({
                        "job_url": job_url,
                        "query": f"LinkedIn Guest API: {title}",
                        "title_keyword": job_title
                    }, dry_urls)
                    continue
                
                urls_to_scrape.append(job_url)
        except Exception as e:
            log(f"Error fetching LinkedIn guest API for '{title}': {e}")
            
        time.sleep(random.uniform(1.0, 2.5))

    scraped = []
    if not dry_run and urls_to_scrape:
        log(f"Scraping {len(urls_to_scrape)} LinkedIn URLs in parallel...")
        with ThreadPoolExecutor(max_workers=4) as executor:
            future_to_url = {executor.submit(scrape_single_url, url): url for url in urls_to_scrape}
            for future in as_completed(future_to_url):
                url = future_to_url[future]
                try:
                    job_data = future.result()
                    if job_data and job_data.get("job_description"):
                        job_data["scraped_at"] = get_cdt_now_iso()
                        scraped.append(job_data)
                        log(f"  Scraped LinkedIn Guest Job: '{job_data['job_title']}' at '{job_data['company_name']}'")
                except Exception as e:
                    log(f"Thread execution error scraping LinkedIn URL {url}: {e}")
    return scraped


def fetch_hn_hiring_jobs(target_titles, found_urls, dry_run, dry_urls):
    log("Starting Hacker News 'Who is Hiring' sourcing...")
    discovered = []
    
    search_url = "https://hn.algolia.com/api/v1/search?tags=story,author_whoishiring&query=Who+is+hiring"
    try:
        r = requests.get(search_url, timeout=10)
        if r.status_code != 200:
            log(f"  HN Algolia search API returned status code {r.status_code}")
            return []
        
        hits = r.json().get("hits", [])
        story_id = None
        story_title = ""
        for hit in hits:
            title = hit.get("title", "")
            if title.startswith("Ask HN: Who is hiring?"):
                story_id = hit.get("objectID")
                story_title = title
                break
                
        if not story_id:
            log("  Could not find any recent 'Who is Hiring' story on Hacker News.")
            return []
            
        log(f"  Found latest HN hiring thread: '{story_title}' (ID: {story_id})")
        
        item_url = f"https://hn.algolia.com/api/v1/items/{story_id}"
        r = requests.get(item_url, timeout=15)
        if r.status_code != 200:
            log(f"  HN Algolia item API returned status code {r.status_code}")
            return []
            
        comments = r.json().get("children", [])
        log(f"  Processing {len(comments)} top-level comments...")
        
        import html as html_lib
        def clean_hn_html(html_str):
            if not html_str:
                return ""
            text = html_str.replace("<p>", "\n\n").replace("</p>", "")
            text = text.replace("<pre><code>", "\n```\n").replace("</code></pre>", "\n```\n")
            text = text.replace("<br>", "\n").replace("<br/>", "\n").replace("<br />", "\n")
            text = html_lib.unescape(text)
            text = re.sub(r'<[^>]+>', '', text)
            return text.strip()
            
        matched_count = 0
        for comment in comments:
            raw_text = comment.get("text")
            if not raw_text:
                continue
                
            clean_text = clean_hn_html(raw_text)
            lines = clean_text.split('\n')
            first_line = lines[0].strip() if lines else ""
            parts = [p.strip() for p in re.split(r'[|•–-]', first_line) if p.strip()]
            
            company_name = "HN Startup"
            job_title = "Tech / Engineering Role"
            title_found = False
            
            for part in parts:
                if is_target_job(part, target_titles):
                    job_title = part
                    title_found = True
                    break
                    
            if not title_found:
                has_keyword = False
                for t in target_titles:
                    if t.lower() in clean_text.lower():
                        has_keyword = True
                        job_title = f"{t} Role"
                        break
                if not has_keyword:
                    continue
                if parts:
                    company_name = parts[0]
            else:
                if parts:
                    company_name = parts[0]
                    if company_name.lower() == job_title.lower() and len(parts) > 1:
                        company_name = "HN Startup"
            
            job_url = f"https://news.ycombinator.com/item?id={comment.get('id')}"
            nu = normalize_job_url(job_url)
            if not nu:
                continue
                
            if not add_if_new_url(nu, found_urls):
                continue
                
            matched_count += 1
            
            loc = "Hacker News Sourced"
            if "remote" in clean_text.lower():
                loc = "Remote (Hacker News)"
            elif parts and len(parts) > 2:
                loc = f"{parts[2]} (Hacker News)"
                
            if dry_run:
                log(f"  [DRY RUN MATCH] HN Sourced: '{job_title}' at '{company_name}' - {job_url}")
                append_dry_url({
                    "job_url": job_url,
                    "query": f"HN Sourced: {story_title}",
                    "title_keyword": job_title
                }, dry_urls)
                continue
                
            discovered.append({
                "job_title": job_title,
                "company_name": company_name,
                "job_url": job_url,
                "requirement_id": f"hn-{comment.get('id')}",
                "job_description": clean_text,
                "location_work_type": loc,
                "description_hash": compute_description_hash(clean_text),
                "scraped_at": get_cdt_now_iso(),
                "posted_at": datetime.fromtimestamp(comment.get("created_at_i", time.time()), tz=timezone.utc).isoformat()
            })
            
        log(f"  HN Sourcing complete. Sourced {matched_count} matching startup jobs.")
    except Exception as e:
        log(f"Error during HN sourcing: {e}")
        
    return discovered


def fetch_jooble_jobs(target_titles, search_cfg, found_urls, dry_run, dry_urls):
    api_key = os.environ.get("JOOBLE_API_KEY")
    if not api_key and isinstance(search_cfg, dict):
        api_key = search_cfg.get("jooble_api_key")
    if not api_key:
        return []
    
    log("Starting Jooble API job discovery...")
    urls_to_scrape = []
    country = search_cfg.get("country_phrase", "United States")
    
    headers = {
        "Content-Type": "application/json"
    }
    
    for title in target_titles:
        if SEARCH_STATE["aborted"]:
            break
        url = f"https://jooble.org/api/{api_key}"
        payload = {
            "keywords": title,
            "location": country,
            "page": "1"
        }
        try:
            log(f"Querying Jooble API for title: '{title}'")
            r = requests.post(url, headers=headers, json=payload, timeout=10)
            if r.status_code != 200:
                log(f"  Jooble API returned status code {r.status_code}")
                continue
            
            data = r.json()
            jobs = data.get("jobs", [])
            log(f"  Found {len(jobs)} jobs from Jooble for '{title}'")
            
            for job in jobs:
                job_url = job.get("link")
                if not job_url:
                    continue
                
                nu = normalize_job_url(job_url)
                if not nu:
                    continue
                
                job_title = job.get("title", "")
                if not is_target_job(job_title, [title]):
                    continue
                
                if not add_if_new_url(nu, found_urls):
                    continue
                
                if dry_run:
                    log(f"  [DRY RUN MATCH] Jooble API: '{job_title}' - {job_url}")
                    append_dry_url({
                        "job_url": job_url,
                        "query": f"Jooble API: {title}",
                        "title_keyword": job_title
                    }, dry_urls)
                    continue
                
                urls_to_scrape.append(job_url)
        except Exception as e:
            log(f"Error querying Jooble API for '{title}': {e}")
            
        time.sleep(random.uniform(1.0, 2.0))

    scraped = []
    if not dry_run and urls_to_scrape:
        log(f"Scraping {len(urls_to_scrape)} Jooble URLs in parallel...")
        with ThreadPoolExecutor(max_workers=4) as executor:
            future_to_url = {executor.submit(scrape_single_url, url): url for url in urls_to_scrape}
            for future in as_completed(future_to_url):
                url = future_to_url[future]
                try:
                    job_data = future.result()
                    if job_data and job_data.get("job_description"):
                        job_data["scraped_at"] = get_cdt_now_iso()
                        scraped.append(job_data)
                        log(f"  Scraped Jooble Job: '{job_data['job_title']}' at '{job_data['company_name']}'")
                except Exception as e:
                    log(f"Thread execution error scraping Jooble URL {url}: {e}")
    return scraped


def normalize_job_url(url):
    """Same canonical form as company scraper / Supabase (https, strip tracking params + hash only)."""
    try:
        from company_scraper.url_normalize import canonical_job_url

        return canonical_job_url(url or "")
    except Exception:
        if not url:
            return ""
        try:
            p = urlparse(url)
            path = p.path.rstrip("/")
            return f"{p.scheme}://{p.netloc.lower()}{path}".lower()
        except Exception:
            return (url or "").lower().strip()


def build_yahoo_queries(title, search_cfg):
    """Build Yahoo `site:` queries from config.search (or defaults)."""
    country = search_cfg.get("country_phrase", "United States")
    us = json.dumps(country)
    templates = search_cfg.get("yahoo_site_templates")
    if isinstance(templates, list) and templates:
        out = []
        for t in templates:
            try:
                out.append(t.format(title=title, country=us))
            except Exception:
                continue
        return out if out else []

    # Group target ATS platforms to minimize search query counts and prevent rate limits.
    # Group 1: Core/Popular ATS
    g1 = f'"{title}" {us} (site:boards.greenhouse.io OR site:jobs.lever.co OR site:myworkdayjobs.com OR site:jobs.ashbyhq.com OR site:apply.workable.com OR site:jobs.smartrecruiters.com)'
    # Group 2: Job Boards & Aggregators
    g2 = f'"{title}" {us} (site:linkedin.com/jobs/view OR site:workatastartup.com/jobs OR site:remoterocketship.com/jobs OR site:wellfound.com/jobs OR site:remotive.com OR site:remotive.io)'
    # Group 3: Modern/Niche ATS
    g3 = f'"{title}" {us} (site:pinpointhq.com OR site:breezy.hr OR site:recruitee.com OR site:teamtailor.com OR site:homerun.co OR site:gem.com)'
    # Group 4: Enterprise/HR ATS
    g4 = f'"{title}" {us} (site:oraclecloud.com OR site:rippling-ats.com OR site:gusto-ats.com OR site:jobvite.com OR site:icims.com OR site:adp.com OR site:trinethire.com)'
    # Group 5: Custom Subdomains/Paths & General ATS
    g5 = f'"{title}" {us} (site:catsone.com OR site:jazzhr.com OR site:jazz.co OR site:dover.com OR site:factorialhr.com OR site:paylocity.com OR site:keka.com)'
    # Group 6: Custom Subdomain & Career Page Discovery
    g6 = f'"{title}" {us} (inurl:jobs OR inurl:careers OR inurl:people OR inurl:talent)'
    
    core = [g1, g2, g3, g4, g5, g6]
    
    # Optional remote job boards
    if search_cfg.get("include_remote_primary_boards", True):
        g_remote = f'"{title}" {us} (site:weworkremotely.com OR site:remote.co)'
        core.append(g_remote)
        
    return core


def expand_target_titles_with_gemini(target_titles, api_key=None):
    """
    Expand target titles using Gemini 2.5 Flash, falling back to a static mapping if it fails or keys are exhausted.
    """
    STATIC_SYNONYM_FALLBACK = {
        "DevOps Engineer": ["DevOps", "Site Reliability Engineer", "SRE"],
        "Cloud Automation Engineer": ["Cloud Infrastructure Engineer", "Automation Engineer", "Cloud Engineer"],
        "Platform Engineering": ["Platform Engineer", "Infrastructure Engineer", "Internal Developer Platform"],
        "Platform Engineer": ["Platform Engineering", "Infrastructure Engineer", "DevOps Engineer"],
        "Cloud Infrastructure Engineer": ["Cloud Engineer", "Infrastructure Engineer", "DevOps"],
        "DevSecOps": ["DevSecOps Engineer", "Security Engineer", "DevOps Security", "Cloud SecOps"],
        "Site Reliability Engineer (SRE)": ["SRE", "Site Reliability Engineer", "Reliability Engineer", "DevOps Engineer"],
        "Site Reliability Engineer": ["SRE", "Reliability Engineer", "DevOps Engineer"],
        "Continuous Integration (CI/CD)": ["CI/CD Engineer", "Release Engineer", "Build Engineer", "DevOps CI/CD"],
        "CI/CD Engineer": ["Release Engineer", "Build Engineer", "DevOps CI/CD"],
        "System Engineer": ["Systems Engineer", "Linux Systems Engineer", "Operations Engineer"],
        "Systems Engineer": ["System Engineer", "Linux Systems Engineer", "Operations Engineer"],
    }
    
    prompt = f"""
You are an expert technical recruiter and sourcing agent.
Given the following list of target job titles:
{json.dumps(target_titles)}

Generate 2-3 highly relevant, search-friendly synonyms, abbreviations, or closely related titles for each target title.
These will be used for searching job boards, so choose terms commonly used in job listings.
Avoid overly generic terms that would cause search query bloat or return irrelevant results.

Return ONLY a JSON object mapping each original title to a list of its 2-3 synonyms/abbreviations.
Conform exactly to this structure:
{{
  "Title 1": ["Synonym A", "Synonym B"],
  "Title 2": ["Synonym C", "Synonym D"]
}}
"""

    while True:
        active_key = get_active_gemini_key()
        if not active_key:
            log("No Gemini API keys left in the pool for query expansion. Falling back to static synonym mapping.")
            return {title: STATIC_SYNONYM_FALLBACK.get(title, []) for title in target_titles}

        try:
            import google.generativeai as genai
            genai.configure(api_key=active_key)
            model = genai.GenerativeModel(
                model_name="gemini-2.5-flash",
                generation_config={"response_mime_type": "application/json"}
            )
            response = model.generate_content(prompt)
            text = response.text.strip()
            if text.startswith("```"):
                lines = text.split("\n")
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines[-1].startswith("```"):
                    lines = lines[:-1]
                text = "\n".join(lines).strip()
            expanded = json.loads(text)
            
            result = {}
            for title in target_titles:
                syns = expanded.get(title, expanded.get(title.strip(), []))
                if isinstance(syns, list):
                    clean_syns = [str(s).strip() for s in syns if s][:3]
                    result[title] = clean_syns
                else:
                    result[title] = STATIC_SYNONYM_FALLBACK.get(title, [])
            log(f"Successfully generated query expansions with Gemini for {len(result)} titles.")
            return result
        except Exception as e:
            err_msg = str(e).lower()
            if any(term in err_msg for term in ["429", "400", "403", "quota", "limit", "exhausted", "invalid", "blocked", "denied", "resourceexhausted"]):
                log(f"Gemini key rate-limited/exhausted/invalid during query expansion: {active_key[:8]}... Rotating...")
                if rotate_gemini_key(active_key):
                    continue
            log(f"Gemini query expansion failed: {e}. Falling back to static synonym mapping.")
            return {title: STATIC_SYNONYM_FALLBACK.get(title, []) for title in target_titles}


_DOMAIN_TO_ATS_SOURCE = (
    ("greenhouse.io", "greenhouse"),
    ("lever.co", "lever"),
    ("myworkdayjobs.com", "workday"),
    ("ashbyhq.com", "ashby"),
    ("workable.com", "workable"),
    ("smartrecruiters.com", "smartrecruiters"),
    ("weworkremotely.com", "weworkremotely"),
    ("remote.co", "remote_co"),
    ("linkedin.com", "linkedin"),
    ("workatastartup.com", "ycombinator"),
)


def scrape_single_url(href, api_key=None):
    # Introduce randomized rate throttling delay (1.5 to 4.0 seconds)
    time.sleep(random.uniform(1.5, 4.0))
    domain = urlparse(href).netloc.lower()
    ats_source = next((name for host, name in _DOMAIN_TO_ATS_SOURCE if host in domain), "generic")
    job_data = None
    retried_via_fallback = False

    # Manual timing (not record_operation's exception-based success) because
    # the existing try/except below intentionally swallows scraper errors and
    # falls through to the Gemini fallback - "success" here means "did
    # extraction actually produce a job", not "did the block avoid raising".
    t0 = time.perf_counter()
    try:
        if 'greenhouse.io' in domain:
            job_data = scrape_greenhouse(href)
        elif 'lever.co' in domain:
            job_data = scrape_lever(href)
        elif 'myworkdayjobs.com' in domain:
            job_data = scrape_workday(href)
        elif 'ashbyhq.com' in domain:
            job_data = scrape_ashby(href)
        elif 'workable.com' in domain:
            job_data = scrape_workable(href)
        elif 'smartrecruiters.com' in domain:
            job_data = scrape_smartrecruiters(href)
        elif 'weworkremotely.com' in domain:
            job_data = scrape_weworkremotely(href)
        elif 'remote.co' in domain:
            job_data = scrape_remoteco(href)
        elif 'linkedin.com' in domain:
            job_data = scrape_linkedin(href)
        elif 'workatastartup.com' in domain:
            job_data = scrape_yc(href)
        else:
            job_data = scrape_url_with_gemini_fallback(href)
    except Exception as e:
        print(f"Scraper error for {href}: {e}", flush=True)
    finally:
        _record_connector_extraction(ats_source, time.perf_counter() - t0, bool(job_data), retried=False)

    if job_data and job_data.get("inactive"):
        return None

    if not job_data or len(job_data.get("job_description", "")) < 200:
        retried_via_fallback = True
        t0 = time.perf_counter()
        try:
            job_data = scrape_url_with_gemini_fallback(href)
        except Exception as e:
            print(f"Gemini fallback scraper failed for {href}: {e}", flush=True)
        finally:
            _record_connector_extraction("generic", time.perf_counter() - t0, bool(job_data), retried=retried_via_fallback)

    if job_data:
        desc = job_data.get("job_description", "")
        if desc:
            job_data["description_hash"] = compute_description_hash(desc)

    return job_data


def _record_connector_extraction(ats_source, elapsed_s, extracted, retried):
    try:
        from pipeline_metrics import append_pipeline_metric

        append_pipeline_metric(
            str(WORKSPACE),
            "operation",
            {
                "operation_name": "connector_extract",
                "stage": "discovery",
                "ats_source": ats_source,
                "duration_ms": int(elapsed_s * 1000),
                "success": extracted,
                "jobs_processed": 1 if extracted else 0,
                "metadata": {"retry": retried},
            },
        )
    except Exception:
        pass

def search_and_scrape_for_keyword(keyword, search_cfg, found_urls, dry_run, dry_urls):
    """
    Search Yahoo and scrape jobs for a given keyword/title.
    Returns a list of newly scraped job dictionaries and count of unique URLs found.
    """
    queries = build_yahoo_queries(keyword, search_cfg)
    keyword_scraped_jobs = []
    urls_found_for_keyword = 0
    urls_to_scrape = []
    
    for query in queries:
        if SEARCH_STATE["aborted"]:
            break
        
        urls = None
        using_api = False
        
        has_google = bool(os.environ.get("GOOGLE_SEARCH_API_KEY") and os.environ.get("GOOGLE_SEARCH_CX"))
        has_bing = bool(os.environ.get("BING_SEARCH_API_KEY"))
        has_serper = bool(os.environ.get("SERPER_API_KEY"))
        has_serpapi = bool(os.environ.get("SERPAPI_API_KEY"))
        
        if has_google:
            using_api = True
            log(f"Searching Google Custom Search API: {query}")
            urls = search_google_custom(query)
        elif has_bing:
            using_api = True
            log(f"Searching Bing Search API: {query}")
            urls = search_bing_api(query)
        elif has_serper:
            using_api = True
            log(f"Searching Serper API: {query}")
            urls = search_serper(query)
        elif has_serpapi:
            using_api = True
            log(f"Searching SerpApi: {query}")
            urls = search_serpapi(query)
            
        if not urls and not SEARCH_STATE["aborted"]:
            using_api = False
            log(f"Searching Yahoo: {query}")
            urls = search_yahoo(query)
            if not urls and not SEARCH_STATE["aborted"] and _duckduckgo_reachable():
                log(f"Yahoo search returned 0 results for '{query}'. Falling back to DuckDuckGo...")
                urls = search_duckduckgo(query)
        
        if SEARCH_STATE["aborted"]:
            break
            
        if urls:
            urls = filter_discovered_links(urls)
            
        if not urls:
            SEARCH_STATE["consecutive_zero_yields"] += 1
        else:
            SEARCH_STATE["consecutive_zero_yields"] = 0
            
        if SEARCH_STATE["consecutive_zero_yields"] >= 10:
            log("Aborting search discovery stage early: 10 consecutive search engine queries returned 0 results (likely rate-limited or blocked).")
            SEARCH_STATE["aborted"] = True
            break
            
        if using_api:
            delay = random.uniform(1.5, 3.0)
        else:
            delay = random.uniform(8.0, 15.0)
        log(f"Sleeping for {delay:.2f} seconds...")
        time.sleep(delay)

        for href in urls:
            nu = normalize_job_url(href)
            if not nu:
                continue
            if not add_if_new_url(nu, found_urls):
                continue
            urls_found_for_keyword += 1

            if dry_run:
                append_dry_url({"job_url": href, "query": query, "title_keyword": keyword}, dry_urls)
                continue
            
            urls_to_scrape.append(href)

    if not dry_run and urls_to_scrape:
        log(f"Scraping {len(urls_to_scrape)} URLs in parallel for keyword '{keyword}'...")
        with ThreadPoolExecutor(max_workers=4) as executor:
            future_to_url = {executor.submit(scrape_single_url, url): url for url in urls_to_scrape}
            for future in as_completed(future_to_url):
                url = future_to_url[future]
                try:
                    job_data = future.result()
                    if job_data and job_data.get("job_description"):
                        if job_data.get("requirement_id") and job_data.get("requirement_id") != "Unknown":
                            log(f"Scraped: '{job_data['job_title']}' at '{job_data['company_name']}' - Req ID: {job_data['requirement_id']}")
                            job_data["scraped_at"] = get_cdt_now_iso()
                            keyword_scraped_jobs.append(job_data)
                        else:
                            log(f"Discarded (No Requirement ID): {url}")
                    else:
                        if job_data:
                            log(f"Discarded (No JD text or inactive): {url}")
                except Exception as e:
                    log(f"Thread execution error scraping {url}: {e}")
                    
    return keyword_scraped_jobs, urls_found_for_keyword



def is_us_location(location_str):
    if not location_str:
        return False
    loc_lower = location_str.lower()
    
    # 1. Clean and tokenize into words
    words = re.findall(r'\b[a-z]+\b', loc_lower)
    
    # 2. Ignored generic terms
    ignored_words = {
        "remote", "hybrid", "onsite", "work", "from", "home", "anywhere", "location", 
        "timezone", "time", "zone", "eastern", "pacific", "central", "mountain", 
        "et", "pt", "ct", "mt", "hours", "day", "days", "week", "weeks", "flexible", 
        "office", "and", "or", "in", "at", "the", "with", "option", "applicants", 
        "applicable", "global", "worldwide", "only", "based", "located", "reside",
        "resident", "residents", "us-based", "us-remote", "remote-us", "state", "states",
        "united", "america", "americas", "columbia", "district"
    }
    
    # 3. Positive US indicators
    us_indicators = {"us", "usa", "u.s.", "u.s.a", "united states", "america"}
    
    # 4. US states (names and postal codes)
    us_states_abbr = {
        "al", "ak", "az", "ar", "ca", "co", "ct", "de", "fl", "ga", "hi", "id", "il", "in", "ia", "ks", "ky", "la", "me", "md",
        "ma", "mi", "mn", "ms", "mo", "mt", "ne", "nv", "nh", "nj", "nm", "ny", "nc", "nd", "oh", "ok", "or", "pa", "ri", "sc",
        "sd", "tn", "tx", "ut", "vt", "va", "wa", "wv", "wi", "wy"
    }
    us_states_full = {
        "alabama", "alaska", "arizona", "arkansas", "california", "colorado", "connecticut", "delaware", "florida", 
        "georgia", "hawaii", "idaho", "illinois", "indiana", "iowa", "kansas", "kentucky", "louisiana", "maine", 
        "maryland", "massachusetts", "michigan", "minnesota", "mississippi", "missouri", "montana", "nebraska", 
        "nevada", "new hampshire", "new jersey", "new mexico", "new york", "north carolina", "north dakota", 
        "ohio", "oklahoma", "oregon", "pennsylvania", "rhode island", "south carolina", "south dakota", "tennessee", 
        "texas", "utah", "vermont", "virginia", "washington", "west virginia", "wisconsin", "wyoming"
    }
    
    # 5. Major US cities
    us_cities = {
        "san francisco", "sf", "seattle", "new york", "nyc", "austin", "chicago", "boston", 
        "denver", "los angeles", "la", "atlanta", "dallas", "houston", "miami", "philadelphia", 
        "phoenix", "san diego", "san jose", "sunnyvale", "mountain view", "palo alto", "redmond", 
        "bellevue", "oakland", "detroit", "minneapolis", "portland", "salt lake city", "pittsburgh", 
        "washington", "arlington", "boulder", "cambridge", "raleigh", "durham", "charlotte", 
        "nashville", "salt lake", "las vegas", "orlando", "tampa", "tempe", "culver city",
        "menlo park", "cupertino", "santa clara", "redwood city", "irvine", "berkeley", "columbus"
    }
    
    # Check for direct negative indicator match (e.g. EMEA, Canada, Europe, UK, etc.)
    negative_indicators = {
        "europe", "uk", "london", "india", "germany", "france", "canada", "latam", 
        "emea", "apac", "australia", "asia", "singapore", "netherlands", "brazil", 
        "spain", "poland", "ukraine", "philippines", "ireland", "tokyo", "japan",
        "dublin", "toronto", "paris", "berlin", "munich", "sydney", "melbourne", 
        "bengaluru", "bangalore", "vancouver", "montreal", "bucharest", "sao paulo", 
        "amsterdam", "krakow", "mexico", "sweden", "stockholm", "zurich",
        "pakistan", "lahore", "karachi", "islamabad", "italy", "rome", "milan",
        "portugal", "lisbon", "madrid", "barcelona", "china", "beijing",
        "shanghai", "hong kong", "taiwan", "taipei", "vietnam", "thailand", "bangkok",
        "croatia", "zagreb", "czech", "republic", "türkiye", "turkey", "noida",
        "argentina", "ankara", "mississauga", "copenhagen", "denmark", "south korea",
        "korea", "belgrade", "serbia", "yerevan", "armenia", "calgary", "ottawa", 
        "ontario", "british columbia", "quebec", "alberta", "pune", "hyderabad", 
        "chennai", "mumbai", "delhi", "gurugram", "gurgaon", "south america", "africa", 
        "middle east", "nz", "new zealand", "auckland", "wellington", "brisbane", 
        "perth", "adelaide", "cape town", "johannesburg", "nairobi", "lagos", "egypt", 
        "cairo", "dubai", "uae", "abu dhabi", "saudi arabia", "riyadh", "israel", 
        "tel aviv", "colombia", "bogota", "medellin", "chile", "santiago", "peru", 
        "lima", "ecuador", "quito", "bolivia", "uruguay", "montevideo", "costa rica",
        "panama", "guatemala", "malaysia", "kuala lumpur", "indonesia", "jakarta",
        "manila", "seoul", "oslo", "norway", "helsinki", "finland", "vienna", "austria",
        "belgium", "brussels", "switzerland", "geneva", "greece", "athens"
    }
    
    has_negative = any(ni in loc_lower for ni in negative_indicators)
    if has_negative:
        return False
        
    has_positive = any(pi in loc_lower for pi in us_indicators)
    if has_positive:
        return True
        
    has_city = any(city in loc_lower for city in us_cities)
    has_state_full = any(state in loc_lower for state in us_states_full)
    
    if has_city or has_state_full:
        return True
        
    # Check individual words for states
    for w in words:
        if w in us_states_abbr:
            # Avoid matching common words like "in", "or", "me", "la", "co" as states unless prefixed by a comma or space comma
            if w in {"in", "or", "me", "la", "co", "ma"}:
                if re.search(r'\b,\s*' + w + r'\b', loc_lower):
                    return True
            else:
                return True
                
    # If no negative indicators and it has remote/hybrid/onsite, and no other foreign words
    non_generic_non_us = []
    for w in words:
        if (w not in ignored_words and 
            w not in us_states_abbr and 
            w not in us_states_full and 
            w not in us_cities and 
            w not in us_indicators):
            non_generic_non_us.append(w)
            
    if non_generic_non_us:
        return False
        
    return True



# Titles we never source (still filtered at classify; this avoids discovery noise).
_EXCLUDED_JOB_TITLE_RES = [
    re.compile(r"database\s+engineer", re.I),
    re.compile(r"cloud\s+database\s+engineer", re.I),
    re.compile(r"\bcloud\s+database\b", re.I),
    re.compile(r"\bdba\b", re.I),
    re.compile(r"cloud\s+network(ing)?\s+engineer", re.I),
    re.compile(r"cloud\s+security\s+engineer", re.I),
]


def is_target_job(job_title, target_titles):
    jt = job_title.lower()
    if job_title and any(rx.search(job_title) for rx in _EXCLUDED_JOB_TITLE_RES):
        return False

    # 1. Strict substring and all-tokens checks
    for t in target_titles:
        t_lower = t.lower()
        if t_lower in jt:
            return True
        parts = t_lower.split()
        if len(parts) > 1 and all(p in jt for p in parts):
            return True
            
    # 2. Acronym expansion check (aligned with ROLE LABEL strings in Job_classifier_prompt.txt)
    acronyms = {
        "sre": "site reliability",
        "cicd": "continuous integration",
        "iac": "infrastructure",
    }
    words = re.findall(r'\b[a-z]+\b', jt)
    for ac, expanded in acronyms.items():
        if ac in words:
            if any(ac in t.lower() or expanded in t.lower() for t in target_titles):
                return True
                
    # 3. Fuzzy Jaccard token overlap check (Jaccard similarity fallback)
    negatives = {"recruiter", "talent", "hr", "marketing", "sales", "finance", "legal", "accountant", "coordinator", "sourcer"}
    if any(n in words for n in negatives):
        return False
        
    jt_clean = re.sub(r'[^a-z0-9\s]', '', jt)
    jt_tokens = set(jt_clean.split())
    
    for t in target_titles:
        t_clean = re.sub(r'[^a-z0-9\s]', '', t.lower())
        t_tokens = set(t_clean.split())
        if not t_tokens:
            continue
        intersection = jt_tokens.intersection(t_tokens)
        if len(intersection) / len(t_tokens) >= 0.75:
            return True
            
    return False


def fetch_rss_jobs(target_titles, search_cfg, found_urls, dry_run, dry_urls):
    log("Fetching direct RSS feeds from WeWorkRemotely and Remote.co...")
    discovered = []
    matched_count = 0
    
    feeds = {
        "WeWorkRemotely - All": "https://weworkremotely.com/remote-jobs.rss",
        "WeWorkRemotely - DevOps/SysAdmin": "https://weworkremotely.com/categories/remote-devops-sysadmin-jobs.rss",
        "Remote.co": "https://remote.co/feed/?post_type=job_listing"
    }
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/rss+xml, application/xml, text/xml, */*"
    }
    
    for feed_name, url in feeds.items():
        try:
            log(f"Fetching RSS feed: {feed_name}")
            r = http_get(url, headers=headers, timeout=10, attempts=2)
            if r.status_code != 200:
                log(f"Failed to fetch RSS feed {feed_name}: status code {r.status_code}")
                continue
            
            import warnings
            warnings.filterwarnings("ignore", module="bs4")
            soup = BeautifulSoup(r.content, "html.parser")
            items = soup.find_all("item")
            log(f"Found {len(items)} items in RSS feed: {feed_name}")
            
            for item in items:
                title_elem = item.find("title")
                link_elem = item.find("link")
                desc_elem = item.find("description")
                
                if not title_elem or not link_elem:
                    continue
                
                raw_title = title_elem.text.strip()
                job_url = link_elem.text.strip()
                
                pub_date_elem = item.find("pubdate") or item.find("pubDate")
                pub_date_str = pub_date_elem.text.strip() if pub_date_elem else None
                if not is_recent_date(pub_date_str):
                    continue
                
                if not is_target_job(raw_title, target_titles):
                    continue
                
                nu = normalize_job_url(job_url)
                if not nu:
                    continue
                if not add_if_new_url(nu, found_urls):
                    continue
                
                if dry_run:
                    matched_count += 1
                    log(f"  [DRY RUN MATCH] RSS {feed_name}: '{raw_title}' - {job_url}")
                    append_dry_url({
                        "job_url": job_url,
                        "query": f"RSS: {feed_name}",
                        "title_keyword": raw_title
                    }, dry_urls)
                    continue
                
                raw_desc = desc_elem.text if desc_elem else ""
                jd_text = clean_text(raw_desc).strip()
                
                company_name = "Unknown"
                job_title = raw_title
                
                if "weworkremotely" in job_url.lower():
                    if ":" in raw_title:
                        parts = raw_title.split(":", 1)
                        company_name = parts[0].strip()
                        job_title = parts[1].strip()
                elif "remote.co" in job_url.lower():
                    if " - " in raw_title:
                        title_parts = raw_title.split(" - ")
                        if len(title_parts) >= 2:
                            p0 = title_parts[0].strip()
                            p1 = title_parts[1].strip()
                            if not any(w in p0.lower() for w in ["engineer", "developer", "architect", "lead", "manager", "senior", "junior", "remote"]):
                                company_name = p0
                                job_title = p1
                    if company_name == "Unknown":
                        company_name = "Remote.co"
                
                # Geographic gating
                desc_lower = jd_text.lower()
                exclude_keywords = [
                    "europe only", "uk only", "canada only", "asia only", "latam only", 
                    "eu only", "apac only", "emea only", "germany only", "france only", 
                    "outside us", "outside the us", "outside the united states",
                    "india only", "australia only", "south america only", "africa only",
                    "must be located in europe", "must be based in europe",
                    "must be located in uk", "must be based in uk",
                    "must be located in canada", "must be based in canada"
                ]
                if any(kw in desc_lower for kw in exclude_keywords):
                    continue
                
                location = "Remote"
                if "weworkremotely" in job_url.lower():
                    hq_match = re.search(r'Headquarters:\s*([^\n<]+)', raw_desc, re.IGNORECASE)
                    if hq_match:
                        hq_loc = hq_match.group(1).strip()
                        location = f"{hq_loc} (Remote)"
                        if not is_us_location(hq_loc) and not any(ind in desc_lower for ind in ["united states", "us", "u.s.", "usa"]):
                            continue
                
                parsed_url = urlparse(job_url)
                path_parts = [p for p in parsed_url.path.split('/') if p]
                req_id = path_parts[-1] if path_parts else "Unknown"
                if "remote.co" in job_url.lower():
                    uuid_match = re.search(r'([a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})', req_id)
                    if uuid_match:
                        req_id = uuid_match.group(1)
                
                desc_hash = compute_description_hash(jd_text)
                
                matched_count += 1
                discovered.append({
                    "job_title": job_title,
                    "company_name": company_name,
                    "job_url": job_url,
                    "requirement_id": req_id,
                    "job_description": jd_text,
                    "location_work_type": f"{location} (Remote)",
                    "description_hash": desc_hash,
                    "scraped_at": get_cdt_now_iso(),
                    "posted_at": pub_date_str if pub_date_str else get_cdt_now_iso()
                })
        except Exception as e:
            log(f"Error parsing RSS feed {feed_name}: {e}")
            
    log(f"RSS Discovery complete. Found {matched_count} matching US jobs.")
    return discovered


def fetch_company_board_jobs(companies_cfg, target_titles, found_urls, dry_run, dry_urls):
    log("Fetching direct Greenhouse and Lever company board APIs...")
    discovered = []
    matched_count = 0
    
    greenhouse_companies = companies_cfg.get("greenhouse", [])
    lever_companies = companies_cfg.get("lever", [])
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    def process_greenhouse(company):
        local_discovered = []
        local_matched = 0
        url = f"https://boards-api.greenhouse.io/v1/boards/{company}/jobs?content=true"
        try:
            log(f"Querying Greenhouse API for: {company}")
            r = http_get(url, headers=headers, timeout=10, attempts=3)
            if r.status_code != 200:
                log(f"Greenhouse API for {company} returned status code {r.status_code}")
                return local_discovered, local_matched
            
            data = r.json()
            jobs = data.get("jobs", [])
            log(f"  Greenhouse board '{company}': Found {len(jobs)} total jobs")
            
            for job in jobs:
                title = job.get("title", "").strip()
                if not is_target_job(title, target_titles):
                    continue
                
                updated_at_str = job.get("updated_at")
                if not is_recent_date(updated_at_str):
                    continue
                
                location_name = job.get("location", {}).get("name", "").strip()
                if not is_us_location(location_name):
                    continue
                
                job_url = job.get("absolute_url")
                if not job_url:
                    continue
                
                nu = normalize_job_url(job_url)
                if not nu:
                    continue
                
                if not add_if_new_url(nu, found_urls):
                    continue
                
                if dry_run:
                    local_matched += 1
                    log(f"  [DRY RUN MATCH] Greenhouse '{company}': '{title}' - {job_url}")
                    append_dry_url({
                        "job_url": job_url,
                        "query": f"Greenhouse API: {company}",
                        "title_keyword": title
                    }, dry_urls)
                    continue
                
                content_html = job.get("content", "")
                jd_text = clean_text(content_html).strip()
                
                req_id = str(job.get("id"))
                comp_name = job.get("company_name", company.title())
                
                desc_hash = compute_description_hash(jd_text)
                
                local_matched += 1
                local_discovered.append({
                    "job_title": title,
                    "company_name": comp_name,
                    "job_url": job_url,
                    "requirement_id": req_id,
                    "job_description": jd_text,
                    "location_work_type": f"{location_name} (Remote/Hybrid/Onsite)",
                    "description_hash": desc_hash,
                    "scraped_at": get_cdt_now_iso(),
                    "posted_at": updated_at_str if updated_at_str else get_cdt_now_iso()
                })
        except Exception as e:
            log(f"Error querying Greenhouse board '{company}': {e}")
        return local_discovered, local_matched

    def process_lever(company):
        local_discovered = []
        local_matched = 0
        url = f"https://api.lever.co/v0/postings/{company}?mode=json"
        try:
            log(f"Querying Lever API for: {company}")
            r = http_get(url, headers=headers, timeout=10, attempts=3)
            if r.status_code != 200:
                log(f"Lever API for {company} returned status code {r.status_code}")
                return local_discovered, local_matched
            
            jobs = r.json()
            if not isinstance(jobs, list):
                log(f"Lever API for {company} returned invalid format")
                return local_discovered, local_matched
                
            log(f"  Lever board '{company}': Found {len(jobs)} total jobs")
            
            for job in jobs:
                title = job.get("text", "").strip()
                if not is_target_job(title, target_titles):
                    continue
                
                created_at_ms = job.get("createdAt")
                if not is_recent_date(created_at_ms):
                    continue
                
                country = job.get("country", "")
                location_cat = job.get("categories", {}).get("location", "")
                
                is_us = False
                if country.lower() == "us":
                    is_us = True
                elif is_us_location(location_cat):
                    is_us = True
                
                if not is_us:
                    continue
                
                job_url = job.get("hostedUrl")
                if not job_url:
                    continue
                    
                nu = normalize_job_url(job_url)
                if not nu:
                    continue
                if not add_if_new_url(nu, found_urls):
                    continue
                
                if dry_run:
                    local_matched += 1
                    log(f"  [DRY RUN MATCH] Lever '{company}': '{title}' - {job_url}")
                    append_dry_url({
                        "job_url": job_url,
                        "query": f"Lever API: {company}",
                        "title_keyword": title
                    }, dry_urls)
                    continue
                
                parts = []
                if job.get("descriptionPlain"):
                    parts.append(job["descriptionPlain"])
                elif job.get("description"):
                    parts.append(clean_text(job["description"]))
                
                if job.get("openingPlain"):
                    parts.append(job["openingPlain"])
                elif job.get("opening"):
                    parts.append(clean_text(job["opening"]))
                
                for lst in job.get("lists", []):
                    lst_title = lst.get("text", "")
                    lst_content = lst.get("content", "")
                    if lst_title:
                        parts.append(lst_title)
                    if lst_content:
                        parts.append(clean_text(lst_content))
                
                jd_text = "\n\n".join([p.strip() for p in parts if p.strip()])
                if not jd_text:
                    continue
                    
                req_id = str(job.get("id"))
                comp_name = company.title()
                
                location_work = location_cat or "Remote"
                if job.get("workplaceType"):
                    location_work = f"{location_work} ({job['workplaceType'].title()})"
                
                desc_hash = compute_description_hash(jd_text)
                
                local_matched += 1
                local_discovered.append({
                    "job_title": title,
                    "company_name": comp_name,
                    "job_url": job_url,
                    "requirement_id": req_id,
                    "job_description": jd_text,
                    "location_work_type": f"{location_work}",
                    "description_hash": desc_hash,
                    "scraped_at": get_cdt_now_iso(),
                    "posted_at": datetime.fromtimestamp(created_at_ms / 1000.0, tz=timezone.utc).isoformat() if created_at_ms else get_cdt_now_iso()
                })
        except Exception as e:
            log(f"Error querying Lever board '{company}': {e}")
        return local_discovered, local_matched

    with ThreadPoolExecutor(max_workers=20) as executor:
        futures = []
        for company in greenhouse_companies:
            futures.append(executor.submit(process_greenhouse, company))
        for company in lever_companies:
            futures.append(executor.submit(process_lever, company))
            
        for future in as_completed(futures):
            try:
                res_disc, res_match = future.result()
                discovered.extend(res_disc)
                matched_count += res_match
            except Exception as e:
                log(f"Error processing future: {e}")
            
    log(f"Company API Sourcing complete. Found {matched_count} matching US jobs.")
    return discovered

def fetch_ashby_jobs(companies_cfg, target_titles, found_urls, dry_run, dry_urls):
    log("Fetching direct Ashby company board APIs...")
    discovered = []
    matched_count = 0
    
    ashby_companies = companies_cfg.get("ashby", [])
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    def process_ashby(company):
        local_discovered = []
        local_matched = 0
        url = f"https://api.ashbyhq.com/posting-api/job-board/{company}"
        try:
            log(f"Querying Ashby API for: {company}")
            r = http_get(url, headers=headers, timeout=10, attempts=3)
            if r.status_code != 200:
                log(f"Ashby API for {company} returned status code {r.status_code}")
                return local_discovered, local_matched
                
            data = r.json()
            jobs = data.get("jobs", [])
            log(f"  Ashby board '{company}': Found {len(jobs)} total jobs")
            
            for job in jobs:
                title = job.get("title", "").strip()
                if not is_target_job(title, target_titles):
                    continue
                
                published_at_str = job.get("publishedAt")
                if not is_recent_date(published_at_str):
                    continue
                
                location = job.get("location")
                location = location.strip() if location else ""
                
                is_remote = job.get("isRemote") or False
                
                workplace_type = job.get("workplaceType")
                workplace_type = workplace_type.strip() if workplace_type else ""
                
                loc_str = location
                if is_remote or workplace_type.lower() == "remote":
                    if "remote" not in loc_str.lower():
                        loc_str = f"{loc_str} (Remote)" if loc_str else "Remote"
                
                if not is_us_location(loc_str):
                    continue
                
                job_url = job.get("jobUrl")
                if not job_url:
                    continue
                
                nu = normalize_job_url(job_url)
                if not nu:
                    continue
                if not add_if_new_url(nu, found_urls):
                    continue
                
                if dry_run:
                    local_matched += 1
                    log(f"  [DRY RUN MATCH] Ashby '{company}': '{title}' - {job_url}")
                    append_dry_url({
                        "job_url": job_url,
                        "query": f"Ashby API: {company}",
                        "title_keyword": title
                    }, dry_urls)
                    continue
                
                jd_html = job.get("descriptionHtml", "")
                jd_text = clean_text(jd_html).strip()
                
                req_id = str(job.get("id"))
                comp_name = company.title()
                
                desc_hash = compute_description_hash(jd_text)
                
                local_matched += 1
                local_discovered.append({
                    "job_title": title,
                    "company_name": comp_name,
                    "job_url": job_url,
                    "requirement_id": req_id,
                    "job_description": jd_text,
                    "location_work_type": loc_str,
                    "description_hash": desc_hash,
                    "scraped_at": get_cdt_now_iso(),
                    "posted_at": published_at_str if published_at_str else get_cdt_now_iso()
                })
        except Exception as e:
            log(f"Error querying Ashby board '{company}': {e}")
        return local_discovered, local_matched

    with ThreadPoolExecutor(max_workers=20) as executor:
        futures = []
        for company in ashby_companies:
            futures.append(executor.submit(process_ashby, company))
            
        for future in as_completed(futures):
            try:
                res_disc, res_match = future.result()
                discovered.extend(res_disc)
                matched_count += res_match
            except Exception as e:
                log(f"Error processing future: {e}")
                
    log(f"Ashby API Sourcing complete. Found {matched_count} matching US jobs.")
    return discovered

def fetch_workable_global_jobs(target_titles, found_urls, dry_run, dry_urls):
    log("Fetching direct Workable Global Search API...")
    discovered = []
    matched_count = 0
    import urllib.parse
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    for title_query in target_titles:
        encoded_query = urllib.parse.quote(title_query)
        url = f"https://jobs.workable.com/api/v1/jobs?query={encoded_query}"
        
        try:
            log(f"Querying Workable Global Search for: '{title_query}'")
            r = http_get(url, headers=headers, timeout=15, attempts=2)
            if r.status_code != 200:
                log(f"Workable API for query '{title_query}' returned status code {r.status_code}")
                continue
                
            data = r.json()
            jobs = data.get("jobs", [])
            log(f"  Workable search '{title_query}': Found {len(jobs)} total jobs on first page")
            
            for job in jobs:
                title = job.get("title", "").strip()
                if not is_target_job(title, target_titles):
                    continue
                
                published_at_str = job.get("published")
                if not is_recent_date(published_at_str):
                    continue
                
                location_dict = job.get("location", {}) or {}
                location_parts = []
                city = location_dict.get("city")
                subregion = location_dict.get("subregion")
                country = location_dict.get("countryName")
                if city:
                    location_parts.append(city)
                if subregion:
                    location_parts.append(subregion)
                if country:
                    location_parts.append(country)
                
                loc_str = ", ".join(location_parts)
                workplace = job.get("workplace", "")
                if workplace:
                    if workplace.lower() not in loc_str.lower():
                        loc_str = f"{loc_str} ({workplace.title()})" if loc_str else workplace.title()
                
                if not is_us_location(loc_str):
                    continue
                
                job_url = job.get("url")
                if not job_url:
                    continue
                
                nu = normalize_job_url(job_url)
                if not nu:
                    continue
                if not add_if_new_url(nu, found_urls):
                    continue
                
                if dry_run:
                    matched_count += 1
                    log(f"  [DRY RUN MATCH] Workable: '{title}' - {job_url}")
                    append_dry_url({
                        "job_url": job_url,
                        "query": f"Workable Global Search: {title_query}",
                        "title_keyword": title
                    }, dry_urls)
                    continue
                
                desc_html = job.get("description") or ""
                reqs_html = job.get("requirementsSection") or ""
                benefits_html = job.get("benefitsSection") or ""
                
                full_html = f"{desc_html}\n\n{reqs_html}\n\n{benefits_html}"
                jd_text = clean_text(full_html).strip()
                
                if not jd_text:
                    continue
                    
                req_id = str(job.get("id"))
                company_dict = job.get("company") or {}
                comp_name = (company_dict.get("title") or "Unknown Workable Company").strip()
                
                desc_hash = compute_description_hash(jd_text)
                
                matched_count += 1
                discovered.append({
                    "job_title": title,
                    "company_name": comp_name,
                    "job_url": job_url,
                    "requirement_id": req_id,
                    "job_description": jd_text,
                    "location_work_type": loc_str,
                    "description_hash": desc_hash,
                    "scraped_at": get_cdt_now_iso(),
                    "posted_at": published_at_str if published_at_str else get_cdt_now_iso()
                })
        except Exception as e:
            log(f"Error querying Workable Global Search for '{title_query}': {e}")
            
    log(f"Workable Global Search Sourcing complete. Found {matched_count} matching US jobs.")
    return discovered


def fetch_themuse_jobs(target_titles, found_urls, dry_run, dry_urls):
    log("Fetching direct The Muse Global Search API...")
    discovered = []
    matched_count = 0
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    url = "https://www.themuse.com/api/public/jobs?category=Software%20Engineering&page=1"
    
    try:
        log("Querying The Muse Jobs API...")
        r = http_get(url, headers=headers, timeout=15, attempts=2)
        if r.status_code != 200:
            log(f"The Muse API returned status code {r.status_code}")
            return discovered
            
        data = r.json()
        results = data.get("results", [])
        log(f"  The Muse: Found {len(results)} total jobs on first page")
        
        for job in results:
            title = job.get("name", "").strip()
            if not is_target_job(title, target_titles):
                continue
                
            pub_date_str = job.get("publication_date")
            if not is_recent_date(pub_date_str):
                continue
                
            locations_list = job.get("locations", []) or []
            location_names = [loc.get("name", "") for loc in locations_list if loc.get("name")]
            loc_str = ", ".join(location_names)
            
            if not is_us_location(loc_str):
                continue
                
            job_url = job.get("refs", {}).get("landing_page")
            if not job_url:
                continue
                
            nu = normalize_job_url(job_url)
            if not nu:
                continue
            if not add_if_new_url(nu, found_urls):
                continue
            
            if dry_run:
                matched_count += 1
                log(f"  [DRY RUN MATCH] The Muse: '{title}' - {job_url}")
                append_dry_url({
                    "job_url": job_url,
                    "query": "The Muse API",
                    "title_keyword": title
                }, dry_urls)
                continue
                
            contents_html = job.get("contents", "")
            jd_text = clean_text(contents_html).strip()
            if not jd_text:
                continue
                
            req_id = str(job.get("id"))
            comp_name = job.get("company", {}).get("name", "Unknown Muse Company").strip()
            
            desc_hash = compute_description_hash(jd_text)
            
            matched_count += 1
            discovered.append({
                "job_title": title,
                "company_name": comp_name,
                "job_url": job_url,
                "requirement_id": req_id,
                "job_description": jd_text,
                "location_work_type": loc_str,
                "description_hash": desc_hash,
                "scraped_at": get_cdt_now_iso(),
                "posted_at": pub_date_str if pub_date_str else get_cdt_now_iso()
            })
    except Exception as e:
        log(f"Error querying The Muse API: {e}")
        
    log(f"The Muse Sourcing complete. Found {matched_count} matching US jobs.")
    return discovered


def fetch_smartrecruiters_jobs(companies_cfg, target_titles, found_urls, dry_run, dry_urls):
    log("Fetching direct SmartRecruiters company board APIs...")
    discovered = []
    matched_count = 0
    
    smart_companies = companies_cfg.get("smartrecruiters", [])
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    def process_smart(company):
        local_discovered = []
        local_matched = 0
        url = f"https://api.smartrecruiters.com/v1/companies/{company}/postings"
        try:
            log(f"Querying SmartRecruiters API for: {company}")
            r = http_get(url, headers=headers, timeout=10, attempts=3)
            if r.status_code != 200:
                log(f"SmartRecruiters API for {company} returned status code {r.status_code}")
                return local_discovered, local_matched
                
            data = r.json()
            jobs = data.get("content", [])
            log(f"  SmartRecruiters board '{company}': Found {len(jobs)} total jobs")
            
            for job in jobs:
                title = job.get("name", "").strip()
                if not is_target_job(title, target_titles):
                    continue
                    
                released_date_str = job.get("releasedDate")
                if not is_recent_date(released_date_str):
                    continue
                    
                loc_dict = job.get("location", {}) or {}
                city = loc_dict.get("city")
                region = loc_dict.get("region")
                country = loc_dict.get("country")
                loc_parts = [p for p in [city, region, country] if p]
                loc_str = ", ".join(loc_parts)
                
                if job.get("releasedOfWork") or job.get("remote") or "remote" in loc_str.lower():
                    if "remote" not in loc_str.lower():
                        loc_str = f"{loc_str} (Remote)" if loc_str else "Remote"
                        
                if not is_us_location(loc_str):
                    continue
                    
                job_id = job.get("id")
                if not job_id:
                    continue
                job_url = f"https://jobs.smartrecruiters.com/{company}/{job_id}"
                
                nu = normalize_job_url(job_url)
                if not nu:
                    continue
                if not add_if_new_url(nu, found_urls):
                    continue
                
                if dry_run:
                    local_matched += 1
                    log(f"  [DRY RUN MATCH] SmartRecruiters '{company}': '{title}' - {job_url}")
                    append_dry_url({
                        "job_url": job_url,
                        "query": f"SmartRecruiters API: {company}",
                        "title_keyword": title
                    }, dry_urls)
                    continue
                    
                posting_url = f"https://api.smartrecruiters.com/v1/companies/{company}/postings/{job_id}"
                
                try:
                    p_r = http_get(posting_url, headers=headers, timeout=10, attempts=3)
                    if p_r.status_code == 200:
                        p_data = p_r.json()
                        sections = p_data.get("sections", {}) or {}
                        
                        desc_text = ""
                        for sec_name, sec_dict in sections.items():
                            if sec_dict and isinstance(sec_dict, dict):
                                text_val = sec_dict.get("text", "")
                                title_val = sec_dict.get("title", "")
                                if text_val:
                                    desc_text += f"\n\n### {title_val}\n{text_val}" if title_val else f"\n\n{text_val}"
                                    
                        jd_text = clean_text(desc_text).strip()
                    else:
                        jd_text = ""
                except Exception as ex:
                    log(f"Error querying SmartRecruiters details for {job_id}: {ex}")
                    jd_text = ""
                    
                if not jd_text:
                    continue
                    
                comp_name = company.title()
                desc_hash = compute_description_hash(jd_text)
                
                local_matched += 1
                local_discovered.append({
                    "job_title": title,
                    "company_name": comp_name,
                    "job_url": job_url,
                    "requirement_id": str(job_id),
                    "job_description": jd_text,
                    "location_work_type": loc_str,
                    "description_hash": desc_hash,
                    "scraped_at": get_cdt_now_iso(),
                    "posted_at": released_date_str if released_date_str else get_cdt_now_iso()
                })
        except Exception as e:
            log(f"Error querying SmartRecruiters board '{company}': {e}")
        return local_discovered, local_matched

    from concurrent.futures import ThreadPoolExecutor, as_completed
    with ThreadPoolExecutor(max_workers=20) as executor:
        futures = []
        for company in smart_companies:
            futures.append(executor.submit(process_smart, company))
            
        for future in as_completed(futures):
            try:
                res_disc, res_match = future.result()
                discovered.extend(res_disc)
                matched_count += res_match
            except Exception as e:
                log(f"Error processing future: {e}")
                
    log(f"SmartRecruiters API Sourcing complete. Found {matched_count} matching US jobs.")
    return discovered


def discover_new_slugs(discovered_urls, target_companies_cfg):
    log("Scanning discovered URLs for new company slugs...")
    greenhouse_slugs = set(target_companies_cfg.get("greenhouse", []))
    lever_slugs = set(target_companies_cfg.get("lever", []))
    ashby_slugs = set(target_companies_cfg.get("ashby", []))
    smart_slugs = set(target_companies_cfg.get("smartrecruiters", []))
    
    new_greenhouse = []
    new_lever = []
    new_ashby = []
    new_smart = []
    
    import urllib.parse
    
    for url in discovered_urls:
        try:
            parsed = urllib.parse.urlparse(url)
            netloc = parsed.netloc.lower()
            path = parsed.path
            
            if "greenhouse.io" in netloc:
                parts = [p for p in path.split("/") if p]
                if parts and parts[0] not in ("embed", "v1", "boards", "jobs"):
                    slug = parts[0]
                    if slug not in greenhouse_slugs:
                        greenhouse_slugs.add(slug)
                        new_greenhouse.append(slug)
                elif len(parts) > 1 and parts[0] in ("boards", "jobs"):
                    slug = parts[1]
                    if slug not in greenhouse_slugs:
                        greenhouse_slugs.add(slug)
                        new_greenhouse.append(slug)
            
            elif "lever.co" in netloc:
                parts = [p for p in path.split("/") if p]
                if parts and parts[0] not in ("embed", "v0", "postings"):
                    slug = parts[0]
                    if slug not in lever_slugs:
                        lever_slugs.add(slug)
                        new_lever.append(slug)
            
            elif "ashbyhq.com" in netloc:
                parts = [p for p in path.split("/") if p]
                if parts:
                    slug = parts[0]
                    if slug not in ashby_slugs:
                        ashby_slugs.add(slug)
                        new_ashby.append(slug)
            
            elif "smartrecruiters.com" in netloc:
                parts = [p for p in path.split("/") if p]
                if parts and parts[0] not in ("postings", "v1"):
                    slug = parts[0]
                    if slug not in smart_slugs:
                        smart_slugs.add(slug)
                        new_smart.append(slug)
                        
        except Exception:
            pass
            
    if new_greenhouse or new_lever or new_ashby or new_smart:
        log(f"Discovered new slugs to auto-add: Greenhouse: {new_greenhouse}, Lever: {new_lever}, Ashby: {new_ashby}, SmartRecruiters: {new_smart}")
        target_companies_cfg["greenhouse"] = sorted(list(greenhouse_slugs))
        target_companies_cfg["lever"] = sorted(list(lever_slugs))
        target_companies_cfg["ashby"] = sorted(list(ashby_slugs))
        target_companies_cfg["smartrecruiters"] = sorted(list(smart_slugs))
        
        try:
            config_data = {}
            if CONFIG_PATH.exists():
                config_data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            config_data["target_companies"] = target_companies_cfg
            CONFIG_PATH.write_text(json.dumps(config_data, indent=2), encoding="utf-8")
            log("Successfully updated config.json with newly discovered slugs.")
        except Exception as e:
            log(f"Error saving updated config.json: {e}")


def main(dry_run=False):
    _RUN_START_ISO = datetime.now(timezone.utc).isoformat()
    target_titles = []
    config_data = {}
    if CONFIG_PATH.exists():
        try:
            config_data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            target_titles = config_data.get("target_titles", [])
        except Exception as e:
            log(f"Warning: Failed to load config.json: {e}")

    if not target_titles:
        try:
            if str(WORKSPACE) not in sys.path:
                sys.path.insert(0, str(WORKSPACE))
            from jobsearch_constants import DEFAULT_TARGET_TITLES

            target_titles = list(DEFAULT_TARGET_TITLES)
        except Exception:
            target_titles = [
                "DevOps Engineer",
                "Cloud Automation Engineer",
                "Platform Engineering",
                "Cloud Infrastructure Engineer",
                "DevSecOps",
                "Site Reliability Engineer (SRE)",
                "Continuous Integration (CI/CD)",
                "System Engineer",
            ]

    search_cfg = config_data.get("search") or {}
    merge_previous = search_cfg.get("merge_previous_scrape", True)
    merged_by_url = {}
    if merge_previous and SCRAPED_OUTPUT.exists():
        try:
            mtime = datetime.fromtimestamp(SCRAPED_OUTPUT.stat().st_mtime, tz=timezone(timedelta(hours=-5))).isoformat()
            for j in json.loads(SCRAPED_OUTPUT.read_text(encoding="utf-8")):
                u = j.get("job_url")
                if u:
                    if "scraped_at" not in j:
                        j["scraped_at"] = mtime
                    if "description_hash" not in j and j.get("job_description"):
                        j["description_hash"] = compute_description_hash(j["job_description"])
                    merged_by_url[normalize_job_url(u)] = j
        except Exception as e:
            log(f"Warning: could not merge previous scraped_jobs.json: {e}")

    found_urls = set()
    if merge_previous:
        found_urls.update(merged_by_url.keys())
        log(f"Pre-populated seen cache with {len(found_urls)} previously scraped URLs to avoid duplicate searches.")
    scraped_jobs = []
    dry_urls = []

    # 1. Fetch Sourcing Channels in Parallel
    target_companies = config_data.get("target_companies", {})
    
    tasks = {
        "RSS Feeds": lambda: fetch_rss_jobs(target_titles, search_cfg, found_urls, dry_run, dry_urls),
        "Greenhouse/Lever APIs": lambda: fetch_company_board_jobs(target_companies, target_titles, found_urls, dry_run, dry_urls),
        "Ashby API": lambda: fetch_ashby_jobs(target_companies, target_titles, found_urls, dry_run, dry_urls),
        "Workable API": lambda: fetch_workable_global_jobs(target_titles, found_urls, dry_run, dry_urls),
        "SmartRecruiters API": lambda: fetch_smartrecruiters_jobs(target_companies, target_titles, found_urls, dry_run, dry_urls),
        "The Muse API": lambda: fetch_themuse_jobs(target_titles, found_urls, dry_run, dry_urls),
        "LinkedIn Guest API": lambda: fetch_linkedin_guest_jobs(target_titles, search_cfg, found_urls, dry_run, dry_urls),
        "Hacker News Sourcing": lambda: fetch_hn_hiring_jobs(target_titles, found_urls, dry_run, dry_urls),
        "Jooble API": lambda: fetch_jooble_jobs(target_titles, search_cfg, found_urls, dry_run, dry_urls)
    }

    log(f"Launching {len(tasks)} job sourcing channels concurrently...")
    with ThreadPoolExecutor(max_workers=8) as executor:
        future_to_task = {executor.submit(func): name for name, func in tasks.items()}
        for future in as_completed(future_to_task):
            name = future_to_task[future]
            try:
                jobs_list = future.result()
                if jobs_list:
                    scraped_jobs.extend(jobs_list)
                    log(f"Finished concurrent channel '{name}': Sourced {len(jobs_list)} jobs.")
                else:
                    log(f"Finished concurrent channel '{name}': Sourced 0 jobs.")
            except Exception as e:
                log(f"Error executing concurrent channel '{name}': {e}")

    # 2. Yahoo Search Sourcing
    log("Starting Yahoo search for US job postings (remote / hybrid / onsite)...")
    if dry_run:
        log("DRY RUN: collecting URLs only (no per-job page scrape).")

    if not SEARCH_STATE["aborted"] and not _yahoo_reachable():
        log(
            "Skipping Yahoo search discovery entirely: a single reachability probe failed "
            "(persistent block/rate-limit from this IP, not a transient blip). Avoids "
            "burning the per-title 5-failure circuit breaker independently in every "
            "concurrent search worker before each one discovers the same block."
        )
        SEARCH_STATE["aborted"] = True

    yield_threshold = search_cfg.get("yield_threshold", 2)
    api_key = os.environ.get("GEMINI_API_KEY")

    synonyms_map = {} if SEARCH_STATE["aborted"] else expand_target_titles_with_gemini(target_titles, api_key)

    log(f"Running Yahoo searches for {len(target_titles)} target titles in a throttled thread pool...")
    
    def process_title_search(title):
        title_jobs = []
        if SEARCH_STATE["aborted"]:
            return title_jobs
        
        log(f"Processing target title search: '{title}'")
        new_jobs, urls_found = search_and_scrape_for_keyword(title, search_cfg, found_urls, dry_run, dry_urls)
        title_jobs.extend(new_jobs)

        current_yield = len(new_jobs) if not dry_run else urls_found

        if current_yield < yield_threshold:
            syns = synonyms_map.get(title, [])
            if syns:
                log(f"Yield of {current_yield} for '{title}' is below threshold of {yield_threshold}. Triggering query expansion with synonyms: {syns}")
                for synonym in syns:
                    if SEARCH_STATE["aborted"]:
                        break
                    log(f"Executing expanded search for synonym: '{synonym}' (original: '{title}')")
                    syn_jobs, syn_urls_found = search_and_scrape_for_keyword(synonym, search_cfg, found_urls, dry_run, dry_urls)
                    title_jobs.extend(syn_jobs)
        return title_jobs

    with ThreadPoolExecutor(max_workers=2) as search_executor:
        search_futures = [search_executor.submit(process_title_search, title) for title in target_titles]
        for fut in as_completed(search_futures):
            try:
                res_jobs = fut.result()
                if res_jobs:
                    scraped_jobs.extend(res_jobs)
            except Exception as e:
                log(f"Error processing Yahoo title search: {e}")

    # 3. Dynamic Slug Discovery (auto-detect new company boards from crawler logs)
    discover_new_slugs(found_urls, target_companies)

    if dry_run:
        out_path = WORKSPACE / "dry_run_urls.json"
        out_path.write_text(json.dumps(dry_urls, indent=2), encoding="utf-8")
        log(f"Dry run complete. Unique URLs: {len(found_urls)}. Saved list to {out_path}")
        return

    final_map = dict(merged_by_url)
    for j in scraped_jobs:
        u = j.get("job_url")
        if u:
            final_map[normalize_job_url(u)] = j
    out_list = list(final_map.values())
    
    # Extract salary and benefits data
    try:
        from salary_extractor import extract_salary
        from benefits_extractor import extract_benefits
        for j in out_list:
            if "posted_at" not in j or not j["posted_at"]:
                j["posted_at"] = j.get("scraped_at") or get_cdt_now_iso()
            if not j.get("salary_text"):
                sal_info = extract_salary(j.get("job_description", ""), j.get("job_title", ""))
                if sal_info:
                    j.update(sal_info)
            if not j.get("benefits"):
                j["benefits"] = extract_benefits(j.get("job_description", ""))
    except Exception as e:
        log(f"Warning: Failed to extract salary/benefits/posted_at data: {e}")

    try:
        from job_identity import enrich_job_list

        enrich_job_list(out_list)
    except Exception as e:
        log(f"Warning: job_identity enrich failed: {e}")

    # Enforce that only jobs from the target 10k H-1B sponsors are kept
    try:
        log("Filtering scraped jobs against the 10k H-1B/OPT sponsors database...")
        from dashboard_server import get_h1b_sponsors_cleaned, is_sponsor_match
        sponsors = get_h1b_sponsors_cleaned()
        if sponsors:
            filtered_out_list = []
            for j in out_list:
                company = j.get("company_name", "")
                if company:
                    match_data = is_sponsor_match(company, sponsors)
                    if match_data:
                        j["visa_sponsor"] = True
                        j["sponsor_metadata"] = match_data
                        filtered_out_list.append(j)
            log(f"H-1B Sponsor Filter: kept {len(filtered_out_list)} of {len(out_list)} jobs.")
            out_list = filtered_out_list
        else:
            log("Warning: H-1B sponsors cache is empty. Skipping filtering.")
    except Exception as e:
        log(f"Error filtering jobs against H-1B sponsors database: {e}")

    _t_save = time.perf_counter()
    SCRAPED_OUTPUT.write_text(json.dumps(out_list, indent=2), encoding="utf-8")
    _record_substep("save_to_json", time.perf_counter() - _t_save, metadata={"jobs_written": len(out_list)})

    log(f"Completed search and scrape. New/changed rows this run: {len(scraped_jobs)}. Total in {SCRAPED_OUTPUT.name}: {len(out_list)}")

    try:
        from pipeline_metrics import generate_run_summary

        generate_run_summary(str(WORKSPACE), _RUN_START_ISO)
    except Exception:
        pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Yahoo site: discovery and ATS scrape for MAAS jobsearch.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only collect Yahoo result URLs; write dry_run_urls.json and exit.",
    )
    parser.add_argument(
        "--past-24h",
        action="store_true",
        help="Only search for jobs posted in the last 24 hours.",
    )
    args = parser.parse_args()
    
    PAST_24H = args.past_24h or os.environ.get("JOBSEARCH_PAST_24H", "").strip().lower() in ("1", "true", "yes")
    
    dry = args.dry_run or os.environ.get("JOBSEARCH_DRY_RUN", "").strip().lower() in ("1", "true", "yes")
    main(dry_run=dry)
