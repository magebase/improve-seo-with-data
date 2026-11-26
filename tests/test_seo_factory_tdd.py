"""Unified pSEO state-machine contracts."""

from __future__ import annotations

from fleet_state import connect_state_db
from seo_factory import (
    advance_cohort,
    classify_disposal,
    compute_stripped_overlap,
    create_cohort,
    discover_cluster_candidates,
    evaluate_cluster,
    finalize_footprint,
    plan_site_repair,
    record_cohort_measurement,
    register_page_contract,
    save_cluster,
    select_keep_list,
    should_noindex_empty_state,
    validate_page_contract,
)

SITEMAP = [
    "https://smsriver.com/",
    "https://smsriver.com/receive-sms/gb/",
    "https://smsriver.com/country-codes/",
    "https://smsriver.com/country-codes/germany/",
    "https://smsriver.com/compare/",
    "https://smsriver.com/compare/twilio-vs-plivo/",
    "https://smsriver.com/guides/",
    "https://smsriver.com/guides/short-code-vs-10dlc-vs-toll-free-sms-comparison/",
    "https://smsriver.com/status/",
]


def _row(url, **overrides):
    row = {
        "url": url,
        "clicks_90d": 0,
        "impressions_90d": 0,
        "coverage_state": "Crawled - currently not indexed",
        "backlinks": 0,
    }
    row.update(overrides)
    return row


def test_protected_url_is_never_merged_or_deleted():
    decision = classify_disposal(
        _row("https://smsriver.com/receive-sms/gb/", clicks_90d=1),
        sitemap_urls=SITEMAP,
    )
    assert decision["decision"] == "PROTECT"


def test_country_codes_hub_is_not_redirected_into_a_child():
    decision = classify_disposal(
        _row("https://smsriver.com/country-codes/", impressions_90d=100),
        sitemap_urls=SITEMAP,
    )
    assert decision["decision"] == "ENRICH"
    assert decision["target"] is None


def test_country_code_child_merges_to_its_hub():
    decision = classify_disposal(
        _row("https://smsriver.com/country-codes/germany/"),
        sitemap_urls=SITEMAP,
    )
    assert decision["decision"] == "MERGE_301"
    assert decision["target"] == "https://smsriver.com/country-codes/"


def test_compare_child_without_absorbed_value_is_gone_not_301():
    decision = classify_disposal(
        _row("https://smsriver.com/compare/twilio-vs-plivo/"),
        sitemap_urls=SITEMAP,
    )
    assert decision["decision"] == "GONE_410"


def test_compare_child_with_backlinks_keeps_equity_via_301():
    decision = classify_disposal(
        _row(
            "https://smsriver.com/compare/twilio-vs-plivo/",
            backlinks=3,
            legitimate_referring_domains=1,
        ),
        sitemap_urls=SITEMAP,
    )
    assert decision["decision"] == "MERGE_301"
    assert decision["target"] == "https://smsriver.com/compare/"


def test_compare_child_with_only_spam_backlinks_is_gone():
    decision = classify_disposal(
        _row("https://smsriver.com/compare/twilio-vs-plivo/", backlinks=3),
        sitemap_urls=SITEMAP,
    )
    assert decision["decision"] == "GONE_410"


def test_guide_child_with_absorbed_content_can_301():
    decision = classify_disposal(
        _row(
            "https://smsriver.com/guides/short-code-vs-10dlc-vs-toll-free-sms-comparison/",
            content_absorbed=True,
        ),
        sitemap_urls=SITEMAP,
    )
    assert decision["decision"] == "MERGE_301"
    assert decision["target"] == "https://smsriver.com/guides/"


def test_live_inventory_country_page_is_enriched_not_gone():
    decision = classify_disposal(
        _row("https://smsriver.com/receive-sms/au/", live_inventory_count=19),
        sitemap_urls=SITEMAP,
    )
    assert decision["decision"] == "ENRICH"


def test_user_facing_status_page_is_noindexed():
    decision = classify_disposal(
        _row("https://smsriver.com/status/"), sitemap_urls=SITEMAP
    )
    assert decision["decision"] == "NOINDEX"


def test_page_with_impressions_but_no_clicks_is_enriched():
    decision = classify_disposal(
        _row("https://smsriver.com/receive-sms/gb/", impressions_90d=50),
        sitemap_urls=SITEMAP,
    )
    assert decision["decision"] == "ENRICH"


def test_zero_value_url_without_parent_is_gone():
    decision = classify_disposal(
        _row("https://smsriver.com/orphan/"), sitemap_urls=SITEMAP
    )
    assert decision["decision"] == "GONE_410"


def test_repair_plan_persists_url_lifecycle():
    conn = connect_state_db(":memory:")
    plan = plan_site_repair(
        [_row("https://smsriver.com/status/")],
        sitemap_urls=SITEMAP,
        domain="smsriver.com",
        conn=conn,
    )
    assert plan["counts"]["NOINDEX"] == 1
    state = conn.execute(
        "SELECT state FROM url_lifecycle WHERE url = ?",
        ("https://smsriver.com/status/",),
    ).fetchone()[0]
    assert state == "NOINDEX"
    action = conn.execute(
        "SELECT action FROM repair_actions WHERE url = ?",
        ("https://smsriver.com/status/",),
    ).fetchone()[0]
    assert action == "NOINDEX"
    conn.close()


def test_empty_state_guard_noindexes_after_two_weeks_without_inventory():
    assert should_noindex_empty_state(zero_inventory_days=15) is True
    assert (
        should_noindex_empty_state(zero_inventory_days=15, has_unique_telemetry=True)
        is False
    )
    assert should_noindex_empty_state(zero_inventory_days=3) is False


def test_contract_rejects_thin_or_duplicated_payload():
    bad = {
        "url": "https://smsriver.com/verify/discord/",
        "cluster_id": "c1",
        "data_source_hash": "abc",
        "unique_data_fields": 2,
        "stripped_overlap_score": 0.7,
        "planned_indexed_inlinks": 1,
    }
    result = validate_page_contract(bad)
    assert result["valid"] is False
    assert "insufficient_unique_data_fields" in result["reasons"]
    assert "entity_stripped_overlap_too_high" in result["reasons"]


def test_valid_contract_is_registered():
    conn = connect_state_db(":memory:")
    contract = {
        "url": "https://smsriver.com/verify/discord/",
        "cluster_id": "c1",
        "tier": "B",
        "data_source_hash": "abc",
        "unique_data_fields": 5,
        "stripped_overlap_score": 0.2,
        "planned_indexed_inlinks": 4,
    }
    result = register_page_contract(conn, contract)
    assert result["valid"] is True
    assert (
        conn.execute(
            "SELECT status FROM page_contracts WHERE url = ?", (contract["url"],)
        ).fetchone()[0]
        == "VALID"
    )
    conn.close()


def test_entity_stripping_detects_near_duplicate_prose():
    texts = [
        "Germany free sms online receive verification code instantly",
        "France free sms online receive verification code instantly",
    ]
    score = compute_stripped_overlap(texts, ["Germany", "France"])
    assert score > 0.45


def test_cluster_requires_demand_and_weak_top10():
    authority = {
        "reddit.com": {"referring_domains": 5000},
        "thin.example": {"referring_domains": 40},
        "big.example": {"referring_domains": 50000},
    }
    result = evaluate_cluster(
        volumes=[40.0] * 15,
        top10_domains=["reddit.com", "thin.example", "big.example"],
        authority=authority,
    )
    assert result["winnable"] is True
    assert result["weak_top10_count"] == 2


def test_cohort_scales_only_after_indexation_and_impressions():
    conn = connect_state_db(":memory:")
    cohort = create_cohort(
        conn,
        template_id="verify-entity",
        domain="smsriver.com",
        urls=[f"https://smsriver.com/verify/x{i}/" for i in range(5)],
    )
    record_cohort_measurement(
        conn, cohort["cohort_id"], day=21, indexed=9, total=10, impressions=0
    )
    assert advance_cohort(conn, cohort["cohort_id"])["stage"] == "PILOT_LIVE"
    record_cohort_measurement(
        conn, cohort["cohort_id"], day=45, indexed=9, total=10, impressions=10
    )
    assert advance_cohort(conn, cohort["cohort_id"])["stage"] == "SCALING"
    conn.close()


def test_cohort_freezes_below_fifty_percent_at_day21():
    conn = connect_state_db(":memory:")
    cohort = create_cohort(
        conn,
        template_id="t",
        domain="d.com",
        urls=[f"https://d.com/x{i}/" for i in range(5)],
    )
    result = record_cohort_measurement(
        conn, cohort["cohort_id"], day=21, indexed=3, total=10, impressions=5
    )
    assert result["stage"] == "FROZEN"
    assert result["verdict"] == "FREEZE_AND_REVIEW_CONTRACT"
    conn.close()


def test_outside_in_discovery_uses_real_serp_and_authority():
    class FakeClient:
        def keyword_suggestions(self, seeds, limit=100):
            return [
                {"keyword": f"test harness sms {i}", "volume": 40} for i in range(15)
            ]

        def fetch_serp_live(self, keyword, depth=10):
            return [
                {
                    "items": [
                        {"type": "organic", "domain": "reddit.com"},
                        {"type": "organic", "domain": "thin.example"},
                        {"type": "organic", "domain": "big.example"},
                    ]
                }
            ]

        def backlinks_summary(self, domain):
            return {
                "reddit.com": {"referring_domains": 5000},
                "thin.example": {"referring_domains": 30},
                "big.example": {"referring_domains": 50000},
            }[domain]

    funnel: dict = {}
    rows = discover_cluster_candidates(
        FakeClient(), seeds=["test harness"], niche="developer", diagnostics=funnel
    )
    assert len(rows) == 1
    assert rows[0]["volume"] == 600.0
    assert rows[0]["entities"] == 15
    assert rows[0]["winnable"] is True
    assert rows[0]["weak_top10_count"] == 2
    assert funnel["raw_suggestions"] == 15
    assert funnel["valid_entities"] == 15
    assert funnel["aggregate_demand"] == 600.0
    assert funnel["serps_checked"] == 5
    assert funnel["rejection_reason"] == ""


def test_discovered_cluster_is_persisted():
    conn = connect_state_db(":memory:")
    saved = save_cluster(
        conn,
        niche="developer",
        entity_pattern="test harness sms",
        evaluation={
            "demand_score": 120,
            "winnability_score": 70,
            "weakest_top10_rd": 30,
            "winnable": True,
        },
    )
    assert saved["status"] == "WINNABLE"
    assert (
        conn.execute(
            "SELECT status FROM clusters WHERE cluster_id = ?", (saved["cluster_id"],)
        ).fetchone()[0]
        == "WINNABLE"
    )
    conn.close()


def test_finalize_caps_footprint_and_noindexes_non_keep_inventory():
    decisions = [
        {"url": "https://smsriver.com/", "decision": "PROTECT", "evidence": {}},
        {
            "url": "https://smsriver.com/receive-sms/gb/",
            "decision": "ENRICH",
            "evidence": {"impressions_90d": 200, "live_inventory_count": 124},
        },
        {
            "url": "https://smsriver.com/receive-sms/de/",
            "decision": "ENRICH",
            "evidence": {"impressions_90d": 0, "live_inventory_count": 75},
        },
        {
            "url": "https://smsriver.com/orphan/",
            "decision": "ENRICH",
            "evidence": {"impressions_90d": 0, "live_inventory_count": 0},
        },
    ]
    keep = select_keep_list(decisions, limit=2)
    assert keep == ["https://smsriver.com/", "https://smsriver.com/receive-sms/gb/"]
    final = finalize_footprint(decisions, keep_urls=keep)
    assert final["counts"]["NOINDEX"] == 1
    assert final["counts"]["GONE_410"] == 1


def test_discover_reports_empty_funnel_instead_of_a_black_box():
    class EmptyClient:
        def keyword_suggestions(self, seeds, limit=100):
            return [{"keyword": "x", "volume": 0}]

    funnel: dict = {}
    rows = discover_cluster_candidates(
        EmptyClient(), seeds=["x"], niche="test", diagnostics=funnel
    )
    assert rows == []
    assert funnel["raw_suggestions"] == 1
    assert funnel["valid_entities"] == 0
    assert funnel["rejection_reason"] == "no_valid_entities"
