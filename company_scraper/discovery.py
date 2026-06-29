"""Resolve company name to a careers URL (Yahoo + heuristics + HEAD)."""

from __future__ import annotations

import re
from typing import List, Optional
from urllib.parse import quote_plus, urlparse

from bs4 import BeautifulSoup

from company_scraper.http_utils import get_session, head_ok, request_with_retry

# Domains where a 200 response is inherently trustworthy as "a real careers
# page" - these are real ATS platforms, not something an unrelated party
# can squat. Slug-guessed raw domains (careers.{slug}.com, {slug}.com/careers,
# etc.) have no such guarantee and need the content check below.
_TRUSTED_ATS_DOMAINS = ("greenhouse.io", "lever.co", "myworkdayjobs.com", "workdayjobs.com", "icims.com", "ashbyhq.com")

# Real incident (2026-06-29): head_ok() alone accepted
# "americanairlinesinc.com/careers" and "tsmcarizonacorporation.com/careers"
# as "found" candidates during a live discovery run - both resolved to the
# same IP and returned a 114-byte body that was just
# `<script>window.onload=function(){window.location.href="/lander"}</script>`,
# a classic parked-domain redirect stub with zero real content. Confirmed
# live with curl/host. Guards below reject that pattern before find_careers_url()
# trusts a guessed raw domain.
_PARKING_PAGE_PHRASES = (
    "domain is parked", "buy this domain", "this domain may be for sale",
    "domain for sale", "parkingcrew", "sedoparking", "courtesy of dan.com",
    "checkout dan.com", "godaddy.com/domains",
)
_CAREERS_PAGE_SIGNAL_WORDS = (
    "career", "job", "hiring", "apply", "position", "opportunit", "openings", "vacanc", "join our team",
)

# Real incident (2026-06-29), found in the same live discovery run as the
# parking-page bug above: "UNITED WHOLESALE MORTGAGE LLC"'s slug-guessed
# candidate careers.united.com resolved to a genuine, fully real careers
# page - but it's United Airlines' careers page, not United Wholesale
# Mortgage's. The content-sanity check above can't catch this (the page
# really is a careers page), so a separate check is needed: does the page
# actually mention THIS company. Common, generic first words of a company
# name ("united", "american", "national", "global", etc.) are exactly the
# words most likely to coincidentally match an unrelated company's real
# domain, so a match on one of those alone isn't sufficient evidence -
# require a more distinctive token instead, falling back to the generic
# one only if the company name has nothing more specific to offer.
_GENERIC_COLLISION_RISK_WORDS = {
    "united", "american", "national", "global", "first", "general", "allied",
    "premier", "advanced", "capital", "western", "eastern", "southern",
    "central", "pacific", "standard", "international", "consolidated",
}


def _is_genuine_careers_page(url: str, company_name: str = "") -> bool:
    """Reject parked/squatted domains that return a fake 200 for any path,
    and reject a real-but-wrong-company careers page (a slug guess can land
    on an unrelated company's genuine site). Only meaningful for slug-guessed
    raw-domain candidates - callers should skip this check entirely for a
    recognized ATS domain (see _TRUSTED_ATS_DOMAINS), which can't be
    squatted or coincidentally matched the same way.
    """
    try:
        r = request_with_retry("GET", url, session=get_session(), timeout=8, max_attempts=2)
        if r.status_code >= 400:
            return False
        text = r.text or ""
        low = text.lower()
        if any(p in low for p in _PARKING_PAGE_PHRASES):
            return False
        # A genuine careers page has real content; the parking-page stub
        # found live above was 114 bytes with nothing but a JS redirect.
        if len(text.strip()) < 300:
            return False
        if not any(k in low for k in _CAREERS_PAGE_SIGNAL_WORDS):
            return False
        if company_name:
            import find_and_scrape_jobs as fasj

            tokens = fasj.get_company_tokens(company_name)
            distinctive = [t for t in tokens if t not in _GENERIC_COLLISION_RISK_WORDS]
            check_tokens = distinctive or tokens
            if check_tokens and not any(t in low for t in check_tokens):
                return False
        return True
    except Exception:
        return False


def _yahoo_links(query: str) -> List[str]:
    url = f"https://search.yahoo.com/search?p={quote_plus(query)}"
    links: List[str] = []
    try:
        r = request_with_retry("GET", url, session=get_session(), timeout=15, max_attempts=3)
        if r.status_code != 200:
            return links
        soup = BeautifulSoup(r.text, "html.parser")
        for a in soup.find_all("a", href=True):
            href = a["href"]
            m = re.search(r"RU=([^/]+)", href)
            if m:
                from urllib.parse import unquote

                href = unquote(m.group(1))
            # Real bug (2026-06-24): the RU= branch used to append its decoded
            # URL unconditionally, with no domain filter - unlike this check,
            # which the non-RU= branch already had. Yahoo's own search-results
            # page embeds internal links (e.g. shopping.yahoo.com widgets)
            # behind the RU= redirect param, and those were being returned as
            # if they were genuine external "careers URL" results - confirmed
            # live, this caused find_careers_url() to return a literal Yahoo
            # search page for most companies that needed the Yahoo fallback,
            # which detect_ats() then misclassified as "greenhouse" purely
            # because the substring "greenhouse.io" appeared in the URL's own
            # query string (the original search query embedded in the link).
            parsed = urlparse(href)
            dom = parsed.netloc.lower()
            if parsed.scheme.startswith("http") and "yahoo.com" not in dom and "yimg.com" not in dom:
                links.append(href)
    except Exception:
        pass
    return links


def _slug_from_company(name: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "", name.lower())
    return s[:40] or "company"


def _candidate_urls(company_name: str) -> List[str]:
    slug = _slug_from_company(company_name)
    compact = company_name.strip().lower().replace(" ", "")
    parts = [p for p in re.split(r"[^a-zA-Z0-9]+", company_name.strip().lower()) if p]
    first = parts[0] if parts else ""
    roots = [
        f"https://{slug}.greenhouse.io",
        f"https://boards.greenhouse.io/{slug}",
        f"https://jobs.lever.co/{slug}",
        f"https://{slug}.myworkdayjobs.com",
        f"https://careers.{slug}.com",
        f"https://jobs.{slug}.com",
        f"https://careers.{compact}.com",
        f"https://jobs.{compact}.com",
        f"https://careers.{first}.com" if first and first not in (slug, compact) else "",
        f"https://www.{compact}.com/careers",
        f"https://{compact}.com/careers",
    ]
    return [u for u in roots if u]


def find_careers_url(company_name: str, errors: Optional[List[str]] = None) -> Optional[str]:
    import time

    err = errors if errors is not None else []
    name = (company_name or "").strip()
    if not name:
        err.append("empty company name")
        return None

    _t0 = time.perf_counter()

    # Registry-first: skip live discovery entirely if we already know this
    # company's ATS from a previous discovery run (e.g. the 9985-company
    # OPT-friendly probe). See company_registry.py for why this matters -
    # without it, the same discovery cost gets paid again on every call.
    try:
        from company_registry import resolve_company_ats

        cached = resolve_company_ats(name)
        if cached and cached.get("careers_url"):
            _record_discovery_op(name, time.perf_counter() - _t0, success=True, cache_hit=True, ats_source=cached.get("ats_type"))
            return cached["careers_url"]
    except Exception:
        pass

    found_url = None
    for u in _candidate_urls(name):
        if head_ok(u):
            host = urlparse(u).netloc.lower()
            if any(d in host for d in _TRUSTED_ATS_DOMAINS) or _is_genuine_careers_page(u, name):
                found_url = u.rstrip("/")
                break

    if not found_url:
        q = (
            f'"{name}" jobs careers '
            f"(site:greenhouse.io OR site:lever.co OR site:myworkdayjobs.com OR site:icims.com)"
        )
        for link in _yahoo_links(q):
            low = link.lower()
            if any(
                x in low
                for x in (
                    "greenhouse.io",
                    "lever.co",
                    "myworkdayjobs.com",
                    "workdayjobs.com",
                    "icims.com",
                    "careers.",
                    "/careers",
                    "/jobs",
                )
            ):
                if head_ok(link):
                    host = urlparse(link).netloc.lower()
                    if any(d in host for d in _TRUSTED_ATS_DOMAINS) or _is_genuine_careers_page(link, name):
                        found_url = link.rstrip("/")
                        break

    if not found_url:
        err.append(f"could not discover careers URL for {name!r}")
        _record_discovery_op(name, time.perf_counter() - _t0, success=False, cache_hit=False)
        return None

    ats_detected = None
    try:
        from company_registry import upsert_company
        from company_scraper.detector import detect_ats

        ats_detected = detect_ats(found_url)
        upsert_company(
            name,
            careers_url=found_url,
            ats_type=ats_detected,
            verified=True,
            source="live_discovery",
        )
    except Exception:
        pass

    _record_discovery_op(name, time.perf_counter() - _t0, success=True, cache_hit=False, ats_source=ats_detected)
    return found_url


def _record_discovery_op(company_name, elapsed_s, success, cache_hit, ats_source=None):
    try:
        from jobsearch_paths import workspace_root
        from pipeline_metrics import append_pipeline_metric

        append_pipeline_metric(
            str(workspace_root()),
            "operation",
            {
                "operation_name": "company_discovery",
                "stage": "discovery",
                "company": company_name,
                "ats_source": ats_source,
                "duration_ms": int(elapsed_s * 1000),
                "success": success,
                "metadata": {"cache_hit": cache_hit},
            },
        )
    except Exception:
        pass
