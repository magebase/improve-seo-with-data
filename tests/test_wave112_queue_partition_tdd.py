"""Wave 112 TDD: demand and route-rescue candidates must never share a queue.

Empirical driver: the Wave 111 scoring run on smsrvier.com produced a 20-slot
queue in which **17 slots were `orphan_route` rows** and only 3 carried real
GSC demand. The orphan rows are synthesized at `current_pos=100` with a
slug-derived query, so their feature vectors are degenerate and the ranker
outputs one flat score (`0.026`) for all of them; ties then bury the rows that
actually have impressions. The compiled wave consequently emitted heading
edits for phone-number "queries" (`5493812234024`, `33754057766`) that no page
can ever rank for, and 7 such rows are sitting in the live PENDING cursor.

The contract pinned here:
1. Demand ranking only ever sees demand rows.
2. Zero-impression route candidates travel in their own `route_rescue` list.
3. A phone number / numeric prefix is a lookup, not heading-addressable demand.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from cursor_hygiene import is_clean_english_query
from ltr_ranker import (
    is_route_rescue_row,
    partition_demand_and_rescue,
    split_action_queue,
)


def _demand(query: str, score: float, page: str = "https://smsriver.com/status/") -> dict:
    return {
        "page": page,
        "query": query,
        "source": "gsc_window",
        "rank_score": score,
        "priority_score": score,
        "cluster_id": query.split()[0],
        "impressions": 40,
        "clicks_30d": 0,
        "current_pos": 7.0,
    }


def _orphan(page: str, score: float = 9.9) -> dict:
    return {
        "page": page,
        "query": "hopi jitter delivery sla",
        "source": "orphan_route",
        "rank_score": score,
        "priority_score": score,
        "cluster_id": "tools",
        "impressions": 0,
        "clicks_30d": 0,
        "current_pos": 100.0,
    }


def test_route_rescue_detection_covers_every_orphan_signal():
    assert is_route_rescue_row({"source": "orphan_route"}) is True
    assert is_route_rescue_row({"is_sitemap_orphan": True}) is True
    assert is_route_rescue_row({"coverage_state": "Discovered - currently not indexed"}) is True
    assert is_route_rescue_row({"source": "gsc_window", "current_pos": 7.0}) is False


def test_partition_sends_orphans_to_the_rescue_list():
    demand, rescue = partition_demand_and_rescue(
        [_demand("receive sms", 0.4), _orphan("https://smsriver.com/tools/x/")]
    )
    assert [r["source"] for r in demand] == ["gsc_window"]
    assert [r["source"] for r in rescue] == ["orphan_route"]


def test_queue_never_spends_a_slot_on_a_route_rescue_row():
    rows = [_orphan(f"https://smsriver.com/tools/tool-{i}/") for i in range(30)]
    rows += [_demand(f"query {i}", score=0.01 * i) for i in range(10)]

    demand, rescue = partition_demand_and_rescue(rows)
    queue = split_action_queue(demand, n_exploit=7, n_explore=3)

    assert len(rescue) == 30
    assert len(queue) == 10, "queue must be filled from demand rows only"
    assert all(row["source"] != "orphan_route" for row in queue)


def test_queue_still_fills_to_size_when_demand_rows_dominate():
    rows = [_demand(f"query {i}", score=0.5 + i) for i in range(25)]
    demand, rescue = partition_demand_and_rescue(rows)
    queue = split_action_queue(demand, n_exploit=14, n_explore=6)

    assert len(rescue) == 0
    assert len(queue) == 20


@pytest.mark.parametrize(
    "query",
    ["5493812234024", "+14692466072", "60192577631", "12368791984", "0082"],
)
def test_phone_number_and_numeric_prefix_queries_are_not_heading_demand(query: str):
    """A lookup query can never be served by a heading edit: reject it."""
    assert is_clean_english_query(query) is False


@pytest.mark.parametrize(
    "query",
    ["0082 country code", "sms recive", "10dlc registration errors", "receive sms"],
)
def test_queries_with_real_words_survive_the_lookup_gate(query: str):
    assert is_clean_english_query(query) is True


def test_wave_compiler_refuses_lookup_queries():
    """compile_wave_backlog must never emit a heading task for a phone number."""
    from ltr_ranker import compile_wave_backlog

    rows = [
        {
            "page": "https://smsriver.com/",
            "query": "5493812234024",
            "source": "gsc_window",
            "rank_score": 0.9,
            "impressions": 12,
            "clicks_30d": 0,
            "current_pos": 12.0,
            "decision_class": "SHIP",
            "features": {"title_exact_match_rate": 0.0, "parent_hub_internal_links": 1.0},
            "shap": {},
        },
        {
            "page": "https://smsriver.com/status/",
            "query": "online sms status",
            "source": "gsc_window",
            "rank_score": 0.5,
            "impressions": 43,
            "clicks_30d": 0,
            "current_pos": 5.2,
            "decision_class": "SHIP",
            "features": {"title_exact_match_rate": 0.0, "parent_hub_internal_links": 9.0},
            "shap": {},
        },
    ]

    tasks = compile_wave_backlog(rows, target_wave_size=50)

    assert tasks, "the legitimate demand row must still compile"
    assert all(t["query"] != "5493812234024" for t in tasks)
    assert any(t["query"] == "online sms status" for t in tasks)


def test_exploration_never_duplicates_an_exploitation_row():
    """A tiny pool must not let one task occupy both queue slots."""
    rows = [_demand("online sms status", 0.9)]
    queue = split_action_queue(rows, n_exploit=3, n_explore=1)
    assert len(queue) == 1
