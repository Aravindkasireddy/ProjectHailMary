"""
Fire-and-forget Supabase tracking for pipeline and company-targeted scrape runs.

Uses the service-role Supabase client from ``supabase_client`` (writes bypass RLS).
All network updates run in daemon threads so scrape workers are not blocked.
"""

from __future__ import annotations

import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

_ZERO_UUID = "00000000-0000-0000-0000-000000000000"


def _valid_user_id(uid: Optional[str]) -> bool:
    return bool(uid and str(uid).strip() and str(uid).strip() != _ZERO_UUID)


def _fire_async(fn, *args, **kwargs) -> None:
    def _run() -> None:
        try:
            fn(*args, **kwargs)
        except Exception:
            pass

    threading.Thread(target=_run, daemon=True).start()


class ScrapeTracker:
    """Track a single scrape run row in ``public.scrape_runs``."""

    def __init__(
        self,
        user_id: Optional[str],
        user_email: Optional[str],
        run_type: str,
        input_value: Optional[str] = None,
        existing_run_id: Optional[str] = None,
    ) -> None:
        self.user_id = (user_id or "").strip()
        self.user_email = (user_email or "").strip()
        self.run_type = run_type
        self.input_value = input_value
        self._run_id = (existing_run_id or "").strip() or None
        self._t0 = time.perf_counter()

    def start(self) -> str:
        """Insert a new row with status ``running``; returns run UUID (empty if skipped)."""
        if self._run_id:
            return self._run_id
        if not _valid_user_id(self.user_id):
            return ""
        rid = str(uuid.uuid4())
        self._run_id = rid

        uid = self.user_id
        email = self.user_email
        rt = self.run_type
        iv = self.input_value

        def _insert() -> None:
            try:
                from supabase_client import get_supabase_client

                get_supabase_client().table("scrape_runs").insert(
                    {
                        "id": rid,
                        "user_id": uid,
                        "user_email": email or None,
                        "run_type": rt,
                        "status": "running",
                        "input_value": iv,
                    }
                ).execute()
            except Exception:
                pass

        _fire_async(_insert)
        return rid

    @property
    def run_id(self) -> Optional[str]:
        return self._run_id

    def update_stage(self, stage: str) -> None:
        rid = self._run_id
        if not rid:
            return

        def _upd() -> None:
            try:
                from supabase_client import get_supabase_client

                get_supabase_client().table("scrape_runs").update({"stage": stage}).eq("id", rid).execute()
            except Exception:
                pass

        _fire_async(_upd)

    def complete(self, summary: Dict[str, Any]) -> None:
        rid = self._run_id
        if not rid:
            return
        dur = max(0, int(time.perf_counter() - self._t0))

        def _upd() -> None:
            try:
                from supabase_client import get_supabase_client

                finished = datetime.now(timezone.utc).isoformat()
                payload: Dict[str, Any] = {
                    "status": "completed",
                    "finished_at": finished,
                    "duration_seconds": dur,
                    "summary": summary or {},
                }
                ts = summary.get("total_scraped")
                if ts is None:
                    ts = summary.get("scraped_jobs_count")
                if ts is not None:
                    try:
                        payload["total_scraped"] = int(ts)
                    except (TypeError, ValueError):
                        pass
                ij = summary.get("it_jobs_found")
                if ij is not None:
                    try:
                        payload["it_jobs_found"] = int(ij)
                    except (TypeError, ValueError):
                        pass
                sv = summary.get("saved_to_db")
                if sv is not None:
                    try:
                        payload["saved_to_db"] = int(sv)
                    except (TypeError, ValueError):
                        pass
                comp = summary.get("company")
                if comp is not None:
                    payload["company_name"] = str(comp)[:2000]
                ats = summary.get("ats_platform")
                if ats is not None:
                    payload["ats_platform"] = str(ats)[:200]

                get_supabase_client().table("scrape_runs").update(payload).eq("id", rid).execute()
            except Exception:
                pass

        _fire_async(_upd)

    def fail(self, error_message: str) -> None:
        rid = self._run_id
        if not rid:
            return
        dur = max(0, int(time.perf_counter() - self._t0))
        err = (error_message or "")[:8000]

        def _upd() -> None:
            try:
                from supabase_client import get_supabase_client

                get_supabase_client().table("scrape_runs").update(
                    {
                        "status": "failed",
                        "finished_at": datetime.now(timezone.utc).isoformat(),
                        "duration_seconds": dur,
                        "error_message": err,
                    }
                ).eq("id", rid).execute()
            except Exception:
                pass

        _fire_async(_upd)
