"""Unified fleet state DB: no per-domain .db fragmentation (wave 64).

Wave-63 ran incomecanvas.com against its own ``~/.seo_fleet/incomecanvas.db``
- its own backlog cursor, SERP cache, and budget gate - so the fleet-wide
SERP budget gate (<=150 DataForSEO SERPs/day across ALL properties) was
invisible to that run and per-domain DBs will fragment forever as new
properties onboard. This module migrates every per-domain state DB into the
single ``~/.seo_fleet/fleet_state.db`` cursor (rows are already keyed by the
``domain`` column) and sums daily budget totals.

Merge semantics:
- ``atomic_task_backlog``: rows merge with INSERT OR IGNORE; the partial
  unique index ``(page, action_code) WHERE status IN ('PENDING','LEASED')``
  guards open-task collisions, and pairs the TARGET has adjudicated
  REJECTED are terminal - source copies never re-enter (mirrors the
  ``enqueue_tasks`` REJECTED-honoring dedupe).
- ``dfs_serp_cache``: keyed by query; the target's entry wins for shared
  queries (cache-provenance continuity), source fills gaps.
- ``dfs_budget`` / ``url_inspection_budget``: SUM per day - spend events
  recorded in separate DBs were real, distinct DataForSEO calls.
- ``gsc_snapshots`` / ``url_inspections``: keyed by site/url; INSERT OR
  IGNORE (no cross-domain collision exists by construction).
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fleet_state import connect_state_db

DEFAULT_TARGET_DB = "~/.seo_fleet/fleet_state.db"


def merge_state_db(source_path: str, target_path: str) -> dict:
    """Merges a per-domain state DB into the unified fleet cursor DB."""
    src = sqlite3.connect(str(Path(source_path).expanduser()))
    dst = connect_state_db(str(Path(target_path).expanduser()))
    report = {
        "backlog_merged": 0,
        "backlog_ignored_open": 0,
        "backlog_ignored_rejected": 0,
        "serp_cache_merged": 0,
        "budget_days_merged": 0,
        "inspection_budget_days_merged": 0,
        "snapshots_merged": 0,
        "inspections_merged": 0,
    }

    rejected_pairs = {
        (row[0], row[1])
        for row in dst.execute(
            "SELECT page, action_code FROM atomic_task_backlog WHERE status = 'REJECTED'"
        )
    }
    for row in src.execute(
        "SELECT domain, page, query, action_code, target_component, file_target, "
        "tdd_assertion, lgbm_score, priority_score, route_family, status, "
        "created_at, leased_at, shipped_at, commit_sha "
        "FROM atomic_task_backlog"
    ).fetchall():
        if (row[1], row[3]) in rejected_pairs:
            report["backlog_ignored_rejected"] += 1
            continue
        cur = dst.execute(
            "INSERT OR IGNORE INTO atomic_task_backlog "
            "(domain, page, query, action_code, target_component, file_target, "
            " tdd_assertion, lgbm_score, priority_score, route_family, status, "
            " created_at, leased_at, shipped_at, commit_sha) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            row,
        )
        if cur.rowcount > 0:
            report["backlog_merged"] += 1
        else:
            report["backlog_ignored_open"] += 1

    for row in src.execute(
        "SELECT query, fetched_at, items_json, item_types FROM dfs_serp_cache"
    ).fetchall():
        cur = dst.execute(
            "INSERT OR IGNORE INTO dfs_serp_cache "
            "(query, fetched_at, items_json, item_types) VALUES (?, ?, ?, ?)",
            row,
        )
        if cur.rowcount > 0:
            report["serp_cache_merged"] += 1

    for table, key in (
        ("dfs_budget", "budget_days_merged"),
        ("url_inspection_budget", "inspection_budget_days_merged"),
    ):
        for day, spent in src.execute(f"SELECT day, spent FROM {table}").fetchall():
            dst.execute(
                f"INSERT INTO {table} (day, spent) VALUES (?, ?) "
                "ON CONFLICT(day) DO UPDATE SET spent = spent + excluded.spent",
                (day, spent),
            )
            report[key] += 1

    for row in src.execute(
        "SELECT site, window_end, fetched_at, rows_json FROM gsc_snapshots"
    ).fetchall():
        cur = dst.execute(
            "INSERT OR IGNORE INTO gsc_snapshots "
            "(site, window_end, fetched_at, rows_json) VALUES (?, ?, ?, ?)",
            row,
        )
        if cur.rowcount > 0:
            report["snapshots_merged"] += 1

    for row in src.execute(
        "SELECT url, site, coverage_state, indexing_state, last_crawl_time, "
        "inspected_at FROM url_inspections"
    ).fetchall():
        cur = dst.execute(
            "INSERT OR IGNORE INTO url_inspections "
            "(url, site, coverage_state, indexing_state, last_crawl_time, "
            "inspected_at) VALUES (?, ?, ?, ?, ?, ?)",
            row,
        )
        if cur.rowcount > 0:
            report["inspections_merged"] += 1

    dst.commit()
    src.close()
    dst.close()
    return report


def retire_source(source_path: str) -> str:
    """Renames a migrated per-domain DB aside (never deletes data)."""
    src = Path(source_path).expanduser()
    backup = src.with_name(src.name + ".migrated-bak")
    src.rename(backup)
    return str(backup)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Merge per-domain fleet state DBs into the unified "
        "~/.seo_fleet/fleet_state.db cursor (wave-64)."
    )
    parser.add_argument(
        "--source",
        action="append",
        required=True,
        help="per-domain state DB to merge (repeatable)",
    )
    parser.add_argument("--target", default=DEFAULT_TARGET_DB)
    parser.add_argument(
        "--retire-source",
        action="store_true",
        help="rename each merged source DB to <name>.migrated-bak after merge",
    )
    args = parser.parse_args(argv)
    for source in args.source:
        report = merge_state_db(source, args.target)
        print(f"Merged {source} -> {args.target}:")
        for key, value in report.items():
            print(f"    {key}: {value}")
        if args.retire_source:
            backup = retire_source(source)
            print(f"    retired source -> {backup}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
