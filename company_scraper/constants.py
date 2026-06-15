"""Tuning for company-targeted scrapes (maximize roles before IT filter)."""

# Generic Playwright listing → detail fetch
MAX_GENERIC_JOBS = 400

# Workday pagination (Next clicks)
MAX_WORKDAY_PAGES = 24

# Cap on hrefs collected from a listing page (memory / time)
GENERIC_LISTING_LINK_CAP = 2000

# How many distinct listing URLs to try (primary + expansions)
MAX_LISTING_URL_ATTEMPTS = 14
