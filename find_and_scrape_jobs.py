import os
import re
import sys
import json
import time
import logging
import argparse
import requests
import hashlib
import random
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from bs4 import BeautifulSoup
from urllib.parse import urlparse, quote_plus, parse_qs
from playwright.sync_api import sync_playwright
from dotenv import load_dotenv

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:123.0) Gecko/20100101 Firefox/123.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 Edg/122.0.0.0"
]

def get_random_user_agent():
    return random.choice(USER_AGENTS)

def compute_description_hash(description):
    if not description:
        return ""
    normalized = "".join(description.lower().split())
    return hashlib.sha256(normalized.encode('utf-8')).hexdigest()

def search_duckduckgo(query):
    headers = {
        "User-Agent": get_random_user_agent(),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8"
    }
    url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
    links = []
    try:
        r = http_get(url, headers=headers, timeout=15)
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, 'html.parser')
            for a in soup.find_all('a', href=True):
                href = a['href']
                if 'uddg=' in href:
                    parsed_href = urlparse(href)
                    queries = parse_qs(parsed_href.query)
                    actual_url = queries.get('uddg', [None])[0]
                    if actual_url:
                        href = actual_url
                
                if any(tgt in href for tgt in ['boards.greenhouse.io', 'jobs.lever.co', 'myworkdayjobs.com', 'jobs.ashbyhq.com', 'apply.workable.com', 'jobs.smartrecruiters.com', 'weworkremotely.com', 'remote.co', 'linkedin.com/jobs/view', 'workatastartup.com/jobs']):
                    links.append(href)
    except Exception as e:
        log(f"DuckDuckGo search error for '{query}': {e}")
    
    valid_links = []
    for link in links:
        parsed = urlparse(link)
        domain = parsed.netloc.lower()
        if any(bad in domain for bad in ['duckduckgo.com']):
            continue
        if any(tgt in domain for tgt in ['greenhouse.io', 'lever.co', 'myworkdayjobs.com', 'ashbyhq.com', 'workable.com', 'smartrecruiters.com', 'weworkremotely.com', 'remote.co', 'linkedin.com', 'workatastartup.com']):
            path_parts = [p for p in parsed.path.split('/') if p]
            if 'greenhouse.io' in domain:
                if len(path_parts) >= 3 and path_parts[1] == 'jobs':
                    valid_links.append(link)
            elif 'lever.co' in domain:
                if len(path_parts) >= 2:
                    valid_links.append(link)
            elif 'myworkdayjobs.com' in domain:
                if 'job' in path_parts:
                    valid_links.append(link)
            elif 'ashbyhq.com' in domain:
                if len(path_parts) >= 2:
                    valid_links.append(link)
            elif 'workable.com' in domain:
                if len(path_parts) >= 3 and path_parts[1] == 'j':
                    valid_links.append(link)
            elif 'smartrecruiters.com' in domain:
                if len(path_parts) >= 2 and '-' in path_parts[1] and path_parts[1].split('-')[0].isdigit():
                    valid_links.append(link)
            elif 'weworkremotely.com' in domain:
                if 'remote-jobs' in path_parts:
                    valid_links.append(link)
            elif 'remote.co' in domain:
                if 'job-details' in path_parts or 'job' in path_parts:
                    valid_links.append(link)
            elif 'linkedin.com' in domain:
                if 'view' in path_parts:
                    valid_links.append(link)
            elif 'workatastartup.com' in domain:
                if 'jobs' in path_parts:
                    valid_links.append(link)
    return list(set(valid_links))

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

def scrape_url_with_gemini_fallback(url, api_key):
    if not api_key:
        return None
    log(f"Triggering Gemini fallback parser for: {url}")
    html = fetch_with_playwright(url)
    if not html:
        return None
    return extract_job_with_gemini(url, html, api_key)



from jobsearch_paths import workspace_root

WORKSPACE = workspace_root()
load_dotenv(dotenv_path=str(WORKSPACE / ".env"))
CONFIG_PATH = WORKSPACE / "config.json"
SCRAPED_OUTPUT = WORKSPACE / "scraped_jobs.json"


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
    """GET with simple exponential backoff on connection errors."""
    last_exc = None
    h = headers or {}
    for i in range(attempts):
        try:
            return requests.get(url, headers=h, timeout=timeout)
        except (requests.RequestException, OSError) as e:
            last_exc = e
            time.sleep(min(2 ** i, 8))
    if last_exc:
        raise last_exc
    return requests.get(url, headers=h, timeout=timeout)

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

def fetch_with_playwright(url):
    last_err = None
    for attempt in range(1, 4):
        try:
            # Randomized pre-navigation delay (1-3s)
            time.sleep(random.uniform(1.0, 3.0))
            with sync_playwright() as p:
                browser = p.webkit.launch(headless=True)
                context = browser.new_context(
                    user_agent=get_random_user_agent()
                )
                page = context.new_page()
                page.goto(url, wait_until="commit", timeout=20000)
                # Randomized post-navigation delay (2.5-4.5s)
                time.sleep(random.uniform(2.5, 4.5))
                html = page.content()
                browser.close()
                return html
        except Exception as e:
            last_err = e
            log(f"Playwright attempt {attempt} failed for {url}: {e}")
            time.sleep(min(2 ** attempt, 8))
    print(f"Playwright WebKit error for {url}: {last_err}", flush=True)
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
    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
    try:
        response = http_get(url, headers=headers, timeout=10)
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
        return {
            "job_title": title,
            "company_name": company,
            "job_url": url,
            "requirement_id": req_id,
            "job_description": jd_text.strip(),
            "location_work_type": "Remote"
        }
    except Exception as e:
        print(f"Failed to scrape Workday URL {url}: {e}")
        return None

def scrape_ashby(url):
    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
    try:
        response = http_get(url, headers=headers, timeout=10)
        # Handle redirects or inactive job postings
        if response.status_code != 200:
            return None
            
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Check if it redirected away from the job ID path segment
        parsed = urlparse(url)
        path_parts = [p for p in parsed.path.split('/') if p]
        final_parsed = urlparse(response.url)
        final_path_parts = [p for p in final_parsed.path.split('/') if p]
        
        # If the path segments decreased significantly, it redirected to company board
        if len(final_path_parts) < len(path_parts) and len(final_path_parts) <= 1:
            print(f"  Inactive: Ashby page redirected to company board.", flush=True)
            return None
            
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
                return None
                
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
            return None
            
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

def scrape_linkedin(url):
    try:
        html = fetch_with_playwright(url)
        if not html:
            return None
        soup = BeautifulSoup(html, 'html.parser')
        title_elem = soup.find('h1', class_=re.compile('topcard__title|job-search-card__title|title')) or soup.find('h1')
        title = title_elem.get_text().strip() if title_elem else "Unknown Title"
        if "login" in url.lower() or not title or title == "Sign Up" or title == "Unknown Title":
            return None
        company_elem = soup.find('a', class_=re.compile('topcard__org-name-link|company-name')) or soup.find('span', class_=re.compile('topcard__flavor'))
        company = company_elem.get_text().strip() if company_elem else "Unknown"
        loc_elem = soup.find('span', class_=re.compile('topcard__flavor--bullet')) or soup.find('span', class_=re.compile('topcard__flavor--bullet-location'))
        location = loc_elem.get_text().strip() if loc_elem else "Remote"
        jd_div = soup.find('div', class_=re.compile('description__text|show-more-less-html__markup|description'))
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
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8"
    }
    url = f"https://search.yahoo.com/search?p={quote_plus(query)}"
    links = []
    try:
        r = http_get(url, headers=headers, timeout=15)
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, 'html.parser')
            for a in soup.find_all('a', href=True):
                href = a['href']
                if any(tgt in href for tgt in ['boards.greenhouse.io', 'jobs.lever.co', 'myworkdayjobs.com', 'jobs.ashbyhq.com', 'apply.workable.com', 'jobs.smartrecruiters.com', 'weworkremotely.com', 'remote.co', 'linkedin.com/jobs/view', 'workatastartup.com/jobs']):
                    m = re.search(r'RU=([^/]+)', href)
                    if m:
                        from urllib.parse import unquote
                        actual_url = unquote(m.group(1))
                        links.append(actual_url)
                    else:
                        links.append(href)
    except Exception as e:
        log(f"Yahoo search error for '{query}': {e}")
    
    # Filter valid links
    valid_links = []
    for link in links:
        parsed = urlparse(link)
        domain = parsed.netloc.lower()
        if any(bad in domain for bad in ['search.yahoo.com', 'scout.yahoo.com', 'login.yahoo.com']):
            continue
        if any(tgt in domain for tgt in ['greenhouse.io', 'lever.co', 'myworkdayjobs.com', 'ashbyhq.com', 'workable.com', 'smartrecruiters.com', 'weworkremotely.com', 'remote.co', 'linkedin.com', 'workatastartup.com']):
            path_parts = [p for p in parsed.path.split('/') if p]
            if 'greenhouse.io' in domain:
                # Job pages look like /company/jobs/12345
                if len(path_parts) >= 3 and path_parts[1] == 'jobs':
                    valid_links.append(link)
            elif 'lever.co' in domain:
                # Job pages look like /company/uuid
                if len(path_parts) >= 2:
                    valid_links.append(link)
            elif 'myworkdayjobs.com' in domain:
                # Job pages look like /company/job/details
                if 'job' in path_parts:
                    valid_links.append(link)
            elif 'ashbyhq.com' in domain:
                # Job pages look like /company/job-uuid
                if len(path_parts) >= 2:
                    valid_links.append(link)
            elif 'workable.com' in domain:
                # Job pages look like /company/j/job-shortcode/
                if len(path_parts) >= 3 and path_parts[1] == 'j':
                    valid_links.append(link)
            elif 'smartrecruiters.com' in domain:
                # Job pages look like /company/posting-id-slug
                # Skip main lists (which have no hyphen or posting id)
                if len(path_parts) >= 2 and '-' in path_parts[1] and path_parts[1].split('-')[0].isdigit():
                    valid_links.append(link)
            elif 'weworkremotely.com' in domain:
                # Job pages look like /remote-jobs/slug
                if 'remote-jobs' in path_parts:
                    valid_links.append(link)
            elif 'remote.co' in domain:
                # Job pages look like /job-details/slug
                if 'job-details' in path_parts or 'job' in path_parts:
                    valid_links.append(link)
            elif 'linkedin.com' in domain:
                if 'view' in path_parts:
                    valid_links.append(link)
            elif 'workatastartup.com' in domain:
                if 'jobs' in path_parts:
                    valid_links.append(link)
    return list(set(valid_links))

def normalize_job_url(url):
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
    core = [
        f'site:boards.greenhouse.io "{title}" {us}',
        f'site:jobs.lever.co "{title}" {us}',
        f'site:myworkdayjobs.com "{title}" {us}',
        f'site:jobs.ashbyhq.com "{title}" {us}',
        f'site:apply.workable.com "{title}" {us}',
        f'site:jobs.smartrecruiters.com "{title}" {us}',
        f'site:linkedin.com/jobs/view "{title}" {us}',
        f'site:workatastartup.com/jobs "{title}" {us}',
    ]
    if search_cfg.get("include_remote_primary_boards", True):
        core.extend([
            f'site:weworkremotely.com "{title}" {us}',
            f'site:remote.co "{title}" {us}',
        ])
    return core


def expand_target_titles_with_gemini(target_titles, api_key):
    """
    Expand target titles using Gemini 2.5 Flash, falling back to a static mapping if it fails or key is missing.
    """
    STATIC_SYNONYM_FALLBACK = {
        "DevOps Engineer": ["DevOps", "Site Reliability Engineer", "SRE"],
        "Cloud Automation Engineer": ["Cloud Infrastructure Engineer", "Automation Engineer", "Cloud Engineer"],
        "Platform Engineer": ["Platform Engineering", "Infrastructure Engineer", "DevOps Engineer"],
        "Cloud Infrastructure Engineer": ["Cloud Engineer", "Infrastructure Engineer", "DevOps"],
        "Cloud Security Engineer": ["Security Engineer", "DevSecOps", "Cloud SecOps"],
        "DevSecOps": ["DevSecOps Engineer", "Security Engineer", "DevOps Security"],
        "Site Reliability Engineer": ["SRE", "Reliability Engineer", "DevOps Engineer"],
        "CI/CD Engineer": ["Release Engineer", "Build Engineer", "DevOps CI/CD"],
        "Systems Engineer": ["System Engineer", "Linux Systems Engineer", "Operations Engineer"],
        "Cloud Network Engineer": ["Network Engineer", "Cloud Network Administrator"],
        "Data Platform Engineer": ["Data Infrastructure Engineer", "Data Engineer", "Data Ops"],
        "Machine Learning Engineer": ["MLOps Engineer", "ML Infrastructure Engineer", "Machine Learning Infrastructure"],
        "AI Platform Engineer": ["AI Infrastructure Engineer", "AIOps Engineer", "AI Platform"]
    }
    
    if not api_key:
        log("No Gemini API key found for query expansion. Falling back to static synonym mapping.")
        return {title: STATIC_SYNONYM_FALLBACK.get(title, []) for title in target_titles}

    try:
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(
            model_name="gemini-2.5-flash",
            generation_config={"response_mime_type": "application/json"}
        )
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
        log(f"Gemini query expansion failed: {e}. Falling back to static synonym mapping.")
        return {title: STATIC_SYNONYM_FALLBACK.get(title, []) for title in target_titles}


def scrape_single_url(href, api_key=None):
    domain = urlparse(href).netloc.lower()
    job_data = None
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
            job_data = scrape_url_with_gemini_fallback(href, api_key)
    except Exception as e:
        print(f"Scraper error for {href}: {e}", flush=True)

    if not job_data or len(job_data.get("job_description", "")) < 200:
        if api_key:
            try:
                job_data = scrape_url_with_gemini_fallback(href, api_key)
            except Exception as e:
                print(f"Gemini fallback scraper failed for {href}: {e}", flush=True)
                
    if job_data:
        desc = job_data.get("job_description", "")
        if desc:
            job_data["description_hash"] = compute_description_hash(desc)
            
    return job_data

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
        log(f"Searching: {query}")
        urls = search_yahoo(query)
        if not urls:
            log(f"Yahoo search returned 0 results for '{query}'. Falling back to DuckDuckGo...")
            urls = search_duckduckgo(query)
        time.sleep(2)

        for href in urls:
            nu = normalize_job_url(href)
            if not nu:
                continue
            if nu in found_urls:
                continue
            found_urls.add(nu)
            urls_found_for_keyword += 1

            if dry_run:
                dry_urls.append({"job_url": href, "query": query, "title_keyword": keyword})
                continue
            
            urls_to_scrape.append(href)

    if not dry_run and urls_to_scrape:
        log(f"Scraping {len(urls_to_scrape)} URLs in parallel for keyword '{keyword}'...")
        api_key = os.environ.get("GEMINI_API_KEY")
        with ThreadPoolExecutor(max_workers=4) as executor:
            future_to_url = {executor.submit(scrape_single_url, url, api_key): url for url in urls_to_scrape}
            for future in as_completed(future_to_url):
                url = future_to_url[future]
                try:
                    job_data = future.result()
                    if job_data and job_data.get("job_description"):
                        if job_data.get("requirement_id") and job_data.get("requirement_id") != "Unknown":
                            log(f"Scraped: '{job_data['job_title']}' at '{job_data['company_name']}' - Req ID: {job_data['requirement_id']}")
                            job_data["scraped_at"] = datetime.utcnow().isoformat()
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
    
    # Negative indicators - exclude if matched and no positive US indicators are present
    negative_indicators = [
        "europe", "uk", "london", "india", "germany", "france", "canada", "latam", 
        "emea", "apac", "australia", "asia", "singapore", "netherlands", "brazil", 
        "spain", "poland", "ukraine", "philippines", "ireland", "tokyo", "japan",
        "dublin", "toronto", "paris", "berlin", "munich", "sydney", "melbourne", 
        "bengaluru", "bangalore", "vancouver", "montreal", "bucharest", "sao paulo", 
        "amsterdam", "krakow", "mexico", "sweden", "stockholm", "zurich"
    ]
    has_negative = any(ni in loc_lower for ni in negative_indicators)
    
    # Positive indicators
    us_indicators = ["united states", "us", "u.s.", "usa", "u.s.a", "remote - us", "remote us", "remote, us", "america"]
    has_positive = any(ind in loc_lower for ind in us_indicators)
    
    if has_positive:
        return True
        
    # Check major US cities
    us_cities = [
        "san francisco", "sf", "seattle", "new york", "nyc", "austin", "chicago", "boston", 
        "denver", "los angeles", "la", "atlanta", "dallas", "houston", "miami", "philadelphia", 
        "phoenix", "san diego", "san jose", "sunnyvale", "mountain view", "palo alto", "redmond", 
        "bellevue", "oakland", "detroit", "minneapolis", "portland", "salt lake city", "pittsburgh", 
        "washington", "arlington", "boulder", "cambridge", "raleigh", "durham", "charlotte", 
        "nashville", "salt lake", "las vegas", "orlando", "tampa", "tempe", "culver city",
        "menlo park", "cupertino", "santa clara", "redwood city", "irvine", "berkeley"
    ]
    if any(city in loc_lower for city in us_cities):
        if not has_negative:
            return True
            
    # Check words for "us" or "usa"
    words = re.findall(r'\b[a-z]+\b', loc_lower)
    if "us" in words or "usa" in words or "america" in words:
        return True
        
    # State postal codes
    us_states = {
        "al", "ak", "az", "ar", "ca", "co", "ct", "de", "fl", "ga", "hi", "id", "il", "in", "ia", "ks", "ky", "la", "me", "md",
        "ma", "mi", "mn", "ms", "mo", "mt", "ne", "nv", "nh", "nj", "nm", "ny", "nc", "nd", "oh", "ok", "or", "pa", "ri", "sc",
        "sd", "tn", "tx", "ut", "vt", "va", "wa", "wv", "wi", "wy"
    }
    for word in words:
        if word in us_states:
            if word in ["in", "or", "me", "la", "ma", "co"]:
                match = re.search(r'\b,\s*' + word + r'\b', loc_lower)
                if match:
                    return True
            else:
                return True
                
    # If no negative indicators and it has "remote", "anywhere", "worldwide", let's allow it
    if not has_negative and any(term in loc_lower for term in ["remote", "anywhere", "worldwide"]):
        return True
        
    return False


def is_target_job(job_title, target_titles):
    jt = job_title.lower()
    for t in target_titles:
        t_lower = t.lower()
        if t_lower in jt:
            return True
        parts = t_lower.split()
        if len(parts) > 1 and all(p in jt for p in parts):
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
            
            soup = BeautifulSoup(r.content, "xml")
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
                
                if not is_target_job(raw_title, target_titles):
                    continue
                
                nu = normalize_job_url(job_url)
                if not nu:
                    continue
                if nu in found_urls:
                    continue
                found_urls.add(nu)
                
                if dry_run:
                    matched_count += 1
                    log(f"  [DRY RUN MATCH] RSS {feed_name}: '{raw_title}' - {job_url}")
                    dry_urls.append({
                        "job_url": job_url,
                        "query": f"RSS: {feed_name}",
                        "title_keyword": raw_title
                    })
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
                    "outside us", "outside the us", "outside the united states"
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
                            if "worldwide" not in desc_lower and "anywhere" not in desc_lower:
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
                    "scraped_at": datetime.utcnow().isoformat()
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
    
    # 1. Greenhouse Boards API
    for company in greenhouse_companies:
        url = f"https://boards-api.greenhouse.io/v1/boards/{company}/jobs?content=true"
        try:
            log(f"Querying Greenhouse API for: {company}")
            r = http_get(url, headers=headers, timeout=10, attempts=2)
            if r.status_code != 200:
                log(f"Greenhouse API for {company} returned status code {r.status_code}")
                continue
            
            data = r.json()
            jobs = data.get("jobs", [])
            log(f"  Greenhouse board '{company}': Found {len(jobs)} total jobs")
            
            for job in jobs:
                title = job.get("title", "").strip()
                if not is_target_job(title, target_titles):
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
                if nu in found_urls:
                    continue
                found_urls.add(nu)
                
                if dry_run:
                    matched_count += 1
                    log(f"  [DRY RUN MATCH] Greenhouse '{company}': '{title}' - {job_url}")
                    dry_urls.append({
                        "job_url": job_url,
                        "query": f"Greenhouse API: {company}",
                        "title_keyword": title
                    })
                    continue
                
                content_html = job.get("content", "")
                jd_text = clean_text(content_html).strip()
                
                req_id = str(job.get("id"))
                comp_name = job.get("company_name", company.title())
                
                desc_hash = compute_description_hash(jd_text)
                
                matched_count += 1
                discovered.append({
                    "job_title": title,
                    "company_name": comp_name,
                    "job_url": job_url,
                    "requirement_id": req_id,
                    "job_description": jd_text,
                    "location_work_type": f"{location_name} (Remote/Hybrid/Onsite)",
                    "description_hash": desc_hash,
                    "scraped_at": datetime.utcnow().isoformat()
                })
        except Exception as e:
            log(f"Error querying Greenhouse board '{company}': {e}")
            
    # 2. Lever Public Postings API
    for company in lever_companies:
        url = f"https://api.lever.co/v0/postings/{company}?mode=json"
        try:
            log(f"Querying Lever API for: {company}")
            r = http_get(url, headers=headers, timeout=10, attempts=2)
            if r.status_code != 200:
                log(f"Lever API for {company} returned status code {r.status_code}")
                continue
            
            jobs = r.json()
            if not isinstance(jobs, list):
                log(f"Lever API for {company} returned invalid format")
                continue
                
            log(f"  Lever board '{company}': Found {len(jobs)} total jobs")
            
            for job in jobs:
                title = job.get("text", "").strip()
                if not is_target_job(title, target_titles):
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
                if nu in found_urls:
                    continue
                found_urls.add(nu)
                
                if dry_run:
                    matched_count += 1
                    log(f"  [DRY RUN MATCH] Lever '{company}': '{title}' - {job_url}")
                    dry_urls.append({
                        "job_url": job_url,
                        "query": f"Lever API: {company}",
                        "title_keyword": title
                    })
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
                
                matched_count += 1
                discovered.append({
                    "job_title": title,
                    "company_name": comp_name,
                    "job_url": job_url,
                    "requirement_id": req_id,
                    "job_description": jd_text,
                    "location_work_type": f"{location_work}",
                    "description_hash": desc_hash,
                    "scraped_at": datetime.utcnow().isoformat()
                })
        except Exception as e:
            log(f"Error querying Lever board '{company}': {e}")
            
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
    
    for company in ashby_companies:
        url = f"https://api.ashbyhq.com/posting-api/job-board/{company}"
        try:
            log(f"Querying Ashby API for: {company}")
            r = http_get(url, headers=headers, timeout=10, attempts=2)
            if r.status_code != 200:
                log(f"Ashby API for {company} returned status code {r.status_code}")
                continue
                
            data = r.json()
            jobs = data.get("jobs", [])
            log(f"  Ashby board '{company}': Found {len(jobs)} total jobs")
            
            for job in jobs:
                title = job.get("title", "").strip()
                if not is_target_job(title, target_titles):
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
                if nu in found_urls:
                    continue
                found_urls.add(nu)
                
                if dry_run:
                    matched_count += 1
                    log(f"  [DRY RUN MATCH] Ashby '{company}': '{title}' - {job_url}")
                    dry_urls.append({
                        "job_url": job_url,
                        "query": f"Ashby API: {company}",
                        "title_keyword": title
                    })
                    continue
                
                desc_plain = job.get("descriptionPlain")
                desc_html = job.get("descriptionHtml")
                
                if desc_plain:
                    jd_text = desc_plain.strip()
                elif desc_html:
                    jd_text = clean_text(desc_html).strip()
                else:
                    jd_text = ""
                
                if not jd_text:
                    continue
                    
                req_id = str(job.get("id"))
                comp_name = company.title()
                
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
                    "scraped_at": datetime.utcnow().isoformat()
                })
        except Exception as e:
            log(f"Error querying Ashby board '{company}': {e}")
            
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
                if nu in found_urls:
                    continue
                found_urls.add(nu)
                
                if dry_run:
                    matched_count += 1
                    log(f"  [DRY RUN MATCH] Workable: '{title}' - {job_url}")
                    dry_urls.append({
                        "job_url": job_url,
                        "query": f"Workable Global Search: {title_query}",
                        "title_keyword": title
                    })
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
                    "scraped_at": datetime.utcnow().isoformat()
                })
        except Exception as e:
            log(f"Error querying Workable Global Search for '{title_query}': {e}")
            
    log(f"Workable Global Search Sourcing complete. Found {matched_count} matching US jobs.")
    return discovered


def main(dry_run=False):
    target_titles = []
    config_data = {}
    if CONFIG_PATH.exists():
        try:
            config_data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            target_titles = config_data.get("target_titles", [])
        except Exception as e:
            log(f"Warning: Failed to load config.json: {e}")

    if not target_titles:
        target_titles = [
            "DevOps Engineer",
            "Cloud Automation Engineer",
            "Platform Engineer",
            "Cloud Infrastructure Engineer",
            "Cloud Security Engineer",
            "DevSecOps",
            "Site Reliability Engineer",
            "CI/CD Engineer",
            "Systems Engineer",
            "Cloud Network Engineer",
            "Data Platform Engineer",
            "Machine Learning Engineer",
            "AI Platform Engineer",
        ]

    search_cfg = config_data.get("search") or {}
    merge_previous = search_cfg.get("merge_previous_scrape", True)
    merged_by_url = {}
    if merge_previous and SCRAPED_OUTPUT.exists():
        try:
            mtime = datetime.utcfromtimestamp(SCRAPED_OUTPUT.stat().st_mtime).isoformat()
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
    scraped_jobs = []
    dry_urls = []

    # 1. Fetch from RSS Feeds
    log("Starting direct RSS feed sourcing...")
    rss_jobs = fetch_rss_jobs(target_titles, search_cfg, found_urls, dry_run, dry_urls)
    scraped_jobs.extend(rss_jobs)
    
    # 2. Fetch from Company Board APIs
    log("Starting direct Company Board API sourcing...")
    target_companies = config_data.get("target_companies", {})
    api_jobs = fetch_company_board_jobs(target_companies, target_titles, found_urls, dry_run, dry_urls)
    scraped_jobs.extend(api_jobs)

    # 2b. Fetch from Ashby Boards API
    log("Starting direct Ashby Boards API sourcing...")
    ashby_jobs = fetch_ashby_jobs(target_companies, target_titles, found_urls, dry_run, dry_urls)
    scraped_jobs.extend(ashby_jobs)

    # 2c. Fetch from Workable Global Search API
    log("Starting direct Workable Global Search API sourcing...")
    workable_jobs = fetch_workable_global_jobs(target_titles, found_urls, dry_run, dry_urls)
    scraped_jobs.extend(workable_jobs)

    log("Starting Yahoo search for US job postings (remote / hybrid / onsite)...")
    if dry_run:
        log("DRY RUN: collecting URLs only (no per-job page scrape).")

    yield_threshold = search_cfg.get("yield_threshold", 2)
    api_key = os.environ.get("GEMINI_API_KEY")
    
    synonyms_map = expand_target_titles_with_gemini(target_titles, api_key)

    for title in target_titles:
        log(f"Processing target title: '{title}'")
        new_jobs, urls_found = search_and_scrape_for_keyword(title, search_cfg, found_urls, dry_run, dry_urls)
        scraped_jobs.extend(new_jobs)

        current_yield = len(new_jobs) if not dry_run else urls_found

        if current_yield < yield_threshold:
            syns = synonyms_map.get(title, [])
            if syns:
                log(f"Yield of {current_yield} for '{title}' is below threshold of {yield_threshold}. Triggering query expansion with synonyms: {syns}")
                for synonym in syns:
                    log(f"Executing expanded search for synonym: '{synonym}' (original: '{title}')")
                    syn_jobs, syn_urls_found = search_and_scrape_for_keyword(synonym, search_cfg, found_urls, dry_run, dry_urls)
                    scraped_jobs.extend(syn_jobs)
            else:
                log(f"Yield of {current_yield} for '{title}' is below threshold, but no synonyms are available.")
        else:
            log(f"Yield of {current_yield} for '{title}' met or exceeded threshold of {yield_threshold}. No expansion needed.")

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
    SCRAPED_OUTPUT.write_text(json.dumps(out_list, indent=2), encoding="utf-8")

    log(f"Completed search and scrape. New/changed rows this run: {len(scraped_jobs)}. Total in {SCRAPED_OUTPUT.name}: {len(out_list)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Yahoo site: discovery and ATS scrape for MAAS jobsearch.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only collect Yahoo result URLs; write dry_run_urls.json and exit.",
    )
    args = parser.parse_args()
    dry = args.dry_run or os.environ.get("JOBSEARCH_DRY_RUN", "").strip().lower() in ("1", "true", "yes")
    main(dry_run=dry)
