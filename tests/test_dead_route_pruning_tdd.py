"""Post-launch pruning contract: unindexed + unseen after the window."""

import json
from datetime import datetime, timedelta, timezone

from fleet_state import connect_state_db, dead_route_candidates


def _insert(conn, url, coverage, launched_at, impressions):
    conn.execute(
        """
        INSERT INTO page_launch_outcomes
        (domain, url, template_family, launched_at, coverage_state, features_json, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "smsriver.com",
            url,
            "receive-sms",
            launched_at,
            coverage,
            json.dumps({"impressions": impressions}),
            launched_at,
        ),
    )
    conn.commit()


def test_unindexed_and_unseen_route_is_flagged_for_pruning(tmp_path):
    conn = connect_state_db(":memory:")
    old = (datetime.now(timezone.utc) - timedelta(days=50)).isoformat()
    _insert(
        conn,
        "https://smsriver.com/receive-sms/at/",
        "Crawled - currently not indexed",
        old,
        0,
    )
    assert (
        dead_route_candidates(conn, "smsriver.com")[0]["recommendation"]
        == "noindex_or_merge"
    )
    conn.close()


def test_indexed_or_seen_route_is_not_pruned():
    conn = connect_state_db(":memory:")
    old = (datetime.now(timezone.utc) - timedelta(days=50)).isoformat()
    _insert(
        conn, "https://smsriver.com/receive-sms/gb/", "Submitted and indexed", old, 100
    )
    assert dead_route_candidates(conn, "smsriver.com") == []
    conn.close()
