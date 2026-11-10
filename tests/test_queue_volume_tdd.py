"""Unit tests for the skill's queue-volume and outcome-guard upgrades (TDD).

Covers the pure logic added to the improve-seo-with-data skill:
- ltr_ranker.prescribe_all_actions: one row can carry several atomic fixes.
- ltr_ranker record/load/filter cooldown ledger (30-day per (page, action)).
- ltr_ranker.slice_per_domain: per-property quota slicing of the final queue.
- collect_features.synthesize_unseen_rows: DataForSEO suggestion/competitor
  rows become scoreable candidates at current_pos=100.
- collect_features.pull_gsc_window: (query, page) window pull via the seo
  binary (backfill + post-deploy verification windows).
- dataforseo_client keyword_suggestions / domain_intersection envelope
  normalization (offline fake transport).
- log_outcomes_and_retrain.has_recrawl_evidence + detect_regressions:
  the recrawl-lag guard and the negative-delta rollback detector.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from dataforseo_client import DataForSEOClient  # noqa: E402
from log_outcomes_and_retrain import (  # noqa: E402
    detect_regressions,
    has_recrawl_evidence,
)
from ltr_ranker import (  # noqa: E402
    filter_cooldown,
    load_cooldown_keys,
    prescribe_all_actions,
    record_shipped,
    slice_per_domain,
)

# ---------------------------------------------------------------------------
# prescribe_all_actions: multi-prescription SHAP explosion
# ---------------------------------------------------------------------------


def test_deep_unranked_row_prescribes_pseo_launch_first():
    actions = prescribe_all_actions(
        current_pos=100.0,
        title_match_rate=0.1,
        hub_links_shap=-0.2,
        centroid_sim=0.5,
        forum_ratio=0.0,
        impressions=0.0,
        clicks=0.0,
    )
    assert actions[0] == "LAUNCH_PSEO_ROUTE"
    assert "BOOST_INTERNAL_LINKS" in actions  # negative hub SHAP is a second fix
    assert len(actions) == len(set(actions)), "duplicate prescriptions in explosion"


def test_high_impression_zero_click_row_gets_ctr_hook_prescription():
    actions = prescribe_all_actions(
        current_pos=8.0,
        title_match_rate=0.9,
        hub_links_shap=0.1,
        centroid_sim=0.5,
        forum_ratio=0.0,
        impressions=57.0,
        clicks=0.0,
    )
    assert "REWRITE_CTR_TITLE_AND_TOP_300PX" in actions
    assert "LAUNCH_PSEO_ROUTE" not in actions


def test_forum_heavy_serp_spin_out_only_within_striking_distance():
    actions = prescribe_all_actions(
        current_pos=12.0,
        title_match_rate=0.9,
        hub_links_shap=0.0,
        centroid_sim=0.5,
        forum_ratio=0.5,
        impressions=10.0,
        clicks=0.0,
    )
    assert "SPIN_OUT_DEDICATED_SUBROUTE" in actions
    deep = prescribe_all_actions(
        current_pos=60.0,
        title_match_rate=0.9,
        hub_links_shap=0.0,
        centroid_sim=0.5,
        forum_ratio=0.5,
        impressions=10.0,
        clicks=0.0,
    )
    assert "SPIN_OUT_DEDICATED_SUBROUTE" not in deep


def test_clean_winning_row_falls_back_to_snippet_play():
    actions = prescribe_all_actions(
        current_pos=5.0,
        title_match_rate=0.9,
        hub_links_shap=0.2,
        centroid_sim=0.5,
        forum_ratio=0.0,
        impressions=500.0,
        clicks=25.0,
    )
    assert actions == ["REWRITE_SNIPPET_AND_TOP_300PX"]


def test_explosion_preserves_single_action_compatibility():
    from ltr_ranker import prescribe_action

    args = dict(
        current_pos=8.0,
        title_match_rate=0.3,
        hub_links_shap=0.0,
        centroid_sim=0.5,
        forum_ratio=0.0,
        impressions=10.0,
        clicks=0.0,
    )
    assert prescribe_all_actions(**args)[0] == prescribe_action(
        current_pos=args["current_pos"],
        title_match_rate=args["title_match_rate"],
        hub_links_shap=args["hub_links_shap"],
        centroid_sim=args["centroid_sim"],
        forum_ratio=args["forum_ratio"],
    )


# ---------------------------------------------------------------------------
# Cooldown ledger
# ---------------------------------------------------------------------------


def _row(query: str, page: str, action: str, score: float = 1.0) -> dict:
    return {"query": query, "page": page, "prescribed_action": action, "actions": [action], "rank_score": score}


def test_record_and_load_cooldown_keys_roundtrip(tmp_path: Path):
    ledger = str(tmp_path / "shipped.jsonl")
    queue = [_row("q1", "https://a.com/x/", "INJECT_EXACT_H2_AND_TITLE")]
    assert record_shipped(queue, ledger, deployed_at="2026-11-10T00:00:00Z") == 1
    keys = load_cooldown_keys(ledger, within_days=30, now=__import__("datetime").datetime(2026, 11, 12))
    assert ("https://a.com/x/", "INJECT_EXACT_H2_AND_TITLE") in keys


def test_cooldown_expires_after_within_days(tmp_path: Path):
    ledger = str(tmp_path / "shipped.jsonl")
    record_shipped(
        [_row("q1", "https://a.com/x/", "REWRITE_SNIPPET_AND_TOP_300PX")], ledger, deployed_at="2026-01-01T00:00:00Z"
    )
    keys = load_cooldown_keys(ledger, within_days=30, now=__import__("datetime").datetime(2026, 3, 1))
    assert keys == set(), "30-day cooldown did not expire"


def test_filter_cooldown_drops_cooled_actions_and_dead_rows():
    cooled = {
        ("https://a.com/x/", "INJECT_EXACT_H2_AND_TITLE"),  # row fully cooled
        ("https://b.com/y/", "INJECT_EXACT_H2_AND_TITLE"),  # partial: one of two actions
    }
    rows = [
        _row("q1", "https://a.com/x/", "INJECT_EXACT_H2_AND_TITLE"),
        {
            **_row("q2", "https://b.com/y/", "INJECT_EXACT_H2_AND_TITLE"),
            "actions": ["INJECT_EXACT_H2_AND_TITLE", "BOOST_INTERNAL_LINKS"],
        },
    ]
    kept, skipped = filter_cooldown(rows, cooled)
    assert len(kept) == 1 and kept[0]["query"] == "q2"
    assert kept[0]["actions"] == ["BOOST_INTERNAL_LINKS"], "cooled action survived"
    assert len(skipped) == 1 and skipped[0]["query"] == "q1"


# ---------------------------------------------------------------------------
# Per-domain quota slicing
# ---------------------------------------------------------------------------


def test_slice_per_domain_caps_each_domain_and_keeps_global_order():
    rows = [
        _row("a1", "https://smsriver.com/1/", "REWRITE_SNIPPET_AND_TOP_300PX", 3.0),
        _row("a2", "https://smsriver.com/2/", "REWRITE_SNIPPET_AND_TOP_300PX", 2.5),
        _row("a3", "https://smsriver.com/3/", "REWRITE_SNIPPET_AND_TOP_300PX", 2.0),
        _row("b1", "https://openfileconverter.com/1/", "REWRITE_SNIPPET_AND_TOP_300PX", 1.5),
    ]
    sliced = slice_per_domain(rows, per_domain_top=2)
    assert [r["query"] for r in sliced] == ["a1", "a2", "b1"]


def test_slice_per_domain_zero_or_negative_is_identity():
    rows = [_row("a1", "https://a.com/1/", "REWRITE_SNIPPET_AND_TOP_300PX", 1.0)]
    assert slice_per_domain(rows, per_domain_top=0) == rows


# ---------------------------------------------------------------------------
# collect_features: suggestion synthesis + GSC window pulls
# ---------------------------------------------------------------------------


def test_synthesize_unseen_rows_from_suggestion_items():
    items = [
        {"keyword": "sms verification free", "keyword_info": {"search_volume": 120, "keyword_difficulty": 20}},
        {"keyword": "impossible query x", "keyword_info": {"search_volume": 5, "keyword_difficulty": 80}},
    ]
    rows = __import__("collect_features").synthesize_unseen_rows(
        items,
        domain="smsriver.com",
        source="dfseo_suggest",
        min_volume=50,
        max_difficulty=35,
    )
    assert len(rows) == 1
    assert rows[0]["page"] == "https://smsriver.com/sms-verification-free/"
    assert rows[0]["current_pos"] == 100.0
    assert rows[0]["impressions"] == 120
    assert rows[0]["source"] == "dfseo_suggest"


def test_pull_gsc_window_parses_query_page_rows(monkeypatch):
    import collect_features as cf

    payload = {
        "rows": [
            {
                "keys": ["online sms", "https://smsriver.com/receive-sms/us/"],
                "clicks": 2,
                "impressions": 50,
                "position": 8.0,
            },
        ]
    }
    monkeypatch.setattr(
        cf.subprocess,
        "run",
        lambda *a, **k: type("P", (), {"returncode": 0, "stdout": json.dumps(payload), "stderr": ""})(),
    )
    rows = cf.pull_gsc_window("smsriver.com", "2026-01-01", "2026-02-01")
    assert rows[0]["page"] == "https://smsriver.com/receive-sms/us/"
    assert rows[0]["clicks_30d"] == 2.0


# ---------------------------------------------------------------------------
# dataforseo_client: Labs endpoints with fake transport
# ---------------------------------------------------------------------------


def _fake_client(envelope: dict) -> DataForSEOClient:
    return DataForSEOClient("login", "pass", transport=lambda *a, **k: envelope)


def test_keyword_suggestions_normalizes_labs_envelope():
    envelope = {
        "status_code": 20000,
        "tasks": [
            {
                "result": [
                    {
                        "items": [
                            {
                                "keyword": "receive sms online",
                                "keyword_info": {"search_volume": 300, "keyword_difficulty": 25},
                                "serp_info": {"se_results_count": 100},
                            },
                        ]
                    }
                ]
            }
        ],
    }
    rows = _fake_client(envelope).keyword_suggestions(["receive sms"], limit=10, min_volume=50)
    assert len(rows) == 1
    assert rows[0]["keyword"] == "receive sms online"
    assert rows[0]["volume"] == 300
    assert rows[0]["difficulty"] == 25


def test_domain_intersection_normalizes_competitor_rows():
    envelope = {
        "status_code": 20000,
        "tasks": [
            {
                "result": [
                    {
                        "items": [
                            {
                                "keyword_data": {
                                    "keyword": "free sms receive",
                                    "keyword_info": {"search_volume": 90, "keyword_difficulty": 30},
                                },
                                "rank_info": {"pos": 4},
                                "ranked_url": "https://competitor.com/free/",
                            },
                        ]
                    }
                ]
            }
        ],
    }
    rows = _fake_client(envelope).domain_intersection(["competitor.com"], min_volume=50)
    assert rows[0]["keyword"] == "free sms receive"
    assert rows[0]["position"] == 4
    assert rows[0]["url"] == "https://competitor.com/free/"


# ---------------------------------------------------------------------------
# Outcome guards: recrawl lag + negative-delta rollback
# ---------------------------------------------------------------------------


def test_has_recrawl_evidence_requires_post_deploy_impressions():
    post = {"https://a.com/x/": {"impressions": 12, "clicks": 0}}
    assert has_recrawl_evidence("https://a.com/x/", post) is True
    assert has_recrawl_evidence("https://a.com/never/", post) is False
    assert has_recrawl_evidence("https://a.com/zero/", {"https://a.com/zero/": {"impressions": 0}}) is False


def test_detect_regressions_flags_position_drop_and_imp_loss():
    executed = [{"query": "q1", "page": "https://a.com/x/", "prescribed_action": "INJECT_EXACT_H2_AND_TITLE"}]
    pre = {"q1\nhttps://a.com/x/": {"clicks_30d": 0, "impressions": 100, "current_pos": 6.0, "ctr": 0.0}}
    post = {"q1\nhttps://a.com/x/": {"clicks_30d": 0, "impressions": 60, "current_pos": 14.0, "ctr": 0.0}}
    regressions = detect_regressions(executed, pre, post, recrawled_pages={"https://a.com/x/"})
    assert len(regressions) == 1
    assert regressions[0]["action"] == "REVERT_WAVE_COMMIT"
    assert regressions[0]["page"] == "https://a.com/x/"


def test_detect_regressions_ignores_unrecrawled_and_healthy_rows():
    executed = [{"query": "q1", "page": "https://a.com/x/", "prescribed_action": "INJECT_EXACT_H2_AND_TITLE"}]
    pre = {"q1\nhttps://a.com/x/": {"clicks_30d": 0, "impressions": 100, "current_pos": 6.0, "ctr": 0.0}}
    post = {"q1\nhttps://a.com/x/": {"clicks_30d": 0, "impressions": 60, "current_pos": 14.0, "ctr": 0.0}}
    # Not recrawled yet -> never graded as a regression (recrawl-lag guard).
    assert detect_regressions(executed, pre, post, recrawled_pages=set()) == []
    # Recrawled and healthy -> no regression.
    healthy = {"q1\nhttps://a.com/x/": {"clicks_30d": 3, "impressions": 120, "current_pos": 5.0, "ctr": 0.025}}
    assert detect_regressions(executed, pre, healthy, recrawled_pages={"https://a.com/x/"}) == []


def test_detect_regressions_skips_rows_outside_the_protected_band():
    executed = [{"query": "q2", "page": "https://b.com/y/", "prescribed_action": "LAUNCH_PSEO_ROUTE"}]
    pre = {"q2\nhttps://b.com/y/": {"clicks_30d": 0, "impressions": 50, "current_pos": 44.0, "ctr": 0.0}}
    post = {"q2\nhttps://b.com/y/": {"clicks_30d": 0, "impressions": 5, "current_pos": 80.0, "ctr": 0.0}}
    assert detect_regressions(executed, pre, post, recrawled_pages={"https://b.com/y/"}) == []
