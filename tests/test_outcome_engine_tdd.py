"""test_outcome_engine_tdd.py - TDD test suite for Outcome Engine v2 experiment ledger.

Verifies:
- Experiment ledger recording on task shipment
- Difference-in-Differences calculation against matched control cohorts
- Recrawl evidence detection and status state machine
- Adaptive action effectiveness learning with strict multi-tenant isolation
- Two-part scorecard emission with honest 'NOT YET MEASURED' status during observation
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from evaluate_experiments import evaluate_domain_experiments, format_two_part_scorecard
from fleet_state import (
    _SCHEMA,
    connect_state_db,
    enqueue_tasks,
    get_action_effectiveness,
    get_experiment_summary,
    get_fleet_action_effectiveness,
    lease_tasks,
    mark_shipped,
    record_action_effectiveness,
    record_experiment,
    record_shipped_experiments,
    update_experiment_outcomes,
    update_experiment_recrawl,
)


@pytest.fixture
def temp_db(tmp_path):
    db_file = tmp_path / "test_outcome_state.db"
    conn = connect_state_db(str(db_file))
    yield conn
    conn.close()


def test_experiment_ledger_lifecycle_and_recrawl(temp_db):
    """Verifies that an experiment starts as PENDING_RECRAWL and transitions to OBSERVING upon recrawl."""
    now = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)
    exp_id = record_experiment(
        temp_db,
        task_id=101,
        domain="openfileconverter.com",
        page="https://openfileconverter.com/studio/lidar/",
        target_query="las viewer",
        action_code="INJECT_SECONDARY_H2_ONLY",
        deployed_at=now,
        baseline_clicks_28d=10.0,
        baseline_impressions_28d=500.0,
        baseline_ctr=0.02,
        baseline_position=8.5,
    )
    assert exp_id > 0

    # Summary before recrawl
    summary = get_experiment_summary(temp_db, "openfileconverter.com")
    assert summary["total_experiments"] == 1
    assert summary["pending_recrawl"] == 1
    assert summary["observing"] == 0
    assert summary["graded"] == 0
    assert not summary["has_measured_outcomes"]

    # Detect recrawl on target page
    recrawled = update_experiment_recrawl(
        temp_db,
        domain="openfileconverter.com",
        recrawled_pages={"https://openfileconverter.com/studio/lidar/"},
        now=now + timedelta(days=3),
    )
    assert recrawled == 1

    summary_after = get_experiment_summary(temp_db, "openfileconverter.com")
    assert summary_after["pending_recrawl"] == 0
    assert summary_after["observing"] == 1
    assert summary_after["graded"] == 0


def test_difference_in_differences_and_grading(temp_db):
    """Verifies that post-28d GSC evaluation computes treatment lift vs control and updates effectiveness."""
    dep_time = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
    eval_time = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)  # 29 days later

    # Create backlog task and experiment
    enqueue_tasks(
        temp_db,
        [{
            "domain": "openfileconverter.com",
            "page": "https://openfileconverter.com/convert/bmp-to-png/",
            "query": "bmp png",
            "action_code": "CREATE_PROGRAMMATIC_ROUTE",
            "priority_score": 5.0,
        }],
        now=dep_time,
    )
    leased = lease_tasks(temp_db, domain="openfileconverter.com", limit=1, now=dep_time)
    task_id = leased[0]["id"]

    # Record shipped experiment with matched control page
    record_experiment(
        temp_db,
        task_id=task_id,
        domain="openfileconverter.com",
        page="https://openfileconverter.com/convert/bmp-to-png/",
        target_query="bmp png",
        action_code="CREATE_PROGRAMMATIC_ROUTE",
        deployed_at=dep_time,
        baseline_clicks_28d=5.0,
        baseline_impressions_28d=200.0,
        baseline_position=12.0,
        control_cohort_page="https://openfileconverter.com/convert/gif-to-png/",
        control_baseline_clicks=10.0,
    )

    # Simulate 29 days later fresh GSC data:
    # Treatment page went from 5 -> 15 clicks (+200% treatment lift)
    # Control page went from 10 -> 11 clicks (+10% control lift)
    fresh_gsc = {
        "bmp png\nhttps://openfileconverter.com/convert/bmp-to-png/": {
            "page": "https://openfileconverter.com/convert/bmp-to-png/",
            "query": "bmp png",
            "clicks": 15.0,
            "impressions": 450.0,
            "position": 5.2,
            "ctr": 0.033,
        },
        "gif png\nhttps://openfileconverter.com/convert/gif-to-png/": {
            "page": "https://openfileconverter.com/convert/gif-to-png/",
            "query": "gif png",
            "clicks": 11.0,
            "impressions": 250.0,
            "position": 10.0,
            "ctr": 0.044,
        },
    }

    res = evaluate_domain_experiments(temp_db, "openfileconverter.com", fresh_gsc, now=eval_time)
    assert res["outcomes"]["graded"] == 1

    summary = res["summary"]
    assert summary["graded"] == 1
    assert summary["has_measured_outcomes"] is True
    # Incremental clicks = treatment clicks (15) - baseline*(1 + control_lift) = 15 - 5*(1.10) = 9.5
    assert summary["total_incremental_clicks"] >= 9.0

    # Verify action effectiveness stats updated
    eff = get_action_effectiveness(temp_db, "openfileconverter.com", "CREATE_PROGRAMMATIC_ROUTE", "convert")
    assert eff["total_experiments"] == 1
    assert eff["win_rate"] == 1.0
    assert eff["has_empirical_evidence"] is True


def test_cross_property_isolation_in_experiments(temp_db):
    """Strict Rule 16: Experiments and metrics on Domain A never pollute Domain B."""
    now = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)
    record_experiment(
        temp_db,
        domain="smsriver.com",
        page="https://smsriver.com/number/12025550199/",
        target_query="receive sms online",
        action_code="ADD_D1_SPEC_COMPARISON_TABLE",
        deployed_at=now,
        baseline_clicks_28d=50.0,
    )
    record_experiment(
        temp_db,
        domain="openfileconverter.com",
        page="https://openfileconverter.com/studio/whisper/",
        target_query="whisper transcription",
        action_code="INJECT_EXACT_TITLE_AND_H2",
        deployed_at=now,
        baseline_clicks_28d=2.0,
    )

    ofc_summary = get_experiment_summary(temp_db, "openfileconverter.com")
    sms_summary = get_experiment_summary(temp_db, "smsriver.com")

    assert ofc_summary["total_experiments"] == 1
    assert sms_summary["total_experiments"] == 1

    # Update outcomes for openfileconverter only
    fresh_gsc_ofc = {
        "whisper transcription\nhttps://openfileconverter.com/studio/whisper/": {
            "page": "https://openfileconverter.com/studio/whisper/",
            "clicks": 10.0,
            "impressions": 300.0,
            "position": 4.0,
        }
    }
    update_experiment_outcomes(
        temp_db,
        "openfileconverter.com",
        fresh_gsc_ofc,
        days_elapsed=30,
        now=now + timedelta(days=30),
    )

    ofc_updated = get_experiment_summary(temp_db, "openfileconverter.com")
    sms_updated = get_experiment_summary(temp_db, "smsriver.com")

    assert ofc_updated["graded"] == 1
    assert sms_updated["graded"] == 0  # smsriver remains completely unmutated


def test_two_part_scorecard_reporting(temp_db):
    """Verifies that format_two_part_scorecard displays NOT YET MEASURED when within observation window."""
    summary_pending = {
        "domain": "openfileconverter.com",
        "total_experiments": 9,
        "pending_recrawl": 7,
        "observing": 2,
        "graded": 0,
        "has_measured_outcomes": False,
    }
    scorecard = format_two_part_scorecard(
        domain="openfileconverter.com",
        execution_score=9.8,
        execution_breakdown={"isolation": 10.0, "deploy": 9.8},
        summary=summary_pending,
    )
    assert "Part 1: Engineering Execution Quality" in scorecard
    assert "9.8 / 10.0" in scorecard
    assert "Part 2: Measured SEO & Business Effectiveness" in scorecard
    assert "NOT YET MEASURED" in scorecard
    assert "active Googlebot recrawl and 28-day observation window" in scorecard
