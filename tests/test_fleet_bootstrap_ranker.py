#!/usr/bin/env python3
"""
test_fleet_bootstrap_ranker.py - Contract tests for the always-on
Learning-to-Rank architecture (Wave: eliminate the cold-start linear proxy).

Pins the three expansions that let LGBMRanker train on Day 1 with ZERO GSC
clicks, per the DataForSEO-bootstrapped + fleet-pooled architecture:

1. fleet_ingest.harmonize_fleet_history pools (query, page) rows across
   ALL authenticated GSC properties into one domain-agnostic, normalized
   training schema (missing SERP features fill 0.0; volume log-scaled;
   cluster ids assigned from URL paths; deduped per domain).
2. bootstrap_labels.generate_bootstrap_grades derives integer relevance
   grades 0-4 from DataForSEO SERP STRUCTURE (openness x crowding x
   position band x volume, quantile-binned) when the fleet has no click
   variance, and switches to REAL click-bucket grades the moment enough
   clicked rows exist. Deep-head traps (pos > 50, no forums, exact-match
   incumbents) are hard-graded 0.
3. train_ranker trains rank_xendcg ALWAYS (adaptive min_data_in_leaf =
   max(5, n_rows // 30)); below the old 300-outcome gate it no longer
   refuses. score_backlog auto-trains from the candidate rows instead of
   falling back to the linear proxy; the proxy survives ONLY as the
   init_score residual baseline.
"""

import json
import os
import sys
import tempfile
import unittest

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from bootstrap_labels import (  # noqa: E402
    DEEP_HEAD_TRAP_TITLE_MATCH,
    DEEP_HEAD_TRAP_VOLUME_FLOOR,
    generate_bootstrap_grades,
    opportunity_score,
)
from fleet_ingest import harmonize_fleet_history  # noqa: E402
from ltr_ranker import (  # noqa: E402
    FEATURES,
    MIN_TRAINABLE_ROWS,
    load_bundle,
    train_seo_ranker,
)
import score_backlog  # noqa: E402
import train_ranker  # noqa: E402


def _feat_row(query="sms verification", page="https://x.com/tools/lookup/", pos=12.0,
              forum=0.4, title_match=0.1, crowding=0.5, centroid=0.7,
              volume=900.0, clicks=0.0):
    return {
        "query": query,
        "page": page,
        "cluster_id": (page.split("://", 1)[-1].split("/")[1] if "/" in page.split("://", 1)[-1] else "root"),
        "clicks_30d": clicks,
        "conversions_30d": 0.0,
        "impressions": max(50.0, volume / 10.0),
        "current_pos": pos,
        "current_ctr": 0.0,
        "conv_value": 1.0,
        "features": {
            "domain_centroid_sim": centroid,
            "serp_forum_ratio": forum,
            "title_exact_match_rate": title_match,
            "serp_pixel_crowding": crowding,
            "parent_hub_internal_links": 3.0,
            "current_pos": pos,
            "search_volume_log": np.log10(volume + 1),
            "conversion_intent_score": 0.0,
        },
    }


class TestBootstrapGrades(unittest.TestCase):
    def test_zero_click_history_still_yields_grade_variance(self):
        """A brand-new domain (all clicks 0) must produce 3+ distinct grades
        from SERP structure quantiles - the whole point of Day-1 training."""
        rng = np.random.default_rng(7)
        rows = []
        for i in range(60):
            rows.append(_feat_row(
                query=f"query variant {i}",
                page=f"https://x.com/cluster{i % 6}/page-{i}/",
                pos=float(rng.choice([3, 8, 12, 18, 30, 55, 120])),
                forum=float(rng.choice([0.0, 0.2, 0.5])),
                title_match=float(rng.choice([0.0, 0.3, 0.8])),
                volume=float(rng.choice([50, 300, 2000, 9000])),
            ))
        grades, meta = generate_bootstrap_grades(rows)
        self.assertEqual(len(grades), len(rows))
        self.assertGreaterEqual(len(set(grades.tolist())), 3,
                                "SERP bootstrapping must span multiple grades")
        self.assertEqual(meta["label_mode"], "serp_bootstrap")

    def test_deep_head_trap_is_hard_graded_zero(self):
        """Position 207 car-insurance trap: zero forums + exact-match giants
        + real volume must grade 0 no matter how large the volume is."""
        rows = [_feat_row(pos=207.0, forum=0.0, title_match=1.0, volume=50000.0)]
        grades, meta = generate_bootstrap_grades(rows)
        self.assertEqual(int(grades[0]), 0)
        self.assertEqual(meta["trap_count"], 1)

    def test_striking_distance_weak_serp_outranks_crowded_head(self):
        """Open striking-distance SERP (forums present, no exact-match titles)
        must outscore a crowded, exact-match head term at the same position."""
        weak = _feat_row(pos=11.0, forum=0.5, title_match=0.0, crowding=0.0, volume=3000.0)
        locked = _feat_row(pos=11.0, forum=0.0, title_match=1.0, crowding=1.0, volume=3000.0)
        scores = opportunity_score([weak, locked])
        self.assertGreater(scores[0], scores[1] * 2.0)

    def test_real_fleet_clicks_override_serp_quantiles(self):
        """Once >= 50 pooled rows carry real clicks, labels switch to click
        buckets (label_mode flips) - the seamless Day-30 transition."""
        rows = [_feat_row(query=f"q{i}", page=f"https://x.com/c/page-{i}/",
                          clicks=1.0 if i >= 9 else 0.0) for i in range(60)]
        grades, meta = generate_bootstrap_grades(rows)
        self.assertEqual(meta["label_mode"], "fleet_clicks")
        self.assertGreaterEqual(len(set(grades.tolist())), 2)

    def test_grades_are_deterministic(self):
        rows = [_feat_row(query=f"q{i}", page=f"https://x.com/c/page-{i}/",
                          pos=5.0 + i, volume=100.0 * (i + 1)) for i in range(30)]
        g1, _ = generate_bootstrap_grades(rows)
        g2, _ = generate_bootstrap_grades(rows)
        self.assertEqual(g1.tolist(), g2.tolist())

    def test_trap_constants_are_pinned(self):
        """Guard against silent drift of the trap definition."""
        self.assertEqual(DEEP_HEAD_TRAP_TITLE_MATCH, 0.6)
        self.assertEqual(DEEP_HEAD_TRAP_VOLUME_FLOOR, 0.0)


class TestFleetIngest(unittest.TestCase):
    def _property_export(self, domain, clicks=0.0, with_features=True):
        rows = []
        for i in range(5):
            row = {
                "query": f"{domain} query {i}",
                "page": f"https://{domain}/guides/post-{i}/",
                "clicks": clicks,
                "impressions": 100.0 + i,
                "position": 10.0 + i,
                "ctr": 0.01,
            }
            if with_features:
                row["features"] = _feat_row()["features"]
            rows.append(row)
        return {"domain": domain, "rows": rows}

    def test_pools_multiple_properties_into_unified_schema(self):
        pooled = harmonize_fleet_history([
            self._property_export("incomecanvas.com"),
            self._property_export("smsriver.com", clicks=3.0),
        ])
        domains = {r["domain"] for r in pooled}
        self.assertEqual(domains, {"incomecanvas.com", "smsriver.com"})
        for row in pooled:
            self.assertIn("features", row)
            self.assertEqual(len(row["features"]), len(FEATURES))
            self.assertIn("clicks_30d", row)
            self.assertIn("cluster_id", row)

    def test_missing_serp_features_fill_neutral_zero(self):
        pooled = harmonize_fleet_history([self._property_export("a.com", with_features=False)])
        feats = pooled[0]["features"]
        self.assertEqual(feats["serp_forum_ratio"], 0.0)
        self.assertEqual(feats["title_exact_match_rate"], 0.0)
        self.assertEqual(feats["serp_pixel_crowding"], 0.0)

    def test_missing_centroid_sim_fills_neutral_not_off_topic(self):
        """Centroid similarity is a multiplicative factor in the bootstrap
        opportunity score: a 0.0 fill (maximally off-topic) zeroes EVERY
        pooled row's opportunity and collapses all grades to 0. Unknown
        similarity must fill neutral (0.5) so SERP structure alone still
        spreads the grades."""
        pooled = harmonize_fleet_history([self._property_export("a.com", with_features=False)])
        self.assertEqual(pooled[0]["features"]["domain_centroid_sim"], 0.5)
        grades, meta = generate_bootstrap_grades(pooled)
        self.assertEqual(meta["label_mode"], "serp_bootstrap")
        self.assertGreaterEqual(len(set(grades.tolist())), 2)

    def test_volume_is_log_scaled(self):
        pooled = harmonize_fleet_history([self._property_export("a.com", with_features=False)])
        expected = np.log10(101)  # impressions fallback: log10(100 + 1)
        self.assertAlmostEqual(pooled[0]["features"]["search_volume_log"], round(expected, 6), places=5)

    def test_cluster_ids_from_url_paths(self):
        pooled = harmonize_fleet_history([self._property_export("a.com", with_features=False)])
        self.assertEqual(pooled[0]["cluster_id"], "guides")

    def test_dedupes_same_domain_query_page(self):
        prop = self._property_export("a.com")
        prop["rows"].append(dict(prop["rows"][0]))  # exact duplicate
        pooled = harmonize_fleet_history([prop])
        keys = [(r["domain"], r["query"], r["page"]) for r in pooled]
        self.assertEqual(len(keys), len(set(keys)))


class TestAlwaysOnTraining(unittest.TestCase):
    def _write_history(self, path, n_rows=60, clicks=0.0):
        with open(path, "w", encoding="utf-8") as fh:
            for i in range(n_rows):
                row = _feat_row(query=f"q{i}", page=f"https://x.com/cluster{i % 5}/p{i}/",
                                pos=5.0 + (i % 40), volume=100.0 * ((i % 30) + 1),
                                clicks=clicks if clicks else float(i % 3))
                fh.write(json.dumps(row) + "\n")
        return path

    def test_min_trainable_rows_is_below_old_gate(self):
        self.assertLess(MIN_TRAINABLE_ROWS, 300)
        self.assertEqual(MIN_TRAINABLE_ROWS, 10)

    def test_xendcg_trains_on_small_zero_click_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            history = self._write_history(os.path.join(tmp, "h.jsonl"), n_rows=60, clicks=0.0)
            summary = train_ranker.train_from_history(history, os.path.join(tmp, "models"))
            self.assertIsNotNone(summary, "always-on trainer must not refuse a 60-row history")
            self.assertEqual(summary["objective"], "rank_xendcg")
            self.assertEqual(summary["label_mode"], "serp_bootstrap")

    def test_below_floor_still_refuses(self):
        with tempfile.TemporaryDirectory() as tmp:
            history = self._write_history(os.path.join(tmp, "h.jsonl"), n_rows=5, clicks=0.0)
            summary = train_ranker.train_from_history(history, os.path.join(tmp, "models"))
            self.assertIsNone(summary)

    def test_cli_exit_zero_on_zero_click_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            history = self._write_history(os.path.join(tmp, "h.jsonl"), n_rows=60, clicks=0.0)
            models_dir = os.path.join(tmp, "models")
            code = train_ranker.main([
                "--history", history, "--models-dir", models_dir,
                "--objective", "rank_xendcg",
            ])
            self.assertEqual(code, 0)
            self.assertTrue(os.path.exists(os.path.join(models_dir, "seo_lgbm_ranker.txt")))

    def test_adaptive_min_data_in_leaf_small_history(self):
        import lightgbm as lgb  # noqa: F401

        rng = np.random.default_rng(3)
        X = rng.random((60, len(FEATURES)))
        y = np.array([i % 5 for i in range(60)])
        clusters = np.array([f"c{i % 6}" for i in range(60)])
        booster, meta = train_seo_ranker(X, y, clusters, objective="rank_xendcg")
        self.assertGreater(meta["best_iteration"], 0)
        self.assertEqual(meta["objective"], "rank_xendcg")
        self.assertLessEqual(meta["min_data_in_leaf"], 5)

    def test_snapshot_enrichment_upgrades_pooled_rows_in_place(self):
        """collect_features snapshots re-carry (query, page) keys the fleet
        pool already holds, but with REAL DataForSEO SERP features instead of
        0.0 fills. Bootstrap must upgrade those rows in place (no duplicate
        keys, no silent skip) so retraining learns real SERP structure."""
        with tempfile.TemporaryDirectory() as tmp:
            hist = os.path.join(tmp, "history.jsonl")
            base = _feat_row(query="q0", page="https://x.com/c/p0/", forum=0.0,
                             title_match=0.0, crowding=0.0, centroid=0.5)
            base["impressions"] = 100.0
            with open(hist, "w", encoding="utf-8") as fh:
                fh.write(json.dumps(base) + "\n")
            snap = os.path.join(tmp, "snapshot.json")
            json.dump({"rows": [
                _feat_row(query="q0", page="https://x.com/c/p0/", forum=0.6,
                          title_match=0.2, crowding=0.4, centroid=0.8),
                _feat_row(query="q-new", page="https://x.com/c/p9/"),
            ]}, open(snap, "w"))
            added = train_ranker.bootstrap_history_from_features(snap, hist)
            rows = train_ranker.load_history(hist)
            self.assertEqual(len(rows), 2)          # upgraded in place, no dup
            self.assertEqual(added, 1)              # only the genuinely new key
            got = next(r for r in rows if r["query"] == "q0")
            self.assertAlmostEqual(got["features"]["serp_forum_ratio"], 0.6)

    def test_bundle_roundtrip_xendcg(self):
        with tempfile.TemporaryDirectory() as tmp:
            rng = np.random.default_rng(5)
            X = rng.random((80, len(FEATURES)))
            y = np.array([i % 5 for i in range(80)])
            clusters = np.array([f"c{i % 8}" for i in range(80)])
            booster, meta = train_seo_ranker(X, y, clusters, objective="rank_xendcg")
            train_ranker.save_bundle_compat(tmp, booster, meta)
            loaded = load_bundle(tmp)
            self.assertEqual(loaded["objective"], "rank_xendcg")
            preds = loaded["model"].predict(X[:5])
            self.assertEqual(len(preds), 5)


class TestScoreBacklogAlwaysOn(unittest.TestCase):
    def test_auto_trains_instead_of_linear_proxy(self):
        with tempfile.TemporaryDirectory() as tmp:
            rows = [_feat_row(query=f"q{i}", page=f"https://x.com/cluster{i % 4}/p{i}/",
                              pos=5.0 + (i % 30), volume=100.0 * (i + 1)) for i in range(40)]
            result = score_backlog.score_rows(rows, os.path.join(tmp, "models"))
            self.assertEqual(result["mode"], "trained_model")
            self.assertTrue(all("rank_score" in r for r in result["rows"]))
            self.assertTrue(all("prescribed_action" in r for r in result["rows"]))

    def test_refuses_when_no_bundle_and_too_few_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            rows = [_feat_row(query="only one", page="https://x.com/a/b/")]
            with self.assertRaises(RuntimeError):
                score_backlog.score_rows(rows, os.path.join(tmp, "models"))


if __name__ == "__main__":
    unittest.main()
