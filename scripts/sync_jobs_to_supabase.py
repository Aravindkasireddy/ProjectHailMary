#!/usr/bin/env python3
"""
Publish merged local job JSON (+ Notion SQLite mirror) to Supabase public.jobs.

Used by scripts/run_pipeline.sh when MAAS_USER_ID and MAAS_USER_EMAIL are set.
Requires SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in .env (see supabase_client).

Exit codes:
  0 — skipped (no MAAS_USER_*), or upload ok
  1 — misconfiguration or upload raised
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Repo root
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(description="Merge local job artifacts and upsert to Supabase jobs.")
    parser.add_argument("--reason", default="", help="Optional label for logs")
    args = parser.parse_args()

    uid = (os.environ.get("MAAS_USER_ID") or "").strip()
    email = (os.environ.get("MAAS_USER_EMAIL") or "").strip()

    if not uid and not email:
        return 0

    if not uid or not email:
        print(
            "sync_jobs_to_supabase: set both MAAS_USER_ID and MAAS_USER_EMAIL to publish; skipping.",
            file=sys.stderr,
        )
        return 0

    tag = f" ({args.reason})" if args.reason else ""
    try:
        from supabase_client import upload_user_jobs

        ok = upload_user_jobs(uid, email)
        if ok:
            print(f"sync_jobs_to_supabase{tag}: uploaded jobs for {email!r}.")
            return 0
        print(f"sync_jobs_to_supabase{tag}: upload_user_jobs returned False.", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"sync_jobs_to_supabase{tag}: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
