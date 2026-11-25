"""Wave 114 TDD: seed the persistent query ownership map from measured GSC data.

Empirical driver (2026-11-17, GSC 7-day window): the brand query `smsriver`
returns EIGHT distinct URLs at positions 1.0-2.6 — `/` (17 impressions, 14
clicks), `/developer/claude-desktop-sms-integration/` (10, 0),
`/?country=CA` (8, 0), `/verify/google/` (7, 0),
`/developer/multi-tenant-virtual-carrier-pooling/` (5, 0),
`/#numbers-section` (1, 0), `/country-codes/` (1, 0), `/tools/` (1, 0).

`query_ownership_map` exists in the state DB and `get_query_owner` consumes it
to price cannibalization risk, but nothing ever populated it: the table holds
zero rows for every property, so `cannibalization_risk` is always 0.0 and the
compiler is free to propose brand edits on non-owner subpages.

This module turns measured (page, query, clicks, impressions, position) rows
into ownership decisions: one canonical owner per query, chosen by realised
clicks first (Google's own verdict), then position, then impressions.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from fleet_state import connect_state_db, get_query_owner  # noqa: E402
from seed_query_ownership import derive_ownership, seed_ownership  # noqa: E402


def _row(page: str, query: str, *, clicks: float, impressions: float, pos: float) -> dict:
    return {
        "page": page,
        "query": query,
        "clicks_30d": clicks,
        "impressions": impressions,
        "features": {"current_pos": pos},
    }


def test_brand_query_owner_is_the_page_that_earns_the_clicks():
    rows = [
        _row("https://smsriver.com/", "smsriver", clicks=14, impressions=17, pos=1.0),
        _row("https://smsriver.com/verify/google/", "smsriver", clicks=0, impressions=7, pos=1.0),
        _row("https://smsriver.com/?country=CA", "smsriver", clicks=0, impressions=8, pos=1.0),
    ]

    decisions = derive_ownership(rows)
    assert len(decisions) == 1
    decision = decisions[0]
    assert decision["canonical_url"] == "https://smsriver.com/"
    assert decision["ownership_risk_classification"] == "OWNED"
    assert decision["historical_traffic_share"] == pytest.approx(1.0)


def test_uncontested_query_is_owned_by_its_only_page():
    decisions = derive_ownership([_row("https://smsriver.com/status/", "online sms status", clicks=0, impressions=43, pos=5.2)])
    assert decisions[0]["ownership_risk_classification"] == "OWNED"
    assert decisions[0]["canonical_url"] == "https://smsriver.com/status/"


def test_split_traffic_without_a_clear_winner_is_flagged_competition():
    rows = [
        _row("https://smsriver.com/a/", "pdf to docx", clicks=2, impressions=50, pos=8.0),
        _row("https://smsriver.com/b/", "pdf to docx", clicks=2, impressions=50, pos=12.0),
    ]
    decisions = derive_ownership(rows)
    assert decisions[0]["ownership_risk_classification"] == "CONFIRMED_COMPETITION"
    assert decisions[0]["serp_overlap_score"] > 0.0


def test_secondary_queries_are_carried_on_the_owner_row():
    rows = [
        _row("https://smsriver.com/", "smsriver", clicks=10, impressions=12, pos=1.0),
        _row("https://smsriver.com/", "sms river", clicks=2, impressions=4, pos=2.0),
    ]
    decisions = derive_ownership(rows)
    by_query = {d["primary_query"]: d for d in decisions}
    assert by_query["smsriver"]["secondary_queries"] == []
    assert by_query["sms river"]["canonical_url"] == "https://smsriver.com/"


def test_seeding_is_idempotent_and_visible_to_the_risk_engine(tmp_path):
    db = tmp_path / "fleet_state.db"
    conn = connect_state_db(str(db))
    rows = [
        _row("https://smsriver.com/", "smsriver", clicks=14, impressions=17, pos=1.0),
        _row("https://smsriver.com/verify/google/", "smsriver", clicks=0, impressions=7, pos=1.0),
    ]

    first = seed_ownership(conn, domain="smsriver.com", rows=rows)
    second = seed_ownership(conn, domain="smsriver.com", rows=rows)

    assert first["written"] == second["written"] == 1
    count = conn.execute("SELECT COUNT(*) FROM query_ownership_map WHERE domain = 'smsriver.com'").fetchone()[0]
    assert count == 1  # one ownership row per query cluster

    owner = get_query_owner(conn, "smsriver.com", "smsriver", candidate_page="https://smsriver.com/verify/google/")
    assert owner is not None
    assert owner["canonical_url"].rstrip("/") == "https://smsriver.com"
    assert owner["cannibalization_risk"] > 0.5
    conn.close()
