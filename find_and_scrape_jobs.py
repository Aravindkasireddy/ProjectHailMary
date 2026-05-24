import os
import re
import sys
import json
import time
import logging
import argparse
import requests
from pathlib import Path
from bs4 import BeautifulSoup
from urllib.parse import urlparse, quote_plus
from playwright.sync_api import sync_playwright
from dotenv import load_dotenv

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
            with sync_playwright() as p:
                browser = p.webkit.launch(headless=True)
                context = browser.new_context(
                    user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15"
                )
                page = context.new_page()
                page.goto(url, wait_until="commit", timeout=20000)
                time.sleep(3)
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


def search_and_scrape_for_keyword(keyword, search_cfg, found_urls, dry_run, dry_urls):
    """
    Search Yahoo and scrape jobs for a given keyword/title.
    Returns a list of newly scraped job dictionaries and count of unique URLs found.
    """
    queries = build_yahoo_queries(keyword, search_cfg)
    keyword_scraped_jobs = []
    urls_found_for_keyword = 0
    
    for query in queries:
        log(f"Searching: {query}")
        urls = search_yahoo(query)
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
            except Exception as e:
                log(f"Scraper error for {href}: {e}")

            if job_data and job_data.get("job_description"):
                if job_data.get("requirement_id") and job_data.get("requirement_id") != "Unknown":
                    log(f"Scraped: '{job_data['job_title']}' at '{job_data['company_name']}' - Req ID: {job_data['requirement_id']}")
                    keyword_scraped_jobs.append(job_data)
                else:
                    log(f"Discarded (No Requirement ID): {href}")
            else:
                if job_data:
                    log(f"Discarded (No JD text or inactive): {href}")
                    
    return keyword_scraped_jobs, urls_found_for_keyword


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
            for j in json.loads(SCRAPED_OUTPUT.read_text(encoding="utf-8")):
                u = j.get("job_url")
                if u:
                    merged_by_url[normalize_job_url(u)] = j
        except Exception as e:
            log(f"Warning: could not merge previous scraped_jobs.json: {e}")

    found_urls = set()
    scraped_jobs = []
    dry_urls = []

    log("Starting Yahoo search for US job postings (remote / hybrid / onsite)...")
    if dry_run:
        log("DRY RUN: collecting URLs only (no per-job page scrape).")

    yield_threshold = search_cfg.get("yield_threshold", 2)
    api_key = os.environ.get("GEMINI_API_KEY")
    
    # Generate synonym expansion mapping using Gemini (with fallback)
    synonyms_map = expand_target_titles_with_gemini(target_titles, api_key)

    for title in target_titles:
        log(f"Processing target title: '{title}'")
        new_jobs, urls_found = search_and_scrape_for_keyword(title, search_cfg, found_urls, dry_run, dry_urls)
        scraped_jobs.extend(new_jobs)

        # Track search yield
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
