#!/usr/bin/env python3
"""
train_ranker.py - Stage 2 of the Learning-to-Rank closed loop.

Builds the training matrix from the outcome history, trains the LightGBM
LambdaRanker (cluster-integrity split, monotone constraints, heuristic
init_score residual learning), calibrates raw margins onto Expected 30-Day
Clicks with isotonic regression, and persists the deployable bundle:

    models/seo_lgbm_ranker.txt        native LightGBM format (no joblib)
    models/seo_lgbm_ranker.meta.json  features, constraints, calibrator knots

Usage:
    python3 scripts/train_ranker.py                     # standard path
    python3 scripts/train_ranker.py --objective rank_xendcg
    python3 scripts/train_ranker.py --history custom.jsonl --models-dir models/

Exits with code 2 when the history has fewer than 300 labeled outcomes
(the model is not yet trustworthy; the cold-start proxy stays authoritative).
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
    FEATURES,
    IsotonicCalibrator,
    MIN_TRAINING_ROWS,
    bucket_histogram,
    clicks_to_relevance_grade,
    heuristic_base_score,
    load_bundle,
    position_adjusted_clicks,
    save_bundle,
    train_seo_ranker,
)


def load_history(path: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def build_matrix(rows: List[Dict[str, Any]]) -> tuple:
    X = np.array([[float(r["features"][f]) for f in FEATURES] for r in rows], dtype=float)
    clicks = np.array([float(r.get("clicks_30d", 0)) for r in rows])
    conversions = np.array([float(r.get("conversions_30d", 0)) for r in rows])
    clusters = np.array([str(r.get("cluster_id", "root")) for r in rows])
    return X, clicks, conversions, clusters


def train_from_history(
    history_path: str,
    models_dir: str,
    objective: str = "lambdarank",
    warm_start: bool = True,
    min_rows: int = MIN_TRAINING_ROWS,
    force: bool = False,
) -> Optional[Dict[str, Any]]:
    """Full train -> calibrate -> persist cycle; returns summary metadata."""
    rows = load_history(history_path)
    if len(rows) < min_rows and not force:
        print(
            f"REFUSING TO TRAIN: {len(rows)} labeled outcome rows < {min_rows} required.\n"
            "The cold-start linear proxy remains authoritative until the 30-day\n"
            "delta loop has accumulated enough outcomes (see SKILL.md Stage 3).\n"
            "Override with --force once you understand the consequences."
        )
        return None

    X, clicks, conversions, clusters = build_matrix(rows)
    grades = clicks_to_relevance_grade(clicks, conversions)
    hist = bucket_histogram(grades)
    print(f"Label distribution over {len(rows)} outcomes: {hist}")

    init_score = None
    if warm_start:
        init_score = np.array([
            heuristic_base_score(
                impressions=r.get("impressions", 0),
                current_pos=r.get("current_pos", 50),
                current_ctr=r.get("current_ctr", 0.0),
                conv_value=r.get("conv_value", 1.0),
            ) for r in rows
        ])

    booster, meta = train_seo_ranker(
        X, grades, clusters, objective=objective, init_score=init_score
    )
    print(f"Objective: {objective} | best_iteration: {meta['best_iteration']} "
          f"| train_rows: {meta['train_rows']} | val_rows: {meta['val_rows']}")
    print(f"Cluster integrity: {len(meta['train_clusters'])} train clusters, "
          f"{len(meta['val_clusters'])} held out: {sorted(meta['val_clusters'])[:8]}")

    # Calibrate raw margins against position-adjusted realized clicks on the
    # held-out validation rows.
    val_mask = np.array([c in set(meta["val_clusters"]) for c in clusters])
    if val_mask.any() and meta["best_iteration"]:
        raw_val = booster.predict(X[val_mask])
        realized_val = np.array([
            position_adjusted_clicks(c, r.get("current_pos", 50))
            for c, r in zip(clicks[val_mask], [rows[i] for i in np.where(val_mask)[0]])
        ])
        calibrator = IsotonicCalibrator.fit(raw_val, realized_val)
        print(f"Isotonic calibration fitted on {int(val_mask.sum())} validation rows "
              f"({len(calibrator.knots_x)} knots).")
    else:
        calibrator = None
        print("WARNING: no held-out calibration data; bundle ships uncalibrated margins.")

    importances = booster.feature_importance(importance_type="gain")
    order = np.argsort(importances)[::-1]
    print("Gain importances:")
    for idx in order:
        print(f"  {FEATURES[idx]:<28} {importances[idx]:10.1f}")

    os.makedirs(models_dir, exist_ok=True)
    model_path, meta_path = save_bundle(models_dir, booster, meta, calibrator)
    print(f"Saved bundle: {model_path} + {os.path.basename(meta_path)}")
    return {"best_iteration": meta["best_iteration"], "rows": len(rows)}


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--history", default="data/ltr_training_history.jsonl")
    parser.add_argument("--models-dir", default="models/")
    parser.add_argument("--objective", default="lambdarank",
                        choices=["lambdarank", "rank_xendcg"])
    parser.add_argument("--no-warm-start", action="store_true",
                        help="train from scratch instead of init_score residuals")
    parser.add_argument("--force", action="store_true",
                        help="train even below the 300-outcome guard")
    args = parser.parse_args(argv)

    if not os.path.exists(args.history):
        print(f"ERROR: history file not found: {args.history}\n"
              "Run log_outcomes_and_retrain.py to accumulate labeled outcomes first.")
        return 1

    summary = train_from_history(
        args.history,
        args.models_dir,
        objective=args.objective,
        warm_start=not args.no_warm_start,
        force=args.force,
    )
    if summary is None:
        return 2

    # Smoke-verify the persisted bundle round-trips.
    loaded = load_bundle(args.models_dir)
    print(f"Bundle verification: {loaded['objective']} model loads, "
          f"calibrator={'fitted' if loaded['calibrator'] else 'none'}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
