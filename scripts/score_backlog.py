#!/usr/bin/env python3
"""
score_backlog.py - Stage 3 of the Learning-to-Rank closed loop. ALWAYS-ON.

Scores the collected candidate backlog (data/ltr_features.json) with the
trained model bundle (models/seo_lgbm_ranker.txt), prescribes an executable
action per candidate from SHAP drivers, calibrates margins into Expected
30-Day Clicks, and emits the 85/15 exploration/exploitation queue:

    data/action_queue.json

Always-on behavior: when no model bundle exists yet, this stage AUTO-TRAINS
a rank_xendcg ranker on the candidate rows themselves — labels come from
DataForSEO SERP-structure bootstrap grades (bootstrap_labels.py), never
from the linear proxy. The deterministic formula survives ONLY as the
init_score residual baseline inside training. If there is genuinely nothing
to train on (< MIN_TRAINABLE_ROWS candidate rows), the stage exits 2 with
pooling instructions instead of emitting proxy-ranked guesses.

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

from bootstrap_labels import generate_bootstrap_grades  # noqa: E402
from ltr_ranker import (  # noqa: E402
    EXPLOIT_SLOTS,
    EXPLORE_SLOTS,
    FEATURES,
    MIN_TRAINABLE_ROWS,
    IsotonicCalibrator,
    heuristic_base_score,
    load_bundle,
    prescribe_action,
    save_bundle,
    split_action_queue,
    train_seo_ranker,
)


def _train_on_the_fly(rows: List[Dict[str, Any]], models_dir: str) -> Dict[str, Any]:
    """Always-on fallback: trains a bootstrap-grade ranker on the very rows
    being scored (and persists it so later runs reuse the bundle)."""
    if len(rows) < MIN_TRAINABLE_ROWS:
        raise RuntimeError(
            f"Only {len(rows)} candidate rows — below the {MIN_TRAINABLE_ROWS}-row "
            "training floor. Run collect_features.py (more candidates), pool the "
            "fleet (fleet_ingest.py), and rerun. The linear proxy is retired; "
            "guess-ranked queues are no longer emitted."
        )
    grades, label_meta = generate_bootstrap_grades(rows)
    X = np.array([[float(r["features"][f]) for f in FEATURES] for r in rows])
    clusters = np.array([str(r.get("cluster_id", "root")) for r in rows])
    init_score = np.array([
        heuristic_base_score(
            impressions=r.get("impressions", 0),
            current_pos=r.get("current_pos", 50),
            current_ctr=r.get("current_ctr", 0.0),
            conv_value=r.get("conv_value", 1.0),
        ) for r in rows
    ])
    booster, meta = train_seo_ranker(
        X, grades, clusters, objective="rank_xendcg", init_score=init_score
    )
    os.makedirs(models_dir, exist_ok=True)
    save_bundle(models_dir, booster, meta, None)
    print(f"Auto-trained rank_xendcg bundle on {len(rows)} rows "
          f"(label_mode={label_meta['label_mode']}, "
          f"best_iteration={meta['best_iteration']}) -> {models_dir}")
    return {"label_mode": label_meta["label_mode"]}


def score_rows(rows: List[Dict[str, Any]], models_dir: str) -> Dict[str, Any]:
    """Scores rows with the bundle when present, else auto-trains one."""
    bundle = None
    if os.path.exists(os.path.join(models_dir, "seo_lgbm_ranker.txt")):
        bundle = load_bundle(models_dir)
    label_mode = None

    if bundle is None:
        print("No trained bundle found -> AUTO-TRAINING a rank_xendcg ranker on "
              "bootstrap grades (the linear proxy is retired).")
        label_mode = _train_on_the_fly(rows, models_dir)["label_mode"]
        bundle = load_bundle(models_dir)

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
    return {"mode": "trained_model", "label_mode": label_mode, "rows": rows}


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

    # One action per query: cannibalised (query, page) pairs collapse onto the
    # best-scoring row (the URL-ownership model allows a single owner per task).
    by_query: Dict[str, Dict[str, Any]] = {}
    for row in scored:
        keeper = by_query.get(row["query"])
        if keeper is None or row.get("rank_score", 0.0) > keeper.get("rank_score", 0.0):
            by_query[row["query"]] = row
    scored = list(by_query.values())

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
