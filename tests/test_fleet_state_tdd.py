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
    pending_count,
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
