#!/usr/bin/env python3
"""
Company-targeted IT job scraper entrypoint (subprocess from dashboard_server).

On-demand only: job rows are upserted directly to Supabase ``public.jobs`` (no pipeline JSON).
This process still emits logs under ``logs/company_scraper.log`` and a summary JSON line on stdout.

Environment (set by caller):
  MAAS_USER_ID, MAAS_USER_EMAIL — required for Supabase upsert

Argument: base64(JSON({"input": "...", "it_prefs": {...optional}})) or raw string (legacy).
"""

from __future__ import annotations

import base64
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv

load_dotenv(dotenv_path=_ROOT / ".env")

from jobsearch_paths import workspace_root

_PROGRESS_PREFIX = "COMPANY_SCRAPER_PROGRESS:"


def _emit_progress(phase_key: str, tracker=None) -> None:
    """Emit a single-line progress marker read by dashboard_server (stderr, not logging)."""
    print(f"{_PROGRESS_PREFIX}{json.dumps({'phase': phase_key})}", file=sys.stderr, flush=True)
    if tracker is None:
        return
    stage_map = {
        "discovering": "discovery",
        "scraping": "scraping",
        "filtering": "filtering",
        "saving": "saving",
    }
    st = stage_map.get(phase_key)
    if st:
        tracker.update_stage(st)


def _setup_logging() -> None:
    log_dir = workspace_root() / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / "company_scraper.log"
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    fh = logging.FileHandler(path, encoding="utf-8")
    fh.setFormatter(fmt)
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(logging.INFO)
    root.addHandler(fh)
    sh = logging.StreamHandler(sys.stderr)
    sh.setFormatter(fmt)
    sh.setLevel(logging.INFO)
    root.addHandler(sh)


def _parse_main_cli():
    """Parse ``[payload] [--run-id UUID]`` or ``--run-id UUID [payload]`` from argv."""
    args = sys.argv[1:]
    run_id = None
    positional: list[str] = []
    i = 0
    while i < len(args):
        if args[i] == "--run-id" and i + 1 < len(args):
            run_id = args[i + 1].strip()
            i += 2
            continue
        positional.append(args[i])
        i += 1
    raw = positional[0] if positional else ""
    try:
        decoded = base64.b64decode(raw.encode("ascii"), validate=True).decode("utf-8")
        data = json.loads(decoded)
        if isinstance(data, dict) and "input" in data:
            it_prefs = data.get("it_prefs") if isinstance(data.get("it_prefs"), dict) else {}
            return run_id, str(data["input"] or "").strip(), it_prefs
    except Exception:
        pass
    return run_id, raw.strip(), {}


def _scrape_listing(
    careers_url: str,
    company_hint: str,
    ats: str,
    *,
    max_generic_jobs: int = 40,
    max_workday_pages: int = 24,
):
    from company_scraper.scrapers import greenhouse, generic, icims, lever, workday

    if ats == "greenhouse":
        return greenhouse.fetch_jobs(careers_url, company_hint)
    if ats == "lever":
        return lever.fetch_jobs(careers_url, company_hint)
    if ats == "workday":
        return workday.fetch_jobs(careers_url, company_hint, max_pages=max_workday_pages)
    if ats == "icims":
        return icims.fetch_jobs(careers_url, company_hint)
    return generic.fetch_jobs(careers_url, company_hint, max_jobs=max_generic_jobs)


def _careers_listing_url_plan(primary: str) -> list[str]:
    from company_scraper.detector import listing_url_candidates_from_careers_url

    p = (primary or "").strip().rstrip("/")
    out: list[str] = []
    seen: set[str] = set()
    for u in [p] + listing_url_candidates_from_careers_url(p):
        u = u.strip().rstrip("/")
        if u and u not in seen:
            seen.add(u)
            out.append(u)
    return out


def _best_listing_batch(
    urls: list[str],
    company_hint: str,
    log: logging.Logger,
    *,
    max_generic_jobs: int,
    max_workday_pages: int,
) -> tuple[list, str, str, list[dict[str, Any]]]:
    """Try several listing URLs; return the batch with the most rows (dedupe by job_url)."""
    from company_scraper.constants import MAX_LISTING_URL_ATTEMPTS
    from company_scraper.detector import detect_ats
    from company_scraper.url_normalize import canonical_job_url

    best: list = []
    best_url = ""
    best_ats = "generic"
    attempts: list[dict[str, Any]] = []
    seen_try: set[str] = set()
    for url in urls[:MAX_LISTING_URL_ATTEMPTS]:
        url = (url or "").strip().rstrip("/")
        if not url or url in seen_try:
            continue
        seen_try.add(url)
        ats_c = detect_ats(url)
        err_s: str | None = None
        try:
            batch = _scrape_listing(
                url,
                company_hint,
                ats_c,
                max_generic_jobs=max_generic_jobs,
                max_workday_pages=max_workday_pages,
            )
        except Exception as e:
            err_s = str(e)[:500]
            log.info("listing scrape failed %s (%s): %s", url, ats_c, e)
            batch = []
        by_url: dict[str, Any] = {}
        for row in batch:
            ju = canonical_job_url(row.get("job_url") or "")
            if ju:
                row["job_url"] = ju
                by_url[ju] = row
        deduped = list(by_url.values())
        prev_best = len(best)
        picked = len(deduped) > prev_best
        if picked:
            best = deduped
            best_url = url
            best_ats = ats_c
            log.info("best listing so far: %s jobs from %s (%s)", len(best), url, ats_c)
        attempts.append(
            {
                "url": url,
                "ats": ats_c,
                "jobs_found": len(deduped),
                "error": err_s,
                "picked": picked,
            }
        )
    return best, best_url, best_ats, attempts


def _dedupe_jobs_canonical_rows(jobs: list) -> list:
    """Normalize ``job_url`` to canonical form and collapse duplicates in one run."""
    from company_scraper.url_normalize import canonical_job_url

    by_c: dict[str, dict] = {}
    for row in jobs:
        u = canonical_job_url(row.get("job_url") or "")
        if not u:
            continue
        row["job_url"] = u
        by_c[u] = row
    return list(by_c.values())


def run(input_str: str, scrape_run_id=None, it_prefs: dict[str, Any] | None = None):
    _setup_logging()
    log = logging.getLogger("company_scraper")
    errors: list[str] = []
    summary = {
        "company": input_str.strip(),
        "careers_url": "",
        "ats_platform": "generic",
        "total_scraped": 0,
        "it_jobs_found": 0,
        "saved_to_db": 0,
        "errors": errors,
        "transcript": [],
        "listing_attempts": [],
        "listing_winner_url": "",
    }
    transcript: list[str] = []

    def tr(msg: str) -> None:
        transcript.append(msg)
        log.info(msg)

    uid = (os.environ.get("MAAS_USER_ID") or "").strip()
    email = (os.environ.get("MAAS_USER_EMAIL") or "").strip()
    tracker = None
    if scrape_run_id and uid:
        try:
            from scrape_tracker import ScrapeTracker

            tracker = ScrapeTracker(
                uid,
                email,
                "company_targeted",
                input_value=(input_str or "").strip(),
                existing_run_id=scrape_run_id,
            )
        except Exception:
            tracker = None
    if not uid or not email:
        errors.append("MAAS_USER_ID and MAAS_USER_EMAIL must be set for Supabase publish")
        print(json.dumps(summary))
        return summary

    from company_scraper.constants import MAX_GENERIC_JOBS, MAX_WORKDAY_PAGES
    from company_scraper.detector import (
        brand_label_from_careers_url,
        detect_ats,
        detect_input_type,
        listing_url_candidates_from_job_url,
    )
    from company_scraper.discovery import find_careers_url
    from company_scraper.filters import merge_it_prefs, passes_it_job
    from company_scraper.publisher import upsert_jobs
    from company_scraper.scrapers import generic, greenhouse, lever

    raw = (input_str or "").strip()
    if not raw:
        errors.append("empty input")
        print(json.dumps(summary))
        return summary

    env_it = (os.environ.get("COMPANY_SCRAPER_IT_JSON") or "").strip()
    prefs_in: dict[str, Any] = dict(it_prefs or {})
    if env_it:
        try:
            jo = json.loads(env_it)
            if isinstance(jo, dict):
                prefs_in = {**jo, **prefs_in}
        except Exception:
            pass
    it_prefs_merged = merge_it_prefs(prefs_in)
    summary["it_prefs_effective"] = it_prefs_merged
    tr(
        f"IT filter: min_score={it_prefs_merged.get('min_it_score')} "
        f"strict_engineering={it_prefs_merged.get('strict_engineering_only')} "
        f"include_data={it_prefs_merged.get('include_data_roles')} "
        f"include_analyst={it_prefs_merged.get('include_analyst_roles')}"
    )

    kind = detect_input_type(raw)
    careers_url = ""
    company_hint = ""

    if kind == "company_name":
        company_hint = raw
        _emit_progress("discovering", tracker)
        tr(f"Input type: company name → discovering careers URL for {raw!r}")
        careers_url = find_careers_url(raw, errors) or ""
        summary["company"] = raw
        if not careers_url:
            log.error("discovery failed for %r", raw)
            tr("Discovery failed: no careers URL found.")
            summary["transcript"] = transcript
            print(json.dumps(summary))
            return summary
        tr(f"Discovered careers URL: {careers_url}")
    elif kind == "careers_url":
        careers_url = raw.rstrip("/")
        company_hint = brand_label_from_careers_url(careers_url)
        summary["company"] = company_hint
        tr(f"Input type: careers URL → {careers_url}")
    else:
        careers_url = raw
        company_hint = brand_label_from_careers_url(raw)
        tr(f"Input type: job posting URL → {raw[:120]}{'…' if len(raw) > 120 else ''}")

    ats = detect_ats(careers_url)
    summary["careers_url"] = careers_url
    summary["ats_platform"] = ats
    listing_attempts: list[dict[str, Any]] = []

    _emit_progress("scraping", tracker)

    jobs: list = []
    max_g = MAX_GENERIC_JOBS
    max_wd = MAX_WORKDAY_PAGES
    try:
        if kind == "job_url":
            summary["company"] = company_hint or brand_label_from_careers_url(raw) or summary["company"]
            hint = company_hint or brand_label_from_careers_url(raw)
            ats_job = detect_ats(raw)
            summary["ats_platform"] = ats_job
            if ats_job == "greenhouse":
                tr("Scrape path: Greenhouse board API (full board from job or listing URL).")
                jobs = greenhouse.fetch_jobs(raw, hint)
                listing_attempts = [
                    {
                        "url": raw,
                        "ats": "greenhouse",
                        "jobs_found": len(jobs),
                        "error": None,
                        "picked": True,
                    }
                ]
            elif ats_job == "lever":
                tr("Scrape path: Lever postings API (full board).")
                jobs = lever.fetch_jobs(raw, hint)
                listing_attempts = [
                    {
                        "url": raw,
                        "ats": "lever",
                        "jobs_found": len(jobs),
                        "error": None,
                        "picked": True,
                    }
                ]
            else:
                plan = listing_url_candidates_from_job_url(raw)
                tr(f"Trying up to {len(plan)} derived listing URLs for job URL…")
                jobs, win_u, win_ats, listing_attempts = _best_listing_batch(
                    plan, hint, log, max_generic_jobs=max_g, max_workday_pages=max_wd
                )
                if jobs:
                    summary["careers_url"] = win_u or raw
                    summary["ats_platform"] = win_ats
                    summary["listing_winner_url"] = win_u
                    tr(f"Listing winner: {win_ats} @ {win_u} ({len(jobs)} jobs)")
                else:
                    tr("No listing batch succeeded; falling back to single job page fetch.")
                    jobs = generic.fetch_single_job_page(raw, hint)
                    summary["careers_url"] = raw
                    summary["ats_platform"] = detect_ats(raw)
        else:
            plan = _careers_listing_url_plan(careers_url)
            tr(f"Careers / company flow: trying {len(plan)} listing URL(s), picking largest batch.")
            jobs, win_u, win_ats, listing_attempts = _best_listing_batch(
                plan, company_hint, log, max_generic_jobs=max_g, max_workday_pages=max_wd
            )
            if win_u:
                summary["careers_url"] = win_u
                summary["listing_winner_url"] = win_u
            if jobs:
                summary["ats_platform"] = win_ats
                tr(f"Listing winner: {win_ats} @ {win_u} ({len(jobs)} jobs)")
            if not jobs:
                log.warning("multi-listing scrape empty; generic fallback on %s", careers_url)
                tr(f"All listing attempts empty; generic fallback on primary URL {careers_url}")
                jobs = generic.fetch_jobs(careers_url, company_hint, max_jobs=max_g)
                summary["ats_platform"] = "generic"
    except Exception as e:
        errors.append(str(e))
        log.exception("scrape failed")
        tr(f"Scrape exception: {e}")
        try:
            jobs = (
                generic.fetch_jobs(careers_url, company_hint, max_jobs=max_g) if careers_url else []
            )
            summary["ats_platform"] = "generic"
            tr("Recovered via generic fetch on primary careers URL.")
        except Exception as e2:
            errors.append(str(e2))
            tr(f"Generic fallback also failed: {e2}")

    summary["listing_attempts"] = listing_attempts
    for a in listing_attempts:
        err = a.get("error")
        extra = f" error={err!r}" if err else ""
        tr(
            f"  try: {a.get('ats')} jobs_found={a.get('jobs_found')} picked={a.get('picked')} "
            f"url={a.get('url', '')[:100]}{extra}"
        )

    jobs = _dedupe_jobs_canonical_rows(jobs)
    tr(f"After canonical URL dedupe: {len(jobs)} unique job rows.")

    summary["total_scraped"] = len(jobs)

    _emit_progress("filtering", tracker)

    it_jobs = []
    for j in jobs:
        dept = str(j.get("department") or "")
        if passes_it_job(j.get("job_title") or "", dept, it_prefs_merged):
            it_jobs.append(j)
    summary["it_jobs_found"] = len(it_jobs)
    tr(f"IT filter pass: {len(it_jobs)} of {len(jobs)} rows (tiered score + your prefs).")

    _emit_progress("saving", tracker)

    try:
        summary["saved_to_db"] = upsert_jobs(it_jobs, uid, email, summary["ats_platform"])
        tr(f"Saved {summary['saved_to_db']} rows to Supabase.")
    except Exception as e:
        errors.append(f"publisher: {e}")
        log.exception("publish failed")
        tr(f"Publisher error: {e}")

    if errors:
        tr("Errors: " + "; ".join(errors[:12]))

    summary["transcript"] = transcript

    log.info(
        "summary company=%s ats=%s scraped=%s it=%s saved=%s",
        summary["company"],
        summary["ats_platform"],
        summary["total_scraped"],
        summary["it_jobs_found"],
        summary["saved_to_db"],
    )
    print(json.dumps(summary))
    return summary


if __name__ == "__main__":
    rid, inp, prefs = _parse_main_cli()
    run(inp, scrape_run_id=rid, it_prefs=prefs)
