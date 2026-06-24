from __future__ import annotations

from typing import Any, Dict, List

from connectors.base import BaseConnector
from company_scraper.scrapers.lever import fetch_jobs


class LeverConnector(BaseConnector):
    ats_source = "lever"

    def _fetch_raw(self, careers_url: str, company_hint: str) -> List[Dict[str, Any]]:
        return fetch_jobs(careers_url, company_hint)
