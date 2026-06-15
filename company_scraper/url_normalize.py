"""Normalize job posting URLs for dedup keys while keeping links usable in a browser."""

from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

# Strip only known marketing / analytics params. Do NOT drop the whole query — many ATS
# listings need ?jobId=…, ?from=… (when functional), etc., or the URL 404s.
_TRACKING_PARAM_NAMES = frozenset(
    {
        "fbclid",
        "gclid",
        "mc_cid",
        "mc_eid",
        "_ga",
        "igshid",
        "si",
        "mkt_tok",
        "oly_enc_id",
        "spm",
        "trk",
        "trkcorp",
        "trkpublic",
        "gbraid",
        "wbraid",
    }
)


def _is_tracking_param(key: str) -> bool:
    k = (key or "").strip().lower()
    if not k:
        return False
    if k in _TRACKING_PARAM_NAMES:
        return True
    if k.startswith("utm_"):
        return True
    return False


def canonical_job_url(url: str) -> str:
    """
    Stable key for deduplication: https, host lowercased, path without trailing slash,
    query string with only known tracking params removed (functional params kept),
    no fragment.
    """
    u = (url or "").strip()
    if not u:
        return ""
    try:
        p = urlparse(u)
        netloc = (p.netloc or "").strip().lower()
        if "@" in netloc:
            netloc = netloc.split("@")[-1]
        if netloc.endswith(":80") or netloc.endswith(":443"):
            netloc = netloc.rsplit(":", 1)[0]
        path = (p.path or "").rstrip("/")
        scheme = "https"
        pairs = parse_qsl(p.query, keep_blank_values=True)
        kept = [(k, v) for k, v in pairs if not _is_tracking_param(k)]
        new_query = urlencode(kept, doseq=True) if kept else ""
        return urlunparse((scheme, netloc, path, "", new_query, ""))
    except Exception:
        return u.split("#")[0].rstrip("/")
