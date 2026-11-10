"""Unit tests for the fleet state machine (SQLite persistence + task cursor).

Covers:
- gsc snapshot save/load with a 24h TTL (stale -> None, fresh -> rows)
- SERP cache upsert/lookup with a 30-day TTL
- atomic task backlog: enqueue (deduped on page+action) -> lease (priority
  order, PENDING -> LEASED) -> mark SHIPPED
- DataForSEO daily budget gate: cap enforcement across calls, midnight reset
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from fleet_state import (
    DailyBudgetGate,
    connect_state_db,
    enqueue_tasks,
    gsc_snapshot_fresh,
    lease_tasks,
    load_cached_serps,
    load_gsc_snapshot,
    mark_shipped,
    mark_tasks_reverted,
    pending_count,
    queries_missing_volume,
    release_stale_leases,
    save_gsc_snapshot,
    save_serp_volumes,
    save_url_inspections,
    upsert_serp_cache,
)


@pytest.fixture
def conn(tmp_path: Path):
    return connect_state_db(str(tmp_path / "state.db"))


NOW = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)


def test_gsc_snapshot_roundtrip_and_24h_ttl(conn):
    save_gsc_snapshot(
        conn,
        "smsriver.com",
        [
            {
                "query": "q",
                "page": "p",
                "clicks_30d": 1,
                "impressions": 10,
                "current_pos": 5.0,
            }
        ],
        now=NOW,
    )
    assert gsc_snapshot_fresh(conn, "smsriver.com", max_age_hours=24, now=NOW) is True
    rows = load_gsc_snapshot(conn, "smsriver.com", max_age_hours=24, now=NOW)
    assert rows and rows[0]["query"] == "q"
    stale_at = NOW + timedelta(hours=25)
    assert gsc_snapshot_fresh(conn, "smsriver.com", max_age_hours=24, now=stale_at) is False
    assert load_gsc_snapshot(conn, "smsriver.com", max_age_hours=24, now=stale_at) is None


def test_serp_cache_ttl_respected(conn):
    upsert_serp_cache(conn, "online sms", [{"type": "organic"}], ["organic"], now=NOW)
    fresh = load_cached_serps(conn, ["online sms"], max_age_days=30, now=NOW)
    assert "online sms" in fresh
    stale = load_cached_serps(conn, ["online sms"], max_age_days=30, now=NOW + timedelta(days=31))
    assert stale == {}


def test_task_backlog_cursor_persists_and_dedupes(conn):
    tasks = [
        {
            "page": "https://a.com/x/",
            "query": "q1",
            "action_code": "INJECT_EXACT_H2_AND_TITLE",
            "priority_score": 1.5,
            "domain": "a.com",
        },
        {
            "page": "https://a.com/x/",
            "query": "q1",
            "action_code": "BOOST_INTERNAL_LINKS",
            "priority_score": 1.2,
            "domain": "a.com",
        },
        {
            "page": "https://a.com/x/",
            "query": "q1",
            "action_code": "INJECT_EXACT_H2_AND_TITLE",
            "priority_score": 9.9,
            "domain": "a.com",
        },  # duplicate of task 1
    ]
    assert enqueue_tasks(conn, tasks, now=NOW) == 2
    assert pending_count(conn) == 2

    leased = lease_tasks(conn, limit=1, now=NOW)
    assert len(leased) == 1
    assert leased[0]["action_code"] == "INJECT_EXACT_TITLE_AND_H2"  # canonicalized from INJECT_EXACT_H2_AND_TITLE
    assert leased[0]["status"] == "LEASED"
    assert pending_count(conn) == 1

    mark_shipped(conn, [leased[0]["id"]], commit_sha="abc1234", now=NOW)
    again = lease_tasks(conn, limit=5, now=NOW)
    assert [t["action_code"] for t in again] == ["WIRE_HUB_AND_FOOTER_INLINKS"]


def test_budget_gate_caps_daily_spend_and_resets_next_day(tmp_path: Path):
    gate = DailyBudgetGate(str(tmp_path / "budget.db"), daily_cap=100)
    now = NOW
    assert gate.record(60, now=now) == 40
    assert gate.record(60, now=now) == 0, "gate allowed spend beyond the daily cap"
    assert gate.remaining(now=now) == 0
    assert gate.remaining(now=now + timedelta(days=1)) == 100, "bucket did not reset"


# ---------------------------------------------------------------------------
# 50x/day hardening: stale-lease release, atomic RETURNING cursor, REVERTED
# ---------------------------------------------------------------------------


def _enqueue(conn, n, domain="smsriver.com", now=NOW):
    tasks = [
        {
            "domain": domain,
            "page": f"https://{domain}/p{i}/",
            "query": f"q{i}",
            "action_code": f"ACTION_{i % 3}",
            "priority_score": float(n - i),
        }
        for i in range(n)
    ]
    enqueue_tasks(conn, tasks, now=now)


def test_wal_mode_enabled_on_connect(tmp_path):
    # WAL is a file-DB journal mode; :memory: always reports "memory".
    conn = connect_state_db(str(tmp_path / "wal.db"))
    mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode == "wal"
    assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000


def test_stale_leases_released_after_ttl(tmp_path):
    conn = connect_state_db(":memory:")
    _enqueue(conn, 3)
    old = NOW - timedelta(hours=2)
    first = lease_tasks(conn, limit=2, now=old)
    assert len(first) == 2 and all(t["status"] == "LEASED" for t in first)

    # A fresh run 1 hour later must reclaim the crashed agent's leases.
    now = NOW + timedelta(hours=1)
    release_stale_leases(conn, ttl_seconds=3600, now=now)
    reclaimed = lease_tasks(conn, limit=3, now=now)
    assert len(reclaimed) == 3  # the 2 stale + the 1 still-pending


def test_lease_cursor_never_repeats_and_exhausts_cleanly():
    conn = connect_state_db(":memory:")
    _enqueue(conn, 5)
    batch1 = lease_tasks(conn, limit=3)
    batch2 = lease_tasks(conn, limit=3)
    batch3 = lease_tasks(conn, limit=3)
    ids = [t["id"] for t in batch1 + batch2 + batch3]
    assert len(ids) == len(set(ids)) == 5  # no overlap, all 5 leased once
    assert pending_count(conn) == 0


def test_mark_tasks_reverted_is_terminal_and_unleasable():
    conn = connect_state_db(":memory:")
    _enqueue(conn, 2)
    leased = lease_tasks(conn, limit=2)
    mark_shipped(conn, [t["id"] for t in leased], commit_sha="abc1234")
    mark_tasks_reverted(conn, [t["id"] for t in leased])

    statuses = dict(conn.execute("SELECT id, status FROM atomic_task_backlog").fetchall())
    assert set(statuses.values()) == {"REVERTED"}
    assert lease_tasks(conn, limit=5) == []  # REVERTED never re-enters the cursor
    remaining = conn.execute(
        "SELECT COUNT(*) FROM atomic_task_backlog WHERE status='REVERTED' AND commit_sha='abc1234'"
    ).fetchone()[0]
    assert remaining == 2  # audit trail preserved


# ---------------------------------------------------------------------------
# Round 7: route_family stratification, file-target locks, migration
# ---------------------------------------------------------------------------


def test_enqueue_tags_route_family_and_column_migrates(tmp_path):
    conn = connect_state_db(str(tmp_path / "migrate.db"))
    # Legacy row (pre-route_family era) simulated by direct insert:
    conn.execute(
        "INSERT INTO atomic_task_backlog (domain, page, query, action_code, status, created_at) "
        "VALUES ('a.com', 'https://a.com/number/123/', 'q', 'ACT', 'PENDING', '2026-01-01')"
    )
    conn.commit()
    conn.close()
    # Reconnecting must migrate the column AND backfill route_family.
    conn2 = connect_state_db(str(tmp_path / "migrate.db"))
    fam = conn2.execute(
        "SELECT route_family FROM atomic_task_backlog WHERE page='https://a.com/number/123/'"
    ).fetchone()[0]
    assert fam == "number"

    enqueue_tasks(
        conn2,
        [
            {
                "domain": "a.com",
                "page": "https://a.com/guides/x/",
                "query": "q2",
                "action_code": "ACT2",
                "priority_score": 1.0,
            }
        ],
    )
    fam2 = conn2.execute(
        "SELECT route_family FROM atomic_task_backlog WHERE page='https://a.com/guides/x/'"
    ).fetchone()[0]
    assert fam2 == "guides"


def test_lease_tasks_stratifies_families_per_wave():
    conn = connect_state_db(":memory:")
    number_tasks = [
        {
            "domain": "a.com",
            "page": f"https://a.com/number/{i}/",
            "query": f"n{i}",
            "action_code": "ACT",
            "priority_score": 10.0 - i,
        }
        for i in range(10)
    ]
    guide_tasks = [
        {
            "domain": "a.com",
            "page": f"https://a.com/guides/g{i}/",
            "query": f"g{i}",
            "action_code": "ACT",
            "priority_score": 5.0 - i,
        }
        for i in range(10)
    ]
    enqueue_tasks(conn, number_tasks + guide_tasks)
    wave = lease_tasks(
        conn,
        limit=6,
        family_caps={"number": 2},
        default_family_cap=2,
    )
    from collections import Counter

    fams = Counter(t["route_family"] for t in wave)
    assert fams["number"] <= 2 and fams["guides"] <= 2
    assert len(wave) == 4  # caps bind before the limit fills


# ------------------------------------------------- wave-64 two-tier backfill


def test_lease_tasks_backfills_empty_type_buckets_to_limit():
    """Wave-64: empty quota buckets no longer shrink the wave.

    Wave-63 leased 21 slots from an 8/8/6/5/3 quota table; several buckets
    were empty so the wave came home undersized and the adjudication window
    collapsed. quota_pass=1 backfill must now fill the wave to `limit`.
    """
    conn = connect_state_db(":memory:")
    # 12 tasks all of one UNQUOTA'd action code (rank beyond any cap),
    # plus 3 tasks of a quota'd code at rank 1 (within its cap of 2... use
    # cap 2 so 1 row sits in tier 0)
    backlog = [
        {
            "domain": "a.com",
            "page": f"https://a.com/guides/{i}/",
            "query": f"uncapped q{i}",
            "action_code": "UNCAPPED_CODE",
            "priority_score": 20.0 - i,
        }
        for i in range(12)
    ]
    backlog.append(
        {
            "domain": "a.com",
            "page": "https://a.com/guides/hero/",
            "query": "quota'd hero query",
            "action_code": "QUOTA_CODE",
            "priority_score": 30.0,
        }
    )
    enqueue_tasks(conn, backlog)
    wave = lease_tasks(
        conn,
        limit=6,
        type_caps={"QUOTA_CODE": 2},
        default_type_cap=0,
    )
    assert len(wave) == 6, "empty tiers must backfill to the full limit"
    # tier 0 (within cap) first, then tier-1 backfill by priority
    codes = [t["action_code"] for t in wave]
    assert codes[0] == "QUOTA_CODE"
    assert codes[1:].count("UNCAPPED_CODE") == 5


def test_lease_tasks_two_tier_preference_overrides_priority_within_tiers():
    """quota_pass ASC outranks priority_score: a capped-type task within its
    cap beats a higher-priority uncapped task in the backfill tier."""
    conn = connect_state_db(":memory:")
    rows = [
        {
            "domain": "a.com",
            "page": "https://a.com/guides/uncapped-monster/",
            "query": "uncapped monster",
            "action_code": "UNCAPPED_CODE",
            "priority_score": 99.0,
        },
        {
            "domain": "a.com",
            "page": "https://a.com/guides/quota-modest/",
            "query": "quota modest",
            "action_code": "QUOTA_CODE",
            "priority_score": 10.0,
        },
    ]
    enqueue_tasks(conn, rows)
    wave = lease_tasks(
        conn,
        limit=2,
        type_caps={"QUOTA_CODE": 1},
        default_type_cap=0,
    )
    assert [t["action_code"] for t in wave] == ["QUOTA_CODE", "UNCAPPED_CODE"]


def test_lease_tasks_backfill_respects_family_and_file_locks():
    """Backfill rows still respect hard family caps and file-target locks."""
    conn = connect_state_db(":memory:")
    backlog = [
        {
            "domain": "a.com",
            "page": f"https://a.com/number/{i}/",
            "query": f"n{i}",
            "action_code": "UNCAPPED_CODE",
            "priority_score": 20.0 - i,
        }
        for i in range(8)
    ]
    enqueue_tasks(conn, backlog)
    wave = lease_tasks(
        conn,
        limit=8,
        family_caps={"number": 3},
        default_family_cap=0,
        type_caps={"UNCAPPED_CODE": 2},
        default_type_cap=0,
    )
    assert len(wave) == 3, "family cap stays HARD even when quotas backfill"


def test_lease_tasks_backfill_never_dups_page_action_pair():
    """Two leases in a row never hand out the same (page, action_code)."""
    conn = connect_state_db(":memory:")
    rows = [
        {
            "domain": "a.com",
            "page": f"https://a.com/guides/{i}/",
            "query": f"q{i}",
            "action_code": "UNCAPPED_CODE",
            "priority_score": 10.0,
        }
        for i in range(10)
    ]
    enqueue_tasks(conn, rows)
    first = lease_tasks(conn, limit=4, type_caps={"QUOTA_CODE": 2}, default_type_cap=0)
    second = lease_tasks(conn, limit=4, type_caps={"QUOTA_CODE": 2}, default_type_cap=0)
    pairs = {(t["page"], t["action_code"]) for t in first + second}
    assert len(pairs) == len(first) + len(second)


def test_lease_tasks_never_hands_out_locked_file_targets():
    conn = connect_state_db(":memory:")
    # Simulate another worktree having leased file_target 'templates/home.html'
    enqueue_tasks(
        conn,
        [
            {
                "domain": "a.com",
                "page": "https://a.com/one/",
                "query": "q1",
                "action_code": "ACT",
                "priority_score": 10.0,
                "file_target": "templates/home.html",
            },
        ],
    )
    locked = lease_tasks(conn, limit=1)
    assert locked and locked[0]["file_target"] == "templates/home.html"

    enqueue_tasks(
        conn,
        [
            {
                "domain": "a.com",
                "page": "https://a.com/two/",
                "query": "q2",
                "action_code": "ACT",
                "priority_score": 9.0,
                "file_target": "templates/home.html",
            },  # collides with the active lease
            {
                "domain": "a.com",
                "page": "https://a.com/three/",
                "query": "q3",
                "action_code": "ACT",
                "priority_score": 8.0,
                "file_target": "templates/status.html",
            },
        ],
    )
    wave = lease_tasks(conn, limit=2)
    pages = [t["page"] for t in wave]
    assert "https://a.com/two/" not in pages, "locked file_target must not double-lease"
    assert "https://a.com/three/" in pages


def test_serp_volume_column_migration_and_backfill_roundtrip(tmp_path):
    conn = connect_state_db(str(tmp_path / "vol.db"))
    upsert_serp_cache(conn, "q one", [{"type": "organic"}], [])
    upsert_serp_cache(conn, "q two", [{"type": "organic"}], [])
    missing = queries_missing_volume(conn)
    assert set(missing) == {"q one", "q two"}
    save_serp_volumes(conn, {"q one": 5400.0})
    assert queries_missing_volume(conn) == ["q two"]
    row = conn.execute("SELECT search_volume FROM dfs_serp_cache WHERE query = 'q one'").fetchone()
    assert row[0] == 5400.0


def test_mark_tasks_reverted_accepts_leased_tasks(conn):
    """Executor adjudication: an unfit LEASED task must reach terminal REVERTED."""
    from fleet_state import enqueue_tasks, lease_tasks, mark_tasks_reverted

    tasks = [
        {
            "page": "https://smsriver.com/x/",
            "query": "typo recive",
            "action_code": "INJECT_EXACT_TITLE_AND_H2",
            "file_target": "templates/x.html",
        },
        {
            "page": "https://smsriver.com/y/",
            "query": "clean query",
            "action_code": "BOOST_CLUSTER_CROSS_LINKS",
            "file_target": "templates/y.html",
        },
    ]
    enqueue_tasks(conn, tasks)
    conn.commit()
    leased = lease_tasks(conn, domain="smsriver.com", limit=2, now=datetime.now(timezone.utc))
    assert len(leased) == 2
    first_id = leased[0]["id"]
    first_page = leased[0]["page"]
    assert mark_tasks_reverted(conn, [first_id]) == 1
    conn.commit()
    status = conn.execute("SELECT status FROM atomic_task_backlog WHERE id=?", (first_id,)).fetchone()[0]
    assert status == "REVERTED"
    # REVERTED is terminal: a fresh lease never re-picks it
    again = lease_tasks(conn, domain="smsriver.com", limit=5, now=datetime.now(timezone.utc))
    assert all(t["page"] != first_page for t in again)
