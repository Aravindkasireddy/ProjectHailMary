import asyncio
import csv
import logging
import re
from typing import List, Dict
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

KEYWORDS = ['devops', 'infrastructure', 'security', 'data science', 'sre']

def matches_keywords(title: str) -> bool:
    """Check if the job title matches any of our target keywords."""
    title_lower = title.lower()
    return any(keyword in title_lower for keyword in KEYWORDS)

def is_us_location(location: str) -> bool:
    """
    Heuristic to determine if a location is US-based.
    Checks for 'US', 'United States', or common state abbreviations.
    """
    if not location:
        return False
    loc_lower = location.lower()
    
    us_terms = ['united states', 'us', 'usa', 'remote - us', 'us remote']
    if any(term in loc_lower for term in us_terms):
        return True
    
    states = [
        'al', 'ak', 'az', 'ar', 'ca', 'co', 'ct', 'de', 'fl', 'ga', 'hi', 'id', 'il', 'in', 
        'ia', 'ks', 'ky', 'la', 'me', 'md', 'ma', 'mi', 'mn', 'ms', 'mo', 'mt', 'ne', 'nv', 
        'nh', 'nj', 'nm', 'ny', 'nc', 'nd', 'oh', 'ok', 'or', 'pa', 'ri', 'sc', 'sd', 'tn', 
        'tx', 'ut', 'vt', 'va', 'wa', 'wv', 'wi', 'wy'
    ]
    tokens = re.split(r'[,\s/|-]+', loc_lower)
    
    if 'us' in tokens or 'usa' in tokens:
        return True
    if any(state in tokens for state in states):
        return True
        
    return False

async def get_actual_greenhouse_id(career_page_url: str, client: httpx.AsyncClient):
    """Parses the HTML of the career page to find the true board token."""
    try:
        # Use follow_redirects=True to handle cases like plaid -> plaid-careers
        response = await client.get(career_page_url, follow_redirects=True, timeout=10.0)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        token_element = soup.find('input', {'id': 'board_token'}) or \
                        soup.find('meta', {'name': 'board_token'})
        
        if token_element:
            return token_element.get('value') or token_element.get('content')
            
    except Exception as e:
        logger.debug(f"Could not parse HTML from {career_page_url}: {e}")
    return None

async def get_job_board_info(career_page_url: str, client: httpx.AsyncClient):
    """
    Parses a career page URL to return the correct API endpoint and slug.
    """
    if not career_page_url.startswith('http'):
        career_page_url = 'https://' + career_page_url
        
    parsed = urlparse(career_page_url)
    domain = parsed.netloc.lower()
    path = parsed.path.strip('/')
    
    # Extract the slug (usually the last part of the path)
    slug = path.split('/')[-1] if path else None
    
    if not slug:
        return None

    if 'greenhouse.io' in domain:
        # Try to extract the actual token from the HTML metadata first
        actual_slug = await get_actual_greenhouse_id(career_page_url, client) or slug
        return {
            'type': 'greenhouse',
            'slug': actual_slug,
            'api_url': f"https://boards-api.greenhouse.io/v1/boards/{actual_slug}/jobs"
        }
    elif 'lever.co' in domain:
        return {
            'type': 'lever',
            'slug': slug,
            'api_url': f"https://api.lever.co/v0/postings/{slug}"
        }
    elif 'ashbyhq.com' in domain:
        return {
            'type': 'ashby',
            'slug': slug,
            'api_url': f"https://api.ashbyhq.com/posting-api/job-board/{slug}"
        }
    
    return None

async def fetch_greenhouse(info: Dict, client: httpx.AsyncClient) -> List[Dict]:
    url = info['api_url']
    slug = info['slug']
    try:
        response = await client.get(url, timeout=10.0)
        response.raise_for_status()
        data = response.json()
        jobs = data.get('jobs', [])
        normalized = []
        for job in jobs:
            loc = job.get('location', {}).get('name', '')
            title = job.get('title', '')
            if matches_keywords(title) and is_us_location(loc):
                normalized.append({
                    'company_name': slug,
                    'ats_type': 'Greenhouse',
                    'job_title': title,
                    'location': loc,
                    'department': 'Unknown',
                    'job_url': job.get('absolute_url', ''),
                    'apply_url': job.get('absolute_url', ''),
                    'published_at': job.get('updated_at', '')
                })
        return normalized
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            logger.debug(f"Greenhouse 404 for URL {url} (Slug might be invalid or retired)")
        else:
            logger.error(f"Greenhouse HTTP error for {slug}: {e}")
    except Exception as e:
        logger.error(f"Greenhouse error for {slug}: {e}")
    return []

async def fetch_lever(info: Dict, client: httpx.AsyncClient) -> List[Dict]:
    url = info['api_url']
    slug = info['slug']
    try:
        response = await client.get(url, timeout=10.0)
        response.raise_for_status()
        jobs = response.json()
        normalized = []
        for job in jobs:
            loc = job.get('categories', {}).get('location', '')
            title = job.get('text', '')
            dept = job.get('categories', {}).get('team', 'Unknown')
            if matches_keywords(title) and is_us_location(loc):
                normalized.append({
                    'company_name': slug,
                    'ats_type': 'Lever',
                    'job_title': title,
                    'location': loc,
                    'department': dept,
                    'job_url': job.get('hostedUrl', ''),
                    'apply_url': job.get('applyUrl', job.get('hostedUrl', '')),
                    'published_at': str(job.get('createdAt', ''))
                })
        return normalized
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            logger.debug(f"Lever 404 for URL {url} (Slug might be invalid or retired)")
        else:
            logger.error(f"Lever HTTP error for {slug}: {e}")
    except Exception as e:
        logger.error(f"Lever error for {slug}: {e}")
    return []

async def fetch_ashby(info: Dict, client: httpx.AsyncClient) -> List[Dict]:
    url = info['api_url']
    slug = info['slug']
    try:
        response = await client.get(url, timeout=10.0)
        response.raise_for_status()
        data = response.json()
        jobs = data.get('jobs', [])
        normalized = []
        for job in jobs:
            loc = job.get('location', '')
            title = job.get('title', '')
            dept = job.get('department', 'Unknown')
            if matches_keywords(title) and is_us_location(loc):
                normalized.append({
                    'company_name': slug,
                    'ats_type': 'Ashby',
                    'job_title': title,
                    'location': loc,
                    'department': dept,
                    'job_url': job.get('jobUrl', ''),
                    'apply_url': job.get('jobUrl', ''),
                    'published_at': job.get('publishedAt', '')
                })
        return normalized
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            logger.debug(f"Ashby 404 for URL {url} (Slug might be invalid or retired)")
        else:
            logger.error(f"Ashby HTTP error for {slug}: {e}")
    except Exception as e:
        logger.error(f"Ashby error for {slug}: {e}")
    return []

async def process_url(url: str, client: httpx.AsyncClient) -> List[Dict]:
    info = await get_job_board_info(url, client)
    
    if not info:
        logger.warning(f"Could not parse valid ATS or slug from URL: {url}")
        return []
        
    ats_type = info['type']
    logger.info(f"Detected {ats_type} for URL {url}. Fetching from: {info['api_url']}")
    
    if ats_type == 'greenhouse':
        return await fetch_greenhouse(info, client)
    elif ats_type == 'lever':
        return await fetch_lever(info, client)
    elif ats_type == 'ashby':
        return await fetch_ashby(info, client)
        
    return []

def load_urls(filepath: str) -> List[str]:
    urls = []
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            if reader.fieldnames and 'url' in [h.lower() for h in reader.fieldnames]:
                url_field = [h for h in reader.fieldnames if h.lower() == 'url'][0]
                for row in reader:
                    if row.get(url_field):
                        urls.append(row[url_field].strip())
            else:
                f.seek(0)
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and 'http' in line:
                        urls.append(line)
    except FileNotFoundError:
        logger.warning(f"Target file {filepath} not found. Running with example URLs.")
        urls = [
            "https://boards.greenhouse.io/plaid",
            "https://jobs.lever.co/netflix",
            "https://jobs.ashbyhq.com/notion",
            "https://boards.greenhouse.io/anthropic"
        ]
    return urls

async def main():
    urls = load_urls('target_companies.csv')
    all_jobs = []
    
    limits = httpx.Limits(max_keepalive_connections=5, max_connections=10)
    async with httpx.AsyncClient(limits=limits) as client:
        tasks = [process_url(url, client) for url in urls]
        results = await asyncio.gather(*tasks)
        for res in results:
            all_jobs.extend(res)
            
    if not all_jobs:
        logger.info("No jobs found matching criteria.")
        return
        
    keys = ['company_name', 'ats_type', 'job_title', 'location', 'department', 'job_url', 'apply_url', 'published_at']
    output_filename = 'aggregated_jobs.csv'
    
    with open(output_filename, 'w', newline='', encoding='utf-8') as output_file:
        dict_writer = csv.DictWriter(output_file, fieldnames=keys)
        dict_writer.writeheader()
        dict_writer.writerows(all_jobs)
        
    logger.info(f"Successfully saved {len(all_jobs)} filtered US-based jobs to {output_filename}")

if __name__ == "__main__":
    asyncio.run(main())
