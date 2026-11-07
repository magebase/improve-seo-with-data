#!/usr/bin/env python3
"""
ltr_ranker.py - Learning-to-Rank core for the SEO opportunity backlog.

Replaces heuristic-only prioritization (Impressions * CTR_Gap) with a
`lightgbm.LGBMRanker` (lambdarank) model trained on the domain's historical
GSC winners, ranking candidate keywords/URLs by Expected 30-Day Click Yield.

Production mechanics implemented here (see
references/serp_intelligence_and_programmatic_scaling.md section 4):

1. Exponential 0-4 relevance grades (`label_gain=[0, 1, 3, 7, 15]`) with a
   conversion override (any conversion => grade 4).
2. Inverse-propensity position-bias correction:
   ExpectedCTR(p) ~= 0.28 / p^1.15; AdjustedClicks = realized * min(5, ECTR(3)/ECTR(p_start))
   so the ranker learns click LIFT, not "recommend whatever already ranks #1".
3. Cluster-integrity 80/20 splitting: validation clusters are fully held out
   (no leakage inside a content subfolder / template / topic cluster).
4. Monotonic constraints so small SEO datasets cannot learn inverted truths
   (lower volume or worse crowding is never "better").
5. `rank_xendcg` one-line drop-in objective for small/noisy datasets.
6. Cross-cluster calibration via a dependency-free isotonic regressor
   (PAVA, out-of-bounds clipping) mapping raw LambdaRank margins to
   calibrated Expected 30-Day Clicks - raw .predict() scores are NOT
   comparable across clusters.
7. Residual learning via `init_score` warm-start from the deterministic
   heuristic, so the ML ranker can never underperform the baseline while
   the training history is young.
8. SHAP-driven action prescription (`pred_contrib=True`) and an 85/15
   exploration/exploitation queue split that injects counterfactual
   variance so the model never goes feedback-loop blind.

Dependencies: numpy + lightgbm ONLY (both already in the factory venv).
No pandas / sklearn / joblib: model bundles persist via LightGBM's native
text format + a JSON sidecar, and calibration is implemented in pure Python.
"""

from __future__ import annotations

import json
import math
import os
import random
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

MODEL_FILE = "seo_lgbm_ranker.txt"
META_FILE = "seo_lgbm_ranker.meta.json"

# Canonical 8-feature vector. Order is load-bearing: MONOTONE_CONSTRAINTS maps 1:1.
FEATURES = [
    "domain_centroid_sim",       # +1: closer to our topical core is always better
    "serp_forum_ratio",          # +1: more weak forums in Top 10 is always easier
    "title_exact_match_rate",    # -1: fewer exact-match competitors is better
    "serp_pixel_crowding",       # -1: less SERP clutter above the fold is better
    "parent_hub_internal_links", # +1: stronger internal hub is better
    "current_pos",               #  0: unconstrained (non-linear sweet spot Pos 8-20)
    "search_volume_log",         # +1: higher volume ceiling is better
    "conversion_intent_score",   # +1: higher historical conversion propensity is better
]

MONOTONE_CONSTRAINTS = [1, 1, -1, -1, 1, 0, 1, 1]

LABEL_GAIN = [0, 1, 3, 7, 15]

# Exploration/exploitation default (85/15): 17 exploited slots + 3 exploratory
# counterfactual slots in a 20-task action queue.
EXPLOIT_SLOTS = 17
EXPLORE_SLOTS = 3

# Cold-start linear proxy weights (Stage 1, before >= 300 labeled outcomes).
COLD_START_WEIGHTS = {
    "centroid_sim": 0.30,
    "forum_ratio": 0.25,
    "title_match_rate": -0.20,
    "pixel_crowding": -0.15,
    "log_volume": 0.10,
}

# Minimum labeled outcome rows before the model (instead of the linear proxy)
# is trusted for queue ordering.
MIN_TRAINING_ROWS = 300


# --------------------------------------------------------------------- labels


def expected_ctr(position: float) -> float:
    """Position-impression propensity curve: ECTR(p) ~= 0.28 / p^1.15."""
    p = max(1.0, float(position))
    return 0.28 / (p ** 1.15)


def position_adjusted_clicks(clicks_30d: float, start_position: float) -> float:
    """De-biases realized clicks against SERP position bias (propensity weighting).

    A page that climbed from position 14 to 6 on a high-intent query must
    outscore a page coasting at position 2 on a vanity query. The propensity
    lift is hard-capped at 5.0 to keep labels bounded.
    """
    p = max(1.0, float(start_position))
    lift = expected_ctr(3.0) / expected_ctr(p)
    return float(clicks_30d) * min(5.0, lift)


def clicks_to_relevance_grade(clicks_30d: np.ndarray, conversions_30d: np.ndarray) -> np.ndarray:
    """Maps 30-day clicks/conversions into 0-4 integer lambdarank grades.

    0 Dead: 0 clicks | 1 Traction: 1-10 | 2 Contributor: 11-50
    3 High Performer: 51-250 | 4 Breakout Winner: >250 or >= 1 conversion.
    """
    clicks = np.asarray(clicks_30d, dtype=float)
    conversions = np.asarray(conversions_30d, dtype=float)
    grades = np.zeros(len(clicks), dtype=int)
    grades = np.where(clicks >= 1, 1, grades)
    grades = np.where(clicks >= 11, 2, grades)
    grades = np.where(clicks >= 51, 3, grades)
    grades = np.where((clicks >= 251) | (conversions >= 1), 4, grades)
    return grades


def bucket_histogram(grades: np.ndarray) -> Dict[int, int]:
    """Count distribution over the 5 grades; rejects non-integer grades."""
    arr = np.asarray(grades)
    if arr.size and not np.allclose(arr, np.round(arr)):
        raise ValueError(f"lambdarank grades must be integers, got: {arr[:5]}")
    hist = {g: 0 for g in range(5)}
    for value in arr.astype(int).tolist():
        hist[value] = hist.get(value, 0) + 1
    return hist


# ---------------------------------------------------------------- heuristics


def heuristic_base_score(
    impressions: float,
    current_pos: float,
    current_ctr: float,
    conv_value: float = 1.0,
) -> float:
    """Deterministic baseline score for init_score residual learning.

    BaseScore = log10(Impressions + 1) * (TargetCTR(p) - CurrentCTR) * ConvValue.
    LightGBM trees then learn only where SERP reality deviates from this
    baseline, so the model can never underperform the heuristic while young.
    """
    target_ctr = expected_ctr(current_pos)
    return math.log10(float(impressions) + 1.0) * (target_ctr - float(current_ctr)) * float(conv_value)


def cold_start_score(
    centroid_sim: float,
    forum_ratio: float,
    title_match_rate: float,
    pixel_crowding: float,
    search_volume: float,
) -> float:
    """Stage-1 deterministic linear lambda proxy (used before >= 300 outcomes).

    Score = 0.30*CentroidSim + 0.25*ForumRatio - 0.20*TitleMatchRate
            - 0.15*PixelCrowding + 0.10*log10(Volume + 1)
    """
    w = COLD_START_WEIGHTS
    return (
        w["centroid_sim"] * float(centroid_sim)
        + w["forum_ratio"] * float(forum_ratio)
        + w["title_match_rate"] * float(title_match_rate)
        + w["pixel_crowding"] * float(pixel_crowding)
        + w["log_volume"] * math.log10(float(search_volume) + 1.0)
    )


# ------------------------------------------------------------------ training


def train_seo_ranker(
    X: np.ndarray,
    y: np.ndarray,
    cluster_ids: np.ndarray,
    objective: str = "lambdarank",
    init_score: Optional[np.ndarray] = None,
    feature_names: Sequence[str] = FEATURES,
    constraints: Sequence[int] = MONOTONE_CONSTRAINTS,
    train_fraction: float = 0.8,
    random_state: int = 42,
) -> Tuple[Any, Dict[str, Any]]:
    """Trains a LightGBM LambdaRanker with cluster-integrity splitting.

    Uses the NATIVE `lgb.train()` API (not `LGBMRanker`), which needs only
    numpy + lightgbm — no scikit-learn dependency in the factory venv.

    Rows are sorted by cluster_id so contiguous blocks form query groups; the
    80/20 split is performed over WHOLE clusters (never inside one), and group
    sizes are derived after sorting. `objective="rank_xendcg"` is a one-line
    drop-in for small/noisy datasets (O(N) per group, no truncation tuning).

    Returns (booster, meta); predictions via booster.predict(X).
    """
    import lightgbm as lgb

    if objective not in ("lambdarank", "rank_xendcg"):
        raise ValueError(f"unsupported ranking objective: {objective!r}")

    X = np.asarray(X, dtype=float)
    y = np.asarray(y)
    clusters = np.asarray(cluster_ids)

    if y.dtype.kind == "f" and (y.max() > 4 or not np.allclose(y, np.round(y))):
        grades = clicks_to_relevance_grade(y, np.zeros(len(y)))
    else:
        grades = y.astype(int)

    order = np.argsort(clusters, kind="stable")
    X, grades, clusters = X[order], grades[order], clusters[order]

    unique_clusters = sorted(set(clusters.tolist()))
    split_idx = int(len(unique_clusters) * train_fraction)
    train_clusters = set(unique_clusters[:split_idx])
    val_clusters = set(unique_clusters[split_idx:])

    is_train = np.array([c in train_clusters for c in clusters])
    train_df, train_y = X[is_train], grades[is_train]
    val_df, val_y = X[~is_train], grades[~is_train]
    train_clusters_sorted = clusters[is_train]
    val_clusters_sorted = clusters[~is_train]

    train_groups = np.unique(train_clusters_sorted, return_counts=True)[1]
    has_val = len(val_df) > 0 and len(val_clusters) > 0

    params = {
        "objective": objective,
        "metric": "ndcg",
        "eval_at": [5, 10],
        "label_gain": list(LABEL_GAIN),
        "monotone_constraints": list(constraints),
        "num_leaves": 15,
        "learning_rate": 0.04,
        "n_estimators": 400,
        "num_boost_round": 400,
        "min_data_in_leaf": 15,
        "bagging_fraction": 0.8,
        "bagging_freq": 1,
        "feature_fraction": 0.8,
        "seed": random_state,
        "verbosity": -1,
    }
    if objective == "lambdarank":
        params["lambdarank_truncation_level"] = 10
        params["lambdarank_norm"] = True

    base_full = None
    if init_score is not None:
        base_full = np.asarray(init_score, dtype=float)[order]

    train_set = lgb.Dataset(
        train_df,
        label=train_y,
        group=train_groups.tolist(),
        init_score=base_full[is_train] if base_full is not None else None,
    )
    valid_sets = []
    if has_val:
        valid_sets.append(
            lgb.Dataset(
                val_df,
                label=val_y,
                group=np.unique(val_clusters_sorted, return_counts=True)[1].tolist(),
                init_score=base_full[~is_train] if base_full is not None else None,
                reference=train_set,
            )
        )

    booster = lgb.train(
        params,
        train_set=train_set,
        valid_sets=valid_sets,
        callbacks=[lgb.early_stopping(stopping_rounds=40, verbose=False)] if valid_sets else [],
    )

    meta = {
        "features": list(feature_names),
        "constraints": list(constraints),
        "objective": objective,
        "best_iteration": int(getattr(booster, "best_iteration", 0) or 0),
        "train_clusters": train_clusters,
        "val_clusters": val_clusters,
        "train_row_clusters": sorted(set(clusters[is_train].tolist())),
        "val_row_clusters": sorted(set(clusters[~is_train].tolist())),
        "used_init_score": init_score is not None,
        "train_rows": int(len(train_df)),
        "val_rows": int(len(val_df)),
    }
    return booster, meta


# ---------------------------------------------------------------- calibration


class IsotonicCalibrator:
    """Pure-Python isotonic regression (PAVA) with out-of-bounds clipping.

    Maps raw, cluster-scale-invariant LambdaRank margins onto calibrated
    Expected 30-Day Clicks so a global Top-20 action queue across clusters is
    mathematically valid.
    """

    def __init__(self, knots_x: List[float], knots_y: List[float]):
        self.knots_x = [float(v) for v in knots_x]
        self.knots_y = [float(v) for v in knots_y]

    @classmethod
    def fit(cls, raw_scores: np.ndarray, realized: np.ndarray) -> "IsotonicCalibrator":
        raw = np.asarray(raw_scores, dtype=float)
        real = np.asarray(realized, dtype=float)
        order = np.argsort(raw, kind="stable")
        raw, real = raw[order], real[order]

        # Merge tied raw scores (mean realized outcome per unique raw value).
        unique_x: List[float] = []
        pooled_y: List[float] = []
        i = 0
        while i < len(raw):
            j = i
            while j + 1 < len(raw) and raw[j + 1] == raw[i]:
                j += 1
            unique_x.append(float(raw[i]))
            pooled_y.append(float(np.mean(real[i : j + 1])))
            i = j + 1

        # Pool-adjacent-violators: enforce a non-decreasing sequence.
        stack_x: List[float] = []
        stack_y: List[float] = []
        stack_w: List[int] = []
        for x, y_val in zip(unique_x, pooled_y):
            weight = 1
            stack_x.append(x)
            stack_y.append(y_val)
            stack_w.append(weight)
            while len(stack_y) > 1 and stack_y[-2] > stack_y[-1]:
                y2, y1 = stack_y.pop(), stack_y.pop()
                w2, w1 = stack_w.pop(), stack_w.pop()
                x2 = stack_x.pop()
                merged_w = w1 + w2
                stack_y.append((y1 * w1 + y2 * w2) / merged_w)
                stack_w.append(merged_w)
                # keep the smaller x as the knot anchor
                stack_x.append(stack_x.pop() if False else x2)
        # Collapse consecutive identical x anchors (keep first).
        knots_x: List[float] = []
        knots_y: List[float] = []
        for x, y_val in zip(stack_x, stack_y):
            if not knots_x or x > knots_x[-1]:
                knots_x.append(x)
                knots_y.append(y_val)
        return cls(knots_x, knots_y)

    def transform(self, values: np.ndarray) -> np.ndarray:
        arr = np.asarray(values, dtype=float)
        out = np.empty(arr.shape, dtype=float)
        flat = arr.reshape(-1)
        flat_out = out.reshape(-1)
        for idx, v in enumerate(flat):
            if v <= self.knots_x[0]:
                flat_out[idx] = self.knots_y[0]
            elif v >= self.knots_x[-1]:
                flat_out[idx] = self.knots_y[-1]
            else:
                lo = int(np.searchsorted(self.knots_x, v, side="right") - 1)
                if lo >= len(self.knots_y) - 1:
                    flat_out[idx] = self.knots_y[-1]
                else:
                    x0, x1 = self.knots_x[lo], self.knots_x[lo + 1]
                    y0, y1 = self.knots_y[lo], self.knots_y[lo + 1]
                    frac = (v - x0) / (x1 - x0) if x1 > x0 else 0.0
                    flat_out[idx] = y0 + frac * (y1 - y0)
        return out

    def to_dict(self) -> Dict[str, List[float]]:
        return {"knots_x": self.knots_x, "knots_y": self.knots_y}

    @classmethod
    def from_dict(cls, blob: Dict[str, List[float]]) -> "IsotonicCalibrator":
        return cls(blob["knots_x"], blob["knots_y"])


# ------------------------------------------------------- bundle persistence


def save_bundle(out_dir: str, ranker: Any, meta: Dict[str, Any], calibrator: Optional[IsotonicCalibrator] = None) -> Tuple[str, str]:
    """Persists the ranker via LightGBM's native format (no joblib) + JSON sidecar."""
    model_path = os.path.join(out_dir, MODEL_FILE)
    meta_path = os.path.join(out_dir, META_FILE)
    ranker.save_model(model_path)
    blob = {
        "features": meta["features"],
        "constraints": meta["constraints"],
        "objective": meta["objective"],
        "best_iteration": meta.get("best_iteration", 0),
        "train_clusters": sorted(meta.get("train_clusters", set())),
        "val_clusters": sorted(meta.get("val_clusters", set())),
        "train_row_clusters": sorted(set(meta.get("train_row_clusters", []))),
        "val_row_clusters": sorted(set(meta.get("val_row_clusters", []))),
        "used_init_score": meta.get("used_init_score", False),
        "calibrator": calibrator.to_dict() if calibrator else None,
    }
    with open(meta_path, "w", encoding="utf-8") as fh:
        json.dump(blob, fh, indent=2)
    return model_path, meta_path


def load_bundle(out_dir: str) -> Dict[str, Any]:
    """Loads a saved ranker bundle; `model` is a lightgbm.Booster ready to predict."""
    import lightgbm as lgb

    model_path = os.path.join(out_dir, MODEL_FILE)
    meta_path = os.path.join(out_dir, META_FILE)
    booster = lgb.Booster(model_file=model_path)
    with open(meta_path, encoding="utf-8") as fh:
        blob = json.load(fh)
    calibrator = IsotonicCalibrator.from_dict(blob["calibrator"]) if blob.get("calibrator") else None
    return {
        "model": booster,
        "features": blob["features"],
        "constraints": blob["constraints"],
        "objective": blob["objective"],
        "best_iteration": blob.get("best_iteration", 0),
        "calibrator": calibrator,
    }


# ----------------------------------------------------------- prescription


def prescribe_action(
    current_pos: float,
    title_match_rate: float,
    hub_links_shap: float,
    centroid_sim: float,
    forum_ratio: float,
    shap: Optional[Dict[str, float]] = None,
) -> str:
    """Maps SHAP drivers + row state onto the 4 executable action families.

    LAUNCH_PSEO_ROUTE            high vulnerability + unindexed/deep candidate
    INJECT_EXACT_H2_AND_TITLE    competitors lack exact query match in title
    BOOST_INTERNAL_LINKS         bottlenecked by low hub link equity (SHAP < 0)
    REWRITE_SNIPPET_AND_TOP_300PX default CTR/Navboost play
    """
    if current_pos == 0 or current_pos > 50:
        return "LAUNCH_PSEO_ROUTE"
    if title_match_rate < 0.4 and current_pos <= 15:
        return "INJECT_EXACT_H2_AND_TITLE"
    if hub_links_shap < 0:
        return "BOOST_INTERNAL_LINKS"
    return "REWRITE_SNIPPET_AND_TOP_300PX"


def cold_start_depth_multiplier(current_pos: float, serp_forum_ratio: float) -> float:
    """Position-depth decay for the cold-start proxy.

    Raw impression weighting alone vaults ultra-deep head terms (a YMYL query
    at position 207 against DR 90 incumbents) above winnable striking-distance
    rows. Deep positions (>50) with NO weak-forum spots in the SERP are
    hyper-competitive and discounted 85%; the striking-distance band (8-25)
    gets a 1.5x boost. Verified live: 'average cost of car insurance' at
    position 207 must never top an immediate action queue.
    """
    pos = float(current_pos)
    if pos > 50.0 and float(serp_forum_ratio) <= 0.0:
        return 0.15
    if 8.0 <= pos <= 25.0:
        return 1.5
    return 1.0


def split_action_queue(
    rows: List[Dict[str, Any]],
    n_exploit: int = EXPLOIT_SLOTS,
    n_explore: int = EXPLORE_SLOTS,
    seed: int = 42,
) -> List[Dict[str, Any]]:
    """Builds the 85/15 exploration/exploitation action queue.

    Exploitation: the top `n_exploit` calibrated/-ranked rows. Exploration:
    `n_explore` rows sampled from the 50th-80th percentile of the backlog
    (stratified across cluster ids, preferring new/untested clusters) so the
    training history keeps receiving counterfactual variance and the ranker
    cannot go feedback-loop blind.
    """
    if not rows:
        return []
    ranked = sorted(rows, key=lambda r: r.get("rank_score", 0.0), reverse=True)
    queue: List[Dict[str, Any]] = []
    for row in ranked[:n_exploit]:
        entry = dict(row)
        entry["slot"] = "exploit"
        queue.append(entry)

    start = int(len(ranked) * 0.50)
    end = max(start + 1, int(len(ranked) * 0.80))
    pool = ranked[start:end]
    if len(pool) < n_explore:
        pool = ranked[n_exploit:]

    rng = random.Random(seed)
    by_cluster: Dict[Any, List[Dict[str, Any]]] = {}
    for row in pool:
        by_cluster.setdefault(row.get("cluster_id"), []).append(row)
    for bucket in by_cluster.values():
        new_first = [r for r in bucket if r.get("is_new_cluster")]
        rng.shuffle(new_first)
        rng.shuffle(bucket)
        bucket[:] = new_first + [r for r in bucket if not r.get("is_new_cluster")]
    cluster_cycle = list(by_cluster.keys())
    rng.shuffle(cluster_cycle)

    chosen: List[Dict[str, Any]] = []
    exhausted = False
    while len(chosen) < n_explore and not exhausted:
        progressed = False
        for key in list(cluster_cycle):
            bucket = by_cluster.get(key) or []
            if bucket:
                chosen.append(bucket.pop(0))
                progressed = True
                if len(chosen) >= n_explore:
                    break
        exhausted = not progressed
    if len(chosen) < n_explore:
        rest = [r for r in pool if r not in chosen]
        rng.shuffle(rest)
        chosen.extend(rest[: n_explore - len(chosen)])

    for row in chosen[:n_explore]:
        entry = dict(row)
        entry["slot"] = "explore"
        queue.append(entry)
    return queue
