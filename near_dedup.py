import re
from urllib.parse import urlparse

def clean_string_for_similarity(s):
    if not s:
        return ""
    # Keep only letters and numbers
    return re.sub(r'[^a-z0-9\s]', '', s.lower()).strip()

def get_word_set(text):
    if not text:
        return set()
    # Normalize, lowercase, and keep words of size 3+
    words = re.findall(r'\b[a-z]{3,}\b', text.lower())
    # Define a clean list of stop words to skip
    stop_words = {
        'the', 'and', 'with', 'for', 'you', 'will', 'our', 'are', 'that', 'this', 
        'from', 'your', 'about', 'have', 'their', 'they', 'them', 'who', 'what',
        'has', 'been', 'was', 'were', 'had', 'should', 'would', 'could', 'but'
    }
    return set(w for w in words if w not in stop_words)

def compute_similarity(job1, job2):
    """
    Computes text Jaccard similarity of two job postings.
    Returns Jaccard similarity score (0.0 to 1.0).
    Requires company name and location to be compatible.
    """
    # 1. Company name check
    comp1 = clean_string_for_similarity(job1.get("company_name", ""))
    comp2 = clean_string_for_similarity(job2.get("company_name", ""))
    if not comp1 or not comp2 or comp1 != comp2:
        return 0.0
        
    # 2. Location check: if both have location, compare them.
    # Allow matching if both are remote, but block grouping if they specify different physical cities.
    loc1 = clean_string_for_similarity(job1.get("location_work_type", ""))
    loc2 = clean_string_for_similarity(job2.get("location_work_type", ""))
    if loc1 and loc2 and loc1 != loc2:
        is_remote1 = 'remote' in loc1
        is_remote2 = 'remote' in loc2
        if not (is_remote1 and is_remote2):
            return 0.0
            
    # 3. Calculate Jaccard similarity of description word tokens
    set1 = get_word_set(job1.get("job_description", ""))
    set2 = get_word_set(job2.get("job_description", ""))
    
    if not set1 or not set2:
        return 0.0
        
    intersection = len(set1.intersection(set2))
    union = len(set1.union(set2))
    
    return intersection / union

def group_and_flag_duplicates(jobs, threshold=0.85):
    """
    Sorts jobs chronologically, groups them by company, and sets:
    - job['is_duplicate'] = True
    - job['duplicate_of'] = original_job_url
    - original_job['duplicates'] = list of duplicate urls
    Returns the modified jobs list.
    """
    if not jobs:
        return []
        
    # Clean duplicates state first
    for j in jobs:
        j["is_duplicate"] = False
        j["duplicate_of"] = None
        j["duplicates"] = []
        
    # Sort chronologically by scraped_at so the oldest remains original
    def get_time(job_item):
        s = job_item.get("scraped_at", "")
        return s if s else "1970-01-01"
        
    sorted_jobs = sorted(jobs, key=get_time)
    
    # Group jobs by company
    company_groups = {}
    for job in sorted_jobs:
        comp = clean_string_for_similarity(job.get("company_name", ""))
        if comp:
            company_groups.setdefault(comp, []).append(job)
            
    # Perform N^2 comparisons within each company group
    for comp, comp_jobs in company_groups.items():
        if len(comp_jobs) < 2:
            continue
            
        for i in range(len(comp_jobs)):
            job_i = comp_jobs[i]
            if job_i["is_duplicate"]:
                continue
                
            for j in range(i + 1, len(comp_jobs)):
                job_j = comp_jobs[j]
                if job_j["is_duplicate"]:
                    continue
                    
                sim = compute_similarity(job_i, job_j)
                if sim >= threshold:
                    job_j["is_duplicate"] = True
                    job_j["duplicate_of"] = job_i.get("job_url")
                    job_i["duplicates"].append(job_j.get("job_url"))
                    
    return sorted_jobs

if __name__ == "__main__":
    # Quick self-test
    job_a = {
        "company_name": "Test Company",
        "job_url": "url1",
        "location_work_type": "Austin, TX (Remote)",
        "job_description": "We are looking for a Senior DevOps Engineer with experience in AWS, Kubernetes, Terraform, and Python. Great healthcare and dental.",
        "scraped_at": "2026-05-25T12:00:00"
    }
    job_b = {
        "company_name": "Test Company",
        "job_url": "url2",
        "location_work_type": "Remote",
        "job_description": "Test Company is seeking a Senior DevOps Engineer with skills in AWS, Kubernetes, Terraform, and Python. Dental and medical covered.",
        "scraped_at": "2026-05-25T14:00:00"
    }
    job_c = {
        "company_name": "Test Company",
        "job_url": "url3",
        "location_work_type": "Dallas, TX",
        "job_description": "We are seeking a Senior DevOps Engineer with skills in AWS, Kubernetes, Terraform, and Python. Dental and medical covered.",
        "scraped_at": "2026-05-25T15:00:00"
    }
    
    results = group_and_flag_duplicates([job_a, job_b, job_c])
    print("Deduplication results:")
    for r in results:
        print(f"URL: {r['job_url']}, is_duplicate: {r['is_duplicate']}, duplicate_of: {r['duplicate_of']}, duplicates: {r['duplicates']}")
