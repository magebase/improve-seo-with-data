"""TDD contracts for the indexation forecast and launch evidence gate."""

from __future__ import annotations

import json
import math
import random
from datetime import datetime, timedelta, timezone

from fleet_state import connect_state_db
from indexation_forecast import (
    IndexationModel,
    backtest,
    evaluate_launch_candidate,
    extract_launch_features,
    labels_from_outcomes,
    record_indexation_outcome,
    record_launch_outcome,
    record_launches_from_tasks,
    sync_outcomes_from_inspections,
)


def _strong_candidate() -> dict:
    return {
        "query": "receive sms online in germany",
        "page": "https://example.com/receive-sms/de/",
        "current_pos": 95.0,
        "impressions": 90.0,
        "search_volume_log": 2.6,
        "template_index_rate": 0.82,
        "unique_data_fields": 7,
        "sibling_similarity": 0.18,
        "inlinks_from_indexed": 5,
    }


def _synthetic_pair() -> dict:
    return {
        "query": "receive sms online in de",
        "page": "https://example.com/receive-sms/de/",
        "current_pos": 100.0,
        "impressions": 0.0,
        "clicks_30d": 0.0,
        "source": "catalog_matrix",
    }


def test_synthetic_matrix_pair_never_clears_the_launch_gate():
    decision = evaluate_launch_candidate(_synthetic_pair())
    assert decision.eligible is False
    assert "no_demand_evidence" in decision.reasons
    assert "insufficient_unique_data" in decision.reasons
    assert "sibling_similarity_too_high" in decision.reasons
    assert "insufficient_indexed_inlinks" in decision.reasons


def test_evidence_backed_candidate_clears_the_launch_gate():
    decision = evaluate_launch_candidate(_strong_candidate())
    assert decision.eligible is True, decision.reasons
    assert decision.p_index_28d >= 0.70
    assert decision.p_index_56d >= 0.80
    assert decision.lower_28d >= 0.60
    assert decision.lower_56d >= 0.68
    assert decision.reasons == []


def test_high_similarity_blocks_even_a_high_demand_candidate():
    candidate = _strong_candidate()
    candidate["sibling_similarity"] = 0.82
    decision = evaluate_launch_candidate(candidate)
    assert decision.eligible is False
    assert "sibling_similarity_too_high" in decision.reasons


def test_existing_owner_blocks_new_url_creation():
    candidate = _strong_candidate()
    candidate["has_existing_owner"] = True
    decision = evaluate_launch_candidate(candidate)
    assert decision.eligible is False
    assert "query_owned_by_existing_page" in decision.reasons


def test_missing_data_fields_block_a_demand_backed_candidate():
    candidate = _strong_candidate()
    candidate["unique_data_fields"] = 1
    decision = evaluate_launch_candidate(candidate)
    assert decision.eligible is False
    assert "insufficient_unique_data" in decision.reasons


def test_launch_model_persists_and_round_trips(tmp_path):
    model = IndexationModel()
    path = model.save(tmp_path / "indexation.json")
    loaded = IndexationModel.load(path)
    before = model.predict(extract_launch_features(_strong_candidate()), 28)
    after = loaded.predict(extract_launch_features(_strong_candidate()), 28)
    assert math.isclose(before["probability"], after["probability"], rel_tol=1e-9)


def _training_records() -> list[dict]:
    """Deterministic labelled launch history with a learnable signal."""
    rng = random.Random(20261126)
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    records: list[dict] = []
    for index in range(220):
        volume_log = rng.uniform(0.0, 4.5)
        impressions_log = rng.uniform(0.0, 6.0)
        template_rate = rng.uniform(0.05, 0.95)
        unique_fields = rng.uniform(0, 9)
        similarity = rng.uniform(0.05, 0.95)
        inlinks = rng.uniform(0, 9)
        freshness = rng.uniform(0, 4)
        forum = rng.uniform(0, 1)
        title_match = rng.uniform(0.2, 1.0)
        owner = 1.0 if rng.random() < 0.12 else 0.0
        age_log = rng.uniform(0, 5)
        logit = (
            -5.2
            + 0.45 * volume_log
            + 0.55 * impressions_log
            + 0.25 * (inlinks / 3.0)
            + 2.1 * template_rate
            + 0.38 * unique_fields
            - 3.2 * similarity
            + 0.10 * freshness
            + 0.25 * forum
            - 0.20 * title_match
            - 2.4 * owner
            + 0.12 * age_log
        )
        probability = 1.0 / (1.0 + math.exp(-logit))
        label = 1 if rng.random() < probability else 0
        horizon = 28 if index % 2 == 0 else 56
        records.append(
            {
                "url": f"https://example.com/page-{index}/",
                "template_family": "receive-sms",
                "launched_at": (start + timedelta(days=index)).isoformat(),
                "horizon_days": horizon,
                "label": label,
                "features": {
                    "search_volume_log": volume_log,
                    "impressions_log": impressions_log,
                    "position_strength": rng.uniform(0, 1),
                    "template_index_rate": template_rate,
                    "unique_data_fields": unique_fields,
                    "sibling_similarity": similarity,
                    "inlinks_from_indexed": inlinks,
                    "freshness_days_log": freshness,
                    "serp_forum_ratio": forum,
                    "title_exact_match_rate": title_match,
                    "has_existing_owner": owner,
                    "page_age_days_log": age_log,
                },
            }
        )
    return records


def test_model_learns_the_historical_indexation_signal():
    records = _training_records()
    model = IndexationModel().fit(records[:160])
    assert model.fitted is True
    assert model.n_train >= 100

    # A strong evidence row must score above a weak synthetic pair.
    strong = model.predict(extract_launch_features(_strong_candidate()), 28)
    weak = model.predict(extract_launch_features(_synthetic_pair()), 28)
    assert strong["probability"] > weak["probability"]


def test_time_ordered_backtest_reports_usable_discrimination_and_precision():
    metrics = backtest(_training_records(), train_fraction=0.70, threshold=0.70)
    assert metrics["test_n"] >= 40
    assert metrics["auc"] >= 0.75, metrics
    assert metrics["brier"] <= 0.25, metrics
    assert metrics["precision"] >= 0.65, metrics


def test_outcome_ledger_labels_positive_negative_and_censors_recent_launches():
    conn = connect_state_db(":memory:")
    now = datetime.now(timezone.utc)

    # 70 days old, indexed on day 10 -> positive at 28 and 56.
    record_launch_outcome(
        conn,
        domain="example.com",
        url="https://example.com/indexed/",
        template_family="receive-sms",
        launched_at=(now - timedelta(days=70)).isoformat(),
        features=extract_launch_features(_strong_candidate()),
    )
    record_indexation_outcome(
        conn,
        domain="example.com",
        url="https://example.com/indexed/",
        coverage_state="Submitted and indexed",
        indexed_at=(now - timedelta(days=60)).isoformat(),
    )

    # 70 days old, still crawled-not-indexed -> negative at 28 and 56.
    record_launch_outcome(
        conn,
        domain="example.com",
        url="https://example.com/rejected/",
        template_family="receive-sms",
        launched_at=(now - timedelta(days=70)).isoformat(),
        features=extract_launch_features(_synthetic_pair()),
    )
    record_indexation_outcome(
        conn,
        domain="example.com",
        url="https://example.com/rejected/",
        coverage_state="Crawled - currently not indexed",
    )

    # Recent launch with no outcome yet -> censored, never guessed.
    record_launch_outcome(
        conn,
        domain="example.com",
        url="https://example.com/recent/",
        template_family="receive-sms",
        launched_at=(now - timedelta(days=2)).isoformat(),
        features=extract_launch_features(_strong_candidate()),
    )

    labels = labels_from_outcomes(conn)
    by_url = {(record["url"], record["horizon_days"]): record["label"] for record in labels}
    assert by_url[("https://example.com/indexed/", 28)] == 1
    assert by_url[("https://example.com/indexed/", 56)] == 1
    assert by_url[("https://example.com/rejected/", 28)] == 0
    assert by_url[("https://example.com/rejected/", 56)] == 0
    assert not any(record["url"].endswith("/recent/") for record in labels)

    # Idempotent upsert: a second launch record must not duplicate the row.
    record_launch_outcome(
        conn,
        domain="example.com",
        url="https://example.com/indexed/",
        template_family="receive-sms",
        launched_at=(now - timedelta(days=70)).isoformat(),
        features=extract_launch_features(_strong_candidate()),
    )
    count = conn.execute("SELECT COUNT(*) FROM page_launch_outcomes").fetchone()[0]
    assert count == 3
    conn.close()


def test_launch_tasks_are_persisted_to_the_outcome_ledger():
    conn = connect_state_db(":memory:")
    count = record_launches_from_tasks(
        conn,
        [
            {
                "action_code": "CREATE_PROGRAMMATIC_ROUTE",
                "domain": "example.com",
                "page": "https://example.com/receive-sms/de/",
                "template_family": "receive-sms",
                "source": "gsc",
                "p_index_28d": 0.84,
                "p_index_56d": 0.87,
                "launch_features": extract_launch_features(_strong_candidate()),
            },
            {
                "action_code": "INJECT_EXACT_TITLE_AND_H2",
                "domain": "example.com",
                "page": "https://example.com/existing/",
            },
        ],
    )
    assert count == 1
    row = conn.execute(
        "SELECT template_family, p_index_28d, p_index_56d FROM page_launch_outcomes"
    ).fetchone()
    assert row[0] == "receive-sms"
    assert row[1] == 0.84
    assert row[2] == 0.87
    conn.close()


def test_inspection_coverage_syncs_into_the_launch_ledger():
    conn = connect_state_db(":memory:")
    record_launch_outcome(
        conn,
        domain="example.com",
        url="https://example.com/receive-sms/de/",
        template_family="receive-sms",
        launched_at="2026-01-01T00:00:00+00:00",
        features=extract_launch_features(_strong_candidate()),
    )
    conn.execute(
        """
        INSERT INTO url_inspections
            (url, site, coverage_state, indexing_state, last_crawl_time, inspected_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            "https://example.com/receive-sms/de/",
            "sc-domain:example.com",
            "Submitted and indexed",
            "INDEXING_ALLOWED",
            "2026-01-05T00:00:00+00:00",
            "2026-01-06T00:00:00+00:00",
        ),
    )
    conn.commit()
    assert sync_outcomes_from_inspections(conn) == 1
    row = conn.execute(
        "SELECT coverage_state, first_crawled_at, indexed_at FROM page_launch_outcomes"
    ).fetchone()
    assert row[0] == "Submitted and indexed"
    assert row[1] == "2026-01-05T00:00:00+00:00"
    assert row[2] == "2026-01-06T00:00:00+00:00"
    conn.close()


def test_backtest_refuses_to_claim_metrics_from_too_few_records():
    metrics = backtest([], train_fraction=0.7)
    assert "error" in metrics
    assert metrics["n"] == 0


def test_feature_extraction_is_pessimistic_when_evidence_is_missing():
    features = extract_launch_features({"page": "https://example.com/new/", "current_pos": 100})
    assert features["sibling_similarity"] == 1.0
    assert features["inlinks_from_indexed"] == 0.0
    assert features["unique_data_fields"] == 0.0
    assert features["search_volume_log"] == 0.0
    assert features["has_existing_owner"] == 0.0
