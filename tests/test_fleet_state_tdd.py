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
    release_stale_leases,
    save_gsc_snapshot,
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
    assert (
        gsc_snapshot_fresh(conn, "smsriver.com", max_age_hours=24, now=stale_at)
        is False
    )
    assert (
        load_gsc_snapshot(conn, "smsriver.com", max_age_hours=24, now=stale_at) is None
    )


def test_serp_cache_ttl_respected(conn):
    upsert_serp_cache(conn, "online sms", [{"type": "organic"}], ["organic"], now=NOW)
    fresh = load_cached_serps(conn, ["online sms"], max_age_days=30, now=NOW)
    assert "online sms" in fresh
    stale = load_cached_serps(
        conn, ["online sms"], max_age_days=30, now=NOW + timedelta(days=31)
    )
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
    assert (
        leased[0]["action_code"] == "INJECT_EXACT_H2_AND_TITLE"
    )  # highest priority first
    assert leased[0]["status"] == "LEASED"
    assert pending_count(conn) == 1

    mark_shipped(conn, [leased[0]["id"]], commit_sha="abc1234", now=NOW)
    again = lease_tasks(conn, limit=5, now=NOW)
    assert [t["action_code"] for t in again] == ["BOOST_INTERNAL_LINKS"]


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

    statuses = dict(
        conn.execute("SELECT id, status FROM atomic_task_backlog").fetchall()
    )
    assert set(statuses.values()) == {"REVERTED"}
    assert lease_tasks(conn, limit=5) == []  # REVERTED never re-enters the cursor
    remaining = conn.execute(
        "SELECT COUNT(*) FROM atomic_task_backlog WHERE status='REVERTED' AND commit_sha='abc1234'"
    ).fetchone()[0]
    assert remaining == 2  # audit trail preserved
