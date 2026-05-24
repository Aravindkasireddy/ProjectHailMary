import json
import re
import sys
import time
import hashlib
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright

def compute_description_hash(description):
    if not description:
        return ""
    normalized = "".join(description.lower().split())
    return hashlib.sha256(normalized.encode('utf-8')).hexdigest()

def load_known_hashes(workspace_path):
    approved_hashes = {}
    failed_hashes = {}
    
    approved_path = workspace_path / "approved_jobs.json"
    if approved_path.exists():
        try:
            jobs = json.loads(approved_path.read_text(encoding="utf-8"))
            for j in jobs:
                h = j.get("description_hash")
                if not h and j.get("job_description"):
                    h = compute_description_hash(j["job_description"])
                if h:
                    approved_hashes[h] = j
        except Exception as e:
            print(f"Error loading approved hashes: {e}")
            
    failed_path = workspace_path / "failed_candidate_jobs.json"
    if failed_path.exists():
        try:
            jobs = json.loads(failed_path.read_text(encoding="utf-8"))
            for j in jobs:
                h = j.get("description_hash")
                if not h and j.get("job_description"):
                    h = compute_description_hash(j["job_description"])
                if h:
                    failed_hashes[h] = j
        except Exception as e:
            print(f"Error loading failed hashes: {e}")
            
    return approved_hashes, failed_hashes


_scripts_dir = Path(__file__).resolve().parent
_repo_root = _scripts_dir.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))
from jobsearch_paths import workspace_root

WORKSPACE = workspace_root()

headers = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8"
}

def clean_text(html_content):
    if not html_content:
        return ""
    soup = BeautifulSoup(html_content, 'html.parser')
    for script in soup(["script", "style"]):
        script.extract()
    text = soup.get_text(separator="\n")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return "\n".join(lines)

def fetch_with_playwright(url):
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
        print(f"Playwright WebKit error for {url}: {e}", flush=True)
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

def scrape_workday_via_api(url):
    parsed = urlparse(url)
    host = parsed.netloc
    path = parsed.path
    
    parts = [p for p in path.split('/') if p]
    if 'job' not in parts:
        return None
    job_idx = parts.index('job')
    board_id = parts[job_idx - 1] if job_idx > 0 else "External"
    subdomain = host.split('.')[0]
    job_path = "/".join(parts[job_idx + 1:])
    
    tenant_choices = [subdomain]
    if '-' in subdomain:
        tenant_choices.append(subdomain.split('-')[0])
    if 'wd' in subdomain:
        tenant_choices.append(subdomain.split('.')[0])
        
    for tenant in tenant_choices:
        api_url = f"https://{host}/wday/cxs/{tenant}/{board_id}/job/{job_path}"
        try:
            r = requests.get(api_url, headers=headers, timeout=10)
            if r.status_code == 200:
                data = r.json()
                posting = data.get("jobPostingInfo", {})
                title = posting.get("title", "Unknown Title")
                desc_html = posting.get("jobDescription", "")
                desc_text = clean_text(desc_html)
                req_id = posting.get("requisitionId", "Unknown")
                if not req_id or req_id == "Unknown":
                    url_match = re.search(r'_([a-zA-Z0-9\-]+)$', url)
                    req_id = url_match.group(1) if url_match else "Unknown"
                    
                loc = posting.get("location", "")
                if not loc and posting.get("locationsText"):
                    loc = posting.get("locationsText")
                return {
                    "job_title": title,
                    "company_name": tenant.capitalize(),
                    "job_url": url,
                    "requirement_id": req_id,
                    "job_description": desc_text.strip(),
                    "location_work_type": f"{loc} (Remote/Hybrid)" if loc else "Remote"
                }
        except Exception:
            pass
    return None

def scrape_ashby(url):
    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code != 200:
            return None
            
        soup = BeautifulSoup(response.text, 'html.parser')
        
        parsed = urlparse(url)
        path_parts = [p for p in parsed.path.split('/') if p]
        final_parsed = urlparse(response.url)
        final_path_parts = [p for p in final_parsed.path.split('/') if p]
        
        if len(final_path_parts) < len(path_parts) and len(final_path_parts) <= 1:
            print(f"  Inactive: Ashby redirected.", flush=True)
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
                pass
                
        title_elem = soup.find('title') or soup.find('h1') or soup.find('h2')
        title_text = title_elem.text.strip() if title_elem else "Unknown Title"
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
        print(f"Failed to scrape Ashby: {e}")
        return None

def scrape_workable(url):
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
                acct_res = requests.get(acct_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=5)
                if acct_res.status_code == 200:
                    company_name = acct_res.json().get("name", company_name)
            except Exception:
                pass
                
        api_url = f"https://apply.workable.com/api/v2/accounts/{company_slug}/jobs/{job_id}"
        response = requests.get(api_url, headers=headers, timeout=10)
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
        print(f"Failed to scrape Workable: {e}")
        return None

def scrape_smartrecruiters(url):
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
        response = requests.get(api_url, headers=headers, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            if not data.get("active", True):
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
            
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code != 200:
            return None
            
        if "This job is no longer available" in response.text or "no longer available" in response.text:
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
        print(f"Failed to scrape SmartRecruiters: {e}")
        return None

def check_red_flags(job):
    title = job.get("job_title", "").lower()
    desc = job.get("job_description", "").lower()
    
    red_flags = []
    
    # 1. Work authorization restriction
    auth_patterns = [
        r"us citizen", r"u\.s\. citizen", r"united states citizen",
        r"security clearance", r"active clearance", r"secret clearance", r"top secret", r"ts/sci", r"government clearance",
        r"itar", r"export control", r"export-controlled", r"u\.s\. export",
        r"must be u\.s\. person", r"u\.s\. persons only",
        r"no visa sponsorship", r"not eligible for sponsorship", r"unable to sponsor", 
        r"does not sponsor", r"cannot sponsor", r"no current or future sponsorship",
        r"without sponsorship now or in the future", r"authorized to work in the us without sponsorship",
        r"must have permanent work authorization"
    ]
    for pattern in auth_patterns:
        if re.search(pattern, desc):
            red_flags.append(f"Work authorization restriction (matched: {pattern})")
            break
            
    # 2. Experience requirement violation (>=8 years)
    exp_words = r"(?:eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|eight\+|nine\+|ten\+)"
    exp_digits = r"(?:8|9|10|11|12|13|14|15|8\+|9\+|10\+)"
    exp_pattern = rf"\b({exp_words}|{exp_digits})\b\s*(?:\+)?\s*(?:-|to)?\s*(?:\d+|{exp_words}|{exp_digits})?\s*years?\b"
    
    matches = re.findall(exp_pattern, desc)
    if matches:
        red_flags.append(f"Experience requirement violation (found: {matches})")
        
    # 3. Seniority / title violation
    seniority_patterns = [
        r"\bmanager\b", r"\bdirector\b", r"\bprincipal\b", r"\barchitect\b", r"\blead\b"
    ]
    for pattern in seniority_patterns:
        if re.search(pattern, title):
            red_flags.append(f"Seniority / title violation (title has: {pattern})")
            break
            
    # 4. Out of scope
    if "qa engineer" in title or "quality assurance" in title:
        red_flags.append("Out of scope (QA)")
    elif "data scientist" in title or "data science" in title:
        red_flags.append("Out of scope (Data Science)")
    elif "desktop support" in title or "edi" in title:
        red_flags.append("Out of scope (Desktop support/EDI)")
        
    # 5. Non-US Location check
    loc_lower = job.get("location_work_type", "").lower()
    non_us_countries_cities = [
        "canada", "toronto", "vancouver", "montreal", "ottawa", "calgary", "edmonton", "quebec",
        "united kingdom", " u.k.", ", uk", " u.k", "/uk", " london", "manchester",
        "germany", "berlin", "munich", "frankfurt", "hamburg",
        "india", "bangalore", "bengaluru", "pune", "mumbai", "hyderabad", "chennai", "delhi",
        "australia", "sydney", "melbourne", "brisbane",
        "france", "paris", "spain", "madrid", "barcelona",
        "poland", "warsaw", "krakow", "netherlands", "amsterdam", "rotterdam",
        "ireland", "dublin", "brazil", "mexico", "switzerland", "zurich", "geneva",
        "sweden", "stockholm", "singapore", "philippines", "manila", "ukraine", "kyiv"
    ]
    
    has_non_us_loc = False
    for term in non_us_countries_cities:
        if term in loc_lower:
            red_flags.append(f"Non-US Location restriction (matched: {term} in location field)")
            has_non_us_loc = True
            break
            
    if not has_non_us_loc:
        non_us_phrases = [
            r"must be located in canada", r"must be based in canada",
            r"must be based in the uk", r"must be located in the uk",
            r"located in london", r"based in london",
            r"located in germany", r"based in germany",
            r"located in india", r"based in india",
            r"must be resident of canada", r"must reside in canada",
            r"eligible to work in canada", r"authorized to work in canada",
            r"eligible to work in the uk", r"authorized to work in the uk"
        ]
        for phrase in non_us_phrases:
            if re.search(phrase, desc):
                red_flags.append(f"Non-US Location restriction (matched: {phrase} in description)")
                break
        
    return red_flags

def main():
    input_path = str(WORKSPACE / "scraped_jobs.json")
    with open(input_path, 'r') as f:
        jobs = json.load(f)
        
    print(f"Loaded {len(jobs)} scraped jobs. Validating active status and checking red flags...", flush=True)
    
    approved_hashes, failed_hashes = load_known_hashes(WORKSPACE)
    
    passed_jobs = []
    failed_jobs = []
    
    for i, job in enumerate(jobs):
        url = job.get("job_url", "")
        domain = urlparse(url).netloc.lower()
        company = job.get("company_name", "Unknown")
        
        # Check description hash cache
        desc = job.get("job_description", "")
        h = job.get("description_hash")
        if not h and desc:
            h = compute_description_hash(desc)
            job["description_hash"] = h
            
        if h:
            if h in approved_hashes:
                print(f"[{i+1}/{len(jobs)}] Cache HIT (Approved) for {company} - {url}. Skipping filter.", flush=True)
                matched = approved_hashes[h]
                job["red_flags"] = []
                if "scraped_at" in matched:
                    job["scraped_at"] = matched["scraped_at"]
                passed_jobs.append(job)
                continue
            elif h in failed_hashes:
                print(f"[{i+1}/{len(jobs)}] Cache HIT (Failed) for {company} - {url}. Skipping filter.", flush=True)
                matched = failed_hashes[h]
                job["red_flags"] = matched.get("red_flags", ["Previously rejected"])
                failed_jobs.append(job)
                continue

        print(f"[{i+1}/{len(jobs)}] Processing {company} - {url}...", flush=True)
        time.sleep(1) # Sleep to avoid rate limiting
        
        scraped_data = None
        
        if 'myworkdayjobs.com' in domain:
            scraped_data = scrape_workday_via_api(url)
            if not scraped_data:
                print("  Failed to scrape via Workday REST API.", flush=True)
                continue
        elif 'workable.com' in domain:
            scraped_data = scrape_workable(url)
            if not scraped_data:
                print("  Failed to scrape via Workable API.", flush=True)
                continue
        elif 'smartrecruiters.com' in domain:
            scraped_data = scrape_smartrecruiters(url)
            if not scraped_data:
                print("  Failed to scrape via SmartRecruiters API.", flush=True)
                continue
        elif 'ashbyhq.com' in domain:
            scraped_data = scrape_ashby(url)
            if not scraped_data:
                print("  Failed to scrape via Ashby JSON-LD.", flush=True)
                continue
        elif 'weworkremotely.com' in domain:
            scraped_data = scrape_weworkremotely(url)
            if not scraped_data:
                print("  Failed to scrape via We Work Remotely Playwright.", flush=True)
                continue
        elif 'remote.co' in domain:
            scraped_data = scrape_remoteco(url)
            if not scraped_data:
                print("  Failed to scrape via Remote.co Playwright.", flush=True)
                continue
        elif 'linkedin.com' in domain:
            scraped_data = scrape_linkedin(url)
            if not scraped_data:
                print("  Failed to scrape via LinkedIn Playwright.", flush=True)
                continue
        elif 'workatastartup.com' in domain:
            scraped_data = scrape_yc(url)
            if not scraped_data:
                print("  Failed to scrape via YC Playwright.", flush=True)
                continue
        else:
            # Greenhouse or Lever
            try:
                r = requests.get(url, headers=headers, timeout=10)
                final_url = r.url
                parsed_final = urlparse(final_url)
                
                # Greenhouse redirect check
                if "greenhouse.io" in parsed_final.netloc:
                    if "error=true" in final_url or "/jobs/" not in parsed_final.path:
                        print(f"  Inactive: Greenhouse redirected to board.", flush=True)
                        continue
                        
                # Lever redirect/board check
                if "lever.co" in parsed_final.netloc:
                    path_parts = [p for p in parsed_final.path.split('/') if p]
                    if len(path_parts) < 2:
                        print(f"  Inactive: Lever redirected to board.", flush=True)
                        continue
                    soup = BeautifulSoup(r.text, 'html.parser')
                    title = soup.title.get_text() if soup.title else ""
                    if "Jobs at" in title or "Current Openings" in title:
                        print(f"  Inactive: Lever board title.", flush=True)
                        continue
                        
                soup = BeautifulSoup(r.text, 'html.parser')
                true_title = ""
                if "greenhouse.io" in parsed_final.netloc:
                    app_title = soup.find(class_='app-title')
                    if app_title:
                        true_title = app_title.get_text().strip()
                    else:
                        h1 = soup.find('h1')
                        if h1:
                            true_title = h1.get_text().strip()
                elif "lever.co" in parsed_final.netloc:
                    posting_header = soup.find(class_='posting-header')
                    if posting_header and posting_header.find('h2'):
                        true_title = posting_header.find('h2').get_text().strip()
                    else:
                        h2 = soup.find('h2')
                        true_title = h2.get_text().strip() if h2 else ""
                        if not true_title:
                            h1 = soup.find('h1')
                            true_title = h1.get_text().strip() if h1 else ""
                            
                for script in soup(["script", "style"]):
                    script.extract()
                desc_text = soup.get_text(separator="\n")
                lines = [line.strip() for line in desc_text.splitlines() if line.strip()]
                desc_clean = "\n".join(lines)
                
                if not true_title:
                    true_title = job.get("job_title", "Unknown Title")
                    
                scraped_data = {
                    "job_title": true_title,
                    "company_name": company,
                    "job_url": url,
                    "requirement_id": job.get("requirement_id", "Unknown"),
                    "job_description": desc_clean,
                    "location_work_type": job.get("location_work_type", "Remote")
                }
            except Exception as e:
                print(f"  Error processing URL: {e}", flush=True)
                continue
                
        if scraped_data:
            # Preserve scraped_at if it was in the original job
            if "scraped_at" in job:
                scraped_data["scraped_at"] = job["scraped_at"]
                
            # Check length of description
            if len(scraped_data.get("job_description", "")) < 200:
                print(f"  Inactive: Scraped description too short.", flush=True)
                continue
                
            # Run red flag checks
            red_flags = check_red_flags(scraped_data)
            if red_flags:
                scraped_data["red_flags"] = red_flags
                print(f"  FAILED RED FLAGS: {red_flags}", flush=True)
                failed_jobs.append(scraped_data)
            else:
                scraped_data["red_flags"] = []
                print(f"  PASSED RED FLAGS! Title: '{scraped_data['job_title']}'", flush=True)
                passed_jobs.append(scraped_data)
                
    print(f"\nProcessing complete.\nPassed jobs: {len(passed_jobs)}\nFailed jobs: {len(failed_jobs)}", flush=True)
    
    # Save candidate jobs
    with open(str(WORKSPACE / "active_candidate_jobs.json"), "w") as f:
        json.dump(passed_jobs, f, indent=2)
        
    with open(str(WORKSPACE / "failed_candidate_jobs.json"), "w") as f:
        json.dump(failed_jobs, f, indent=2)

if __name__ == '__main__':
    main()
