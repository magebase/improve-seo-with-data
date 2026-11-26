"""Pre-flight schema, intent, and missing-evidence contracts."""

from __future__ import annotations

from collect_features import (
    classify_page_intent,
    classify_query_intent,
    contract_for_page,
    intent_matches,
    load_or_fetch_search_volumes,
    load_page_contracts,
)
from fleet_state import connect_state_db, save_serp_volumes
from indexation_forecast import evaluate_launch_candidate, extract_launch_features


def test_consumer_verification_query_does_not_match_a_comparison_page():
    query = "Receive Gmail verification code online free"
    assert classify_query_intent(query) == "verification"
    assert (
        classify_page_intent("https://example.com/compare/smspool-vs-temp-number/")
        == "comparison"
    )
    assert (
        intent_matches("https://example.com/compare/smspool-vs-temp-number/", query)
        is False
    )


def test_consumer_verification_query_matches_a_verification_page():
    query = "Receive Gmail verification code online free"
    assert intent_matches("https://example.com/verify/gmail/", query) is True


def test_volume_is_normalised_and_never_borrowed_from_another_query():
    conn = connect_state_db(":memory:")
    save_serp_volumes(conn, {"Burner Phone Number": 6600.0})
    volumes = load_or_fetch_search_volumes(
        conn, ["burner phone number", "unrelated query"]
    )
    assert volumes == {"burner phone number": 6600.0}
    assert "unrelated query" not in volumes
    conn.close()


def test_new_route_without_serp_is_unscored_not_high_probability():
    decision = evaluate_launch_candidate(
        {
            "query": "receive sms online in germany",
            "page": "https://example.com/receive-sms/de/",
            "candidate_kind": "new_route",
            "search_volume_log": 2.4,
            "unique_data_fields": 5,
            "planned_indexed_inlinks": 4,
            "sibling_similarity": 0.18,
            "non_boilerplate_ratio": 0.8,
            "intent_match": True,
        }
    )
    assert decision.eligible is False
    assert decision.status == "unscored_missing_serp"
    assert decision.p_index_28d == 0.0


def test_existing_page_launch_is_enrichment_not_a_new_route():
    decision = evaluate_launch_candidate(
        {
            "query": "receive sms",
            "page": "https://example.com/receive-sms/",
            "candidate_kind": "existing_page",
            "coverage_state": "Crawled - currently not indexed",
        }
    )
    assert decision.eligible is False
    assert decision.status == "existing_page_requires_enrichment"


def test_gate_features_are_flat_and_explicit():
    features = extract_launch_features(
        {
            "query": "q",
            "page": "https://example.com/x/",
            "candidate_kind": "new_route",
            "search_volume_log": 2.4,
            "unique_data_fields": 5,
            "planned_indexed_inlinks": 4,
            "sibling_similarity": 0.18,
            "non_boilerplate_ratio": 0.8,
            "serp_fetched": True,
            "intent_match": True,
        }
    )
    assert features["search_volume_log"] == 2.4
    assert features["planned_indexed_inlinks"] == 4.0
    assert features["serp_fetched"] == 1.0
    assert features["intent_match"] == 1.0


def test_page_contract_is_loaded_by_family_and_page(tmp_path):
    path = tmp_path / "contracts.json"
    path.write_text(
        '{"receive-sms": {"unique_data_fields": 5, "planned_indexed_inlinks": 4, "non_boilerplate_ratio": 0.8}}',
        encoding="utf-8",
    )
    contracts = load_page_contracts(str(path))
    contract = contract_for_page("https://example.com/receive-sms/de/", contracts)
    assert contract["unique_data_fields"] == 5
    assert contract["planned_indexed_inlinks"] == 4
