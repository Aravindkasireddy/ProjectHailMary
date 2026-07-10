"""
ATS board freshness checker.

Validates every Greenhouse / Lever / Ashby slug in config.json by hitting
their public API endpoints and marking any that return 404 / non-200 as dead.

Usage:
    python scripts/check_ats_boards.py           # report only
    python scripts/check_ats_boards.py --prune   # remove dead slugs from config.json

Output: prints a table of live / dead slugs; with --prune writes config.json.
"""
import json
import sys
import argparse
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.json"

_SESSION = requests.Session()
_SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (compatible; ATS-Freshness-Checker/1.0)"
})

ENDPOINTS = {
    "greenhouse": "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs",
    "lever":      "https://api.lever.co/v0/postings/{slug}?mode=json&limit=1",
    "ashby":      "https://api.ashbyhq.com/posting-api/job-board/{slug}",
}

# Some boards are huge — only fetch 1 item to confirm the slug exists
TIMEOUT = 10


def check_slug(ats: str, slug: str) -> tuple[str, str, bool, str]:
    """Return (ats, slug, is_live, reason)."""
    url = ENDPOINTS[ats].format(slug=slug)
    try:
        r = _SESSION.get(url, timeout=TIMEOUT)
        if r.status_code == 200:
            # Confirm the board actually returned job data (not an empty 200 shell)
            try:
                data = r.json()
                if ats == "greenhouse":
                    count = len(data.get("jobs", []))
                elif ats == "lever":
                    count = len(data) if isinstance(data, list) else 0
                elif ats == "ashby":
                    count = len(data.get("jobPostings", []))
                else:
                    count = 1
                return ats, slug, True, f"200 OK ({count} jobs)"
            except Exception:
                return ats, slug, True, "200 OK (unparseable body)"
        elif r.status_code == 404:
            return ats, slug, False, "404 Not Found"
        else:
            return ats, slug, False, f"HTTP {r.status_code}"
    except requests.RequestException as e:
        return ats, slug, False, f"Error: {type(e).__name__}"


def main():
    parser = argparse.ArgumentParser(description="Check ATS board slug freshness")
    parser.add_argument("--prune", action="store_true", help="Remove dead slugs from config.json")
    parser.add_argument("--workers", type=int, default=10, help="Concurrent workers (default 10)")
    parser.add_argument("--ats", choices=["greenhouse", "lever", "ashby", "all"], default="all")
    args = parser.parse_args()

    with open(CONFIG_PATH) as f:
        config = json.load(f)

    target_companies = config.get("target_companies", {})
    ats_list = ["greenhouse", "lever", "ashby"] if args.ats == "all" else [args.ats]

    tasks = []
    for ats in ats_list:
        for slug in target_companies.get(ats, []):
            tasks.append((ats, slug))

    print(f"Checking {len(tasks)} slugs across {', '.join(ats_list)}...\n")

    results = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(check_slug, ats, slug): (ats, slug) for ats, slug in tasks}
        for i, future in enumerate(as_completed(futures), 1):
            ats, slug, live, reason = future.result()
            results.append((ats, slug, live, reason))
            status = "✓" if live else "✗"
            print(f"[{i:>3}/{len(tasks)}] {status} {ats:<12} {slug:<40} {reason}")

    dead = [(ats, slug) for ats, slug, live, _ in results if not live]
    live_count = len(results) - len(dead)

    print(f"\n{'='*60}")
    print(f"Live: {live_count}  Dead: {len(dead)}  Total: {len(results)}")

    if dead:
        print(f"\nDead slugs ({len(dead)}):")
        for ats, slug in sorted(dead):
            print(f"  {ats}: {slug}")

    if args.prune and dead:
        dead_by_ats: dict[str, set] = {}
        for ats, slug in dead:
            dead_by_ats.setdefault(ats, set()).add(slug)

        pruned = 0
        for ats, dead_slugs in dead_by_ats.items():
            before = config["target_companies"].get(ats, [])
            after = [s for s in before if s not in dead_slugs]
            config["target_companies"][ats] = after
            pruned += len(before) - len(after)

        with open(CONFIG_PATH, "w") as f:
            json.dump(config, f, indent=2)
        print(f"\n--prune: removed {pruned} dead slugs from config.json")
    elif dead and not args.prune:
        print("\nRun with --prune to remove dead slugs from config.json")


if __name__ == "__main__":
    main()
