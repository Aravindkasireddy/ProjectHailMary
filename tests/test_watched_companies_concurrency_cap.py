"""Regression test for the watched-companies scheduler concurrency cap.

Real incident (2026-06-25): registering 307 OPT-friendly companies (all with
no last_scraped_at yet, so all instantly "due" on the very first tick)
spawned ~300 concurrent company_scraper subprocesses with no cap at all on
a 2-vCPU production VM, overloading it so badly even SSH stopped responding
and the box needed a hard reset. MAX_CONCURRENT_WATCHED_SCRAPES caps how
many scrapes _run_scheduler_tick() will start in a single tick.
"""
import watched_companies_scheduler as wcs


class _FakeTable:
    def __init__(self, rows):
        self._rows = rows
        self._filters = {}
        self._update_payload = None

    def select(self, *_a, **_k):
        return self

    def eq(self, col, val):
        self._filters[col] = val
        return self

    def update(self, payload):
        self._update_payload = payload
        return self

    def execute(self):
        if self._update_payload is not None:
            row_id = self._filters.get("id")
            for r in self._rows:
                if r["id"] == row_id:
                    r.update(self._update_payload)
            return type("R", (), {"data": []})()
        matching = [
            r for r in self._rows
            if all(r.get(k) == v for k, v in self._filters.items())
        ]
        return type("R", (), {"data": matching})()


class _FakeSupabase:
    def __init__(self, rows):
        self.rows = rows

    def table(self, name):
        assert name == "watched_companies"
        return _FakeTable(self.rows)


def _make_rows(n):
    # All with no last_scraped_at - every one is instantly "due", same as
    # the real incident.
    return [
        {"id": f"row-{i}", "is_active": True, "company_name": f"Co {i}", "last_scraped_at": None}
        for i in range(n)
    ]


def test_never_starts_more_than_the_cap_in_one_tick(monkeypatch):
    wcs._watched_scrape_inflight.clear()
    rows = _make_rows(307)
    sb = _FakeSupabase(rows)

    started_threads = []
    started = wcs._run_scheduler_tick(sb, start_thread=lambda company: started_threads.append(company))

    assert started == wcs.MAX_CONCURRENT_WATCHED_SCRAPES
    assert len(started_threads) == wcs.MAX_CONCURRENT_WATCHED_SCRAPES
    wcs._watched_scrape_inflight.clear()


def test_rows_already_inflight_are_skipped(monkeypatch):
    wcs._watched_scrape_inflight.clear()
    rows = _make_rows(5)
    sb = _FakeSupabase(rows)
    wcs._watched_scrape_inflight.add("row-0")

    started_threads = []
    wcs._run_scheduler_tick(sb, start_thread=lambda company: started_threads.append(company["id"]))

    assert "row-0" not in started_threads
    wcs._watched_scrape_inflight.clear()


def test_not_due_rows_are_not_started(monkeypatch):
    import datetime as dt

    wcs._watched_scrape_inflight.clear()
    rows = [
        {
            "id": "row-recent",
            "is_active": True,
            "company_name": "Recent Co",
            "last_scraped_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "poll_interval_minutes": 10,
        }
    ]
    sb = _FakeSupabase(rows)

    started_threads = []
    started = wcs._run_scheduler_tick(sb, start_thread=lambda company: started_threads.append(company))

    assert started == 0
    assert started_threads == []
    wcs._watched_scrape_inflight.clear()
