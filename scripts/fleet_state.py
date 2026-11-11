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
from typing import Any
from urllib.parse import urlparse

from candidate_hygiene import CANONICAL_ACTION_CODE_MAP, canonicalize_action_code

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
CREATE TABLE IF NOT EXISTS dfs_budget_domain (
    day         TEXT NOT NULL,
    domain      TEXT NOT NULL,
    spent       INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (day, domain)
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
CREATE TABLE IF NOT EXISTS experiment_ledger (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id                 INTEGER,
    domain                  TEXT NOT NULL,
    page                    TEXT NOT NULL,
    target_query            TEXT NOT NULL,
    query_cluster           TEXT,
    action_code             TEXT NOT NULL,
    decision_class          TEXT NOT NULL DEFAULT 'SHIP',
    implementation_details  TEXT,
    commit_sha              TEXT,
    deployed_at             TEXT NOT NULL,
    baseline_clicks_28d     REAL NOT NULL DEFAULT 0.0,
    baseline_impressions_28d REAL NOT NULL DEFAULT 0.0,
    baseline_ctr            REAL NOT NULL DEFAULT 0.0,
    baseline_position       REAL NOT NULL DEFAULT 0.0,
    recrawl_detected_at     TEXT,
    indexation_status       TEXT DEFAULT 'UNKNOWN',
    post_7d_clicks          REAL,
    post_7d_impressions     REAL,
    post_7d_position        REAL,
    post_7d_ctr             REAL,
    post_14d_clicks         REAL,
    post_14d_impressions    REAL,
    post_14d_position       REAL,
    post_14d_ctr            REAL,
    post_28d_clicks         REAL,
    post_28d_impressions    REAL,
    post_28d_position       REAL,
    post_28d_ctr            REAL,
    post_56d_clicks         REAL,
    post_56d_impressions    REAL,
    post_56d_position       REAL,
    post_56d_ctr            REAL,
    conversions_baseline    REAL DEFAULT 0.0,
    conversions_post        REAL,
    control_cohort_page     TEXT,
    control_baseline_clicks REAL DEFAULT 0.0,
    control_post_clicks     REAL,
    incremental_clicks_est  REAL,
    incremental_impressions_est REAL,
    attribution_confidence  REAL DEFAULT 0.0,
    attribution_limitations TEXT,
    status                  TEXT NOT NULL DEFAULT 'PENDING_RECRAWL',
    updated_at              TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS experiment_domain_status
    ON experiment_ledger (domain, status);
CREATE INDEX IF NOT EXISTS experiment_page
    ON experiment_ledger (page);
CREATE TABLE IF NOT EXISTS query_ownership_map (
    domain                  TEXT NOT NULL,
    query_cluster           TEXT NOT NULL,
    canonical_url           TEXT NOT NULL,
    primary_query           TEXT NOT NULL,
    secondary_queries_json  TEXT NOT NULL DEFAULT '[]',
    intent_category         TEXT NOT NULL DEFAULT 'informational',
    created_at              TEXT NOT NULL,
    updated_at              TEXT NOT NULL,
    PRIMARY KEY (domain, query_cluster)
);
CREATE INDEX IF NOT EXISTS query_ownership_url
    ON query_ownership_map (domain, canonical_url);
CREATE TABLE IF NOT EXISTS action_effectiveness_stats (
    domain                  TEXT NOT NULL,
    action_code             TEXT NOT NULL,
    route_family            TEXT NOT NULL DEFAULT 'root',
    total_experiments       INTEGER NOT NULL DEFAULT 0,
    successful_experiments  INTEGER NOT NULL DEFAULT 0,
    avg_click_lift          REAL NOT NULL DEFAULT 0.0,
    avg_impression_lift     REAL NOT NULL DEFAULT 0.0,
    avg_rank_delta          REAL NOT NULL DEFAULT 0.0,
    updated_at              TEXT NOT NULL,
    PRIMARY KEY (domain, action_code, route_family)
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
            conn.execute("ALTER TABLE atomic_task_backlog ADD COLUMN route_family TEXT NOT NULL DEFAULT 'root'")
            conn.commit()
        except sqlite3.OperationalError:
            pass  # concurrent migration already applied it
    if "decision_class" not in columns:
        try:
            conn.execute("ALTER TABLE atomic_task_backlog ADD COLUMN decision_class TEXT NOT NULL DEFAULT 'SHIP'")
            conn.commit()
        except sqlite3.OperationalError:
            pass
    if "expected_value" not in columns:
        try:
            conn.execute("ALTER TABLE atomic_task_backlog ADD COLUMN expected_value REAL NOT NULL DEFAULT 0.0")
            conn.commit()
        except sqlite3.OperationalError:
            pass
    if "cannibalization_risk" not in columns:
        try:
            conn.execute("ALTER TABLE atomic_task_backlog ADD COLUMN cannibalization_risk REAL NOT NULL DEFAULT 0.0")
            conn.commit()
        except sqlite3.OperationalError:
            pass
    if "confidence" not in columns:
        try:
            conn.execute("ALTER TABLE atomic_task_backlog ADD COLUMN confidence REAL NOT NULL DEFAULT 1.0")
            conn.commit()
        except sqlite3.OperationalError:
            pass
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
        "SELECT COUNT(*) FROM atomic_task_backlog WHERE route_family = 'root' AND page LIKE '%/%'"
    ).fetchone()[0]
    if stale:
        for task_id, page in conn.execute("SELECT id, page FROM atomic_task_backlog WHERE route_family = 'root'"):
            conn.execute(
                "UPDATE atomic_task_backlog SET route_family = ? WHERE id = ?",
                (extract_route_family(page), task_id),
            )
        conn.commit()
    # One-time backfill: legacy rows predate the domain column. Domain-scoped
    # leases and per-domain quotas depend on it; derive it from the page URL.
    stale_domains = conn.execute(
        "SELECT COUNT(*) FROM atomic_task_backlog WHERE (domain IS NULL OR domain = '') AND page LIKE 'http%'"
    ).fetchone()[0]
    if stale_domains:
        from urllib.parse import urlparse

        for task_id, page in conn.execute(
            "SELECT id, page FROM atomic_task_backlog WHERE (domain IS NULL OR domain = '') AND page LIKE 'http%'"
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


def _utc_now(now: datetime | None) -> datetime:
    return now or datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


# ------------------------------------------------------------------ snapshots


def save_gsc_snapshot(
    conn: sqlite3.Connection,
    site: str,
    rows: list,
    now: datetime | None = None,
    window_end: str | None = None,
) -> None:
    stamp = _utc_now(now)
    conn.execute(
        "INSERT OR REPLACE INTO gsc_snapshots (site, window_end, fetched_at, rows_json) VALUES (?, ?, ?, ?)",
        (site, window_end or stamp.date().isoformat(), _iso(stamp), json.dumps(rows)),
    )
    conn.commit()


def gsc_snapshot_fresh(
    conn: sqlite3.Connection,
    site: str,
    max_age_hours: int = GSC_SNAPSHOT_TTL_HOURS,
    now: datetime | None = None,
) -> bool:
    stamp = _utc_now(now)
    cutoff = stamp - timedelta(hours=max_age_hours)
    row = conn.execute(
        "SELECT fetched_at FROM gsc_snapshots WHERE site = ? ORDER BY fetched_at DESC LIMIT 1",
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
    now: datetime | None = None,
) -> list | None:
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
    now: datetime | None = None,
) -> None:
    stamp = _utc_now(now)
    conn.execute(
        "INSERT OR REPLACE INTO dfs_serp_cache (query, fetched_at, items_json, item_types) VALUES (?, ?, ?, ?)",
        (query, _iso(stamp), json.dumps(items), json.dumps(item_types)),
    )
    conn.commit()


def queries_missing_volume(conn: sqlite3.Connection, limit: int = 1000) -> list:
    """Cache queries still without a Keywords-Data volume (surrogate starvation)."""
    rows = conn.execute(
        "SELECT query FROM dfs_serp_cache WHERE search_volume IS NULL AND items_json != '[]' LIMIT ?",
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
    now: datetime | None = None,
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

# Wave-62 / Wave-65 task-type quota split: every wave must carry a MIX of
# work products, not 30 identical heading checks. Canonical action taxonomy
# prevents synonym codes from leaking across PARTITION BY action_code windows.
DEFAULT_TYPE_CAPS = {
    "ADD_D1_SPEC_COMPARISON_TABLE": 8,
    "WIRE_HUB_AND_FOOTER_INLINKS": 8,
    "OVERHAUL_CTR_HOOK_AND_WEBAPP_SCHEMA": 6,
    "INJECT_EXACT_TITLE_AND_H2": 3,
    "INJECT_EXACT_H2_AND_TITLE": 2,
    "CREATE_PROGRAMMATIC_ROUTE": 3,
    "INJECT_SECONDARY_H2_ONLY": 4,
    # Backward compatibility aliases:
    "BOOST_CLUSTER_CROSS_LINKS": 4,
    "STRENGTHEN_HUB_INTERNAL_LINKS": 4,
}
DEFAULT_TYPE_CAP_FALLBACK = 3


def canonicalize_backlog_action_codes(conn: sqlite3.Connection) -> int:
    """Normalizes legacy action codes in atomic_task_backlog to canonical names.

    Merges duplicate open tasks for the same page that arose from legacy synonym codes:
    - INJECT_EXACT_H2_AND_TITLE -> INJECT_EXACT_TITLE_AND_H2
    - LAUNCH_PSEO_ROUTE -> CREATE_PROGRAMMATIC_ROUTE
    - STRENGTHEN_HUB_INTERNAL_LINKS / BOOST_INTERNAL_LINKS / RESCUE_ORPHAN_ROUTE_INLINKS / BOOST_CLUSTER_CROSS_LINKS -> WIRE_HUB_AND_FOOTER_INLINKS
    """
    cur = conn.cursor()
    rows = cur.execute("SELECT id, page, action_code, status, priority_score FROM atomic_task_backlog").fetchall()

    modified = 0
    for task_id, page, action_code, status, score in rows:
        target_code = CANONICAL_ACTION_CODE_MAP.get(action_code)
        if not target_code:
            continue

        if status in ("PENDING", "LEASED"):
            existing = cur.execute(
                "SELECT id, status, priority_score FROM atomic_task_backlog "
                "WHERE page = ? AND action_code = ? AND status IN ('PENDING', 'LEASED') AND id != ?",
                (page, target_code, task_id),
            ).fetchone()

            if existing:
                exist_id, exist_status, exist_score = existing
                if (exist_status == "LEASED" and status == "PENDING") or (
                    exist_status == status and exist_score >= score
                ):
                    cur.execute("DELETE FROM atomic_task_backlog WHERE id = ?", (task_id,))
                    modified += 1
                    continue
                else:
                    cur.execute("DELETE FROM atomic_task_backlog WHERE id = ?", (exist_id,))
                    cur.execute(
                        "UPDATE atomic_task_backlog SET action_code = ? WHERE id = ?",
                        (target_code, task_id),
                    )
                    modified += 1
                    continue

        cur.execute(
            "UPDATE atomic_task_backlog SET action_code = ? WHERE id = ?",
            (target_code, task_id),
        )
        modified += 1

    conn.commit()
    return modified


def enqueue_tasks(
    conn: sqlite3.Connection,
    tasks: list,
    now: datetime | None = None,
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
        if domain and page and page.startswith("http"):
            from candidate_hygiene import is_valid_property_host

            if not is_valid_property_host(page, domain):
                continue
        try:
            raw_action = str(task.get("action_code") or task.get("prescribed_action") or "")
            action_code = canonicalize_action_code(raw_action)
            # REJECTED is terminal (cursor hygiene): junk queries purged by
            # preflight_hygiene must never re-enter via the next compile wave.
            already_rejected = conn.execute(
                "SELECT 1 FROM atomic_task_backlog WHERE page = ? AND action_code = ? AND status = 'REJECTED'",
                (page, action_code),
            ).fetchone()
            if already_rejected:
                continue
            dec_class = str(task.get("decision_class") or "SHIP").upper()
            ev = float(task.get("expected_value") or task.get("ev") or 0.0)
            cann_risk = float(task.get("cannibalization_risk") or 0.0)
            conf = float(task.get("confidence") or 1.0)
            conn.execute(
                "INSERT INTO atomic_task_backlog "
                "(domain, page, query, action_code, target_component, file_target, "
                " tdd_assertion, lgbm_score, priority_score, route_family, "
                " decision_class, expected_value, cannibalization_risk, confidence, status, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', ?)",
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
                    dec_class,
                    ev,
                    cann_risk,
                    conf,
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
    now: datetime | None = None,
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
    domain: str | None = None,
    limit: int = 35,
    now: datetime | None = None,
    family_caps: dict | None = None,
    default_family_cap: int = 0,
    type_caps: dict | None = None,
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
    canonicalize_backlog_action_codes(conn)
    stamp = _iso(_utc_now(now))
    domain_filter = "AND domain = ?" if domain else ""
    family_filters = []
    family_params: list = []
    caps = dict(family_caps or {})
    if caps or default_family_cap > 0:
        for family in sorted(caps):
            family_filters.append("(route_family = ? AND family_rank <= ?)")
            family_params.extend([family, caps[family]])
        family_filters.append(f"(route_family NOT IN ({', '.join('?' * len(caps)) or "''"}) AND family_rank <= ?)")
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
            case_parts.append(f"(action_code NOT IN ({', '.join('?' * len(tcaps)) or "''"}) AND type_rank <= ?)")
            quota_params.extend([*tcaps.keys(), default_type_cap])
        quota_case = "CASE WHEN " + " OR ".join(case_parts) + " THEN 0 ELSE 1 END"
    else:
        quota_case = "0"
    family_where = " OR ".join(family_filters) if family_filters else "1 = 1"
    select_sql = (
        "WITH ranked_pending AS ("
        "  SELECT id, route_family, action_code, priority_score, file_target, page,"
        "         ROW_NUMBER() OVER ("
        "             PARTITION BY route_family ORDER BY priority_score DESC"
        "         ) AS family_rank,"
        "         ROW_NUMBER() OVER ("
        "             PARTITION BY action_code ORDER BY priority_score DESC"
        "         ) AS type_rank,"
        "         ROW_NUMBER() OVER ("
        "             PARTITION BY page ORDER BY priority_score DESC"
        "         ) AS page_rank"
        "  FROM atomic_task_backlog"
        f"  WHERE status = 'PENDING' {domain_filter}"
        "), pass_tagged AS ("
        "  SELECT id, priority_score, " + quota_case + " AS quota_pass"
        "  FROM ranked_pending"
        f"  WHERE ({family_where})"
        "    AND page_rank = 1"
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
        "file_target, tdd_assertion, lgbm_score, priority_score, route_family, "
        "decision_class, expected_value, cannibalization_risk, confidence"
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
            "decision_class": row[11] if len(row) > 11 else "SHIP",
            "expected_value": row[12] if len(row) > 12 else 0.0,
            "cannibalization_risk": row[13] if len(row) > 13 else 0.0,
            "confidence": row[14] if len(row) > 14 else 1.0,
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
    commit_sha: str | None = None,
    now: datetime | None = None,
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
    now: datetime | None = None,
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


def pending_count(conn: sqlite3.Connection, domain: str | None = None) -> int:
    if domain:
        row = conn.execute(
            "SELECT COUNT(*) FROM atomic_task_backlog WHERE status = 'PENDING' AND domain = ?",
            (domain,),
        ).fetchone()
    else:
        row = conn.execute("SELECT COUNT(*) FROM atomic_task_backlog WHERE status = 'PENDING'").fetchone()
    return int(row[0])


# ------------------------------------------------------------- Outcome Engine v2: Experiment Ledger & Evaluation


def record_experiment(
    conn: sqlite3.Connection,
    *,
    task_id: int | None = None,
    domain: str,
    page: str,
    target_query: str,
    action_code: str,
    decision_class: str = "SHIP",
    implementation_details: str | None = None,
    commit_sha: str | None = None,
    deployed_at: datetime | None = None,
    baseline_clicks_28d: float = 0.0,
    baseline_impressions_28d: float = 0.0,
    baseline_ctr: float = 0.0,
    baseline_position: float = 0.0,
    control_cohort_page: str | None = None,
    control_baseline_clicks: float = 0.0,
    attribution_limitations: str | None = None,
) -> int:
    """Records an executed SEO change into the persistent experiment ledger."""
    now_str = _iso(_utc_now(deployed_at))
    cur = conn.execute(
        """
        INSERT INTO experiment_ledger (
            task_id, domain, page, target_query, query_cluster, action_code,
            decision_class, implementation_details, commit_sha, deployed_at,
            baseline_clicks_28d, baseline_impressions_28d, baseline_ctr, baseline_position,
            control_cohort_page, control_baseline_clicks, attribution_limitations,
            status, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING_RECRAWL', ?)
        """,
        (
            task_id,
            domain,
            page,
            target_query,
            target_query.lower().strip(),
            action_code,
            decision_class,
            implementation_details,
            commit_sha,
            now_str,
            float(baseline_clicks_28d),
            float(baseline_impressions_28d),
            float(baseline_ctr),
            float(baseline_position),
            control_cohort_page,
            float(control_baseline_clicks),
            attribution_limitations,
            now_str,
        ),
    )
    conn.commit()
    return int(cur.lastrowid)


def record_shipped_experiments(
    conn: sqlite3.Connection,
    task_ids: list[int],
    commit_sha: str | None = None,
    baseline_gsc: dict[str, dict[str, Any]] | None = None,
    control_pages: dict[str, str] | None = None,
    now: datetime | None = None,
) -> int:
    """Auto-enqueues experiment rows for tasks being marked SHIPPED.

    Matches baseline metrics from baseline_gsc or gsc_snapshots if available,
    and assigns a matched control page from the same domain/route family.
    """
    now_dt = _utc_now(now)
    recorded = 0
    for tid in task_ids:
        row = conn.execute(
            """
            SELECT id, domain, page, query, action_code, route_family
            FROM atomic_task_backlog WHERE id = ?
            """,
            (tid,),
        ).fetchone()
        if not row:
            continue
        _id, domain, page, query, action_code, route_family = row

        base_clicks = 0.0
        base_impr = 0.0
        base_ctr = 0.0
        base_pos = 0.0
        if baseline_gsc:
            key = f"{query.strip().lower()}\n{page.strip().lower()}"
            gsc_row = baseline_gsc.get(key)
            if gsc_row:
                base_clicks = float(gsc_row.get("clicks", 0.0) or 0.0)
                base_impr = float(gsc_row.get("impressions", 0.0) or 0.0)
                base_ctr = float(gsc_row.get("ctr", 0.0) or 0.0)
                base_pos = float(gsc_row.get("position", 0.0) or 0.0)

        ctrl_page = None
        if control_pages and page in control_pages:
            ctrl_page = control_pages[page]
        elif domain:
            ctrl_candidate = conn.execute(
                """
                SELECT DISTINCT page FROM atomic_task_backlog
                WHERE domain = ? AND page != ? AND route_family = ? AND status = 'SHIPPED'
                LIMIT 1
                """,
                (domain, page, route_family),
            ).fetchone()
            if ctrl_candidate:
                ctrl_page = ctrl_candidate[0]

        record_experiment(
            conn,
            task_id=_id,
            domain=domain,
            page=page,
            target_query=query,
            action_code=action_code,
            commit_sha=commit_sha,
            deployed_at=now_dt,
            baseline_clicks_28d=base_clicks,
            baseline_impressions_28d=base_impr,
            baseline_ctr=base_ctr,
            baseline_position=base_pos,
            control_cohort_page=ctrl_page,
        )
        recorded += 1
    return recorded


def update_experiment_recrawl(
    conn: sqlite3.Connection,
    domain: str,
    recrawled_pages: set[str],
    now: datetime | None = None,
) -> int:
    """Updates recrawl status for experiments whose target pages show recrawl evidence."""
    now_str = _iso(_utc_now(now))
    updated = 0
    for page in recrawled_pages:
        cur = conn.execute(
            """
            UPDATE experiment_ledger
            SET recrawl_detected_at = ?,
                indexation_status = 'INDEXED',
                status = CASE WHEN status = 'PENDING_RECRAWL' THEN 'OBSERVING' ELSE status END,
                updated_at = ?
            WHERE domain = ? AND page = ? AND recrawl_detected_at IS NULL
            """,
            (now_str, now_str, domain, page),
        )
        updated += cur.rowcount
    conn.commit()
    return updated


def update_experiment_outcomes(
    conn: sqlite3.Connection,
    domain: str,
    fresh_gsc_rows: dict[str, dict[str, Any]],
    days_elapsed: int = 28,
    now: datetime | None = None,
) -> dict[str, int]:
    """Evaluates pending experiments with post-deployment GSC metrics and Difference-in-Differences.

    Computes:
    - Treatment lift against baseline
    - Matched control cohort lift
    - Net incremental clicks
    - Updates action_effectiveness_stats
    """
    now_dt = _utc_now(now)
    now_str = _iso(now_dt)
    graded_count = 0
    observing_count = 0

    # Read pending and observing experiments for this domain
    cur = conn.execute(
        """
        SELECT experiment_ledger.id, experiment_ledger.page, experiment_ledger.target_query,
               experiment_ledger.action_code,
               COALESCE(atomic_task_backlog.route_family, 'root') AS route_family,
               experiment_ledger.deployed_at,
               experiment_ledger.baseline_clicks_28d, experiment_ledger.baseline_impressions_28d,
               experiment_ledger.baseline_position, experiment_ledger.baseline_ctr,
               experiment_ledger.control_cohort_page, experiment_ledger.control_baseline_clicks,
               experiment_ledger.status
        FROM experiment_ledger
        LEFT JOIN atomic_task_backlog ON experiment_ledger.task_id = atomic_task_backlog.id
        WHERE experiment_ledger.domain = ? AND experiment_ledger.status IN ('PENDING_RECRAWL', 'OBSERVING')
        """,
        (domain,),
    )
    experiments = cur.fetchall()

    for exp in experiments:
        (
            exp_id, page, query, action_code, route_family, deployed_at_str,
            base_clicks, base_impr, base_pos, base_ctr,
            ctrl_page, ctrl_base_clicks, status
        ) = exp

        # Calculate actual days elapsed since deployment
        try:
            dep_dt = datetime.fromisoformat(deployed_at_str)
            actual_days = max(1, (now_dt - dep_dt).days)
        except Exception:
            actual_days = days_elapsed

        # Match fresh GSC data
        key = f"{query.strip().lower()}\n{page.strip().lower()}"
        post_gsc = fresh_gsc_rows.get(key)

        # Fallback to page-level aggregate if query is not broken down
        if not post_gsc:
            page_matches = [
                v for k, v in fresh_gsc_rows.items()
                if v.get("page", "").strip().lower() == page.strip().lower()
            ]
            if page_matches:
                post_gsc = {
                    "clicks": sum(float(m.get("clicks", 0.0) or 0.0) for m in page_matches),
                    "impressions": sum(float(m.get("impressions", 0.0) or 0.0) for m in page_matches),
                    "position": (
                        sum(float(m.get("position", 0.0) or 0.0) * float(m.get("impressions", 0.0) or 1.0) for m in page_matches)
                        / max(sum(float(m.get("impressions", 0.0) or 1.0) for m in page_matches), 1.0)
                    ),
                    "ctr": sum(float(m.get("clicks", 0.0) or 0.0) for m in page_matches) / max(sum(float(m.get("impressions", 0.0) or 1.0) for m in page_matches), 1.0),
                }

        if not post_gsc:
            continue

        p_clicks = float(post_gsc.get("clicks", 0.0) or 0.0)
        p_impr = float(post_gsc.get("impressions", 0.0) or 0.0)
        p_pos = float(post_gsc.get("position", 0.0) or 0.0)
        p_ctr = float(post_gsc.get("ctr", 0.0) or (p_clicks / max(p_impr, 1.0)))

        # Control cohort performance
        ctrl_p_clicks = ctrl_base_clicks
        if ctrl_page:
            ctrl_matches = [
                v for k, v in fresh_gsc_rows.items()
                if v.get("page", "").strip().lower() == ctrl_page.strip().lower()
            ]
            if ctrl_matches:
                ctrl_p_clicks = sum(float(m.get("clicks", 0.0) or 0.0) for m in ctrl_matches)

        # Difference-in-Differences calculation
        treatment_lift = (p_clicks - base_clicks) / max(base_clicks, 1.0)
        control_lift = (ctrl_p_clicks - ctrl_base_clicks) / max(ctrl_base_clicks, 1.0)
        net_lift = treatment_lift - control_lift
        inc_clicks = max(0.0, p_clicks - (base_clicks * (1.0 + max(-0.9, control_lift))))
        inc_impr = max(0.0, p_impr - base_impr)

        # Attribution confidence
        # Requires: recrawl detected, minimum baseline impressions, >= 14 days
        conf = 0.50
        if p_impr >= 50:
            conf += 0.20
        if actual_days >= 28:
            conf += 0.20
        if ctrl_page and ctrl_base_clicks > 0:
            conf += 0.10
        conf = min(1.0, conf)

        # Determine target interval column to populate
        col_prefix = "post_28d"
        if actual_days < 10:
            col_prefix = "post_7d"
        elif actual_days < 20:
            col_prefix = "post_14d"
        elif actual_days >= 45:
            col_prefix = "post_56d"

        new_status = "OBSERVING"
        if actual_days >= 28 and p_impr > 0:
            new_status = "GRADED"
            graded_count += 1
            # Feed into adaptive action effectiveness
            is_success = net_lift > 0.05 or inc_clicks > 1.0 or (p_pos < base_pos and base_pos > 0)
            record_action_effectiveness(
                conn,
                domain=domain,
                action_code=action_code,
                route_family=route_family or "root",
                is_success=is_success,
                click_lift=net_lift,
                impression_lift=(p_impr - base_impr) / max(base_impr, 1.0),
                rank_delta=(base_pos - p_pos),
                now=now_dt,
            )
        else:
            observing_count += 1

        conn.execute(
            f"""
            UPDATE experiment_ledger
            SET {col_prefix}_clicks = ?,
                {col_prefix}_impressions = ?,
                {col_prefix}_position = ?,
                {col_prefix}_ctr = ?,
                control_post_clicks = ?,
                incremental_clicks_est = ?,
                incremental_impressions_est = ?,
                attribution_confidence = ?,
                status = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                p_clicks, p_impr, p_pos, p_ctr,
                ctrl_p_clicks, inc_clicks, inc_impr, conf,
                new_status, now_str, exp_id,
            ),
        )

    conn.commit()
    return {"graded": graded_count, "observing": observing_count}


def get_experiment_summary(conn: sqlite3.Connection, domain: str) -> dict[str, Any]:
    """Generates an honest outcome summary: separates verified outcomes from pending ones."""
    total = conn.execute(
        "SELECT COUNT(*) FROM experiment_ledger WHERE domain = ?", (domain,)
    ).fetchone()[0]
    pending = conn.execute(
        "SELECT COUNT(*) FROM experiment_ledger WHERE domain = ? AND status = 'PENDING_RECRAWL'", (domain,)
    ).fetchone()[0]
    observing = conn.execute(
        "SELECT COUNT(*) FROM experiment_ledger WHERE domain = ? AND status = 'OBSERVING'", (domain,)
    ).fetchone()[0]
    graded = conn.execute(
        "SELECT COUNT(*) FROM experiment_ledger WHERE domain = ? AND status = 'GRADED'", (domain,)
    ).fetchone()[0]

    graded_stats = conn.execute(
        """
        SELECT SUM(incremental_clicks_est), SUM(incremental_impressions_est),
               AVG(attribution_confidence)
        FROM experiment_ledger
        WHERE domain = ? AND status = 'GRADED'
        """,
        (domain,),
    ).fetchone()

    total_inc_clicks = float(graded_stats[0] or 0.0)
    total_inc_impr = float(graded_stats[1] or 0.0)
    avg_conf = float(graded_stats[2] or 0.0)

    return {
        "domain": domain,
        "total_experiments": total,
        "pending_recrawl": pending,
        "observing": observing,
        "graded": graded,
        "total_incremental_clicks": total_inc_clicks,
        "total_incremental_impressions": total_inc_impr,
        "avg_confidence": avg_conf,
        "has_measured_outcomes": graded > 0,
    }


# ------------------------------------------------------------- Query Ownership & Cannibalization Prevention


def upsert_query_ownership(
    conn: sqlite3.Connection,
    *,
    domain: str,
    query_cluster: str,
    canonical_url: str,
    primary_query: str,
    secondary_queries: list[str] | None = None,
    intent_category: str = "tool",
    now: datetime | None = None,
) -> None:
    now_str = _iso(_utc_now(now))
    sec_json = json.dumps(sorted(set(secondary_queries or [])))
    conn.execute(
        """
        INSERT INTO query_ownership_map (
            domain, query_cluster, canonical_url, primary_query,
            secondary_queries_json, intent_category, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(domain, query_cluster) DO UPDATE SET
            canonical_url = excluded.canonical_url,
            primary_query = excluded.primary_query,
            secondary_queries_json = excluded.secondary_queries_json,
            intent_category = excluded.intent_category,
            updated_at = excluded.updated_at
        """,
        (
            domain,
            query_cluster.strip().lower(),
            canonical_url.strip(),
            primary_query.strip(),
            sec_json,
            intent_category.strip().lower(),
            now_str,
            now_str,
        ),
    )
    conn.commit()


def get_query_owner(
    conn: sqlite3.Connection,
    domain: str,
    query: str,
) -> dict[str, Any] | None:
    """Finds the primary owner URL for a query or query cluster on a domain."""
    q_norm = query.strip().lower()
    row = conn.execute(
        """
        SELECT query_cluster, canonical_url, primary_query, secondary_queries_json, intent_category
        FROM query_ownership_map
        WHERE domain = ? AND (query_cluster = ? OR primary_query = ?)
        LIMIT 1
        """,
        (domain, q_norm, q_norm),
    ).fetchone()
    if row:
        return {
            "query_cluster": row[0],
            "canonical_url": row[1],
            "primary_query": row[2],
            "secondary_queries": json.loads(row[3]),
            "intent_category": row[4],
            "fuzzy_match": False,
        }
    q_tokens = set(q_norm.split())
    if not q_tokens:
        return None
    for r in conn.execute(
        "SELECT query_cluster, canonical_url, primary_query, secondary_queries_json, intent_category "
        "FROM query_ownership_map WHERE domain = ?",
        (domain,),
    ):
        sec_queries = json.loads(r[3])
        if any(q_norm == sq.strip().lower() or sq.strip().lower() in q_norm for sq in sec_queries):
            return {
                "query_cluster": r[0],
                "canonical_url": r[1],
                "primary_query": r[2],
                "secondary_queries": sec_queries,
                "intent_category": r[4],
                "fuzzy_match": True,
            }
        cluster_tokens = set(r[0].split())
        overlap = len(q_tokens & cluster_tokens) / max(len(q_tokens | cluster_tokens), 1)
        cluster_contained = len(cluster_tokens) > 0 and len(q_tokens & cluster_tokens) / len(cluster_tokens) >= 0.75
        if overlap >= 0.70 or cluster_contained:
            return {
                "query_cluster": r[0],
                "canonical_url": r[1],
                "primary_query": r[2],
                "secondary_queries": sec_queries,
                "intent_category": r[4],
                "fuzzy_match": True,
            }
    return None


# ------------------------------------------------------------- Adaptive Action Effectiveness Learning


def record_action_effectiveness(
    conn: sqlite3.Connection,
    *,
    domain: str,
    action_code: str,
    route_family: str = "root",
    is_success: bool,
    click_lift: float = 0.0,
    impression_lift: float = 0.0,
    rank_delta: float = 0.0,
    now: datetime | None = None,
) -> None:
    """Updates empirical win-rate and lift tracking for an action type."""
    now_str = _iso(_utc_now(now))
    row = conn.execute(
        """
        SELECT total_experiments, successful_experiments, avg_click_lift, avg_impression_lift, avg_rank_delta
        FROM action_effectiveness_stats
        WHERE domain = ? AND action_code = ? AND route_family = ?
        """,
        (domain, action_code, route_family),
    ).fetchone()

    if not row:
        conn.execute(
            """
            INSERT INTO action_effectiveness_stats (
                domain, action_code, route_family, total_experiments, successful_experiments,
                avg_click_lift, avg_impression_lift, avg_rank_delta, updated_at
            ) VALUES (?, ?, ?, 1, ?, ?, ?, ?, ?)
            """,
            (
                domain,
                action_code,
                route_family,
                1 if is_success else 0,
                click_lift,
                impression_lift,
                rank_delta,
                now_str,
            ),
        )
    else:
        tot, succ, old_c_lift, old_i_lift, old_r_delta = row
        new_tot = tot + 1
        new_succ = succ + (1 if is_success else 0)
        new_c_lift = (old_c_lift * tot + click_lift) / new_tot
        new_i_lift = (old_i_lift * tot + impression_lift) / new_tot
        new_r_delta = (old_r_delta * tot + rank_delta) / new_tot
        conn.execute(
            """
            UPDATE action_effectiveness_stats
            SET total_experiments = ?, successful_experiments = ?,
                avg_click_lift = ?, avg_impression_lift = ?, avg_rank_delta = ?,
                updated_at = ?
            WHERE domain = ? AND action_code = ? AND route_family = ?
            """,
            (new_tot, new_succ, new_c_lift, new_i_lift, new_r_delta, now_str, domain, action_code, route_family),
        )
    conn.commit()


def get_action_effectiveness(
    conn: sqlite3.Connection,
    domain: str,
    action_code: str,
    route_family: str = "root",
) -> dict[str, Any]:
    """Returns empirical win-rate and average lift for an action type."""
    row = conn.execute(
        """
        SELECT total_experiments, successful_experiments, avg_click_lift, avg_impression_lift, avg_rank_delta
        FROM action_effectiveness_stats
        WHERE domain = ? AND action_code = ? AND route_family = ?
        """,
        (domain, action_code, route_family),
    ).fetchone()
    if not row or row[0] == 0:
        return {
            "total_experiments": 0,
            "win_rate": 0.50,  # uninformative prior
            "avg_click_lift": 0.0,
            "avg_impression_lift": 0.0,
            "avg_rank_delta": 0.0,
            "has_empirical_evidence": False,
        }
    return {
        "total_experiments": row[0],
        "win_rate": float(row[1]) / float(row[0]),
        "avg_click_lift": float(row[2]),
        "avg_impression_lift": float(row[3]),
        "avg_rank_delta": float(row[4]),
        "has_empirical_evidence": True,
    }


def get_fleet_action_effectiveness(
    conn: sqlite3.Connection,
    action_code: str,
    route_family: str | None = None,
) -> dict[str, Any]:
    """Cross-property aggregated effectiveness prior (strict multi-tenant data privacy).

    Only aggregates anonymous totals and win-rates across domains without
    exposing individual URLs or queries.
    """
    if route_family:
        row = conn.execute(
            """
            SELECT SUM(total_experiments), SUM(successful_experiments),
                   AVG(avg_click_lift), AVG(avg_impression_lift), AVG(avg_rank_delta)
            FROM action_effectiveness_stats
            WHERE action_code = ? AND route_family = ?
            """,
            (action_code, route_family),
        ).fetchone()
    else:
        row = conn.execute(
            """
            SELECT SUM(total_experiments), SUM(successful_experiments),
                   AVG(avg_click_lift), AVG(avg_impression_lift), AVG(avg_rank_delta)
            FROM action_effectiveness_stats
            WHERE action_code = ?
            """,
            (action_code,),
        ).fetchone()
    if not row or not row[0]:
        return {
            "total_experiments": 0,
            "win_rate": 0.50,
            "avg_click_lift": 0.0,
            "has_empirical_evidence": False,
        }
    tot = int(row[0])
    succ = int(row[1] or 0)
    return {
        "total_experiments": tot,
        "win_rate": float(succ) / float(tot) if tot > 0 else 0.5,
        "avg_click_lift": float(row[2] or 0.0),
        "has_empirical_evidence": True,
    }


# ------------------------------------------------------------- budget gate


class DailyBudgetGate:
    """24-hour DataForSEO spend bucket (stdlib SQLite; no extra deps).

    Caps ALL skill invocations on one machine to ``daily_cap`` Standard-Queue
    SERP tasks per UTC day ($0.0006 each -> a 100 cap is $0.06/day max).
    """

    def __init__(self, db_path: str = DEFAULT_DB_PATH, daily_cap: int = DEFAULT_DAILY_SERP_BUDGET):
        self._conn = connect_state_db(db_path)
        self.daily_cap = daily_cap
        # Wave-64 review R3: property-level starvation guard. Every property
        # holds a guaranteed floor of the daily cap; anything past its floor
        # draws from the shared pool (cap minus all floors), so one hungry
        # domain can never drain the whole fleet budget.
        self.max_domain_floor = 35

    def _dynamic_floor(self, active_domains: int) -> int:
        """Per-domain guaranteed floor that scales with fleet size.

        Review follow-up: a STATIC 50/day floor breaks at >= 3 domains
        (3 x 50 = 150 = the whole cap, so the 4th domain of the day starves
        to 0). The floor is therefore dynamic: ``min(max_domain_floor,
        daily_cap // active_domains)`` - floors never sum past the cap, so
        every REGISTERED domain keeps a functional guaranteed slice
        (30/day up to 5 properties, shrinking gracefully beyond).
        """
        return min(self.max_domain_floor, self.daily_cap // max(1, active_domains))

    def _day(self, now: datetime | None) -> str:
        return _utc_now(now).date().isoformat()

    def _total_spent(self, day: str) -> int:
        row = self._conn.execute("SELECT spent FROM dfs_budget WHERE day = ?", (day,)).fetchone()
        return int(row[0]) if row else 0

    def _domain_spent(self, day: str, domain: str) -> int:
        row = self._conn.execute(
            "SELECT spent FROM dfs_budget_domain WHERE day = ? AND domain = ?",
            (day, domain),
        ).fetchone()
        return int(row[0]) if row else 0

    def remaining(self, now: datetime | None = None, domain: str | None = None) -> int:
        day = self._day(now)
        total_left = max(0, self.daily_cap - self._total_spent(day))
        if not domain:
            return total_left
        # guaranteed floor slice first (bounded by the whole-day cap), then
        # the shared pool for anything beyond the floor
        floor_count = self._conn.execute(
            "SELECT COUNT(DISTINCT domain) FROM dfs_budget_domain WHERE day = ?",
            (day,),
        ).fetchone()[0]
        # a domain not yet in today's ledger still occupies a floor slot
        active_domains = floor_count + (1 if self._domain_spent(day, domain) == 0 else 0)
        floor = self._dynamic_floor(active_domains)
        guaranteed_left = max(0, floor - self._domain_spent(day, domain))
        shared_pool = max(0, self.daily_cap - min(active_domains * floor, self.daily_cap))
        shared_used = self._conn.execute(
            "SELECT COALESCE(SUM(MAX(spent - ?, 0)), 0) FROM dfs_budget_domain WHERE day = ?",
            (floor, day),
        ).fetchone()[0]
        shared_left = max(0, shared_pool - int(shared_used))
        return min(max(guaranteed_left, 0) + shared_left, total_left)

    def record(self, n: int, now: datetime | None = None, domain: str | None = None) -> int:
        """Records n tasks; returns the remaining budget after the spend."""
        remaining = self.remaining(now=now, domain=domain)
        allowed = min(max(0, int(n)), remaining)
        if allowed:
            day = self._day(now)
            self._conn.execute(
                "INSERT INTO dfs_budget (day, spent) VALUES (?, ?) ON CONFLICT(day) DO UPDATE SET spent = spent + ?",
                (day, allowed, allowed),
            )
            if domain:
                self._conn.execute(
                    "INSERT INTO dfs_budget_domain (day, domain, spent) VALUES (?, ?, ?) "
                    "ON CONFLICT(day, domain) DO UPDATE SET spent = spent + ?",
                    (day, domain, allowed, allowed),
                )
            self._conn.commit()
        return self.remaining(now=now, domain=domain)


# ------------------------------------------------------- URL Inspection state

INSPECTION_TTL_HOURS = 24 * 7  # coverage states are stable week-to-week
DEFAULT_DAILY_INSPECTION_BUDGET = 2000  # GSC free allowance per property/day


def save_url_inspections(
    conn: sqlite3.Connection,
    site: str,
    results: dict,
    now: datetime | None = None,
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
    now: datetime | None = None,
) -> dict:
    """Returns fresh (within TTL) inspection records for the requested URLs."""
    stamp = _utc_now(now)
    cutoff = stamp - timedelta(hours=max_age_hours)
    fresh: dict[str, dict[str, Any]] = {}
    for url in urls:
        row = conn.execute(
            "SELECT coverage_state, indexing_state, last_crawl_time, inspected_at FROM url_inspections WHERE url = ?",
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
    now: datetime | None = None,
) -> int:
    """Free-tier guard: max 2,000 URL Inspection calls per UTC day."""
    day = _utc_now(now).date().isoformat()
    row = conn.execute("SELECT spent FROM url_inspection_budget WHERE day = ?", (day,)).fetchone()
    return max(0, daily_cap - int(row[0] if row else 0))


def record_inspection_calls(
    conn: sqlite3.Connection,
    n: int,
    daily_cap: int = DEFAULT_DAILY_INSPECTION_BUDGET,
    now: datetime | None = None,
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
