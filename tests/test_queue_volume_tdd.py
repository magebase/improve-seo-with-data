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
import tempfile
from pathlib import Path

import pytest


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
    return {
        "query": query,
        "page": page,
        "prescribed_action": action,
        "actions": [action],
        "rank_score": score,
    }


def test_record_and_load_cooldown_keys_roundtrip(tmp_path: Path):
    ledger = str(tmp_path / "shipped.jsonl")
    queue = [_row("q1", "https://a.com/x/", "INJECT_EXACT_H2_AND_TITLE")]
    assert record_shipped(queue, ledger, deployed_at="2026-11-10T00:00:00Z") == 1
    keys = load_cooldown_keys(
        ledger, within_days=30, now=__import__("datetime").datetime(2026, 11, 12)
    )
    assert ("https://a.com/x/", "INJECT_EXACT_H2_AND_TITLE") in keys


def test_cooldown_expires_after_within_days(tmp_path: Path):
    ledger = str(tmp_path / "shipped.jsonl")
    record_shipped(
        [_row("q1", "https://a.com/x/", "REWRITE_SNIPPET_AND_TOP_300PX")],
        ledger,
        deployed_at="2026-01-01T00:00:00Z",
    )
    keys = load_cooldown_keys(
        ledger, within_days=30, now=__import__("datetime").datetime(2026, 3, 1)
    )
    assert keys == set(), "30-day cooldown did not expire"


def test_filter_cooldown_drops_cooled_actions_and_dead_rows():
    cooled = {
        ("https://a.com/x/", "INJECT_EXACT_H2_AND_TITLE"),  # row fully cooled
        (
            "https://b.com/y/",
            "INJECT_EXACT_H2_AND_TITLE",
        ),  # partial: one of two actions
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
        _row(
            "b1",
            "https://openfileconverter.com/1/",
            "REWRITE_SNIPPET_AND_TOP_300PX",
            1.5,
        ),
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
        {
            "keyword": "sms verification free",
            "keyword_info": {"search_volume": 120, "keyword_difficulty": 20},
        },
        {
            "keyword": "impossible query x",
            "keyword_info": {"search_volume": 5, "keyword_difficulty": 80},
        },
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
        lambda *a, **k: type(
            "P", (), {"returncode": 0, "stdout": json.dumps(payload), "stderr": ""}
        )(),
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
                                "keyword_info": {
                                    "search_volume": 300,
                                    "keyword_difficulty": 25,
                                },
                                "serp_info": {"se_results_count": 100},
                            },
                        ]
                    }
                ]
            }
        ],
    }
    rows = _fake_client(envelope).keyword_suggestions(
        ["receive sms"], limit=10, min_volume=50
    )
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
                                    "keyword_info": {
                                        "search_volume": 90,
                                        "keyword_difficulty": 30,
                                    },
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
    assert (
        has_recrawl_evidence(
            "https://a.com/zero/", {"https://a.com/zero/": {"impressions": 0}}
        )
        is False
    )


def test_detect_regressions_flags_position_drop_and_imp_loss():
    executed = [
        {
            "query": "q1",
            "page": "https://a.com/x/",
            "prescribed_action": "INJECT_EXACT_H2_AND_TITLE",
        }
    ]
    pre = {
        "q1\nhttps://a.com/x/": {
            "clicks_30d": 0,
            "impressions": 100,
            "current_pos": 6.0,
            "ctr": 0.0,
        }
    }
    post = {
        "q1\nhttps://a.com/x/": {
            "clicks_30d": 0,
            "impressions": 60,
            "current_pos": 14.0,
            "ctr": 0.0,
        }
    }
    regressions = detect_regressions(
        executed, pre, post, recrawled_pages={"https://a.com/x/"}
    )
    assert len(regressions) == 1
    assert regressions[0]["action"] == "REVERT_WAVE_COMMIT"
    assert regressions[0]["page"] == "https://a.com/x/"


def test_detect_regressions_ignores_unrecrawled_and_healthy_rows():
    executed = [
        {
            "query": "q1",
            "page": "https://a.com/x/",
            "prescribed_action": "INJECT_EXACT_H2_AND_TITLE",
        }
    ]
    pre = {
        "q1\nhttps://a.com/x/": {
            "clicks_30d": 0,
            "impressions": 100,
            "current_pos": 6.0,
            "ctr": 0.0,
        }
    }
    post = {
        "q1\nhttps://a.com/x/": {
            "clicks_30d": 0,
            "impressions": 60,
            "current_pos": 14.0,
            "ctr": 0.0,
        }
    }
    # Not recrawled yet -> never graded as a regression (recrawl-lag guard).
    assert detect_regressions(executed, pre, post, recrawled_pages=set()) == []
    # Recrawled and healthy -> no regression.
    healthy = {
        "q1\nhttps://a.com/x/": {
            "clicks_30d": 3,
            "impressions": 120,
            "current_pos": 5.0,
            "ctr": 0.025,
        }
    }
    assert (
        detect_regressions(executed, pre, healthy, recrawled_pages={"https://a.com/x/"})
        == []
    )


def test_detect_regressions_skips_rows_outside_the_protected_band():
    executed = [
        {
            "query": "q2",
            "page": "https://b.com/y/",
            "prescribed_action": "LAUNCH_PSEO_ROUTE",
        }
    ]
    pre = {
        "q2\nhttps://b.com/y/": {
            "clicks_30d": 0,
            "impressions": 50,
            "current_pos": 44.0,
            "ctr": 0.0,
        }
    }
    post = {
        "q2\nhttps://b.com/y/": {
            "clicks_30d": 0,
            "impressions": 5,
            "current_pos": 80.0,
            "ctr": 0.0,
        }
    }
    assert (
        detect_regressions(executed, pre, post, recrawled_pages={"https://b.com/y/"})
        == []
    )


# ---------------------------------------------------------------------------
# Orphan route detector (sitemap -> GSC left join)
# ---------------------------------------------------------------------------


def test_synthesize_orphan_rows_injects_zero_impression_sitemap_urls():
    from collect_features import synthesize_orphan_rows

    sitemap = [
        "https://openfileconverter.com/convert/heic-to-jpg/",
        "https://openfileconverter.com/tools/merge-pdf/",
        "https://openfileconverter.com/privacy/",
    ]
    gsc_pages = {"https://openfileconverter.com/convert/heic-to-jpg/"}
    rows = synthesize_orphan_rows(sitemap, gsc_pages, domain="openfileconverter.com")
    pages = [r["page"] for r in rows]
    assert "https://openfileconverter.com/tools/merge-pdf/" in pages
    assert "https://openfileconverter.com/privacy/" in pages
    assert "https://openfileconverter.com/convert/heic-to-jpg/" not in pages
    orphan = next(r for r in rows if r["page"].endswith("tools/merge-pdf/"))
    assert orphan["current_pos"] == 100.0
    assert orphan["impressions"] == 0.0
    assert orphan["query"] == "merge pdf"  # slug-synthesized demand proxy
    assert orphan["source"] == "orphan_route"


def test_orphan_rows_get_internal_link_and_expansion_prescriptions():
    from collect_features import synthesize_orphan_rows
    from ltr_ranker import ORPHAN_ACTIONS

    rows = synthesize_orphan_rows(
        ["https://a.com/tools/merge-pdf/"], set(), domain="a.com"
    )
    assert rows[0]["actions"] == ORPHAN_ACTIONS
    assert "BOOST_INTERNAL_LINKS" in ORPHAN_ACTIONS


def test_fetch_sitemap_urls_parses_locs_and_index(monkeypatch):
    from collect_features import fetch_sitemap_urls

    class FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return (
                "<urlset><url><loc>https://a.com/one/</loc></url></urlset>"
            ).encode()

    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: FakeResp())
    urls = fetch_sitemap_urls("a.com")
    assert urls == ["https://a.com/one/"]


# ---------------------------------------------------------------------------
# Query cannibalization detector
# ---------------------------------------------------------------------------


def test_detect_cannibalization_flags_multi_page_queries_beyond_top10():
    from ltr_ranker import detect_cannibalization

    rows = [
        {
            "query": "cheap insurance",
            "page": "https://a.com/p1/",
            "current_pos": 14.0,
            "prescribed_action": "REWRITE_SNIPPET_AND_TOP_300PX",
            "actions": ["REWRITE_SNIPPET_AND_TOP_300PX"],
        },
        {
            "query": "cheap insurance",
            "page": "https://a.com/p2/",
            "current_pos": 22.0,
            "prescribed_action": "REWRITE_SNIPPET_AND_TOP_300PX",
            "actions": ["REWRITE_SNIPPET_AND_TOP_300PX"],
        },
        {
            "query": "healthy query",
            "page": "https://a.com/p3/",
            "current_pos": 5.0,
            "prescribed_action": "REWRITE_SNIPPET_AND_TOP_300PX",
            "actions": ["REWRITE_SNIPPET_AND_TOP_300PX"],
        },
    ]
    keepers, tasks = detect_cannibalization(rows)
    task_queries = [t["query"] for t in tasks]
    assert task_queries == ["cheap insurance"]
    assert set(tasks[0]["pages"]) == {"https://a.com/p1/", "https://a.com/p2/"}
    keeper = next(r for r in keepers if r["query"] == "cheap insurance")
    assert "CONSOLIDATE_CANNIBALIZED_URLS" in keeper["actions"]
    # A winning page (pos <= 10) is never flagged (Guardrail 2).
    assert "healthy query" not in task_queries


def test_cannibalization_ignores_single_page_queries():
    from ltr_ranker import detect_cannibalization

    rows = [
        {
            "query": "solo",
            "page": "https://a.com/solo/",
            "current_pos": 30.0,
            "prescribed_action": "REWRITE_SNIPPET_AND_TOP_300PX",
            "actions": ["x"],
        }
    ]
    keepers, tasks = detect_cannibalization(rows)
    assert tasks == [] and len(keepers) == 1


# ---------------------------------------------------------------------------
# coverageState triage (URL Inspection export)
# ---------------------------------------------------------------------------


def test_triage_inspection_states_maps_coverage_to_fixes():
    from log_outcomes_and_retrain import triage_inspection_states

    inspection = {
        "https://a.com/discovered/": {
            "coverageState": "Discovered - currently not indexed"
        },
        "https://a.com/crawled/": {"coverageState": "Crawled - currently not indexed"},
        "https://a.com/dup/": {
            "coverageState": "Duplicate, Google chose different canonical than user"
        },
        "https://a.com/indexed/": {"coverageState": "Submitted and indexed"},
    }
    tasks = triage_inspection_states(inspection)
    by_page = {t["page"]: t["action"] for t in tasks}
    assert by_page["https://a.com/discovered/"] == "BOOST_INTERNAL_LINKS"
    assert by_page["https://a.com/crawled/"] == "INJECT_UNIQUE_DATA_TABLE"
    assert by_page["https://a.com/dup/"] == "PRUNE_DUPLICATE_ROUTE"
    assert "https://a.com/indexed/" not in by_page


def test_inspection_recrawl_evidence_respects_seven_day_rule():
    from log_outcomes_and_retrain import recrawl_from_inspection

    inspection = {
        "https://a.com/fresh/": {"lastCrawlTime": "2026-11-20T00:00:00Z"},
        "https://a.com/stale/": {"lastCrawlTime": "2026-11-12T00:00:00Z"},
    }
    deployed = __import__("datetime").datetime(
        2026, 11, 9, tzinfo=__import__("datetime").timezone.utc
    )
    assert recrawl_from_inspection("https://a.com/fresh/", inspection, deployed) is True
    assert (
        recrawl_from_inspection("https://a.com/stale/", inspection, deployed) is False
    )
    assert (
        recrawl_from_inspection("https://a.com/missing/", inspection, deployed) is False
    )


# ---------------------------------------------------------------------------
# item_types persistence (zero-extra-cost SERP feature flags)
# ---------------------------------------------------------------------------


def test_serp_item_types_persisted_as_row_metadata():
    import collect_features as cf

    serp_items = [{"type": "organic", "url": "https://x.com/", "title": "online sms"}]
    feature_block = {
        "item_types": [
            "organic",
            "ai_overview",
            "people_also_ask",
            "discussions_and_forums",
        ],
    }
    meta = cf.serp_item_metadata(feature_block, serp_items, "online sms")
    assert meta["has_ai_overview"] is True
    assert meta["has_forums"] is True
    assert meta["has_people_also_ask"] is True
    assert meta["serp_item_types"] == [
        "organic",
        "ai_overview",
        "people_also_ask",
        "discussions_and_forums",
    ]
    empty = cf.serp_item_metadata({}, [], "q")
    assert empty["has_ai_overview"] is False and empty["serp_item_types"] == []


# ---------------------------------------------------------------------------
# ensure_candidate_depth waterfall (minimum candidate guarantee)
# ---------------------------------------------------------------------------


def test_waterfall_tops_up_from_orphans_then_matrix_then_suggestions():
    from collect_features import ensure_candidate_depth

    gsc = [
        {
            "query": "q1",
            "page": "https://a.com/one/",
            "impressions": 10.0,
            "current_pos": 8.0,
            "clicks_30d": 0.0,
            "ctr": 0.0,
            "source": "gsc",
        }
    ]
    sitemap = ["https://a.com/one/", "https://a.com/two/", "https://a.com/three/"]
    matrix_fn = lambda need: [  # noqa: E731
        {
            "query": f"pair {i}",
            "page": f"https://a.com/pair-{i}/",
            "impressions": 0.0,
            "current_pos": 100.0,
            "clicks_30d": 0.0,
            "ctr": 0.0,
            "source": "catalog_matrix",
        }
        for i in range(need)
    ]
    rows, report = ensure_candidate_depth(
        "a.com",
        gsc,
        sitemap,
        min_rows=4,
        matrix_fn=matrix_fn,
        suggest_fn=None,
    )
    assert len(rows) >= 4
    assert report["tiers_used"] == ["gsc", "sitemap_orphans", "catalog_matrix"]


def test_waterfall_never_drops_below_tier_order_and_dedupes():
    from collect_features import ensure_candidate_depth

    gsc = [
        {
            "query": "q1",
            "page": "https://a.com/one/",
            "impressions": 10.0,
            "current_pos": 8.0,
            "clicks_30d": 0.0,
            "ctr": 0.0,
            "source": "gsc",
        }
    ]
    sitemap = ["https://a.com/one/"]  # duplicate of the GSC row -> no orphan
    suggest_fn = lambda need: [  # noqa: E731
        {
            "query": f"sug {i}",
            "page": f"https://a.com/sug-{i}/",
            "impressions": 60.0,
            "current_pos": 100.0,
            "clicks_30d": 0.0,
            "ctr": 0.0,
            "source": "dfseo_suggest",
        }
        for i in range(need)
    ]
    rows, report = ensure_candidate_depth(
        "a.com",
        gsc,
        sitemap,
        min_rows=3,
        matrix_fn=lambda need: [],
        suggest_fn=suggest_fn,
    )
    assert len(rows) >= 3
    assert report["tiers_used"] == ["gsc", "catalog_matrix", "dfseo_suggest"]


def test_pairwise_matrix_synthesizes_unbuilt_entity_pairs():
    from collect_features import pairwise_matrix_from_sitemap

    sitemap = [
        "https://smsriver.com/receive-sms/us/",
        "https://smsriver.com/receive-sms/gb/",
        "https://smsriver.com/receive-sms/fr/",
        "https://smsriver.com/receive-sms/de/",
        "https://smsriver.com/verify/whatsapp/",
    ]
    rows = pairwise_matrix_from_sitemap(
        sitemap,
        family_prefix="receive-sms",
        templates=["receive sms online in {entity}"],
        max_pairs=3,
    )
    queries = [r["query"] for r in rows]
    assert any("receive sms online in de" == q for q in queries) or rows == []
    for row in rows:
        assert row["current_pos"] == 100.0
        assert row["source"] == "catalog_matrix"


# ---------------------------------------------------------------------------
# compile_wave_backlog: multi-action compiler with TDD assertions
# ---------------------------------------------------------------------------


def _scored(
    query, page, pos, imp, clicks, title_match, hub_links, shap_hub=0.0, **extra
):
    return {
        "query": query,
        "page": page,
        "current_pos": pos,
        "impressions": imp,
        "clicks_30d": clicks,
        "rank_score": 1.0,
        "cluster_id": "c",
        "features": {
            "title_exact_match_rate": title_match,
            "parent_hub_internal_links": hub_links,
            "serp_forum_ratio": 0.0,
            "current_pos": pos,
            "search_volume_log": 2.0,
            "domain_centroid_sim": 0.5,
            "conversion_intent_score": 0.0,
            "serp_pixel_crowding": 0.0,
        },
        "actions": [],
        "shap": {"parent_hub_internal_links": shap_hub},
        "source": "gsc",
        **extra,
    }


def test_compile_wave_backlog_fills_target_with_distinct_atomic_tasks():
    from ltr_ranker import compile_wave_backlog

    rows = [
        _scored("q1", "https://a.com/p1/", 8.0, 60.0, 0.0, 0.9, 6.0, shap_hub=-0.2),
        _scored("q2", "https://a.com/p2/", 12.0, 10.0, 1.0, 0.3, 2.0),
        _scored("q3", "https://b.com/p3/", 95.0, 0.0, 0.0, 0.9, 1.0),
    ]
    tasks = compile_wave_backlog(rows, shipped_ledger=set(), target_wave_size=8)
    codes = [t["action_code"] for t in tasks]
    assert len(tasks) >= 5
    assert "BOOST_CLUSTER_CROSS_LINKS" in codes  # q1: negative hub SHAP
    assert "OVERHAUL_CTR_HOOK_AND_WEBAPP_SCHEMA" in codes  # q1: high imp, 0 clicks
    assert "INJECT_EXACT_TITLE_AND_H2" in codes  # q2: title match 0.3
    assert "CREATE_PROGRAMMATIC_ROUTE" in codes  # q3: pos >= 90
    # Every task carries an executable TDD assertion + a file target.
    for task in tasks:
        assert task["tdd_assertion"] and task["file_target"]


def test_compile_wave_backlog_respects_cooldown_and_dedupes():
    from ltr_ranker import compile_wave_backlog

    rows = [_scored("q1", "https://a.com/p1/", 8.0, 60.0, 0.0, 0.9, 6.0, shap_hub=-0.2)]
    shipped = {("https://a.com/p1/", "OVERHAUL_CTR_HOOK_AND_WEBAPP_SCHEMA")}
    tasks = compile_wave_backlog(rows, shipped_ledger=shipped, target_wave_size=5)
    codes = [t["action_code"] for t in tasks]
    assert "OVERHAUL_CTR_HOOK_AND_WEBAPP_SCHEMA" not in codes
    assert len(codes) == len(set(codes)), "duplicate action emitted for one URL"


def test_compile_wave_backlog_propagates_across_catalog_siblings():
    from ltr_ranker import compile_wave_backlog

    rows = [
        _scored(
            "receive sms france",
            "https://a.com/receive-sms/fr/",
            12.0,
            10.0,
            1.0,
            0.3,
            2.0,
        )
    ]
    siblings = {"/receive-sms/": 9}
    tasks = compile_wave_backlog(
        rows, shipped_ledger=set(), target_wave_size=5, sibling_counts=siblings
    )
    propagation = [t for t in tasks if t.get("catalog_propagation")]
    assert propagation, "catalog propagation hint missing for programmatic route"
    assert propagation[0]["catalog_propagation"]["siblings"] == 9


# ---------------------------------------------------------------------------
# Offline DataForSEO surrogate (LightGBM-only, no sklearn)
# ---------------------------------------------------------------------------


def test_surrogate_predicts_clipped_serp_features_offline():
    from dfs_surrogate import OfflineDataForSEOSurrogate

    history = []
    for i in range(40):
        history.append(
            {
                "query": f"receive sms online {i} free tool",
                "search_volume_log": 2.0 + (i % 5) * 0.1,
                "serp_forum_ratio": 0.1 if i % 2 else 0.6,
                "title_exact_match_rate": 0.2 + (i % 3) * 0.2,
                "serp_pixel_crowding": 1.0 + (i % 4),
            }
        )
    surrogate = OfflineDataForSEOSurrogate()
    surrogate.fit(history, models_dir=tempfile.mkdtemp())  # never pollute models/
    preds = surrogate.predict_serp_features(
        ["receive sms online 99 free tool", "vs compare x"]
    )
    assert len(preds) == 2
    for row in preds:
        assert 0.0 <= row["serp_forum_ratio"] <= 1.0
        assert 0.0 <= row["title_exact_match_rate"] <= 1.0
        assert 0.5 <= row["search_volume_log"] <= 5.0
        assert row["feature_source"] == "local_surrogate"


def test_surrogate_refuses_to_fit_below_the_data_floor():
    from dfs_surrogate import OfflineDataForSEOSurrogate

    with pytest.raises(RuntimeError):
        OfflineDataForSEOSurrogate().fit(
            [
                {
                    "query": "q",
                    "search_volume_log": 2.0,
                    "serp_forum_ratio": 0.1,
                    "title_exact_match_rate": 0.5,
                    "serp_pixel_crowding": 1.0,
                }
            ]
        )


# ---------------------------------------------------------------------------
# DOM gap flags (local HTML vs cached SERP)
# ---------------------------------------------------------------------------


def test_dom_gap_flags_detect_missing_h2_table_and_schema():
    from collect_features import dom_gap_flags

    html = "<html><h2>Something else</h2><p>no table</p></html>"
    flags = dom_gap_flags(
        html,
        serp_items=[
            {"type": "people_also_ask", "questions": ["what is x?"], "type_paa": 1}
        ],
        query="heic to jpg",
        internal_inlinks=1.0,
        is_tool_route=True,
    )
    assert flags["missing_exact_h2"] is True
    assert flags["missing_data_table"] is True
    assert flags["missing_app_schema"] is True
    assert flags["weak_internal_inlinks"] is True
    assert flags["missing_paa_coverage"] is True
    healthy = dom_gap_flags(
        "<html><h2>heic to jpg guide</h2><table><tr><td>a</td></tr></table>"
        '<script type="application/ld+json">{"@type":"WebApplication"}</script>'
        "<h3>what is x?</h3></html>",
        serp_items=[],
        query="heic to jpg",
        internal_inlinks=5.0,
        is_tool_route=True,
    )
    assert healthy["missing_exact_h2"] is False
    assert healthy["missing_data_table"] is False
    assert healthy["missing_app_schema"] is False
    assert healthy["weak_internal_inlinks"] is False


# ---------------------------------------------------------------------------
# Round 4: gap-flag compiler codes, title CTR deficit, sibling auto-derivation,
# surrogate refit from the fleet state DB
# ---------------------------------------------------------------------------


def _flagged(query, page, dom_gaps=None, **extra):
    row = _scored(query, page, 8.0, 10.0, 1.0, 0.3, 2.0)
    if dom_gaps is not None:
        row["dom_gaps"] = dom_gaps
    row.update(extra)
    return row


def test_compile_wave_backlog_consumes_dom_gap_flags_and_orphan_source():
    from ltr_ranker import compile_wave_backlog

    rows = [
        _flagged(
            "convert heic to jpg",
            "https://a.com/convert/heic-to-jpg/",
            dom_gaps={
                "missing_exact_h2": False,
                "missing_data_table": True,
                "missing_paa_coverage": True,
                "missing_app_schema": True,
                "weak_internal_inlinks": False,
            },
            paa_questions=["what is heic?", "is heic lossless?", "how to open heic?"],
        ),
        _flagged("sms france", "https://a.com/receive-sms/fr/", source="orphan_route"),
        _flagged(
            "cheap vpn 2026",
            "https://a.com/vpn/",
            dom_gaps={"title_ctr_deficit": True, "missing_data_table": False},
        ),
    ]
    tasks = compile_wave_backlog(rows, shipped_ledger=set(), target_wave_size=25)
    codes = {t["action_code"] for t in tasks}
    assert "ADD_D1_SPEC_COMPARISON_TABLE" in codes
    assert "INJECT_PAA_SEMANTIC_SECTIONS" in codes
    assert "ADD_WEBAPP_JSONLD_SCHEMA" in codes
    assert "RESCUE_ORPHAN_ROUTE_INLINKS" in codes
    assert "REWRITE_HIGH_CONTRAST_TITLE" in codes
    for task in tasks:
        assert task["tdd_assertion"] and task["file_target"]
    # No duplicate (url, action) pairs even when several flags fire at once.
    keys = [(t["page"], t["action_code"]) for t in tasks]
    assert len(keys) == len(set(keys))


def test_compile_wave_backlog_flags_respect_cooldown():
    from ltr_ranker import compile_wave_backlog

    rows = [
        _flagged(
            "convert heic to jpg",
            "https://a.com/convert/heic-to-jpg/",
            dom_gaps={"missing_data_table": True, "missing_app_schema": True},
        )
    ]
    shipped = {("https://a.com/convert/heic-to-jpg/", "ADD_D1_SPEC_COMPARISON_TABLE")}
    tasks = compile_wave_backlog(rows, shipped_ledger=shipped, target_wave_size=10)
    codes = [t["action_code"] for t in tasks]
    assert "ADD_D1_SPEC_COMPARISON_TABLE" not in codes
    assert "ADD_WEBAPP_JSONLD_SCHEMA" in codes


def test_dom_gap_flags_title_ctr_deficit():
    from collect_features import dom_gap_flags

    weak = dom_gap_flags(
        "<html><title>Cheap VPN Provider</title><h2>Cheap VPN Provider</h2></html>",
        serp_items=[],
        query="cheap vpn",
        ctr=0.015,
        current_pos=5.0,
    )
    assert weak["title_ctr_deficit"] is True
    healthy = dom_gap_flags(
        "<html><title>7 Best Cheap VPN Providers [2026]</title><h2>Cheap VPN</h2></html>",
        serp_items=[],
        query="cheap vpn",
        ctr=0.05,
        current_pos=5.0,
    )
    assert healthy["title_ctr_deficit"] is False
    deep = dom_gap_flags(
        "<html><title>Cheap VPN</title></html>",
        serp_items=[],
        query="cheap vpn",
        ctr=0.001,
        current_pos=40.0,
    )
    assert (
        deep["title_ctr_deficit"] is False
    )  # position > 12: CTR deficit is expected, not a title defect


def test_derive_sibling_counts_groups_distinct_pages_per_prefix():
    from ltr_ranker import derive_sibling_counts

    rows = [
        _scored("q1", f"https://a.com/receive-sms/{cc}/", 10.0, 5.0, 0.0, 0.1, 2.0)
        for cc in ["fr", "de", "it", "es", "pl", "gb", "us", "ca", "au"]
    ]
    rows.append(_scored("q2", "https://a.com/status/", 5.0, 5.0, 1.0, 0.2, 9.0))
    counts = derive_sibling_counts(rows)
    assert counts["/receive-sms/"] == 9
    assert "/status/" not in counts  # single page: no sibling family


def test_refit_from_state_db_trains_and_predicts_on_real_cache_shapes():
    from dataforseo_client import FORUM_UGC_DOMAINS
    from dfs_surrogate import refit_from_state_db
    from fleet_state import connect_state_db, upsert_serp_cache
    import tempfile

    db_path = tempfile.mktemp(suffix=".db")
    conn = connect_state_db(db_path)
    for i in range(25):
        items = [
            {
                "type": "organic",
                "domain": "competitor-x.com",
                "title": f"widget guide {i}" if i % 2 else f"widget guide {i} free",
            },
            {
                "type": "organic",
                "domain": "competitor-y.com",
                "title": f"widget {i} tutorial",
            },
            {
                "type": "organic",
                "domain": FORUM_UGC_DOMAINS[0],
                "title": f"reddit thread {i}",
            },
            {
                "type": "discussions_and_forums",
                "domain": "community.org",
                "title": f"thread {i}",
            },
            {
                "type": "people_also_ask",
                "questions": [f"what is widget {i}?", f"is widget {i} free?"],
            },
        ]
        if i % 3 == 0:
            items.append({"type": "ai_overview", "domain": "google.com"})
        if i % 4 == 0:
            items.append({"type": "keyword_info", "keyword_volume": 100 + i * 10})
        upsert_serp_cache(
            conn, f"widget question {i}", items, ["organic", "people_also_ask"]
        )
    conn.commit()
    conn.close()

    models_dir = tempfile.mkdtemp()
    meta = refit_from_state_db(db_path, models_dir=models_dir)
    assert meta["rows"] >= 20  # floor met -> refit actually trained

    from dfs_surrogate import OfflineDataForSEOSurrogate

    surrogate = OfflineDataForSEOSurrogate()
    assert surrogate.load(models_dir=models_dir) is True
    preds = surrogate.predict_serp_features(["widget question 999"])
    assert preds[0]["feature_source"] == "local_surrogate"
    assert 0.0 <= preds[0]["serp_forum_ratio"] <= 1.0


# ---------------------------------------------------------------------------
# Round 5: URL Inspection coverageState enrichment + combinatorial exhaustion
# guard (three-way expansion)
# ---------------------------------------------------------------------------


def test_url_inspection_state_roundtrip_budget_and_ttl():
    from datetime import datetime, timedelta, timezone

    from fleet_state import (
        inspection_calls_remaining,
        load_url_inspections,
        record_inspection_calls,
        save_url_inspections,
    )
    import tempfile

    from fleet_state import connect_state_db

    conn = connect_state_db(tempfile.mktemp(suffix=".db"))
    now = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)
    save_url_inspections(
        conn,
        "a.com",
        {
            "https://a.com/x/": {
                "coverage_state": "Crawled - currently not indexed",
                "indexing_state": "CRAWLED",
                "last_crawl_time": "2026-11-09",
            }
        },
        now=now,
    )
    fresh = load_url_inspections(conn, ["https://a.com/x/"], now=now)
    assert (
        fresh["https://a.com/x/"]["coverage_state"] == "Crawled - currently not indexed"
    )
    stale = load_url_inspections(
        conn, ["https://a.com/x/"], now=now + timedelta(days=8)
    )
    assert stale == {}

    assert record_inspection_calls(conn, 1998, now=now) == 2
    assert (
        record_inspection_calls(conn, 5, now=now) == 0
    )  # capped at the daily allowance
    assert inspection_calls_remaining(conn, now=now) == 0
    tomorrow = now + timedelta(days=1)
    assert inspection_calls_remaining(conn, now=tomorrow) == 2000


def test_inspect_coverage_states_enriches_caches_and_skips_failures():
    import tempfile

    from collect_features import inspect_coverage_states

    from fleet_state import connect_state_db

    conn = connect_state_db(tempfile.mktemp(suffix=".db"))
    calls = []

    def fake_runner(site, url):
        calls.append(url)
        if url.endswith("broken/"):
            raise RuntimeError("inspection failed")
        return {
            "inspectionResult": {
                "indexStatusResult": {
                    "coverageState": "Crawled - currently not indexed",
                    "indexingState": "CRAWLED",
                    "lastCrawlTime": "2026-11-09T00:00:00Z",
                }
            }
        }

    urls = ["https://a.com/one/", "https://a.com/two/", "https://a.com/broken/"]
    result = inspect_coverage_states(
        "a.com", urls, state_conn=conn, runner=fake_runner, max_calls=10
    )
    assert (
        result["https://a.com/one/"]["coverage_state"]
        == "Crawled - currently not indexed"
    )
    assert "https://a.com/broken/" not in result
    assert len(calls) == 3

    # Second invocation: everything served from the 7-day cache, zero new calls.
    cached = inspect_coverage_states(
        "a.com", urls, state_conn=conn, runner=fake_runner, max_calls=10
    )
    assert (
        cached["https://a.com/two/"]["coverage_state"]
        == "Crawled - currently not indexed"
    )
    assert (
        len(calls) == 4
    )  # successes cached; the failed URL is retried, never poisoned


def test_three_way_matrix_expands_entities_with_modifiers():
    from collect_features import three_way_matrix_from_sitemap

    sitemap = [
        "https://smsriver.com/receive-sms/us/",
        "https://smsriver.com/receive-sms/gb/",
        "https://smsriver.com/receive-sms/fr/",
    ]
    rows = three_way_matrix_from_sitemap(
        sitemap,
        family_prefix="receive-sms",
        modifiers=["free", "without verification"],
        templates=["receive sms online in {entity} {modifier}"],
        max_rows=5,
    )
    assert len(rows) == 5
    assert rows[0]["source"] == "three_way_matrix"
    assert rows[0]["current_pos"] == 100.0
    assert "{entity}" not in rows[0]["query"] and "{modifier}" not in rows[0]["query"]


def test_ensure_candidate_depth_engages_three_way_on_exhaustion():
    from collect_features import ensure_candidate_depth

    gsc = [
        {
            "query": "q1",
            "page": "https://a.com/one/",
            "impressions": 10.0,
            "current_pos": 8.0,
            "clicks_30d": 0.0,
            "ctr": 0.0,
            "source": "gsc",
        }
    ]
    three_way_fn = lambda need: [  # noqa: E731
        {
            "query": f"tw {i}",
            "page": f"https://a.com/tw-{i}/",
            "impressions": 0.0,
            "current_pos": 100.0,
            "clicks_30d": 0.0,
            "ctr": 0.0,
            "source": "three_way_matrix",
        }
        for i in range(need)
    ]

    # (a) exhausted pairwise space (matrix yields nothing) -> three-way engages
    rows, report = ensure_candidate_depth(
        "a.com",
        gsc,
        ["https://a.com/one/"],
        min_rows=3,
        matrix_fn=lambda need: [],
        three_way_fn=three_way_fn,
    )
    assert "three_way_expansion" in report["tiers_used"]
    assert len(rows) >= 3

    # (b) pending backlog below the exhaustion threshold -> three-way engages
    #     even when the pairwise matrix still returned rows
    rows, report = ensure_candidate_depth(
        "a.com",
        gsc,
        ["https://a.com/one/"],
        min_rows=4,
        matrix_fn=lambda need: [
            {
                "query": "pair",
                "page": "https://a.com/pair/",
                "impressions": 0.0,
                "current_pos": 100.0,
                "clicks_30d": 0.0,
                "ctr": 0.0,
            }
        ],
        three_way_fn=three_way_fn,
        pending_backlog=50,
    )
    assert "three_way_expansion" in report["tiers_used"]

    # (c) healthy backlog and matrix delivering rows -> three-way stays idle
    rows, report = ensure_candidate_depth(
        "a.com",
        gsc,
        ["https://a.com/one/"],
        min_rows=3,
        matrix_fn=lambda need: [
            {
                "query": f"pair {i}",
                "page": f"https://a.com/pair-{i}/",
                "impressions": 0.0,
                "current_pos": 100.0,
                "clicks_30d": 0.0,
                "ctr": 0.0,
            }
            for i in range(need)
        ],
        three_way_fn=three_way_fn,
        pending_backlog=500,
    )
    assert "three_way_expansion" not in report["tiers_used"]


def test_compiler_coverage_state_triggers():
    from ltr_ranker import compile_wave_backlog

    crawled = _scored("thin page", "https://a.com/thin/", 8.0, 10.0, 1.0, 0.9, 6.0)
    crawled["coverage_state"] = "Crawled - currently not indexed"
    discovered = _scored(
        "hidden page", "https://a.com/hidden/", 95.0, 0.0, 0.0, 0.9, 1.0
    )
    discovered["coverage_state"] = "Discovered - currently not indexed"
    tasks = compile_wave_backlog(
        [crawled, discovered], shipped_ledger=set(), target_wave_size=10
    )
    codes = {t["action_code"] for t in tasks}
    assert (
        "ADD_D1_SPEC_COMPARISON_TABLE" in codes
    )  # crawled-not-indexed: thin-content gate
    assert (
        "RESCUE_ORPHAN_ROUTE_INLINKS" in codes
    )  # discovered-not-indexed: discovery gate


# ---------------------------------------------------------------------------
# Round 5b: report -> gsc-query window fallback (binary report shape drift)
# ---------------------------------------------------------------------------


def test_gsc_candidates_with_fallback_prefers_report_then_window():
    from collect_features import gsc_candidates_with_fallback

    report_rows = [
        {
            "query": "q1",
            "page": "https://a.com/",
            "clicks": 1,
            "impressions": 10,
            "position": 5.0,
            "ctr": 0.1,
        }
    ]
    window_calls = []

    def run_report(report_id, site):
        return {"presentation": {"tables": []}}  # shape drift: no performance rows

    def pull_window(site, start, end):
        window_calls.append((site, start, end))
        return [
            {
                "query": "w1",
                "page": "https://a.com/x/",
                "clicks_30d": 2.0,
                "impressions": 30.0,
                "current_pos": 7.0,
                "ctr": 0.06,
                "window_days": 0,
                "source": "gsc_window",
            }
        ]

    # Degraded report -> window fallback supplies the candidates.
    candidates, mode = gsc_candidates_with_fallback(
        "sc-domain:a.com",
        run_report_fn=run_report,
        pull_window_fn=pull_window,
        window_days=28,
    )
    assert mode == "gsc_window"
    assert candidates and candidates[0]["source"] == "gsc_window"
    assert len(window_calls) == 1

    # Healthy report -> no window call at all.
    def healthy_report(report_id, site):
        return {"rows": report_rows}

    candidates, mode = gsc_candidates_with_fallback(
        "sc-domain:a.com",
        run_report_fn=healthy_report,
        pull_window_fn=pull_window,
    )
    assert mode == "report"
    assert candidates[0]["query"] == "q1"
    assert len(window_calls) == 1  # unchanged


def test_gsc_candidates_with_fallback_raises_when_both_sources_empty():
    from collect_features import gsc_candidates_with_fallback

    with pytest.raises(RuntimeError):
        gsc_candidates_with_fallback(
            "sc-domain:a.com",
            run_report_fn=lambda rid, site: {},
            pull_window_fn=lambda site, start, end: [],
        )


# ---------------------------------------------------------------------------
# Round 6: backlog starvation fix (full-depth replenish + route-family cap)
# ---------------------------------------------------------------------------


def test_compile_wave_backlog_caps_tasks_per_route_family():
    from ltr_ranker import compile_wave_backlog

    rows = [
        _scored(
            f"num {i}",
            f"https://a.com/number/1202555{i:04d}/",
            8.0,
            10.0,
            1.0,
            0.3,
            2.0,
        )
        for i in range(10)
    ]
    rows += [
        _scored("guide a", "https://a.com/guides/gdpr-sms/", 8.0, 10.0, 1.0, 0.3, 2.0),
        _scored(
            "guide b", "https://a.com/guides/pci-sms-otp/", 8.0, 10.0, 1.0, 0.3, 2.0
        ),
        _scored(
            "compare a",
            "https://a.com/compare/twilio-vs-infobip/",
            8.0,
            10.0,
            1.0,
            0.3,
            2.0,
        ),
    ]
    tasks = compile_wave_backlog(rows, shipped_ledger=set(), target_wave_size=100)
    number_tasks = [t for t in tasks if "/number/" in t["page"]]
    guide_tasks = [t for t in tasks if "/guides/" in t["page"]]
    number_pages = {t["page"] for t in number_tasks}
    assert len(number_pages) <= 3, "one template family must not eat the wave quota"
    assert len(guide_tasks) >= 2
    assert {"INJECT_EXACT_TITLE_AND_H2", "STRENGTHEN_HUB_INTERNAL_LINKS"} <= {
        t["action_code"] for t in tasks
    }
    # Every task carries the registered domain for DB bookkeeping.
    assert all(t["domain"] == "a.com" for t in tasks)


def test_compile_wave_backlog_full_depth_exceeds_wave_size_when_asked():
    from ltr_ranker import compile_wave_backlog

    rows = [
        _scored(f"q{i}", f"https://a.com/fam{i}/route/", 8.0, 10.0, 1.0, 0.3, 2.0)
        for i in range(3)
    ]  # each row triggers exactly 2 rules (title mismatch + weak hub links)
    capped = compile_wave_backlog(rows, shipped_ledger=set(), target_wave_size=4)
    full = compile_wave_backlog(rows, shipped_ledger=set(), target_wave_size=10_000)
    assert len(capped) == 4
    assert len(full) == 6, (
        "replenish mode must decompose EVERY row, not stop at the wave size"
    )


def test_orphan_detector_never_emits_sitemap_index_files():
    from collect_features import synthesize_orphan_rows

    rows = synthesize_orphan_rows(
        [
            "https://a.com/sitemaps/tools.xml",
            "https://a.com/sitemaps/guides.xml/",
            "https://a.com/tools/bulk-validator/",
        ],
        gsc_pages=set(),
        domain="a.com",
    )
    pages = [r["page"] for r in rows]
    assert all(not p.endswith(".xml") for p in pages)
    assert any("bulk-validator" in p for p in pages)
