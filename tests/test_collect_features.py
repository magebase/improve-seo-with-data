#!/usr/bin/env python3
"""
test_collect_features.py - Contract tests for the GSC/DataForSEO feature
collector, pinning the serp_pixel_crowding semantics against the LIVE
advanced-endpoint item shapes (verified 2026-11).
"""

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from collect_features import (
    extract_special_blocks,
    inspect_coverage_states,
    inspection_target_urls,
)
from fleet_state import connect_state_db, save_url_inspections


def _items(*types):
    return [{"type": t} for t in types]


class TestPixelCrowdingFlagCount(unittest.TestCase):
    def test_clean_serp_counts_zero(self):
        serp = _items("organic", "organic", "organic")
        self.assertEqual(extract_special_blocks(serp), 0)

    def test_each_above_fold_block_counts_one(self):
        serp = _items("ai_overview", "organic", "people_also_ask", "organic")
        self.assertEqual(extract_special_blocks(serp), 2)

    def test_bottom_of_page_blocks_never_count(self):
        """related_searches / people_also_search render BELOW the organic
        results on every advanced SERP — counting them poisoned the whole
        backlog (regression: 131/131 rows crowded 2.4-4.0)."""
        serp = _items("organic", "related_searches", "people_also_search")
        self.assertEqual(extract_special_blocks(serp), 0)

    def test_count_capped_at_four(self):
        serp = _items(
            "ai_overview", "featured_snippet", "local_pack",
            "people_also_ask", "video", "images", "paid",
        )
        self.assertEqual(extract_special_blocks(serp), 4)

    def test_feature_value_on_cold_start_scale(self):
        """compute_serp_features must emit the 0-4 scale directly."""
        from collect_features import compute_serp_features

        serp = [*_items("ai_overview"), *_items("organic") * 10, *_items("people_also_ask")]
        feats = compute_serp_features(serp, "test query insurance")
        self.assertLessEqual(feats["serp_pixel_crowding"], 4.0)
        self.assertGreaterEqual(feats["serp_pixel_crowding"], 0.0)



class TestInspectionTargetUrls(unittest.TestCase):
    def test_extra_urls_are_inspected_even_when_not_candidates(self):
        candidates = [{"page": "https://example.com/zero/", "impressions": 0}]
        targets = inspection_target_urls(
            candidates,
            extra_urls=["https://example.com/sitemap-only/"],
            limit=10,
        )
        self.assertEqual(
            targets,
            ["https://example.com/sitemap-only/", "https://example.com/zero/"],
        )

    def test_extras_are_deduped_and_cannot_be_crowded_out(self):
        candidates = [
            {"page": f"https://example.com/c{i}/", "impressions": 0} for i in range(5)
        ]
        targets = inspection_target_urls(
            candidates,
            extra_urls=["https://example.com/sitemap-only/"],
            limit=2,
        )
        self.assertEqual(
            targets,
            ["https://example.com/sitemap-only/", "https://example.com/c0/"],
        )

    def test_impressed_candidates_are_not_inspected(self):
        candidates = [{"page": "https://example.com/impressed/", "impressions": 5}]
        self.assertEqual(inspection_target_urls(candidates, limit=10), [])


class TestForcedInspection(unittest.TestCase):
    def test_force_urls_bypass_a_fresh_cache(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            conn = connect_state_db(str(Path(tmp) / "state.db"))
            url = "https://example.com/sitemap-only/"
            save_url_inspections(
                conn,
                "example.com",
                {url: {"coverage_state": "Not found (404)"}},
            )
            calls: list[str] = []

            def runner(site, target):
                calls.append(target)
                return {
                    "inspectionResult": {
                        "indexStatusResult": {
                            "coverageState": "Submitted and indexed",
                            "lastCrawlTime": "2026-11-27T05:18:31Z",
                        }
                    }
                }

            result = inspect_coverage_states(
                "example.com",
                [url],
                state_conn=conn,
                max_calls=1,
                force_urls=[url],
                runner=runner,
            )
            self.assertEqual(calls, [url])
            self.assertEqual(
                result[url]["coverage_state"], "Submitted and indexed"
            )

if __name__ == "__main__":
    unittest.main()
