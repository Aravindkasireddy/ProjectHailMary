import re

with open("find_and_scrape_jobs.py", "r") as f:
    content = f.read()

# Replace `attempts=2` with `attempts=3` in API calls
content = re.sub(r'http_get\((.*?), attempts=2\)', r'http_get(\1, attempts=3)', content)

# 1. Refactor fetch_company_board_jobs
greenhouse_lever_pattern = re.compile(
    r'(def fetch_company_board_jobs\(.*?\):.*?)(log\("Fetching direct Greenhouse and Lever company board APIs..."\).*?greenhouse_companies = companies_cfg\.get\("greenhouse", \[\]\)\n    lever_companies = companies_cfg\.get\("lever", \[\]\)\n    \n    headers = \{.*?\})[\s\S]*?(?=\n\n    log\(f"Company API Sourcing complete\.)',
    re.DOTALL | re.MULTILINE
)

# Actually, doing this with regex is messy. I will use `replace_file_content` instead.
