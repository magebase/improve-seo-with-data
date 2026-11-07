#!/usr/bin/env python3
"""
score_backlog.py - Stage 3 of the Learning-to-Rank closed loop.

Scores the collected candidate backlog (data/ltr_features.json) with the
trained model bundle (models/seo_lgbm_ranker.txt), prescribes an executable
action per candidate from SHAP drivers, calibrates margins into Expected
30-Day Clicks, and emits the 85/15 exploration/exploitation queue:

    data/action_queue.json

Cold-start behavior: when no model bundle exists yet, candidates are ranked
by the deterministic linear lambda proxy (LTR_COLD_START linear formula) so
the pipeline is operational from day one.

Usage:
    python3 scripts/score_backlog.py
    python3 scripts/score_backlog.py --features data/ltr_features.json \\
        --models-dir models/ --queue-size 20
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, List, Optional

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ltr_ranker import (  # noqa: E402
    EXPLOIT_SLOTS,
    EXPLORE_SLOTS,
    FEATURES,
    cold_start_score,
    load_bundle,
    prescribe_action,
    split_action_queue,
)


def score_rows(rows: List[Dict[str, Any]], models_dir: str) -> Dict[str, Any]:
    """Scores rows with the bundle when present, else the cold-start proxy."""
    bundle = None
    if os.path.exists(os.path.join(models_dir, "seo_lgbm_ranker.txt")):
        bundle = load_bundle(models_dir)

    if bundle is None:
        print("No trained bundle found -> COLD-START linear proxy ranking "
              "(Stage 1 of the closed loop).")
        for row in rows:
            feats = row["features"]
            row["rank_score"] = cold_start_score(
                centroid_sim=feats["domain_centroid_sim"],
                forum_ratio=feats["serp_forum_ratio"],
                title_match_rate=feats["title_exact_match_rate"],
                pixel_crowding=feats["serp_pixel_crowding"],
                search_volume=10 ** feats["search_volume_log"] - 1 if feats["search_volume_log"] > 0 else 0,
            )
            row["expected_clicks_30d"] = None
            row["prescribed_action"] = prescribe_action(
                current_pos=feats["current_pos"],
                title_match_rate=feats["title_exact_match_rate"],
                hub_links_shap=0.0,
                centroid_sim=feats["domain_centroid_sim"],
                forum_ratio=feats["serp_forum_ratio"],
            )
        return {"mode": "cold_start_proxy", "rows": rows}

    print(f"Scoring {len(rows)} candidates with trained {bundle['objective']} model ...")
    X = np.array([[float(r["features"][f]) for f in bundle["features"]] for r in rows])
    raw_scores = bundle["model"].predict(X)

    # SHAP contributions: (n, n_features + 1); last column is the bias term.
    shap_matrix = bundle["model"].predict(X, pred_contrib=True)
    has_calibrator = bundle["calibrator"] is not None
    for i, row in enumerate(rows):
        feats = row["features"]
        row["rank_score"] = float(raw_scores[i])
        if has_calibrator:
            row["expected_clicks_30d"] = float(bundle["calibrator"].transform(np.array([raw_scores[i]]))[0])
        else:
            row["expected_clicks_30d"] = None
        shap_row = shap_matrix[i][: len(FEATURES)]
        shap = dict(zip(FEATURES, (float(v) for v in shap_row)))
        row["shap"] = {k: round(v, 6) for k, v in shap.items()}
        row["prescribed_action"] = prescribe_action(
            current_pos=feats["current_pos"],
            title_match_rate=feats["title_exact_match_rate"],
            hub_links_shap=shap["parent_hub_internal_links"],
            centroid_sim=feats["domain_centroid_sim"],
            forum_ratio=feats["serp_forum_ratio"],
            shap=shap,
        )
    return {"mode": "trained_model", "rows": rows}


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--features", default="data/ltr_features.json")
    parser.add_argument("--models-dir", default="models/")
    parser.add_argument("--output", default="data/action_queue.json")
    parser.add_argument("--queue-size", type=int, default=20)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args(argv)

    if not os.path.exists(args.features):
        print(f"ERROR: {args.features} not found. Run collect_features.py first.")
        return 1

    with open(args.features, encoding="utf-8") as fh:
        payload = json.load(fh)
    rows = payload.get("rows") or []
    if not rows:
        print("ERROR: feature file contains no rows.")
        return 1

    result = score_rows(rows, args.models_dir)
    scored = result["rows"]

    n_exploit = max(1, int(args.queue_size * EXPLOIT_SLOTS / (EXPLOIT_SLOTS + EXPLORE_SLOTS)))
    n_explore = max(1, args.queue_size - n_exploit)
    queue = split_action_queue(scored, n_exploit=n_exploit, n_explore=n_explore, seed=args.seed)

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as fh:
        json.dump({
            "site": payload.get("site"),
            "scoring_mode": result["mode"],
            "queue": queue,
        }, fh, indent=2)

    print(f"\nAction queue ({result['mode']}, {len(queue)} tasks) -> {args.output}")
    print(f"{'slot':<9} {'action':<32} {'score':>8} {'exp30d':>8}  query")
    for entry in queue:
        exp = entry.get("expected_clicks_30d")
        exp_s = f"{exp:.1f}" if isinstance(exp, float) else "-"
        print(f"{entry['slot']:<9} {entry['prescribed_action']:<32} "
              f"{entry['rank_score']:>8.3f} {exp_s:>8}  {entry['query'][:60]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
