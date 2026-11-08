#!/usr/bin/env python3
"""
train_ranker.py - Stage 2 of the Learning-to-Rank closed loop. ALWAYS-ON.

Builds the training matrix from the pooled outcome history, derives
relevance grades, trains the LightGBM ranker (cluster-integrity split,
monotone constraints, heuristic init_score residual learning), calibrates
raw margins onto Expected 30-Day Clicks with isotonic regression when real
clicks exist, and persists the deployable bundle:

    models/seo_lgbm_ranker.txt        native LightGBM format (no joblib)
    models/seo_lgbm_ranker.meta.json  features, constraints, calibrator knots

ALWAYS-ON LABELING (the cold-start linear proxy is no longer the scorer):
  - >= FLEET_CLICK_ROWS pooled rows carry real clicks -> canonical click
    buckets ("fleet_clicks" mode).
  - otherwise -> DataForSEO SERP-structure bootstrap grades
    ("serp_bootstrap" mode): opportunity-score quantiles with deep-head
    traps hard-graded 0 (see bootstrap_labels.py). The 300-outcome refusal
    is GONE: rank_xendcg + adaptive min_data_in_leaf trains cleanly on
    10-150 row histories. The deterministic heuristic survives ONLY as the
    init_score residual baseline, so the model can never underperform it.

Usage:
    python3 scripts/train_ranker.py                     # always-on xendcg
    python3 scripts/train_ranker.py --objective lambdarank
    python3 scripts/train_ranker.py --history custom.jsonl --models-dir models/

Exits with code 2 only when the history is empty or below MIN_TRAINABLE_ROWS
(no trees can split on it); pool the fleet with fleet_ingest.py first.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, List, Optional

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from bootstrap_labels import (  # noqa: E402
    generate_bootstrap_grades,
)
from ltr_ranker import (  # noqa: E402
    FEATURES,
    IsotonicCalibrator,
    MIN_TRAINABLE_ROWS,
    bucket_histogram,
    heuristic_base_score,
    load_bundle,
    position_adjusted_clicks,
    save_bundle,
    train_seo_ranker,
)

# Re-exported for CLI symmetry / external callers.
save_bundle_compat = save_bundle


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
    objective: str = "rank_xendcg",
    warm_start: bool = True,
    min_rows: int = MIN_TRAINABLE_ROWS,
    force: bool = False,
) -> Optional[Dict[str, Any]]:
    """Always-on train -> calibrate -> persist cycle; returns summary metadata.

    Label authority is automatic (bootstrap_labels.generate_bootstrap_grades):
    real fleet click buckets when >= FLEET_CLICK_ROWS clicked rows exist,
    otherwise DataForSEO SERP-structure quantile grades. Returns None (exit 2)
    only when the history cannot support tree splits at all.
    """
    rows = load_history(history_path)
    if len(rows) < min_rows and not force:
        print(
            f"REFUSING TO TRAIN: {len(rows)} rows < {min_rows} trainable floor.\n"
            "Pool the fleet first: python3 scripts/fleet_ingest.py --inputs "
            "'data/fleet/*.json' (all authenticated GSC properties), then rerun."
        )
        return None

    X, clicks, conversions, clusters = build_matrix(rows)
    grades, label_meta = generate_bootstrap_grades(rows)
    hist = bucket_histogram(grades)
    print(f"Label mode: {label_meta['label_mode']} "
          f"(traps graded 0: {label_meta['trap_count']}, "
          f"clicked rows: {label_meta.get('clicked_rows', 0)})")
    print(f"Label distribution over {len(rows)} rows: {hist}")
    if len(set(grades.tolist())) < 2:
        print(
            "REFUSING TO TRAIN: every row received the same grade — the pooled\n"
            "history has neither click variance nor SERP structure variance to\n"
            "learn from. Enrich more candidates with DataForSEO (collect_features.py)\n"
            "and pool more properties (fleet_ingest.py)."
        )
        return None

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
          f"| min_data_in_leaf: {meta['min_data_in_leaf']} "
          f"| train_rows: {meta['train_rows']} | val_rows: {meta['val_rows']}")
    print(f"Cluster integrity: {len(meta['train_clusters'])} train clusters, "
          f"{len(meta['val_clusters'])} held out: {sorted(meta['val_clusters'])[:8]}")

    # Calibrate raw margins against position-adjusted realized clicks on the
    # held-out validation rows - ONLY when the fleet history already carries
    # real click outcomes. Bootstrap-mode bundles ship uncalibrated margins
    # (expected_clicks_30d=None) rather than inventing click semantics.
    val_mask = np.array([c in set(meta["val_clusters"]) for c in clusters])
    clicked_val = int((clicks[val_mask] > 0).sum()) if val_mask.any() else 0
    if val_mask.any() and meta["best_iteration"] and clicked_val >= 20:
        raw_val = booster.predict(X[val_mask])
        realized_val = np.array([
            position_adjusted_clicks(c, r.get("current_pos", 50))
            for c, r in zip(clicks[val_mask], [rows[i] for i in np.where(val_mask)[0]])
        ])
        calibrator = IsotonicCalibrator.fit(raw_val, realized_val)
        print(f"Isotonic calibration fitted on {clicked_val} clicked validation rows "
              f"({len(calibrator.knots_x)} knots).")
    else:
        calibrator = None
        if val_mask.any():
            print("Calibration SKIPPED (bootstrap mode or < 20 clicked validation rows); "
                  "bundle ships uncalibrated margins.")

    importances = booster.feature_importance(importance_type="gain")
    order = np.argsort(importances)[::-1]
    print("Gain importances:")
    for idx in order:
        print(f"  {FEATURES[idx]:<28} {importances[idx]:10.1f}")

    os.makedirs(models_dir, exist_ok=True)
    model_path, meta_path = save_bundle(models_dir, booster, meta, calibrator)
    print(f"Saved bundle: {model_path} + {os.path.basename(meta_path)}")
    return {
        "best_iteration": meta["best_iteration"],
        "rows": len(rows),
        "objective": objective,
        "label_mode": label_meta["label_mode"],
        "min_data_in_leaf": meta["min_data_in_leaf"],
    }


def bootstrap_history_from_features(features_path: str, history_path: str) -> int:
    """Converts a collect_features.py snapshot into labeled history rows.

    Labels are the ABSOLUTE realized clicks in the GSC window (position-bias
    correction happens at scoring/calibration time, and the snapshot's
    realized clicks ARE the training outcomes for a property's very first
    model). Writes only rows not already present (idempotent by query+page).
    """
    with open(features_path, encoding="utf-8") as fh:
        payload = json.load(fh)
    rows_in = payload.get("rows") or []

    SERP_RICHNESS_KEYS = ("serp_forum_ratio", "title_exact_match_rate",
                          "serp_pixel_crowding")

    def _serp_richness(row: Dict[str, Any]) -> float:
        feats = row.get("features") or {}
        return max(float(feats.get(k, 0.0) or 0.0) for k in SERP_RICHNESS_KEYS)

    history_rows = load_history(history_path) if os.path.exists(history_path) else []
    by_key = {(r.get("query"), r.get("page")): r for r in history_rows}
    upgraded = 0
    added = 0
    for row in rows_in:
        key = (row.get("query"), row.get("page"))
        existing = by_key.get(key)
        if existing is not None:
            # Richer SERP evidence wins in place: a DataForSEO-enriched
            # snapshot row replaces the pooled row's neutral 0.0 SERP fills
            # so retraining learns real structure instead of zeros.
            if _serp_richness(row) > _serp_richness(existing):
                existing["features"] = row.get("features")
                if row.get("current_pos"):
                    existing["current_pos"] = float(row["current_pos"])
                    existing["features"]["current_pos"] = float(row["current_pos"])
                upgraded += 1
            continue
        by_key[key] = {
            "query": row.get("query"),
            "page": row.get("page"),
            "cluster_id": row.get("cluster_id", "root"),
            "features": row.get("features"),
            "clicks_30d": float(row.get("clicks_30d", 0)),
            "conversions_30d": 0.0,
            "impressions": float(row.get("impressions", 0)),
            "current_pos": float(row.get("current_pos", 99)),
            "current_ctr": float(row.get("ctr", 0)),
            "conv_value": 1.0,
            "window_days": row.get("window_days", 90),
            "source": "gsc_snapshot_bootstrap",
        }
        added += 1
    if added or upgraded:
        os.makedirs(os.path.dirname(history_path) or ".", exist_ok=True)
        with open(history_path, "w", encoding="utf-8") as fh:
            for row in by_key.values():
                fh.write(json.dumps(row) + "\n")
    print(f"Bootstrapped {added} new + {upgraded} SERP-upgraded rows -> {history_path}")
    return added


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--history", default="data/ltr_training_history.jsonl")
    parser.add_argument("--models-dir", default="models/")
    parser.add_argument("--objective", default="rank_xendcg",
                        choices=["lambdarank", "rank_xendcg"],
                        help="rank_xendcg is the always-on default (small/noisy "
                             "bootstrapped histories); lambdarank for mature pools")
    parser.add_argument("--no-warm-start", action="store_true",
                        help="train from scratch instead of init_score residuals")
    parser.add_argument("--bootstrap-from", dest="bootstrap_from",
                        help="data/ltr_features.json snapshot to label into history first")
    parser.add_argument("--force", action="store_true",
                        help="train even below the MIN_TRAINABLE_ROWS floor")
    args = parser.parse_args(argv)

    if args.bootstrap_from:
        if not os.path.exists(args.bootstrap_from):
            print(f"ERROR: feature snapshot not found: {args.bootstrap_from}")
            return 1
        bootstrap_history_from_features(args.bootstrap_from, args.history)

    if not os.path.exists(args.history):
        print(f"ERROR: history file not found: {args.history}\n"
              "Pool the fleet first: python3 scripts/fleet_ingest.py --inputs 'data/fleet/*.json'\n"
              "(or run log_outcomes_and_retrain.py to accumulate labeled outcomes).")
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
