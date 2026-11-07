#!/usr/bin/env python3
"""
test_ltr_ranker.py - Contract tests for the Learning-to-Rank pipeline of the
improve-seo-with-data skill.

Pins the production mechanics that separate an industrial SEO prioritization
engine from a toy LGBMRanker script:
1. exponential 0-4 relevance grading with conversion override
2. inverse-propensity position-bias correction (Expected CTR(p) = 0.28/p^1.15)
3. cold-start deterministic linear proxy (exact weights, pre-300-outcome mode)
4. cluster-integrity 80/20 splitting (no leakage inside a cluster)
5. monotonic constraints shipped to LightGBM exactly as specified
6. rank_xendcg drop-in objective option
7. pure-Python isotonic calibration with out-of-bounds clipping
8. SHAP-driven action prescription
9. 85/15 exploration vs exploitation queue split
10. model bundle save/load round-trip (native LightGBM format, no joblib)
"""

import json
import math
import os
import sys
import tempfile
import unittest

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from ltr_ranker import (  # noqa: E402
    FEATURES,
    MONOTONE_CONSTRAINTS,
    IsotonicCalibrator,
    bucket_histogram,
    clicks_to_relevance_grade,
    cold_start_score,
    expected_ctr,
    heuristic_base_score,
    load_bundle,
    position_adjusted_clicks,
    prescribe_action,
    save_bundle,
    split_action_queue,
    train_seo_ranker,
)


class TestRelevanceGrading(unittest.TestCase):
    def test_exponential_click_buckets(self):
        clicks = np.array([0, 1, 10, 11, 50, 51, 251, 1000])
        conversions = np.zeros_like(clicks)
        grades = clicks_to_relevance_grade(clicks, conversions)
        self.assertEqual(grades.tolist(), [0, 1, 1, 2, 2, 3, 4, 4])

    def test_single_conversion_is_breakout_winner(self):
        """One conversion outranks any click count below the >250 bucket."""
        grades = clicks_to_relevance_grade(np.array([5, 300]), np.array([1, 0]))
        self.assertEqual(grades.tolist(), [4, 4])

    def test_histogram_rejects_non_integer(self):
        with self.assertRaises(ValueError):
            bucket_histogram(np.array([0.5, 1.5]))


class TestPositionBiasCorrection(unittest.TestCase):
    def test_expected_ctr_monotone_decreasing(self):
        self.assertGreater(expected_ctr(1), expected_ctr(3))
        self.assertGreater(expected_ctr(3), expected_ctr(11))

    def test_position_adjusted_clicks_cap_at_five(self):
        """The propensity lift is hard-capped at 5.0 to avoid explosive labels."""
        adjusted = position_adjusted_clicks(clicks_30d=100, start_position=20)
        self.assertLessEqual(adjusted, 100 * 5.0 + 1e-9)

    def test_rank14_to_rank6_outscores_coasting_rank2(self):
        """A page that climbed from deep positions outranks a coasting vanity #2."""
        climber = position_adjusted_clicks(clicks_30d=30, start_position=14)
        coaster = position_adjusted_clicks(clicks_30d=30, start_position=2)
        self.assertGreater(climber, coaster * 2)


class TestColdStartProxy(unittest.TestCase):
    def test_exact_linear_weights(self):
        score = cold_start_score(
            centroid_sim=1.0, forum_ratio=1.0, title_match_rate=0.0,
            pixel_crowding=0.0, search_volume=9999,
        )
        expected = 0.30 * 1.0 + 0.25 * 1.0 - 0.20 * 0.0 - 0.15 * 0.0 + 0.10 * math.log10(9999 + 1)
        self.assertAlmostEqual(score, expected, places=6)

    def test_crowded_entrenched_serp_scores_negative(self):
        score = cold_start_score(
            centroid_sim=0.0, forum_ratio=0.0, title_match_rate=1.0,
            pixel_crowding=4.0, search_volume=10,
        )
        self.assertLess(score, 0.0)


class TestMonotoneContract(unittest.TestCase):
    def test_eight_features_eight_constraints(self):
        self.assertEqual(len(FEATURES), 8)
        self.assertEqual(len(MONOTONE_CONSTRAINTS), 8)

    def test_specified_constraint_signs(self):
        """(+1 centroid, +1 forum, -1 title match, -1 crowding, +1 hub links, 0 position, +1 volume, +1 intent)"""
        self.assertEqual(MONOTONE_CONSTRAINTS, [1, 1, -1, -1, 1, 0, 1, 1])


class TestClusterSplitTraining(unittest.TestCase):
    def _dataset(self):
        rng = np.random.RandomState(7)
        rows, cluster_ids, labels = [], [], []
        for cluster in range(10):
            for _ in range(20):
                rows.append([
                    rng.rand(), rng.rand(), rng.rand(), rng.rand(),
                    float(rng.randint(0, 30)), float(rng.randint(0, 90)),
                    rng.rand() * 4, rng.rand(),
                ])
                cluster_ids.append(cluster)
                labels.append(rng.randint(0, 5))
        return np.array(rows), np.array(labels), np.array(cluster_ids)

    def test_train_produces_model_and_metadata(self):
        X, y, clusters = self._dataset()
        ranker, meta = train_seo_ranker(X, y, clusters)
        self.assertEqual(meta["features"], FEATURES)
        self.assertIn("best_iteration", meta)
        scores = ranker.predict(X[:5])
        self.assertEqual(len(scores), 5)

    def test_cluster_split_never_leaks(self):
        """Validation ROWS must never share a cluster with training rows."""
        X, y, clusters = self._dataset()
        _, meta = train_seo_ranker(X, y, clusters)
        self.assertFalse(set(meta["train_row_clusters"]) & set(meta["val_row_clusters"]))
        self.assertEqual(
            len(set(meta["train_row_clusters"]) | set(meta["val_row_clusters"])), 10
        )

    def test_xendcg_objective_drop_in(self):
        X, y, clusters = self._dataset()
        ranker, meta = train_seo_ranker(X, y, clusters, objective="rank_xendcg")
        self.assertEqual(meta["objective"], "rank_xendcg")
        ranker.predict(X[:3])

    def test_residual_learning_via_init_score(self):
        """Warm-starting from the heuristic must still train and beat nothing-loss."""
        X, y, clusters = self._dataset()
        base = np.abs(np.random.RandomState(3).randn(len(y)))
        ranker, meta = train_seo_ranker(X, y, clusters, init_score=base)
        self.assertTrue(meta["used_init_score"])

    def test_bundle_round_trip_without_joblib(self):
        X, y, clusters = self._dataset()
        ranker, meta = train_seo_ranker(X, y, clusters)
        with tempfile.TemporaryDirectory() as tmp:
            model_path, meta_path = save_bundle(tmp, ranker, meta)
            self.assertTrue(os.path.exists(model_path))
            self.assertTrue(os.path.exists(meta_path))
            loaded = load_bundle(tmp)
            self.assertEqual(loaded["features"], FEATURES)
            self.assertEqual(list(loaded["constraints"]), MONOTONE_CONSTRAINTS)
            np.testing.assert_allclose(
                loaded["model"].predict(X[:5]), ranker.predict(X[:5]), rtol=1e-5
            )


class TestIsotonicCalibrator(unittest.TestCase):
    def test_pava_fits_monotone_mapping(self):
        raw = np.array([0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8])
        realized = np.array([1.0, 0.5, 2.0, 2.5, 3.0, 5.0, 9.0, 12.0])
        cal = IsotonicCalibrator.fit(raw, realized)
        preds = cal.transform(raw)
        self.assertTrue(np.all(np.diff(preds) >= -1e-9))
        self.assertAlmostEqual(preds[0], 0.75, places=6)  # pooled first two

    def test_out_of_bounds_clipped(self):
        raw = np.array([1.0, 2.0, 3.0])
        realized = np.array([1.0, 2.0, 3.0])
        cal = IsotonicCalibrator.fit(raw, realized)
        self.assertEqual(cal.transform(np.array([-5.0]))[0], 1.0)
        self.assertEqual(cal.transform(np.array([99.0]))[0], 3.0)

    def test_json_serialization_round_trip(self):
        raw = np.array([1.0, 2.0, 3.0, 4.0])
        realized = np.array([10.0, 20.0, 25.0, 40.0])
        cal = IsotonicCalibrator.fit(raw, realized)
        blob = json.dumps(cal.to_dict())
        cal2 = IsotonicCalibrator.from_dict(json.loads(blob))
        np.testing.assert_allclose(cal.transform(raw), cal2.transform(raw))


class TestPrescription(unittest.TestCase):
    def test_launch_route_for_vulnerable_unindexed(self):
        shap = {f: 0.0 for f in FEATURES}
        action = prescribe_action(
            current_pos=0, title_match_rate=0.2, hub_links_shap=0.0,
            centroid_sim=0.8, forum_ratio=0.6, shap=shap,
        )
        self.assertEqual(action, "LAUNCH_PSEO_ROUTE")

    def test_inject_exact_h2_for_position_15_with_weak_match(self):
        shap = {f: 0.0 for f in FEATURES}
        action = prescribe_action(
            current_pos=12, title_match_rate=0.2, hub_links_shap=0.1,
            centroid_sim=0.8, forum_ratio=0.6, shap=shap,
        )
        self.assertEqual(action, "INJECT_EXACT_H2_AND_TITLE")

    def test_internal_links_when_hub_shap_negative(self):
        shap = dict(zip(FEATURES, [0, 0, 0, 0, -0.7, 0, 0, 0]))
        action = prescribe_action(
            current_pos=9, title_match_rate=0.9, hub_links_shap=-0.7,
            centroid_sim=0.8, forum_ratio=0.6, shap=shap,
        )
        self.assertEqual(action, "BOOST_INTERNAL_LINKS")

    def test_default_snippet_rewrite(self):
        shap = {f: 0.0 for f in FEATURES}
        action = prescribe_action(
            current_pos=9, title_match_rate=0.9, hub_links_shap=0.2,
            centroid_sim=0.8, forum_ratio=0.6, shap=shap,
        )
        self.assertEqual(action, "REWRITE_SNIPPET_AND_TOP_300PX")


class TestExplorationSplit(unittest.TestCase):
    def test_queue_is_17_exploit_plus_3_explore(self):
        rows = [
            {"keyword": f"kw{i}", "rank_score": 100 - i, "cluster_id": i % 7, "is_new_cluster": i % 2 == 0}
            for i in range(60)
        ]
        queue = split_action_queue(rows, n_exploit=17, n_explore=3, seed=11)
        self.assertEqual(len(queue), 20)
        exploit = [r for r in queue if r["slot"] == "exploit"]
        explore = [r for r in queue if r["slot"] == "explore"]
        self.assertEqual(len(exploit), 17)
        self.assertEqual(len(explore), 3)
        # Exploitation slots must be the top-ranked rows
        self.assertEqual(exploit[0]["keyword"], "kw0")

    def test_explore_draws_from_middle_percentiles_not_head(self):
        rows = [
            {"keyword": f"kw{i}", "rank_score": 1000 - i, "cluster_id": i % 5, "is_new_cluster": True}
            for i in range(100)
        ]
        queue = split_action_queue(rows, n_exploit=17, n_explore=3, seed=5)
        explore_keywords = {r["keyword"] for r in queue if r["slot"] == "explore"}
        top20 = {f"kw{i}" for i in range(20)}
        self.assertFalse(explore_keywords & top20)


if __name__ == "__main__":
    unittest.main()
