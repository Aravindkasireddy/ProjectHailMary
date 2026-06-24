"""Standard interface every ATS connector implements.

Goal: stop adding new ATS support as one-off scraper scripts with whatever
shape happened to be convenient at the time (company_scraper/scrapers/*.py
already has 3 slightly different return shapes). Every new connector from
here on implements discover_jobs/extract_job/normalize_job with the same
signatures, so adding ATS #8/#9/#10 doesn't require re-learning a different
pattern each time.

Existing scrapers (greenhouse.py, lever.py, workday.py under
company_scraper/scrapers/) are NOT rewritten - their fetch_jobs() functions
already work and are battle-tested. Each connector here wraps the matching
scraper module instead of duplicating its HTTP/parsing logic, and adds the
three-method contract plus output normalization on top.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, TypedDict


class RawJob(TypedDict, total=False):
    job_url: str
    job_title: str
    company_name: str
    job_description: str
    location_work_type: str
    requirement_id: str


class CanonicalJob(TypedDict, total=False):
    job_url: str
    job_title: str
    company_name: str
    job_description: str
    location_work_type: str
    requirement_id: str
    ats_source: str
    canonical_fingerprint: str
    salary_min: Optional[float]
    salary_max: Optional[float]
    salary_currency: str
    pay_period: str
    is_remote: bool
    is_hybrid: bool


class BaseConnector:
    """Subclasses must set ``ats_source`` and implement the three methods below."""

    ats_source: str = "generic"

    def discover_jobs(self, careers_url: str, company_hint: str = "") -> List[str]:
        """Return every job_url found at this company's board. Default
        implementation calls _fetch_raw() and caches the full raw rows so
        extract_job() doesn't need a second network round-trip per URL -
        override only if discovery and extraction genuinely need to be
        separate network calls for a given ATS (most JSON-API-based ATSs,
        like Greenhouse/Lever, return full job data in one discovery call).
        """
        raw_jobs = self._fetch_raw(careers_url, company_hint)
        self._raw_by_url = {j["job_url"]: j for j in raw_jobs if j.get("job_url")}
        return list(self._raw_by_url.keys())

    def extract_job(self, job_url: str) -> RawJob:
        """Return the raw (un-normalized) job dict for a single discovered URL."""
        raw_by_url = getattr(self, "_raw_by_url", None) or {}
        if job_url in raw_by_url:
            return raw_by_url[job_url]
        raise KeyError(f"{job_url!r} was not returned by discover_jobs() - call it first")

    def normalize_job(self, raw: RawJob) -> CanonicalJob:
        """Apply salary/location/company normalization and tag the ATS source +
        canonical fingerprint. Shared across all connectors - subclasses should
        not need to override this.
        """
        from company_normalizer import normalize_company
        from location_normalizer import normalize_location
        from salary_normalizer import normalize_salary
        from job_fingerprint import canonical_fingerprint

        company = normalize_company(raw.get("company_name", ""))
        loc = normalize_location(raw.get("location_work_type", ""))
        salary = normalize_salary(raw.get("job_description", ""), raw.get("job_title", ""))

        job: Dict[str, Any] = {
            **raw,
            "company_name": company,
            "location_work_type": loc["display"],
            "is_remote": loc["is_remote"],
            "is_hybrid": loc["is_hybrid"],
            "ats_source": self.ats_source,
            "salary_min": salary.get("salary_min"),
            "salary_max": salary.get("salary_max"),
            "salary_currency": salary.get("currency", "USD"),
            "pay_period": salary.get("pay_period", "year"),
        }
        job["canonical_fingerprint"] = canonical_fingerprint(job)
        return job

    def fetch_all_normalized(self, careers_url: str, company_hint: str = "") -> List[CanonicalJob]:
        """Convenience: run the full discover -> extract -> normalize pipeline."""
        urls = self.discover_jobs(careers_url, company_hint)
        return [self.normalize_job(self.extract_job(u)) for u in urls]

    def _fetch_raw(self, careers_url: str, company_hint: str) -> List[RawJob]:
        raise NotImplementedError("Subclasses must implement _fetch_raw()")
