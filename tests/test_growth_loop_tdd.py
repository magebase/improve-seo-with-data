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
        "impressions": 5000.0,
        "clicks_30d": 2.0,
        "current_pos": 8.0,
        "ctr": 0.002,
        "coverage_state": "Submitted and indexed",
        "host_legitimate_rd": 500,
        "weakest_top10_rd": 50,
        "features": {
            "current_pos": 8.0,
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
            host_legitimate_rd=5000,
            p_index_28d=0.95,
            features={
                "current_pos": 8,
                "serp_forum_ratio": 0.60,
                "title_exact_match_rate": 0.10,
            },
        )
    )
    far = estimate_ranking_probability(
        _row(
            current_pos=45,
            inlinks_from_indexed=0,
            unique_data_fields=0,
            weakest_top10_rd=300,
            host_legitimate_rd=10,
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
    assert action["action_code"] not in {
        "CREATE_PROGRAMMATIC_ROUTE",
        "LAUNCH_PSEO_ROUTE",
    }
    assert plan["guarantee"] == "below_materiality_floor"
    assert action["action_code"] == "BUILD_TIER_A_ASSET"


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


def test_numeric_phone_queries_never_become_title_actions():
    plan = build_growth_plan(
        [
            _row(
                page="https://example.com/",
                query="5493812234024",
                impressions=5000.0,
                current_pos=3.0,
                coverage_state="Submitted and indexed",
                features={"current_pos": 3.0},
            ),
            _row(
                page="https://example.com/receive-sms/us/",
                query="receive sms usa",
                impressions=5000.0,
                current_pos=9.0,
                coverage_state="Submitted and indexed",
                features={"current_pos": 9.0},
            ),
        ],
        domain="example.com",
    )
    queries = {action["query"] for action in plan["actions"]}
    assert "5493812234024" not in queries
    assert "receive sms usa" in queries


def test_cached_inspection_failure_becomes_indexation_action():
    conn = connect_state_db(":memory:")
    ensure_growth_schema(conn)
    conn.execute(
        "INSERT INTO url_inspections (url, site, coverage_state, indexing_state, inspected_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (
            "https://example.com/orphan/",
            "sc-domain:example.com",
            "Discovered - currently not indexed",
            "INDEXING_ALLOWED",
            "2026-11-26T00:00:00+00:00",
        ),
    )
    conn.commit()

    plan = build_growth_plan([], domain="example.com", conn=conn)
    assert plan["actions"]
    assert plan["actions"][0]["action_code"] == "REQUEST_INDEXING"
    assert plan["actions"][0]["page"] == "https://example.com/orphan/"
    assert plan["guarantee"] == "indexation_prerequisite"


def test_domain_scoped_plan_never_falls_back_to_another_domain():
    plan = build_growth_plan(
        [_row(page="https://figiva.com/calculators/", query="crypto calculator")],
        domain="smsriver.com",
    )
    assert plan["guarantee"] == "information_only"
    assert plan["actions"][0]["page"] == "https://smsriver.com/"


def test_unindexed_page_never_gets_a_title_action():
    plan = build_growth_plan(
        [
            _row(
                page="https://example.com/receive-sms/us/",
                query="receive sms usa",
                impressions=5000.0,
                current_pos=8.0,
                coverage_state="Crawled - currently not indexed",
            )
        ],
        domain="example.com",
    )
    assert plan["guarantee"] == "indexation_prerequisite"
    assert plan["actions"]
    assert all(
        action["action_code"] != "REWRITE_TITLE_META" for action in plan["actions"]
    )
    assert all(action["priority_track"] == "indexation" for action in plan["actions"])


def test_sub_materiality_ctr_edit_escalates_instead_of_shipping_noise():
    plan = build_growth_plan(
        [
            _row(
                page="https://example.com/small/",
                query="small demand",
                impressions=60.0,
                current_pos=8.0,
                coverage_state="Submitted and indexed",
            )
        ],
        domain="example.com",
    )
    assert plan["guarantee"] == "below_materiality_floor"
    assert plan["actions"][0]["action_code"] == "BUILD_TIER_A_ASSET"
    assert not any(
        action["action_code"] == "REWRITE_TITLE_META" for action in plan["actions"]
    )


def test_authority_ratio_damps_an_impossible_top10_prior():
    strong = estimate_ranking_probability(
        _row(host_legitimate_rd=5000, weakest_top10_rd=50)
    )
    weak = estimate_ranking_probability(
        _row(host_legitimate_rd=42, weakest_top10_rd=674)
    )
    assert strong["p_top10"] > weak["p_top10"]
    assert weak["authority_ratio"] < 0.1
    assert weak["authority_factor"] < 0.3


def test_review_refuses_to_learn_from_a_sub_volume_baseline():
    conn = connect_state_db(":memory:")
    ensure_growth_schema(conn)
    plan = build_growth_plan([_row(impressions=20.0)], domain="example.com")
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
        {plan["actions"][0]["page"]: {"clicks": 5, "position": 5}},
        domain="example.com",
    )
    assert reviews[0]["status"] == "INSUFFICIENT_BASELINE"


def test_review_quarantines_a_window_overlapping_a_core_update():
    conn = connect_state_db(":memory:")
    ensure_growth_schema(conn)
    plan = build_growth_plan([_row()], domain="example.com")
    record_growth_plan(conn, plan)
    key = plan["actions"][0]["action_key"]
    complete_growth_action(conn, key, review_days=1)
    conn.execute(
        "UPDATE growth_actions SET due_at = ?, completed_at = ? WHERE action_key = ?",
        ("2026-12-20T00:00:00+00:00", "2026-12-01T00:00:00+00:00", key),
    )
    conn.commit()

    reviews = review_growth_actions(
        conn,
        {plan["actions"][0]["page"]: {"clicks": 99, "position": 3}},
        domain="example.com",
        now=datetime(2026, 12, 20, tzinfo=timezone.utc),
    )
    assert reviews[0]["status"] == "QUARANTINED_CORE_UPDATE"
    assert reviews[0]["outcome"]["reason"] == "core_update_window"


def test_crawled_not_indexed_requires_content_enrichment_not_title():
    plan = build_growth_plan(
        [
            _row(
                page="https://example.com/receive-sms/gb/",
                query="receive sms uk",
                coverage_state="Crawled - currently not indexed",
                impressions=1000.0,
            )
        ],
        domain="example.com",
    )
    assert plan["guarantee"] == "indexation_prerequisite"
    assert plan["actions"][0]["action_code"] == "ENRICH_UNIQUE_DATA"
    assert not any(
        action["action_code"] == "REWRITE_TITLE_META" for action in plan["actions"]
    )


def test_page_level_indexation_action_is_not_duplicated_per_query():
    plan = build_growth_plan(
        [
            _row(
                page="https://example.com/receive-sms/gb/",
                query="receive sms uk",
                coverage_state="Crawled - currently not indexed",
                impressions=1000.0,
            ),
            _row(
                page="https://example.com/receive-sms/gb/",
                query="sms receive",
                coverage_state="Crawled - currently not indexed",
                impressions=50.0,
            ),
        ],
        domain="example.com",
    )
    page_actions = [
        action
        for action in plan["actions"]
        if action["page"] == "https://example.com/receive-sms/gb/"
        and action["action_code"] == "ENRICH_UNIQUE_DATA"
    ]
    assert len(page_actions) == 1
