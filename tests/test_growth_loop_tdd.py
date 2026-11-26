"""Growth-loop contracts: non-empty plans, honest guarantees, and review state."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fleet_state import connect_state_db
from growth_loop import (
    build_growth_plan,
    complete_growth_action,
    ensure_growth_schema,
    estimate_ranking_probability,
    record_growth_plan,
    review_growth_actions,
)


def _row(**overrides):
    row = {
        "page": "https://example.com/receive-sms/gb/",
        "query": "receive sms uk",
        "impressions": 1000.0,
        "clicks_30d": 2.0,
        "current_pos": 12.0,
        "ctr": 0.002,
        "features": {
            "current_pos": 12.0,
            "serp_forum_ratio": 0.35,
            "title_exact_match_rate": 0.20,
            "serp_pixel_crowding": 0.30,
            "parent_hub_internal_links": 1.0,
            "search_volume_log": 3.4,
        },
    }
    row.update(overrides)
    if "features" in overrides:
        row["features"] = {**row["features"], **overrides["features"]}
    return row


def test_ranking_probability_rewards_near_open_and_linked_pages():
    near = estimate_ranking_probability(
        _row(
            current_pos=8,
            inlinks_from_indexed=12,
            unique_data_fields=8,
            weakest_top10_rd=5,
            p_index_28d=0.95,
            features={"current_pos": 8, "serp_forum_ratio": 0.60, "title_exact_match_rate": 0.10},
        )
    )
    far = estimate_ranking_probability(
        _row(
            current_pos=45,
            inlinks_from_indexed=0,
            unique_data_fields=0,
            weakest_top10_rd=300,
            p_index_28d=0.40,
            features={
                "current_pos": 45,
                "serp_forum_ratio": 0.0,
                "title_exact_match_rate": 0.90,
                "serp_pixel_crowding": 0.90,
            },
        )
    )
    assert near["p_top10"] > far["p_top10"]
    assert near["p_top3"] > far["p_top3"]
    assert 0.0 <= near["p_top10_lower"] <= near["p_top10"] <= 1.0


def test_plan_prefers_positive_measured_click_lift():
    plan = build_growth_plan([_row()], domain="example.com", limit=3)
    assert plan["guarantee"] == "positive_expected_click_lift"
    assert plan["positive_action_count"] >= 1
    assert plan["actions"][0]["expected_clicks_lower"] > 0
    assert plan["actions"][0]["action_code"] in {
        "INJECT_SECONDARY_H2_ONLY",
        "REWRITE_TITLE_META",
        "INJECT_CONTEXTUAL_INLINK",
    }
    assert plan["actions"][0]["evidence"]["ranking"]["model"] == "transparent_prior_v1"


def test_plan_never_returns_empty_and_never_fabricates_a_launch():
    plan = build_growth_plan(
        [
            _row(
                page="https://example.com/stale/",
                query="tiny demand",
                impressions=2.0,
                clicks_30d=0.0,
                current_pos=70.0,
                features={"current_pos": 70.0, "parent_hub_internal_links": 5.0},
            )
        ],
        domain="example.com",
    )
    assert len(plan["actions"]) == 1
    action = plan["actions"][0]
    assert action["action_code"] != "CREATE_PROGRAMMATIC_ROUTE"
    assert action["action_code"] != "LAUNCH_PSEO_ROUTE"
    assert plan["guarantee"] in {"fallback_existing_page", "information_only"}


def test_empty_input_returns_instrumentation_with_honest_guarantee():
    plan = build_growth_plan([], domain="example.com")
    assert plan["guarantee"] == "information_only"
    assert plan["actions"][0]["action_code"] == "INSTRUMENT_TELEMETRY"
    assert plan["actions"][0]["expected_clicks_lower"] == 0


def test_record_dedupes_open_actions_and_complete_releases_them():
    conn = connect_state_db(":memory:")
    ensure_growth_schema(conn)
    first = build_growth_plan([_row()], domain="example.com")
    assert record_growth_plan(conn, first) >= 1
    second = build_growth_plan([_row()], domain="example.com", conn=conn)
    assert second["actions"]
    open_keys = {action["action_key"] for action in first["actions"]}
    # An OPEN action is never re-emitted while it is still in flight.
    assert all(action["action_key"] not in open_keys for action in second["actions"])

    key = first["actions"][0]["action_key"]
    assert complete_growth_action(conn, key, commit_sha="abc123", review_days=1)
    assert not complete_growth_action(conn, key)


def test_review_marks_click_growth_as_success():
    conn = connect_state_db(":memory:")
    ensure_growth_schema(conn)
    plan = build_growth_plan([_row()], domain="example.com")
    record_growth_plan(conn, plan)
    key = plan["actions"][0]["action_key"]
    complete_growth_action(conn, key, review_days=1)
    conn.execute(
        "UPDATE growth_actions SET due_at = ? WHERE action_key = ?",
        ((datetime.now(timezone.utc) - timedelta(days=1)).isoformat(), key),
    )
    conn.commit()

    reviews = review_growth_actions(
        conn,
        {"https://example.com/receive-sms/gb/": {"clicks": 10, "position": 7}},
        domain="example.com",
    )
    assert reviews
    assert reviews[0]["status"] == "SUCCESS"
    assert reviews[0]["outcome"]["click_ok"] is True


def test_unmeasured_due_action_stays_awaiting_observation():
    conn = connect_state_db(":memory:")
    ensure_growth_schema(conn)
    plan = build_growth_plan([_row()], domain="example.com")
    record_growth_plan(conn, plan)
    key = plan["actions"][0]["action_key"]
    complete_growth_action(conn, key, review_days=1)
    conn.execute(
        "UPDATE growth_actions SET due_at = ? WHERE action_key = ?",
        ((datetime.now(timezone.utc) - timedelta(days=1)).isoformat(), key),
    )
    conn.commit()

    reviews = review_growth_actions(conn, {}, domain="example.com")
    assert reviews[0]["status"] == "AWAITING_OBSERVATION"
