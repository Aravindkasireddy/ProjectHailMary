"""Maps a detected ATS kind (company_scraper.detector.detect_ats) to its connector."""
from __future__ import annotations

from typing import Optional

from connectors.base import BaseConnector
from connectors.greenhouse import GreenhouseConnector
from connectors.lever import LeverConnector
from connectors.workday import WorkdayConnector

_REGISTRY = {
    "greenhouse": GreenhouseConnector,
    "lever": LeverConnector,
    "workday": WorkdayConnector,
}


def get_connector(ats_kind: str) -> Optional[BaseConnector]:
    cls = _REGISTRY.get(ats_kind)
    return cls() if cls else None
