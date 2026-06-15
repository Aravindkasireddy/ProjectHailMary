#!/usr/bin/env python3
"""
One-off: remove duplicate rows in public.jobs that represent the same posting.

Groups by (user_id, canonical_job_url) using the same rules as company_scraper/url_normalize.py.
Keeps the row with the latest scraped_at (ties: smallest id wins). Deletes the rest, then sets
the survivor's job_url to the canonical form.

Requires SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY in .env (same as supabase_client).

Usage:
  python3 scripts/dedupe_existing_jobs_supabase.py          # dry-run: print counts only
  python3 scripts/dedupe_existing_jobs_supabase.py --apply # perform deletes/updates
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv

load_dotenv(_ROOT / ".env")

from company_scraper.url_normalize import canonical_job_url


def _fetch_all_job_keys(supabase, page_size: int = 1000):
    """Yield minimal rows: id, user_id, job_url, scraped_at."""
    offset = 0
    while True:
        res = (
            supabase.table("jobs")
            .select("id,user_id,job_url,scraped_at")
            .order("id")
            .range(offset, offset + page_size - 1)
            .execute()
        )
        batch = res.data or []
        for row in batch:
            yield row
        if len(batch) < page_size:
            break
        offset += page_size


def main() -> int:
    parser = argparse.ArgumentParser(description="Dedupe public.jobs by canonical job_url per user.")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply deletes and URL updates (default is dry-run).",
    )
    args = parser.parse_args()

    from supabase_client import get_supabase_client

    supabase = get_supabase_client()

    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in _fetch_all_job_keys(supabase):
        uid = row.get("user_id")
        ju = row.get("job_url") or ""
        c = canonical_job_url(ju)
        if not uid or not c:
            continue
        groups[(str(uid), c)].append(row)

    dup_groups = {k: v for k, v in groups.items() if len(v) > 1}
    solo_fix = 0
    for k, members in groups.items():
        if len(members) != 1:
            continue
        m = members[0]
        if (m.get("job_url") or "") != k[1]:
            solo_fix += 1

    to_delete = sum(len(v) - 1 for v in dup_groups.values())
    print(f"Duplicate groups (same user + canonical URL): {len(dup_groups)}")
    print(f"Rows to delete: {to_delete}")
    print(f"Single rows needing URL canonicalization only: {solo_fix}")

    if not args.apply:
        print("Dry-run only. Re-run with --apply to execute.")
        return 0

    deleted = 0
    updated = 0
    for (uid, canon), members in dup_groups.items():

        def sort_key(m: dict):
            ts = m.get("scraped_at") or ""
            return (ts, str(m.get("id") or ""))

        members_sorted = sorted(members, key=sort_key, reverse=True)
        winner = members_sorted[0]
        win_id = winner["id"]

        for loser in members_sorted[1:]:
            supabase.table("jobs").delete().eq("id", loser["id"]).execute()
            deleted += 1

        if (winner.get("job_url") or "") != canon:
            supabase.table("jobs").update({"job_url": canon}).eq("id", win_id).execute()
            updated += 1

    for (uid, canon), members in groups.items():
        if len(members) != 1:
            continue
        m = members[0]
        if (m.get("job_url") or "") != canon:
            supabase.table("jobs").update({"job_url": canon}).eq("id", m["id"]).execute()
            updated += 1

    print(f"Applied: deleted={deleted}, canonical URL updates={updated}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
