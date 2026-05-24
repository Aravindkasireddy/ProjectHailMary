import re
import os
import sys
import json
import requests
from pathlib import Path
from bs4 import BeautifulSoup
from urllib.parse import urlparse

def clean_text(html_content):
    """Convert HTML content to plain text, preserving paragraphs."""
    if not html_content:
        return ""
    soup = BeautifulSoup(html_content, 'html.parser')
    # Remove script and style elements
    for script in soup(["script", "style"]):
        script.extract()
    return soup.get_text(separator="\n")

def scrape_greenhouse(url):
    print(f"Scraping Greenhouse: {url}")
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code != 200:
            print(f"Error: HTTP {response.status_code} for {url}")
            return None
            
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Title
        title_elem = soup.find('h1')
        title = title_elem.get_text().strip() if title_elem else "Unknown Title"
        
        # Company
        # URL format: https://boards.greenhouse.io/company/jobs/id
        parsed = urlparse(url)
        path_parts = [p for p in parsed.path.split('/') if p]
        company = path_parts[0].capitalize() if path_parts else "Unknown"
        
        # Location
        loc_elem = soup.find(class_='location')
        location = loc_elem.get_text().strip() if loc_elem else "Remote"
        
        # Requirement ID
        # Greenhouse job board ID is the last path component
        req_id = path_parts[-1] if path_parts else "Unknown"
        
        # Look for a Requisition ID in the text
        text = soup.get_text()
        req_match = re.search(r'(?:Req(?:uisition)?\s*(?:ID|Code|#)|Job\s*(?:ID|Code|#)|Requisition\s*(?:ID|Code|#))[:\-\s#]+([a-zA-Z0-9\-_]+)', text, re.IGNORECASE)
        if req_match:
            req_id = req_match.group(1).strip()
            
        # Job Description
        jd_div = soup.find(id='content') or soup.find(class_='job-post') or soup.find(class_='job__description')
        if jd_div:
            jd_text = clean_text(str(jd_div))
        else:
            # Fallback to body text
            body = soup.find('body')
            jd_text = clean_text(str(body)) if body else ""
            
        return {
            "job_title": title,
            "company_name": company,
            "job_url": url,
            "requirement_id": req_id,
            "job_description": jd_text.strip(),
            "location_work_type": f"{location} (Remote/Hybrid)"
        }
    except Exception as e:
        print(f"Exception scraping {url}: {e}")
        return None

def scrape_lever(url):
    print(f"Scraping Lever: {url}")
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code != 200:
            print(f"Error: HTTP {response.status_code} for {url}")
            return None
            
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Title
        title_elem = soup.find('h2') or soup.find('h1')
        title = title_elem.get_text().strip() if title_elem else "Unknown Title"
        if title == "Unknown Title" or len(title) > 100:
            # Check og:title
            og_title = soup.find('meta', property='og:title')
            if og_title and og_title.get('content'):
                title = og_title.get('content').split('-')[0].strip()
                
        # Company
        parsed = urlparse(url)
        path_parts = [p for p in parsed.path.split('/') if p]
        company = path_parts[0].capitalize() if path_parts else "Unknown"
        
        # Location
        loc_elem = soup.find(class_='location') or soup.find(class_='posting-categories')
        location = loc_elem.get_text().strip() if loc_elem else "Remote"
        location = re.sub(r'\s+', ' ', location)
        
        # Requirement ID
        # Lever uses uuid as job ID in path: jobs.lever.co/company/uuid
        req_id = path_parts[-1] if len(path_parts) > 1 else "Unknown"
        
        # Look for a Requisition ID in the text
        text = soup.get_text()
        req_match = re.search(r'(?:Req(?:uisition)?\s*(?:ID|Code|#)|Job\s*(?:ID|Code|#)|Requisition\s*(?:ID|Code|#))[:\-\s#]+([a-zA-Z0-9\-_]+)', text, re.IGNORECASE)
        if req_match:
            req_id = req_match.group(1).strip()
            
        # Job Description
        jd_div = soup.find(class_='posting-sections') or soup.find(class_='job-post')
        if jd_div:
            jd_text = clean_text(str(jd_div))
        else:
            body = soup.find('body')
            jd_text = clean_text(str(body)) if body else ""
            
        return {
            "job_title": title,
            "company_name": company,
            "job_url": url,
            "requirement_id": req_id,
            "job_description": jd_text.strip(),
            "location_work_type": f"{location} (Remote/Hybrid)"
        }
    except Exception as e:
        print(f"Exception scraping {url}: {e}")
        return None

def scrape_workday(url):
    print(f"Scraping Workday: {url}")
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code != 200:
            print(f"Error: HTTP {response.status_code} for {url}")
            return None
            
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Company name
        parsed = urlparse(url)
        company = parsed.netloc.split('.')[0].capitalize()
        
        # Look for JSON-LD script
        json_ld_script = soup.find('script', type='application/ld+json')
        if json_ld_script:
            try:
                data = json.loads(json_ld_script.string)
                title = data.get("title", "Unknown Title")
                description_html = data.get("description", "")
                description = clean_text(description_html)
                
                # Extract Req ID from JSON-LD identifier
                identifier = data.get("identifier", {})
                req_id = identifier.get("value", "") if isinstance(identifier, dict) else ""
                
                if not req_id:
                    # Try parsing from URL ending: Job-Title_JR2600965-1 -> JR2600965-1
                    url_match = re.search(r'_([a-zA-Z0-9\-]+)$', url)
                    if url_match:
                        req_id = url_match.group(1)
                    else:
                        req_id = "Unknown"
                        
                # Extract Location
                location_data = data.get("jobLocation", {})
                address = location_data.get("address", {}) if isinstance(location_data, dict) else {}
                locality = address.get("addressLocality", "Remote") if isinstance(address, dict) else "Remote"
                country = address.get("addressCountry", "US") if isinstance(address, dict) else "US"
                location = f"{locality}, {country}"
                
                return {
                    "job_title": title,
                    "company_name": company,
                    "job_url": url,
                    "requirement_id": req_id,
                    "job_description": description.strip(),
                    "location_work_type": f"{location} (Remote/Hybrid)"
                }
            except Exception as e:
                print(f"JSON-LD parsing exception for Workday: {e}")
                
        # Fallback parsing
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
        print(f"Exception scraping Workday {url}: {e}")
        return None

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 scrape_jobs.py <url1> <url2> ...")
        sys.exit(1)
        
    urls = sys.argv[1:]
    results = []
    
    for url in urls:
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        
        job_data = None
        if 'greenhouse.io' in domain:
            job_data = scrape_greenhouse(url)
        elif 'lever.co' in domain:
            job_data = scrape_lever(url)
        elif 'myworkdayjobs.com' in domain:
            job_data = scrape_workday(url)
        else:
            print(f"Unknown job board domain: {domain} for URL {url}")
            
        if job_data:
            results.append(job_data)
            
    # Save results to scraped_jobs.json
    output_file = str(Path(__file__).resolve().parent / "scraped_jobs.json")
    with open(output_file, 'w') as f:
        json.dump(results, f, indent=2)
        
    print(f"\nSuccessfully scraped {len(results)} jobs and saved to {output_file}")

if __name__ == '__main__':
    main()
