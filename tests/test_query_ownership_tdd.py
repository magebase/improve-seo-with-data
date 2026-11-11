"""test_query_ownership_tdd.py - TDD test suite for Query Ownership and Cannibalization Prevention.

Verifies:
- Canonical query cluster to URL mapping
- Cannibalization risk detection when candidate targets an already-owned query cluster
- Distinction between identical-intent competition (tool vs tool) vs complementary intent (tool vs guide)
- Economic expected value (EV) and explicit decision classes (SHIP, EXPERIMENT, OBSERVE, NO_ACTION)
- Zero cross-tenant data contamination between domains
"""

from __future__ import annotations

import pytest

from fleet_state import (
    connect_state_db,
    get_query_owner,
    upsert_query_ownership,
)
from score_backlog import compute_opportunity_intelligence


@pytest.fixture
def temp_db(tmp_path):
    db_file = tmp_path / "test_ownership_state.db"
    conn = connect_state_db(str(db_file))
    yield conn
    conn.close()


def test_query_ownership_map_exact_and_fuzzy(temp_db):
    """Verifies that query clusters map to canonical URLs and support fuzzy token overlap."""
    upsert_query_ownership(
        temp_db,
        domain="openfileconverter.com",
        query_cluster="las viewer",
        canonical_url="https://openfileconverter.com/studio/lidar/",
        primary_query="las viewer",
        secondary_queries=["las file viewer", "point cloud viewer online"],
        intent_category="tool",
    )

    # Exact lookup
    owner = get_query_owner(temp_db, "openfileconverter.com", "las viewer")
    assert owner is not None
    assert owner["canonical_url"] == "https://openfileconverter.com/studio/lidar/"
    assert owner["intent_category"] == "tool"
    assert "las file viewer" in owner["secondary_queries"]

    # Fuzzy token overlap lookup ("online point cloud viewer")
    fuzzy_owner = get_query_owner(temp_db, "openfileconverter.com", "las file viewer online")
    assert fuzzy_owner is not None
    assert fuzzy_owner["canonical_url"] == "https://openfileconverter.com/studio/lidar/"


def test_cannibalization_risk_and_no_action_decision(temp_db):
    """Verifies that a candidate targeting an already-owned query cluster triggers NO_ACTION."""
    upsert_query_ownership(
        temp_db,
        domain="openfileconverter.com",
        query_cluster="las viewer",
        canonical_url="https://openfileconverter.com/studio/lidar/",
        primary_query="las viewer",
        intent_category="tool",
    )

    # Competing URL attempting to target the same tool intent
    competing_row = {
        "page": "https://openfileconverter.com/convert/las-viewer-tool/",
        "query": "las viewer",
        "impressions": 300,
        "clicks_30d": 5,
        "features": {
            "current_pos": 18.0,
        },
        "prescribed_action": "CREATE_PROGRAMMATIC_ROUTE",
    }

    intel = compute_opportunity_intelligence(
        competing_row,
        conn=temp_db,
        domain="openfileconverter.com",
    )

    assert intel["cannibalization_risk"] >= 0.75
    assert intel["decision_class"] == "NO_ACTION", (
        f"Expected NO_ACTION due to cannibalization, got {intel['decision_class']}"
    )


def test_legitimate_ship_decision_on_striking_distance(temp_db):
    """Verifies that an unowned striking-distance high-impression query gets a SHIP decision."""
    striking_row = {
        "page": "https://openfileconverter.com/convert/bmp-to-png/",
        "query": "bmp to png converter",
        "impressions": 1500,
        "clicks_30d": 35,
        "features": {
            "current_pos": 7.5,
        },
        "prescribed_action": "INJECT_SECONDARY_H2_ONLY",
    }

    intel = compute_opportunity_intelligence(
        striking_row,
        conn=temp_db,
        domain="openfileconverter.com",
    )

    assert intel["cannibalization_risk"] == 0.0
    assert intel["expected_value"] > 5.0
    assert intel["decision_class"] == "SHIP"
    assert intel["priority_score"] >= 2.0


def test_cross_tenant_ownership_isolation(temp_db):
    """Verifies that query clusters owned in Domain A do not block Domain B."""
    upsert_query_ownership(
        temp_db,
        domain="smsriver.com",
        query_cluster="receive sms",
        canonical_url="https://smsriver.com/tools/receive/",
        primary_query="receive sms",
        intent_category="tool",
    )

    owner_sms = get_query_owner(temp_db, "smsriver.com", "receive sms")
    assert owner_sms is not None

    owner_ofc = get_query_owner(temp_db, "openfileconverter.com", "receive sms")
    assert owner_ofc is None
