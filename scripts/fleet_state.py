#!/usr/bin/env python3
"""fleet_state.py - Persistent SQLite state machine for high-frequency runs.

Decouples DATA SYNC (once per day, network-bound) from WAVE GENERATION
(many times per day, local-only). One database holds four layers:

- gsc_snapshots      24h TTL: the first run of the day pulls GSC once; every
                     later run reads the snapshot locally (GSC tables only
                     update every 24-48h, so re-pulling inside a day returns
                     the same numbers anyway).
- dfs_serp_cache     30-day TTL: every real DataForSEO SERP payload ever
                     fetched; a query is never re-fetched inside the window.
- atomic_task_backlog  the pre-exploded task cursor: runs pop PENDING tasks
                     (priority DESC), mark them LEASED while implementing and
                     SHIPPED at commit time, so back-to-back invocations never
                     emit the same fix twice.
- dfs_budget         daily DataForSEO spend bucket (DailyBudgetGate).
- url_inspections    7-day TTL cache of GSC URL Inspection coverageState
                     results (the 2,000/day free allowance is guarded by a
                     daily counter, so repeated invocations never re-inspect
                     a URL already cached this week).

All state lives under ~/.seo_fleet/ by default (override with --db-path).
stdlib sqlite3 only — no new dependencies.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

DEFAULT_DB_DIR = Path.home() / ".seo_fleet"
DEFAULT_DB_PATH = str(DEFAULT_DB_DIR / "fleet_state.db")

GSC_SNAPSHOT_TTL_HOURS = 24
SERP_CACHE_TTL_DAYS = 30
DEFAULT_DAILY_SERP_BUDGET = 100

_SCHEMA = """
CREATE TABLE IF NOT EXISTS gsc_snapshots (
    site        TEXT NOT NULL,
    window_end  TEXT NOT NULL,
    fetched_at  TEXT NOT NULL,
    rows_json   TEXT NOT NULL,
    PRIMARY KEY (site, window_end)
);
CREATE TABLE IF NOT EXISTS dfs_serp_cache (
    query       TEXT PRIMARY KEY,
    fetched_at  TEXT NOT NULL,
    items_json  TEXT NOT NULL,
    item_types  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS atomic_task_backlog (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    domain          TEXT NOT NULL,
    page            TEXT NOT NULL,
    query           TEXT NOT NULL,
    action_code     TEXT NOT NULL,
    target_component TEXT,
    file_target     TEXT,
    tdd_assertion   TEXT,
    lgbm_score      REAL NOT NULL DEFAULT 0.0,
    priority_score  REAL NOT NULL DEFAULT 0.0,
    status          TEXT NOT NULL DEFAULT 'PENDING',
    created_at      TEXT NOT NULL,
    leased_at       TEXT,
    shipped_at      TEXT,
    commit_sha      TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS backlog_open_task
    ON atomic_task_backlog (page, action_code) WHERE status IN ('PENDING', 'LEASED');
CREATE INDEX IF NOT EXISTS backlog_status_priority
    ON atomic_task_backlog (status, priority_score DESC);
CREATE TABLE IF NOT EXISTS dfs_budget (
    day         TEXT NOT NULL,
    spent       INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (day)
);
CREATE TABLE IF NOT EXISTS url_inspections (
    url             TEXT PRIMARY KEY,
    site            TEXT NOT NULL,
    coverage_state  TEXT,
    indexing_state  TEXT,
    last_crawl_time TEXT,
    inspected_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS url_inspections_site_age
    ON url_inspections (site, inspected_at);
CREATE TABLE IF NOT EXISTS url_inspection_budget (
    day         TEXT NOT NULL,
    spent       INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (day)
);
"""


def connect_state_db(db_path: str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    path = Path(db_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.executescript(_SCHEMA)
    conn.commit()
    return conn


def _utc_now(now: Optional[datetime]) -> datetime:
    return now or datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


# ------------------------------------------------------------------ snapshots


def save_gsc_snapshot(
    conn: sqlite3.Connection,
    site: str,
    rows: list,
    now: Optional[datetime] = None,
    window_end: Optional[str] = None,
) -> None:
    stamp = _utc_now(now)
    conn.execute(
        "INSERT OR REPLACE INTO gsc_snapshots (site, window_end, fetched_at, rows_json) "
        "VALUES (?, ?, ?, ?)",
        (site, window_end or stamp.date().isoformat(), _iso(stamp), json.dumps(rows)),
    )
    conn.commit()


def gsc_snapshot_fresh(
    conn: sqlite3.Connection,
    site: str,
    max_age_hours: int = GSC_SNAPSHOT_TTL_HOURS,
    now: Optional[datetime] = None,
) -> bool:
    stamp = _utc_now(now)
    cutoff = stamp - timedelta(hours=max_age_hours)
    row = conn.execute(
        "SELECT fetched_at FROM gsc_snapshots WHERE site = ? "
        "ORDER BY fetched_at DESC LIMIT 1",
        (site,),
    ).fetchone()
    if not row:
        return False
    try:
        fetched = datetime.fromisoformat(row[0])
    except ValueError:
        return False
    if fetched.tzinfo is None:
        fetched = fetched.replace(tzinfo=timezone.utc)
    return fetched >= cutoff


def load_gsc_snapshot(
    conn: sqlite3.Connection,
    site: str,
    max_age_hours: int = GSC_SNAPSHOT_TTL_HOURS,
    now: Optional[datetime] = None,
) -> Optional[list]:
    if not gsc_snapshot_fresh(conn, site, max_age_hours=max_age_hours, now=now):
        return None
    row = conn.execute(
        "SELECT rows_json FROM gsc_snapshots WHERE site = ? ORDER BY fetched_at DESC LIMIT 1",
        (site,),
    ).fetchone()
    return json.loads(row[0]) if row else None


# ----------------------------------------------------------------- serp cache


def upsert_serp_cache(
    conn: sqlite3.Connection,
    query: str,
    items: list,
    item_types: list,
    now: Optional[datetime] = None,
) -> None:
    stamp = _utc_now(now)
    conn.execute(
        "INSERT OR REPLACE INTO dfs_serp_cache (query, fetched_at, items_json, item_types) "
        "VALUES (?, ?, ?, ?)",
        (query, _iso(stamp), json.dumps(items), json.dumps(item_types)),
    )
    conn.commit()


def load_cached_serps(
    conn: sqlite3.Connection,
    queries: list,
    max_age_days: int = SERP_CACHE_TTL_DAYS,
    now: Optional[datetime] = None,
) -> dict:
    stamp = _utc_now(now)
    cutoff = stamp - timedelta(days=max_age_days)
    fresh: dict[str, dict[str, Any]] = {}
    for query in queries:
        row = conn.execute(
            "SELECT items_json, item_types, fetched_at FROM dfs_serp_cache WHERE query = ?",
            (query,),
        ).fetchone()
        if not row:
            continue
        try:
            fetched = datetime.fromisoformat(row[2])
        except ValueError:
            continue
        if fetched.tzinfo is None:
            fetched = fetched.replace(tzinfo=timezone.utc)
        if fetched >= cutoff:
            fresh[query] = {
                "items": json.loads(row[0]),
                "item_types": json.loads(row[1]),
            }
    return fresh


# ------------------------------------------------------------- task backlog


def enqueue_tasks(
    conn: sqlite3.Connection,
    tasks: list,
    now: Optional[datetime] = None,
) -> int:
    """Appends tasks as PENDING; dedupes on (page, action_code) while open."""
    stamp = _iso(_utc_now(now))
    added = 0
    for task in tasks:
        try:
            conn.execute(
                "INSERT INTO atomic_task_backlog "
                "(domain, page, query, action_code, target_component, file_target, "
                " tdd_assertion, lgbm_score, priority_score, status, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', ?)",
                (
                    str(task.get("domain") or ""),
                    str(task.get("page") or task.get("url") or ""),
                    str(task.get("query") or ""),
                    str(task.get("action_code") or task.get("prescribed_action") or ""),
                    task.get("target_component"),
                    task.get("file_target"),
                    task.get("tdd_assertion"),
                    float(task.get("lgbm_score") or 0.0),
                    float(task.get("priority_score") or task.get("rank_score") or 0.0),
                    stamp,
                ),
            )
            added += 1
        except sqlite3.IntegrityError:
            continue  # same (page, action_code) already open -> idempotent
    conn.commit()
    return added


def lease_tasks(
    conn: sqlite3.Connection,
    domain: Optional[str] = None,
    limit: int = 35,
    now: Optional[datetime] = None,
) -> list:
    """Pops the next PENDING tasks (priority DESC) and marks them LEASED."""
    stamp = _iso(_utc_now(now))
    if domain:
        rows = conn.execute(
            "SELECT id, domain, page, query, action_code, target_component, file_target, "
            "tdd_assertion, lgbm_score, priority_score FROM atomic_task_backlog "
            "WHERE status = 'PENDING' AND domain = ? ORDER BY priority_score DESC LIMIT ?",
            (domain, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, domain, page, query, action_code, target_component, file_target, "
            "tdd_assertion, lgbm_score, priority_score FROM atomic_task_backlog "
            "WHERE status = 'PENDING' ORDER BY priority_score DESC LIMIT ?",
            (limit,),
        ).fetchall()
    leased: list[dict[str, Any]] = []
    for row in rows:
        conn.execute(
            "UPDATE atomic_task_backlog SET status = 'LEASED', leased_at = ? WHERE id = ?",
            (stamp, row[0]),
        )
        leased.append(
            {
                "id": row[0],
                "domain": row[1],
                "page": row[2],
                "query": row[3],
                "action_code": row[4],
                "target_component": row[5],
                "file_target": row[6],
                "tdd_assertion": row[7],
                "lgbm_score": row[8],
                "priority_score": row[9],
                "status": "LEASED",
            }
        )
    conn.commit()
    return leased


def mark_shipped(
    conn: sqlite3.Connection,
    task_ids: list,
    commit_sha: Optional[str] = None,
    now: Optional[datetime] = None,
) -> int:
    stamp = _iso(_utc_now(now))
    marked = 0
    for task_id in task_ids:
        cur = conn.execute(
            "UPDATE atomic_task_backlog SET status = 'SHIPPED', shipped_at = ?, commit_sha = ? "
            "WHERE id = ? AND status IN ('PENDING', 'LEASED')",
            (stamp, commit_sha, task_id),
        )
        marked += cur.rowcount
    conn.commit()
    return marked


def pending_count(conn: sqlite3.Connection, domain: Optional[str] = None) -> int:
    if domain:
        row = conn.execute(
            "SELECT COUNT(*) FROM atomic_task_backlog WHERE status = 'PENDING' AND domain = ?",
            (domain,),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT COUNT(*) FROM atomic_task_backlog WHERE status = 'PENDING'"
        ).fetchone()
    return int(row[0])


# ------------------------------------------------------------- budget gate


class DailyBudgetGate:
    """24-hour DataForSEO spend bucket (stdlib SQLite; no extra deps).

    Caps ALL skill invocations on one machine to ``daily_cap`` Standard-Queue
    SERP tasks per UTC day ($0.0006 each -> a 100 cap is $0.06/day max).
    """

    def __init__(
        self, db_path: str = DEFAULT_DB_PATH, daily_cap: int = DEFAULT_DAILY_SERP_BUDGET
    ):
        self._conn = connect_state_db(db_path)
        self.daily_cap = daily_cap

    def _day(self, now: Optional[datetime]) -> str:
        return _utc_now(now).date().isoformat()

    def remaining(self, now: Optional[datetime] = None) -> int:
        row = self._conn.execute(
            "SELECT spent FROM dfs_budget WHERE day = ?", (self._day(now),)
        ).fetchone()
        return max(0, self.daily_cap - int(row[0] if row else 0))

    def record(self, n: int, now: Optional[datetime] = None) -> int:
        """Records n tasks; returns the remaining budget after the spend."""
        allowed = min(max(0, int(n)), self.remaining(now=now))
        if allowed:
            self._conn.execute(
                "INSERT INTO dfs_budget (day, spent) VALUES (?, ?) "
                "ON CONFLICT(day) DO UPDATE SET spent = spent + ?",
                (self._day(now), allowed, allowed),
            )
            self._conn.commit()
        return self.remaining(now=now)


# ------------------------------------------------------- URL Inspection state

INSPECTION_TTL_HOURS = 24 * 7  # coverage states are stable week-to-week
DEFAULT_DAILY_INSPECTION_BUDGET = 2000  # GSC free allowance per property/day


def save_url_inspections(
    conn: sqlite3.Connection,
    site: str,
    results: dict,
    now: Optional[datetime] = None,
) -> None:
    """Persists URL Inspection results keyed by URL (week-long TTL reads)."""
    stamp = _iso(_utc_now(now))
    for url, record in results.items():
        conn.execute(
            "INSERT OR REPLACE INTO url_inspections "
            "(url, site, coverage_state, indexing_state, last_crawl_time, inspected_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                str(url),
                str(site),
                record.get("coverage_state"),
                record.get("indexing_state"),
                record.get("last_crawl_time"),
                stamp,
            ),
        )
    conn.commit()


def load_url_inspections(
    conn: sqlite3.Connection,
    urls: list,
    max_age_hours: int = INSPECTION_TTL_HOURS,
    now: Optional[datetime] = None,
) -> dict:
    """Returns fresh (within TTL) inspection records for the requested URLs."""
    stamp = _utc_now(now)
    cutoff = stamp - timedelta(hours=max_age_hours)
    fresh: dict[str, dict[str, Any]] = {}
    for url in urls:
        row = conn.execute(
            "SELECT coverage_state, indexing_state, last_crawl_time, inspected_at "
            "FROM url_inspections WHERE url = ?",
            (str(url),),
        ).fetchone()
        if not row:
            continue
        try:
            inspected = datetime.fromisoformat(row[3])
        except ValueError:
            continue
        if inspected.tzinfo is None:
            inspected = inspected.replace(tzinfo=timezone.utc)
        if inspected >= cutoff:
            fresh[str(url)] = {
                "coverage_state": row[0],
                "indexing_state": row[1],
                "last_crawl_time": row[2],
            }
    return fresh


def inspection_calls_remaining(
    conn: sqlite3.Connection,
    daily_cap: int = DEFAULT_DAILY_INSPECTION_BUDGET,
    now: Optional[datetime] = None,
) -> int:
    """Free-tier guard: max 2,000 URL Inspection calls per UTC day."""
    day = _utc_now(now).date().isoformat()
    row = conn.execute(
        "SELECT spent FROM url_inspection_budget WHERE day = ?", (day,)
    ).fetchone()
    return max(0, daily_cap - int(row[0] if row else 0))


def record_inspection_calls(
    conn: sqlite3.Connection,
    n: int,
    daily_cap: int = DEFAULT_DAILY_INSPECTION_BUDGET,
    now: Optional[datetime] = None,
) -> int:
    """Records n inspection calls; returns the remaining budget."""
    day = _utc_now(now).date().isoformat()
    remaining = inspection_calls_remaining(conn, daily_cap=daily_cap, now=now)
    allowed = min(max(0, int(n)), remaining)
    if allowed:
        conn.execute(
            "INSERT INTO url_inspection_budget (day, spent) VALUES (?, ?) "
            "ON CONFLICT(day) DO UPDATE SET spent = spent + ?",
            (day, allowed, allowed),
        )
        conn.commit()
    return inspection_calls_remaining(conn, daily_cap=daily_cap, now=now)
