"""HTTP helpers with retries (requests only)."""

from __future__ import annotations

import random
import time
from typing import Any, Mapping, MutableMapping, Optional

import requests

_DEFAULT_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def get_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(
        {
            "User-Agent": _DEFAULT_UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
    )
    return s


def request_with_retry(
    method: str,
    url: str,
    *,
    session: Optional[requests.Session] = None,
    headers: Optional[Mapping[str, str]] = None,
    params: Optional[Mapping[str, Any]] = None,
    json_body: Any = None,
    timeout: int = 25,
    max_attempts: int = 3,
) -> requests.Response:
    sess = session or get_session()
    last_exc: Optional[Exception] = None
    merged: MutableMapping[str, str] = dict(sess.headers)
    if headers:
        merged.update(dict(headers))
    for attempt in range(1, max_attempts + 1):
        try:
            r = sess.request(
                method,
                url,
                headers=dict(merged),
                params=dict(params) if params else None,
                json=json_body,
                timeout=timeout,
            )
            if r.status_code >= 500 and attempt < max_attempts:
                time.sleep(0.5 * (2 ** (attempt - 1)) + random.uniform(0, 0.3))
                continue
            return r
        except (requests.RequestException, OSError) as e:
            last_exc = e
            if attempt < max_attempts:
                time.sleep(0.5 * (2 ** (attempt - 1)) + random.uniform(0, 0.3))
            else:
                raise
    assert last_exc is not None
    raise last_exc


def head_ok(url: str, timeout: int = 8) -> bool:
    try:
        r = request_with_retry("HEAD", url, timeout=timeout, max_attempts=2)
        if r.status_code == 200:
            return True
        if r.status_code in (301, 302, 303, 307, 308):
            loc = r.headers.get("Location")
            if loc:
                return head_ok(loc, timeout=timeout)
        if r.status_code == 405:
            r2 = request_with_retry("GET", url, timeout=timeout, max_attempts=2)
            return r2.status_code == 200
        return False
    except Exception:
        return False
