"""TDD contracts for the programmatic-route launch gate in the wave compiler."""

from __future__ import annotations

from ltr_ranker import compile_wave_backlog


def _row(**overrides):
    row = {
        "query": "receive sms online in germany",
        "page": "https://example.com/receive-sms/de/",
        "current_pos": 95.0,
        "impressions": 0.0,
        "clicks_30d": 0.0,
        "rank_score": 1.0,
        "source": "gsc",
        "search_volume_log": 3.0,
        "template_index_rate": 0.82,
        "unique_data_fields": 8,
        "sibling_similarity": 0.18,
        "inlinks_from_indexed": 5,
        "features": {
            "title_exact_match_rate": 0.9,
            "parent_hub_internal_links": 5.0,
            "search_volume_log": 3.0,
            "template_index_rate": 0.82,
            "unique_data_fields": 8,
            "sibling_similarity": 0.18,
            "inlinks_from_indexed": 5,
        },
    }
    row.update(overrides)
    return row


def test_matrix_pair_without_demand_is_not_compiled_into_a_new_page():
    tasks = compile_wave_backlog(
        [
            {
                "query": "receive sms online in de",
                "page": "https://example.com/receive-sms/de/",
                "current_pos": 100.0,
                "impressions": 0.0,
                "clicks_30d": 0.0,
                "rank_score": 1.0,
                "source": "catalog_matrix",
            }
        ],
        target_wave_size=10,
    )
    assert tasks == []


def test_evidence_backed_route_is_compiled_with_forecast_fields():
    tasks = compile_wave_backlog([_row()], target_wave_size=10)
    assert [task["action_code"] for task in tasks] == ["CREATE_PROGRAMMATIC_ROUTE"]
    task = tasks[0]
    assert task["p_index_28d"] >= 0.70
    assert task["p_index_56d"] >= 0.80
    assert task["launch_evidence"]["unique_data_fields"] == 8
    assert task["launch_evidence"]["sibling_similarity"] == 0.18
    assert task["launch_features"]["unique_data_fields"] == 8
    assert task["template_family"] == "receive-sms"


def test_high_similarity_blocks_the_route():
    tasks = compile_wave_backlog([_row(sibling_similarity=0.85)], target_wave_size=10)
    assert tasks == []


def test_existing_owner_blocks_the_route():
    tasks = compile_wave_backlog([_row(has_existing_owner=True)], target_wave_size=10)
    assert tasks == []


def test_zero_inlinks_blocks_the_route():
    tasks = compile_wave_backlog([_row(inlinks_from_indexed=0)], target_wave_size=10)
    assert tasks == []


def test_queue_launch_action_without_evidence_is_removed():
    from ltr_ranker import filter_launch_queue

    queue = [
        {
            "action_code": "LAUNCH_PSEO_ROUTE",
            "query": "new country service pair",
            "page": "https://example.com/receive-sms/de/whatsapp/",
            "current_pos": 100.0,
            "impressions": 0.0,
        },
        {
            "action_code": "INJECT_EXACT_TITLE_AND_H2",
            "query": "existing page",
            "page": "https://example.com/existing/",
        },
    ]
    kept, blocked = filter_launch_queue(queue)
    assert [row["action_code"] for row in kept] == ["INJECT_EXACT_TITLE_AND_H2"]
    assert blocked[0]["reasons"]


def test_legacy_override_is_explicit_and_never_the_default():
    row = {
        "query": "legacy synthetic",
        "page": "https://example.com/legacy/",
        "current_pos": 100.0,
        "impressions": 0.0,
        "rank_score": 1.0,
        "source": "catalog_matrix",
    }
    default_tasks = compile_wave_backlog([row], target_wave_size=10)
    legacy_tasks = compile_wave_backlog(
        [row],
        target_wave_size=10,
        enforce_launch_gate=False,
    )
    assert default_tasks == []
    assert [task["action_code"] for task in legacy_tasks] == [
        "CREATE_PROGRAMMATIC_ROUTE"
    ]
