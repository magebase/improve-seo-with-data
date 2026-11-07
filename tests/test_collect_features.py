#!/usr/bin/env python3
"""
test_collect_features.py - Contract tests for the GSC/DataForSEO feature
collector, pinning the serp_pixel_crowding semantics against the LIVE
advanced-endpoint item shapes (verified 2026-11).
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from collect_features import extract_special_blocks  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()
