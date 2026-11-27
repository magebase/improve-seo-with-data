"""Phase 1 hardening tests: ML calibration, DataForSEO, honest gates, and state locks."""

from __future__ import annotations

import json
import math
from pathlib import Path
from unittest.mock import patch

import numpy as np
from cursor_hygiene import enforce_url_title_lock
from dataforseo_client import DataForSEOClient, _item_domain, serp_vulnerability_score
from evaluate_experiments import format_two_part_scorecard
from figiva_sweep_headers import build_sweep_headers
from fleet_state import connect_state_db, enqueue_tasks, lease_tasks
from log_outcomes_and_retrain import append_labeled_rows
from ltr_ranker import FEATURES, IsotonicCalibrator
from score_backlog import extract_top_shap_string
from seo_factory import (
    advance_cohort,
    create_cohort,
    record_cohort_measurement,
    register_page_contract,
)
from seo_shared import (
    extract_registered_domain,
    score_conversion_intent,
    search_volume_to_log,
    sign_sweep_headers,
    strip_www,
    utc_iso_now,
)
from verify_product_functionality import verify_product_functionality
from verify_technical_seo import audit_html_technical_seo


def test_seo_shared_domain_and_intent_helpers():
    assert strip_www("www.wordpress.com") == "wordpress.com"
    assert strip_www("wikipedia.org") == "wikipedia.org"
    assert extract_registered_domain("https://shop.foo.co.uk/items") == "foo.co.uk"
    assert extract_registered_domain("https://crypto.figiva.com/calculators") == "figiva.com"
    assert score_conversion_intent("best corporate credit card pricing 2026") > 0.5
    assert score_conversion_intent("history of clouds") == 0.0
    assert math.isclose(search_volume_to_log(99.0), 2.0, rel_tol=1e-6)


def test_hmac_sweep_headers_minting():
    h1 = sign_sweep_headers("https://figiva.com/calculators/gpa/?a=1", secret="test-secret", timestamp=1700000000)
    h2 = build_sweep_headers("https://figiva.com/calculators/gpa/?a=1", secret="test-secret", timestamp=1700000000)
    assert h1 == h2
    assert h1["X-SEO-Verify"] == "1"
    assert h1["X-SEO-Sweep-Ts"] == "1700000000"
    assert len(h1["X-SEO-Sweep-Sig"]) == 64


def test_isotonic_calibrator_pava_merges_violators_cleanly():
    raw = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    realized = np.array([5.0, 1.0, 4.0, 2.0, 6.0])
    cal = IsotonicCalibrator.fit(raw, realized)
    assert len(cal.knots_x) == len(cal.knots_y)
    assert all(cal.knots_x[i] < cal.knots_x[i + 1] for i in range(len(cal.knots_x) - 1))
    assert all(cal.knots_y[i] <= cal.knots_y[i + 1] + 1e-12 for i in range(len(cal.knots_y) - 1))


def test_extract_top_shap_string_never_fabricates_fake_numbers():
    out = extract_top_shap_string({"action_code": "INJECT_EXACT_TITLE_AND_H2", "query": "test"})
    assert "title_match_deficit" not in out
    assert "shap_unavailable" in out


def test_scorecard_renders_not_measured_when_execution_unmeasured():
    rendered = format_two_part_scorecard(
        domain="example.com",
        execution_score=None,
        execution_breakdown=None,
        summary={"has_measured_outcomes": False, "pending_recrawl": 1, "observing": 0},
    )
    assert "NOT MEASURED" in rendered
    assert "9.8 / 10.0" not in rendered


def test_dataforseo_domain_crowding_chunking_and_isolation():
    assert _item_domain({"url": "https://wordpress.com/blog"}) == "wordpress.com"
    assert _item_domain({"url": "https://wikipedia.org/wiki/SEO"}) == "wikipedia.org"

    base_items = [
        {"type": "organic", "rank_group": 1, "title": "Random post", "url": "https://www.reddit.com/r/x"},
        {"type": "organic", "rank_group": 2, "title": "Another", "url": "https://www.quora.com/q"},
    ]
    crowded_items = base_items + [{"type": "ai_overview"}, {"type": "local_pack"}]
    s_clean = serp_vulnerability_score(base_items, "widgets")
    s_crowded = serp_vulnerability_score(crowded_items, "widgets")
    assert s_crowded["score"] < s_clean["score"]

    calls = []

    def fake_transport(method, url, body=None, headers=None, timeout=60):
        calls.append((method, url, json.loads(body) if body else None))
        if url.endswith("/task_post"):
            return {"status_code": 20000, "cost": 0.01, "tasks": [{"id": "x"}]}
        if url.endswith("/tasks_ready"):
            return {
                "status_code": 20000,
                "tasks": [
                    {
                        "status_code": 20000,
                        "result_count": 2,
                        "result": [
                            {"id": "mine", "tag": "projA", "endpoint_advanced": "/v3/serp/google/organic/task_get/advanced/mine"},
                            {"id": "other", "tag": "projB", "endpoint_advanced": "/v3/serp/google/organic/task_get/advanced/other"},
                        ],
                    }
                ],
            }
        return {"status_code": 20000, "tasks": [{"status_code": 20000, "result": [{"keyword": "k", "items": []}]}]}

    client = DataForSEOClient(login="l", password="p", transport=fake_transport)
    resp = client.post_serp_tasks([f"kw-{i}" for i in range(150)], tag="projA")
    post_calls = [c for c in calls if c[1].endswith("/task_post")]
    assert len(post_calls) == 2
    assert len(post_calls[0][2]) == 100
    assert len(post_calls[1][2]) == 50
    assert len(resp["tasks"]) == 2

    res = client.collect_ready_tasks(allowed_task_ids={"mine"}, expected_tag="projA")
    assert len(res) == 1
    assert res[0]["task_id"] == "mine"


def test_seo_factory_zero_overlap_and_day21_impressions():
    conn = connect_state_db(":memory:")
    res = register_page_contract(
        conn,
        {
            "url": "https://example.com/tools/calc/",
            "cluster_id": "tools",
            "tier": "A",
            "data_source_hash": "abc",
            "unique_data_fields": 4,
            "stripped_overlap_score": 0.0,
            "planned_indexed_inlinks": 3,
        },
    )
    assert res["valid"] is True
    stored = conn.execute("SELECT stripped_overlap_score FROM page_contracts WHERE url = ?", ("https://example.com/tools/calc/",)).fetchone()[0]
    assert stored == 0.0

    cohort = create_cohort(
        conn,
        template_id="calc",
        domain="example.com",
        urls=[f"https://example.com/tools/c{i}/" for i in range(5)],
    )
    record_cohort_measurement(conn, cohort["cohort_id"], day=21, indexed=9, total=10, impressions=120)
    assert advance_cohort(conn, cohort["cohort_id"])["stage"] == "SCALING"
    conn.close()


def test_verify_technical_seo_canonical_exact_and_fail_closed():
    html = (
        "<html><head><title>Valid SEO Title That Is Long Enough For Gate</title>"
        "<meta name='description' content='A complete and descriptive meta description exceeding seventy characters for testing.'/>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'/>"
        "<link rel='canonical' href='https://evil-example.com/page/'/></head>"
        "<body><h1>Main Heading</h1><p>Body text.</p></body></html>"
    )
    res = audit_html_technical_seo(html, url="https://example.com/page/", expected_canonical_policy="host_match")
    canon_gate = next(g for g in res.gates if g.name == "canonical_url_consistency")
    assert canon_gate.passed is False

    with patch("verify_product_functionality.verify_product_functionality", side_effect=RuntimeError("boom")):
        res2 = audit_html_technical_seo(html.replace("evil-example.com", "example.com"), url="https://example.com/page/")
        func_gate = next(g for g in res2.gates if g.name == "functional_product_utility")
        assert func_gate.passed is False


def test_verify_product_functionality_rejects_empty_compare_page():
    thin_compare = "<html><body><h1>Compare</h1><p>Coming soon.</p></body></html>"
    res = verify_product_functionality("https://example.com/compare/a-vs-b/", thin_compare, status_code=200)
    assert res.passed is False
    assert res.status_label == "VERIFICATION_FAILED"


def test_log_outcomes_allows_post_deploy_after_fleet_pool(tmp_path: Path):
    hist = tmp_path / "ltr_training_history.jsonl"
    hist.write_text(
        json.dumps({
            "query": "test query",
            "page": "https://example.com/p/",
            "source": "fleet_pool",
            "features": {f: 0.0 for f in FEATURES},
            "clicks_30d": 0.0,
        })
        + "\n",
        encoding="utf-8",
    )
    added = append_labeled_rows(
        executed_queue=[{
            "query": "test query",
            "page": "https://example.com/p/",
            "action_code": "REWRITE_SNIPPET_AND_TOP_300PX",
            "deployed_at": "2026-11-20T00:00:00Z",
            "slot": "exploit",
        }],
        outcomes={"test query\nhttps://example.com/p/": {"clicks_30d": 5.0, "impressions": 100.0, "current_pos": 4.0, "ctr": 0.05}},
        conversions={},
        history_path=str(hist),
    )
    assert added == 1


def test_fleet_state_prevents_double_lease_on_same_page_and_utc_lock():
    conn = connect_state_db(":memory:")
    enqueue_tasks(
        conn,
        [
            {"domain": "example.com", "page": "https://example.com/a/", "query": "q1", "action_code": "INJECT_EXACT_TITLE_AND_H2", "priority_score": 10.0},
            {"domain": "example.com", "page": "https://example.com/a/", "query": "q1", "action_code": "REWRITE_SNIPPET_AND_TOP_300PX", "priority_score": 9.0},
            {"domain": "example.com", "page": "https://example.com/b/", "query": "q2", "action_code": "INJECT_EXACT_TITLE_AND_H2", "priority_score": 8.0},
        ],
    )
    wave1 = lease_tasks(conn, domain="example.com", limit=2)
    assert len(wave1) == 2
    assert {t["page"] for t in wave1} == {"https://example.com/a/", "https://example.com/b/"}

    wave2 = lease_tasks(conn, domain="example.com", limit=2)
    assert wave2 == []

    # Verify UTC ISO timestamp comparison in enforce_url_title_lock
    conn.execute(
        "UPDATE atomic_task_backlog SET status = 'SHIPPED', shipped_at = ? WHERE page = ?",
        (utc_iso_now(), "https://example.com/b/"),
    )
    enqueue_tasks(
        conn,
        [{"domain": "example.com", "page": "https://example.com/b/", "query": "q3", "action_code": "REWRITE_SNIPPET_AND_TOP_300PX", "priority_score": 5.0}],
    )
    conn.commit()
    downgraded = enforce_url_title_lock(conn, cooldown_days=21)
    assert downgraded >= 1
    conn.close()
