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
from urllib.parse import urlparse

DEFAULT_DB_DIR = Path.home() / ".seo_fleet"
DEFAULT_DB_PATH = str(DEFAULT_DB_DIR / "fleet_state.db")

GSC_SNAPSHOT_TTL_HOURS = 24
SERP_CACHE_TTL_DAYS = 30
# Wave-64: FLEET-WIDE daily cap across every property in the unified cursor
# DB (was 100 per per-domain DB before unification).
DEFAULT_DAILY_SERP_BUDGET = 150

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
    route_family    TEXT NOT NULL DEFAULT 'root',
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
    # WAL + busy timeout: 20-50 skill invocations may run concurrently on one
    # machine; readers must never block the lease-cursor writer, and contending
    # writers retry briefly instead of failing with "database is locked".
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.executescript(_SCHEMA)
    conn.commit()
    _migrate_schema(conn)
    return conn


def _migrate_schema(conn: sqlite3.Connection) -> None:
    """Safe additive migrations for state DBs created by older skill versions."""
    columns = {row[1] for row in conn.execute("PRAGMA table_info(atomic_task_backlog)")}
    if "route_family" not in columns:
        try:
            conn.execute(
                "ALTER TABLE atomic_task_backlog "
                "ADD COLUMN route_family TEXT NOT NULL DEFAULT 'root'"
            )
            conn.commit()
        except sqlite3.OperationalError:
            pass  # concurrent migration already applied it
    serp_columns = {row[1] for row in conn.execute("PRAGMA table_info(dfs_serp_cache)")}
    if "search_volume" not in serp_columns:
        try:
            conn.execute("ALTER TABLE dfs_serp_cache ADD COLUMN search_volume REAL")
            conn.commit()
        except sqlite3.OperationalError:
            pass  # concurrent migration already applied it
    # One-time backfill: legacy rows predate route tagging. Converges to a
    # no-op after the first successful pass (everything gets tagged).
    stale = conn.execute(
        "SELECT COUNT(*) FROM atomic_task_backlog WHERE route_family = 'root' "
        "AND page LIKE '%/%'"
    ).fetchone()[0]
    if stale:
        for task_id, page in conn.execute(
            "SELECT id, page FROM atomic_task_backlog WHERE route_family = 'root'"
        ):
            conn.execute(
                "UPDATE atomic_task_backlog SET route_family = ? WHERE id = ?",
                (extract_route_family(page), task_id),
            )
        conn.commit()
    # One-time backfill: legacy rows predate the domain column. Domain-scoped
    # leases and per-domain quotas depend on it; derive it from the page URL.
    stale_domains = conn.execute(
        "SELECT COUNT(*) FROM atomic_task_backlog "
        "WHERE (domain IS NULL OR domain = '') AND page LIKE 'http%'"
    ).fetchone()[0]
    if stale_domains:
        from urllib.parse import urlparse

        for task_id, page in conn.execute(
            "SELECT id, page FROM atomic_task_backlog "
            "WHERE (domain IS NULL OR domain = '') AND page LIKE 'http%'"
        ):
            host = (urlparse(str(page)).hostname or "").lower()
            parts = host.split(".")
            domain = ".".join(parts[-2:]) if len(parts) > 2 else host
            conn.execute(
                "UPDATE atomic_task_backlog SET domain = ? WHERE id = ?",
                (domain, task_id),
            )
        conn.commit()


def extract_route_family(url: str) -> str:
    """Normalizes '/number/12025550199/' -> 'number', '/guides/foo/' -> 'guides'.

    Root-level and query-param URLs fall back to the URL itself so each is
    its own family (never capped as a flood).
    """
    raw = str(url)
    path = urlparse(raw).path if "://" in raw else "/" + raw.strip("/")
    parts = [p for p in path.strip("/").split("/") if p]
    if not parts:
        return raw.rstrip("/") or "root"
    return parts[0].lower()


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


def queries_missing_volume(conn: sqlite3.Connection, limit: int = 1000) -> list:
    """Cache queries still without a Keywords-Data volume (surrogate starvation)."""
    rows = conn.execute(
        "SELECT query FROM dfs_serp_cache WHERE search_volume IS NULL "
        "AND items_json != '[]' LIMIT ?",
        (limit,),
    ).fetchall()
    return [row[0] for row in rows]


def save_serp_volumes(conn: sqlite3.Connection, volumes: dict) -> int:
    """Writes Keywords-Data volumes back into dfs_serp_cache (surrogate head)."""
    updated = 0
    for keyword, volume in (volumes or {}).items():
        if volume is None:
            continue
        for candidate in (str(keyword), str(keyword).strip().lower()):
            cur = conn.execute(
                "UPDATE dfs_serp_cache SET search_volume = ? WHERE query = ?",
                (float(volume), candidate),
            )
            updated += cur.rowcount
            if cur.rowcount:
                break
    conn.commit()
    return updated


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

# Wave-62 task-type quota split (per 30-task wave): every wave must carry a
# MIX of work products, not 30 identical heading checks. The inlink family
# shares the 8-slot slice across its two codes; the title/H2 intent family
# shares the 5-slot slice. Uncapped codes fall back to ``default_type_cap``.
DEFAULT_TYPE_CAPS = {
    "ADD_D1_SPEC_COMPARISON_TABLE": 8,
    "BOOST_CLUSTER_CROSS_LINKS": 4,
    "STRENGTHEN_HUB_INTERNAL_LINKS": 4,
    "OVERHAUL_CTR_HOOK_AND_WEBAPP_SCHEMA": 6,
    "INJECT_EXACT_TITLE_AND_H2": 3,
    "INJECT_EXACT_H2_AND_TITLE": 2,
    "CREATE_PROGRAMMATIC_ROUTE": 3,
}
DEFAULT_TYPE_CAP_FALLBACK = 3


def enqueue_tasks(
    conn: sqlite3.Connection,
    tasks: list,
    now: Optional[datetime] = None,
) -> int:
    """Appends tasks as PENDING; dedupes on (page, action_code) while open."""
    stamp = _iso(_utc_now(now))
    added = 0
    for task in tasks:
        page = str(task.get("page") or task.get("url") or "")
        domain = str(task.get("domain") or "")
        if not domain and page:
            from urllib.parse import urlparse

            host = (urlparse(page).hostname or "").lower()
            parts = host.split(".")
            domain = ".".join(parts[-2:]) if len(parts) > 2 else host
        try:
            action_code = str(
                task.get("action_code") or task.get("prescribed_action") or ""
            )
            # REJECTED is terminal (cursor hygiene): junk queries purged by
            # preflight_hygiene must never re-enter via the next compile wave.
            already_rejected = conn.execute(
                "SELECT 1 FROM atomic_task_backlog "
                "WHERE page = ? AND action_code = ? AND status = 'REJECTED'",
                (page, action_code),
            ).fetchone()
            if already_rejected:
                continue
            conn.execute(
                "INSERT INTO atomic_task_backlog "
                "(domain, page, query, action_code, target_component, file_target, "
                " tdd_assertion, lgbm_score, priority_score, route_family, status, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', ?)",
                (
                    domain,
                    page,
                    str(task.get("query") or ""),
                    action_code,
                    task.get("target_component"),
                    task.get("file_target"),
                    task.get("tdd_assertion"),
                    float(task.get("lgbm_score") or 0.0),
                    float(task.get("priority_score") or task.get("rank_score") or 0.0),
                    extract_route_family(page),
                    stamp,
                ),
            )
            added += 1
        except sqlite3.IntegrityError:
            continue  # same (page, action_code) already open -> idempotent
    conn.commit()
    return added


DEFAULT_STALE_LEASE_TTL_SECONDS = 3600


def release_stale_leases(
    conn: sqlite3.Connection,
    ttl_seconds: int = DEFAULT_STALE_LEASE_TTL_SECONDS,
    now: Optional[datetime] = None,
) -> int:
    """Returns crashed agents' uncommitted leases to the PENDING cursor.

    A terminal session that died mid-run must not orphan LEASED tasks forever:
    anything leased more than ``ttl_seconds`` ago (default 1 hour) flips back
    to PENDING so the next invocation can lease it again.
    """
    cutoff = _utc_now(now) - timedelta(seconds=ttl_seconds)
    cursor = conn.execute(
        "UPDATE atomic_task_backlog SET status = 'PENDING', leased_at = NULL "
        "WHERE status = 'LEASED' AND leased_at IS NOT NULL AND leased_at < ?",
        (_iso(cutoff),),
    )
    conn.commit()
    return cursor.rowcount


def lease_tasks(
    conn: sqlite3.Connection,
    domain: Optional[str] = None,
    limit: int = 35,
    now: Optional[datetime] = None,
    family_caps: Optional[dict] = None,
    default_family_cap: int = 0,
    type_caps: Optional[dict] = None,
    default_type_cap: int = 0,
) -> list:
    """Atomically pops the next PENDING tasks (priority DESC) as LEASED.

    Runs `release_stale_leases` first, then performs the cursor flip in ONE
    UPDATE ... RETURNING statement, so two concurrent invocations can never
    lease the same task. REVERTED tasks never re-enter.

    Diversity controls for high-frequency fleets:
    - ``family_caps`` / ``default_family_cap``: per-wave caps on tasks from
      one route family (ROW_NUMBER partition), so a deep /number/* backlog
      cannot make every wave identical.
    - ``type_caps`` / ``default_type_cap``: per-wave caps on tasks of one
      ACTION CODE (second ROW_NUMBER partition), so a wave carries a mix of
      D1 tables, inlinks, CTR hooks and route builds instead of 30 identical
      heading checks. ``DEFAULT_TYPE_CAPS`` encodes the wave-62 quota split
      (8x D1 tables, 8x inlinks, 6x CTR hooks, 5x title/H2 intents,
      3x programmatic routes). Uncapped codes ride ``default_type_cap``
      (0 = unlimited when ``type_caps`` is None, i.e. back-compat).
      Wave-64 two-tier backfill: type caps are QUOTA PREFERENCES, not hard
      exclusions. Rows within their cap rank as quota_pass 0; rows beyond it
      rank as quota_pass 1 and still fill the wave when the quota tiers
      alone cannot reach ``limit`` (empty buckets backfill from the
      highest-scoring remaining rows). Final order:
      ``quota_pass ASC, priority_score DESC``.
    - file-target locks: a wave never leases a PENDING task whose
      ``file_target`` is already held by an ACTIVE lease in another agent
      worktree (NULL/empty file targets are exempt - legacy tasks and
      page-level fixes don't collide). This prevents same-file merge
      collisions across parallel waves.
    """
    release_stale_leases(conn, now=now)
    stamp = _iso(_utc_now(now))
    domain_filter = "AND domain = ?" if domain else ""
    family_filters = []
    family_params: list = []
    caps = dict(family_caps or {})
    if caps or default_family_cap > 0:
        for family in sorted(caps):
            family_filters.append("(route_family = ? AND family_rank <= ?)")
            family_params.extend([family, caps[family]])
        family_filters.append(
            f"(route_family NOT IN ({', '.join('?' * len(caps)) or "''"}) "
            f"AND family_rank <= ?)"
        )
        family_params.extend([*caps.keys(), default_family_cap])
    # Wave-64 two-tier quotas: rows within their type cap rank quota_pass 0
    # (preferred); rows beyond it rank quota_pass 1 (backfill). Both tiers
    # are leasable; preference ordering picks tier 0 first.
    tcaps = dict(type_caps or {})
    quota_params: list = []
    if tcaps or default_type_cap > 0:
        case_parts = []
        for code in sorted(tcaps):
            case_parts.append("(action_code = ? AND type_rank <= ?)")
            quota_params.extend([code, tcaps[code]])
        if default_type_cap > 0:
            case_parts.append(
                f"(action_code NOT IN ({', '.join('?' * len(tcaps)) or "''"}) "
                f"AND type_rank <= ?)"
            )
            quota_params.extend([*tcaps.keys(), default_type_cap])
        quota_case = "CASE WHEN " + " OR ".join(case_parts) + " THEN 0 ELSE 1 END"
    else:
        quota_case = "0"
    family_where = " OR ".join(family_filters) if family_filters else "1 = 1"
    select_sql = (
        "WITH ranked_pending AS ("
        "  SELECT id, route_family, action_code, priority_score, file_target,"
        "         ROW_NUMBER() OVER ("
        "             PARTITION BY route_family ORDER BY priority_score DESC"
        "         ) AS family_rank,"
        "         ROW_NUMBER() OVER ("
        "             PARTITION BY action_code ORDER BY priority_score DESC"
        "         ) AS type_rank"
        "  FROM atomic_task_backlog"
        f"  WHERE status = 'PENDING' {domain_filter}"
        "), pass_tagged AS ("
        "  SELECT id, priority_score, " + quota_case + " AS quota_pass"
        "  FROM ranked_pending"
        f"  WHERE ({family_where})"
        "    AND (file_target IS NULL OR file_target = '' OR file_target NOT IN ("
        "        SELECT DISTINCT bt.file_target FROM atomic_task_backlog bt"
        "        WHERE bt.status = 'LEASED' AND bt.file_target IS NOT NULL "
        "          AND bt.file_target != ''"
        "    ))"
        ") "
        "SELECT id, priority_score FROM pass_tagged"
        " ORDER BY quota_pass ASC, priority_score DESC LIMIT ?"
    )
    cursor = conn.execute(
        select_sql,
        # Placeholder order: domain filter (ranked_pending) -> quota CASE
        # (pass_tagged SELECT list) -> family-cap filters (pass_tagged WHERE)
        # -> LIMIT.
        (*([domain] if domain else []), *quota_params, *family_params, limit),
    )
    wave_ids = [row[0] for row in cursor.fetchall()]
    if not wave_ids:
        conn.commit()
        return []
    # Flip exactly the selected rows; the status='PENDING' guard makes a
    # concurrent lease of the same rows a no-op instead of a double-lease.
    update_sql = (
        "UPDATE atomic_task_backlog SET status = 'LEASED', leased_at = ? "
        f"WHERE id IN ({', '.join('?' * len(wave_ids))}) AND status = 'PENDING' "
        "RETURNING id, domain, page, query, action_code, target_component, "
        "file_target, tdd_assertion, lgbm_score, priority_score, route_family"
    )
    cursor = conn.execute(update_sql, (stamp, *wave_ids))
    leased = [
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
            "route_family": row[10],
            "status": "LEASED",
        }
        for row in cursor.fetchall()
    ]
    # Wave order is the selection order: quota_pass tier 0 (within type
    # caps) first, then tier-1 backfill, each priority DESC. Do NOT re-sort
    # by priority alone - that would destroy the tier preference.
    leased_by_id = {t["id"]: t for t in leased}
    leased = [leased_by_id[i] for i in wave_ids if i in leased_by_id]
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


def mark_tasks_reverted(
    conn: sqlite3.Connection,
    task_ids: list,
    now: Optional[datetime] = None,
) -> int:
    """Records terminal reverts (SHIPPED -> REVERTED, LEASED -> REVERTED).

    REVERTED is terminal: the wave's change was rolled back (Stage 4
    negative-delta detector) OR the executing agent adjudicated the leased
    task unfit before implementing it (parameterized pseudo-pages, typo
    queries, intent-registry violations) — either way the task must NOT
    re-enter the lease cursor and thrash the same page. The commit_sha
    audit trail is preserved; the JSONL cooldown ledger governs whether the
    (page, action) can be re-prescribed later through a fresh scoring run.
    """
    stamp = _iso(_utc_now(now))
    reverted = 0
    for task_id in task_ids:
        cur = conn.execute(
            "UPDATE atomic_task_backlog SET status = 'REVERTED', shipped_at = ? "
            "WHERE id = ? AND status IN ('SHIPPED', 'LEASED')",
            (stamp, task_id),
        )
        reverted += cur.rowcount
    conn.commit()
    return reverted


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
