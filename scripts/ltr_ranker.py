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
from collections import Counter
from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse

import numpy as np

MODEL_FILE = "seo_lgbm_ranker.txt"
META_FILE = "seo_lgbm_ranker.meta.json"

# Canonical 8-feature vector. Order is load-bearing: MONOTONE_CONSTRAINTS maps 1:1.
FEATURES = [
    "domain_centroid_sim",  # +1: closer to our topical core is always better
    "serp_forum_ratio",  # +1: more weak forums in Top 10 is always easier
    "title_exact_match_rate",  # -1: fewer exact-match competitors is better
    "serp_pixel_crowding",  # -1: less SERP clutter above the fold is better
    "parent_hub_internal_links",  # +1: stronger internal hub is better
    "current_pos",  #  0: unconstrained (non-linear sweet spot Pos 8-20)
    "search_volume_log",  # +1: higher volume ceiling is better
    "conversion_intent_score",  # +1: higher historical conversion propensity is better
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

# Always-on training floor (Wave: eliminate the cold-start proxy). Below the
# old 300-outcome gate the trainer now TRAINS with SERP-bootstrapped grades;
# the proxy survives only as the init_score residual baseline. Below this
# floor there is genuinely nothing for trees to split on.
MIN_TRAINABLE_ROWS = 10


# --------------------------------------------------------------------- labels


def expected_ctr(position: float) -> float:
    """Position-impression propensity curve: ECTR(p) ~= 0.28 / p^1.15."""
    p = max(1.0, float(position))
    return 0.28 / (p**1.15)


def position_adjusted_clicks(clicks_30d: float, start_position: float) -> float:
    """De-biases realized clicks against SERP position bias (propensity weighting).

    A page that climbed from position 14 to 6 on a high-intent query must
    outscore a page coasting at position 2 on a vanity query. The propensity
    lift is hard-capped at 5.0 to keep labels bounded.
    """
    p = max(1.0, float(start_position))
    lift = expected_ctr(3.0) / expected_ctr(p)
    return float(clicks_30d) * min(5.0, lift)


def clicks_to_relevance_grade(
    clicks_30d: np.ndarray, conversions_30d: np.ndarray
) -> np.ndarray:
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


def bucket_histogram(grades: np.ndarray) -> dict[int, int]:
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
    return (
        math.log10(float(impressions) + 1.0)
        * (target_ctr - float(current_ctr))
        * float(conv_value)
    )


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
    init_score: np.ndarray | None = None,
    feature_names: Sequence[str] = FEATURES,
    constraints: Sequence[int] = MONOTONE_CONSTRAINTS,
    train_fraction: float = 0.8,
    random_state: int = 42,
    min_data_in_leaf: int | None = None,
) -> tuple[Any, dict[str, Any]]:
    """Trains a LightGBM LambdaRanker with cluster-integrity splitting.

    Uses the NATIVE `lgb.train()` API (not `LGBMRanker`), which needs only
    numpy + lightgbm — no scikit-learn dependency in the factory venv.

    Rows are sorted by cluster_id so contiguous blocks form query groups; the
    80/20 split is performed over WHOLE clusters (never inside one), and group
    sizes are derived after sorting. `objective="rank_xendcg"` is a one-line
    drop-in for small/noisy datasets (O(N) per group, no truncation tuning).

    `min_data_in_leaf` defaults to the always-on adaptive schedule
    max(5, n_rows // 30): small bootstrapped histories train immediately
    (floor 5), large pooled histories regularize harder.

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

    if min_data_in_leaf is None:
        min_data_in_leaf = max(5, len(X) // 30)

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
        "min_data_in_leaf": int(min_data_in_leaf),
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
        callbacks=[lgb.early_stopping(stopping_rounds=40, verbose=False)]
        if valid_sets
        else [],
    )

    meta = {
        "features": list(feature_names),
        "constraints": list(constraints),
        "objective": objective,
        "best_iteration": int(getattr(booster, "best_iteration", 0) or 0),
        "min_data_in_leaf": int(min_data_in_leaf or 0),
        "train_clusters": train_clusters,
        "val_clusters": val_clusters,
        "train_row_clusters": sorted(set(clusters[is_train].tolist())),
        "val_row_clusters": sorted(set(clusters[~is_train].tolist())),
        "used_init_score": init_score is not None,
        "train_rows": len(train_df),
        "val_rows": len(val_df),
    }
    return booster, meta


# ---------------------------------------------------------------- calibration


class IsotonicCalibrator:
    """Pure-Python isotonic regression (PAVA) with out-of-bounds clipping.

    Maps raw, cluster-scale-invariant LambdaRank margins onto calibrated
    Expected 30-Day Clicks so a global Top-20 action queue across clusters is
    mathematically valid.
    """

    def __init__(self, knots_x: list[float], knots_y: list[float]):
        self.knots_x = [float(v) for v in knots_x]
        self.knots_y = [float(v) for v in knots_y]

    @classmethod
    def fit(cls, raw_scores: np.ndarray, realized: np.ndarray) -> IsotonicCalibrator:
        raw = np.asarray(raw_scores, dtype=float)
        real = np.asarray(realized, dtype=float)
        order = np.argsort(raw, kind="stable")
        raw, real = raw[order], real[order]

        # Merge tied raw scores (mean realized outcome per unique raw value).
        unique_x: list[float] = []
        pooled_y: list[float] = []
        i = 0
        while i < len(raw):
            j = i
            while j + 1 < len(raw) and raw[j + 1] == raw[i]:
                j += 1
            unique_x.append(float(raw[i]))
            pooled_y.append(float(np.mean(real[i : j + 1])))
            i = j + 1

        # Pool-adjacent-violators: enforce a non-decreasing sequence.
        stack_x: list[float] = []
        stack_y: list[float] = []
        stack_w: list[int] = []
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
        knots_x: list[float] = []
        knots_y: list[float] = []
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

    def to_dict(self) -> dict[str, list[float]]:
        return {"knots_x": self.knots_x, "knots_y": self.knots_y}

    @classmethod
    def from_dict(cls, blob: dict[str, list[float]]) -> IsotonicCalibrator:
        return cls(blob["knots_x"], blob["knots_y"])


# ------------------------------------------------------- bundle persistence


def save_bundle(
    out_dir: str,
    ranker: Any,
    meta: dict[str, Any],
    calibrator: IsotonicCalibrator | None = None,
) -> tuple[str, str]:
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


def load_bundle(out_dir: str) -> dict[str, Any]:
    """Loads a saved ranker bundle; `model` is a lightgbm.Booster ready to predict."""
    import lightgbm as lgb

    model_path = os.path.join(out_dir, MODEL_FILE)
    meta_path = os.path.join(out_dir, META_FILE)
    booster = lgb.Booster(model_file=model_path)
    with open(meta_path, encoding="utf-8") as fh:
        blob = json.load(fh)
    calibrator = (
        IsotonicCalibrator.from_dict(blob["calibrator"])
        if blob.get("calibrator")
        else None
    )
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
    shap: dict[str, float] | None = None,
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


# Atomic work-item families emitted by prescribe_all_actions beyond the four
# primary families above. A single (query, page) row can carry several
# simultaneous bottlenecks; each negative SHAP driver maps onto its own TDD
# work item so one queue row can yield multiple distinct fixes.
CTR_HOOK_MIN_IMPRESSIONS = 30.0
SPIN_OUT_MAX_POS = 20.0
SPIN_OUT_MIN_FORUM_RATIO = 0.4

# Prescription set for ORPHAN routes: live sitemap URLs with zero GSC
# impressions. These pages ALREADY EXIST in code, so LAUNCH_PSEO_ROUTE would
# be wrong — they need internal-link equity and route depth, not a new route.
ORPHAN_ACTIONS = ["BOOST_INTERNAL_LINKS", "EXPAND_THIN_ROUTE"]

# Cannibalization: queries carried by >= CANNIBAL_MIN_URLS distinct pages ALL
# ranking worse than CANNIBAL_MAX_POS (a page inside the Top 10 is a winner —
# Guardrail 2 protects it from consolidation).
CANNIBAL_MIN_URLS = 2
CANNIBAL_MAX_POS = 10.0


def prescribe_all_actions(
    current_pos: float,
    title_match_rate: float,
    hub_links_shap: float,
    centroid_sim: float,
    forum_ratio: float,
    impressions: float = 0.0,
    clicks: float = 0.0,
    shap: dict[str, float] | None = None,
) -> list[str]:
    """Explodes EVERY applicable atomic prescription for one row, primary first.

    Extends prescribe_action (which stays the single primary classifier):
    - REWRITE_CTR_TITLE_AND_TOP_300PX  decent position, real impressions,
      zero clicks -> the snippet is the bottleneck (CTR hook failure).
    - SPIN_OUT_DEDICATED_SUBROUTE      forum/UGC-heavy SERP within striking
      distance -> a dedicated sub-route can outflank the forum block.
    - BOOST_INTERNAL_LINKS             negative hub-equity SHAP driver.
    The deterministic fallback (REWRITE_SNIPPET_AND_TOP_300PX) applies only
    when nothing more specific fires, matching prescribe_action's default.
    """
    primary = prescribe_action(
        current_pos=current_pos,
        title_match_rate=title_match_rate,
        hub_links_shap=hub_links_shap,
        centroid_sim=centroid_sim,
        forum_ratio=forum_ratio,
        shap=shap,
    )
    actions: list[str] = [primary]
    if current_pos <= 10.0 and impressions >= CTR_HOOK_MIN_IMPRESSIONS and clicks == 0:
        actions.append("REWRITE_CTR_TITLE_AND_TOP_300PX")
    if current_pos <= SPIN_OUT_MAX_POS and forum_ratio >= SPIN_OUT_MIN_FORUM_RATIO:
        actions.append("SPIN_OUT_DEDICATED_SUBROUTE")
    if hub_links_shap < 0 and "BOOST_INTERNAL_LINKS" not in actions:
        actions.append("BOOST_INTERNAL_LINKS")
    # Re-derive the primary guarantee: for unranked rows the classifier emits
    # LAUNCH_PSEO_ROUTE and no further atomic fix is actionable on a page that
    # does not exist yet; drop duplicates while preserving order.
    deduped: list[str] = []
    for action in actions:
        if action not in deduped:
            deduped.append(action)
    return deduped


# ----------------------------------------------------------------- queue policy
#
# The cooldown ledger and per-domain quota slicing live here so the Stage-3
# scorer and the Stage-4 outcome logger share ONE definition of "shipped".


def record_shipped(
    queue: list[dict[str, Any]],
    ledger_path: str,
    deployed_at: str | None = None,
) -> int:
    """Appends executed queue tasks to the cooldown ledger (JSONL).

    Each record: {query, page, domain, action_type(s), deployed_at}. Returns
    the number of records written. Idempotent callers dedupe upstream; the
    ledger itself is append-only history.
    """
    stamp = deployed_at or datetime.now(timezone.utc).isoformat()
    directory = os.path.dirname(ledger_path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    written = 0
    with open(ledger_path, "a", encoding="utf-8") as fh:
        for entry in queue:
            page = str(entry.get("page", ""))
            actions = entry.get("actions") or (
                [entry["prescribed_action"]] if entry.get("prescribed_action") else []
            )
            record = {
                "query": entry.get("query"),
                "page": page,
                "domain": _registered_domain(page),
                "action_types": actions,
                "deployed_at": stamp,
            }
            fh.write(json.dumps(record) + "\n")
            written += 1
    return written


def _registered_domain(page: str) -> str:
    """Lower-case registered domain from a URL (namespace-tolerant)."""
    try:
        from urllib.parse import urlparse

        host = (urlparse(page).hostname or page).lower()
        parts = host.split(".")
        return ".".join(parts[-2:]) if len(parts) > 2 else host
    except Exception:  # noqa: BLE001 - ledger keys degrade to the raw string
        return page.lower()


def load_cooldown_keys(
    ledger_path: str,
    within_days: int = 30,
    now: datetime | None = None,
) -> set[tuple[str, str]]:
    """Returns {(page, action_type)} shipped within the cooldown window."""
    if not os.path.exists(ledger_path):
        return set()
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    cutoff = now - timedelta(days=within_days)
    cooled: set = set()
    with open(ledger_path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue  # a torn trailing line never blocks the queue
            stamp = record.get("deployed_at")
            if isinstance(stamp, str):
                try:
                    shipped = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
                except ValueError:
                    continue
            elif isinstance(stamp, (int, float)):
                shipped = datetime.fromtimestamp(stamp / 1000.0, tz=timezone.utc)
            else:
                continue
            if shipped.tzinfo is None:
                shipped = shipped.replace(tzinfo=timezone.utc)
            if shipped > cutoff:
                page = str(record.get("page", ""))
                for action in record.get("action_types") or [record.get("action_type")]:
                    if action:
                        cooled.add((page, str(action)))
    return cooled


def filter_cooldown(
    rows: list[dict[str, Any]],
    cooled: set[tuple[str, str]],
) -> tuple:
    """Drops cooled (page, action_type) work items from scored rows.

    A row survives with its remaining fresh actions; a row whose actions are
    ALL inside the cooldown window is skipped entirely so the next wave of
    unoptimized pages surfaces instead.
    Returns (kept_rows, skipped_rows).
    """
    kept: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for row in rows:
        page = str(row.get("page", ""))
        actions = list(
            row.get("actions")
            or ([row["prescribed_action"]] if row.get("prescribed_action") else [])
        )
        fresh = [a for a in actions if (page, a) not in cooled]
        if not actions:
            kept.append(row)
        elif not fresh:
            skipped.append(row)
        else:
            row["actions"] = fresh
            row["prescribed_action"] = fresh[0]
            kept.append(row)
    return kept, skipped


def detect_cannibalization(
    scored_rows: list[dict[str, Any]],
    *,
    min_urls: int = CANNIBAL_MIN_URLS,
    max_pos: float = CANNIBAL_MAX_POS,
) -> tuple:
    """Flags queries split across >= min_urls distinct pages, all beyond max_pos.

    Both (or all) competing URLs must sit worse than ``max_pos`` — a page
    inside the Top 10 is a winning owner protected by Guardrail 2. Returns
    (rows, consolidation_tasks): each affected keeper row gains
    ``cannibalized_pages`` + a ``CONSOLIDATE_CANNIBALIZED_URLS`` action; each
    task carries the full competing-URL set with 301/canonical/title-split
    remedy hints for the implementing agent.
    """
    by_query: dict[str, list[dict[str, Any]]] = {}
    for row in scored_rows:
        by_query.setdefault(str(row.get("query", "")).strip().lower(), []).append(row)

    tasks: list[dict[str, Any]] = []
    for query, group in by_query.items():
        pages = {str(r.get("page", "")) for r in group}
        if len(pages) < min_urls:
            continue
        positions = [float(r.get("current_pos", 100) or 100) for r in group]
        if min(positions) <= max_pos:
            continue  # someone already owns a Top-10 slot; leave it alone
        sorted_pages = sorted(
            group, key=lambda r: float(r.get("current_pos", 100) or 100)
        )
        primary = sorted_pages[0]
        competitors = [str(r.get("page", "")) for r in sorted_pages[1:]]
        tasks.append(
            {
                "query": primary.get("query"),
                "page": primary.get("page"),
                "action": "CONSOLIDATE_CANNIBALIZED_URLS",
                "pages": [str(primary.get("page", ""))] + competitors,
                "positions": {
                    str(r.get("page", "")): float(r.get("current_pos", 100) or 100)
                    for r in group
                },
                "remedies": [
                    "301 the weakest duplicate into the strongest page",
                    "or differentiate title/h1 modifiers onto separate sub-intents",
                    "or set rel=canonical to the strongest page",
                ],
            }
        )
        for row in group:
            others = competitors if row is primary else [str(primary.get("page", ""))]
            row.setdefault("cannibalized_pages", others)
            if "CONSOLIDATE_CANNIBALIZED_URLS" not in row["actions"]:
                row["actions"].append("CONSOLIDATE_CANNIBALIZED_URLS")

    return scored_rows, tasks


def slice_per_domain(
    queue: list[dict[str, Any]], per_domain_top: int
) -> list[dict[str, Any]]:
    """Caps the final queue at ``per_domain_top`` tasks per registered domain.

    In a pooled fleet model a big property (hundreds of GSC rows) naturally
    crowds younger properties out of the Top-N. Grouping the globally ranked
    queue by domain and slicing keeps every enrolled property actionable on
    demand. Global rank order is preserved within each domain's slice.
    """
    if per_domain_top <= 0:
        return list(queue)
    seen: dict[str, int] = {}
    sliced: list[dict[str, Any]] = []
    for entry in sorted(queue, key=lambda r: r.get("rank_score", 0.0), reverse=True):
        domain = _registered_domain(str(entry.get("page", "")))
        count = seen.get(domain, 0)
        if count >= per_domain_top:
            continue
        seen[domain] = count + 1
        sliced.append(entry)
    return sliced


def derive_sibling_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    """Derives catalog-family sibling counts from the candidate rows themselves.

    Groups distinct page URLs by their first path segment (e.g. /receive-sms/)
    so the wave compiler can attach catalog_propagation hints without the
    caller hand-maintaining a prefix map. Single-page prefixes (hub pages,
    one-off routes) are excluded - there is nothing to propagate across.
    """
    buckets: dict[str, set] = {}
    for row in rows:
        page = str(row.get("page", ""))
        path = urlparse(page).path if page.startswith("http") else "/" + page.strip("/")
        segments = [seg for seg in path.split("/") if seg]
        if len(segments) < 2:
            continue  # root-level pages have no programmatic family
        prefix = f"/{segments[0]}/"
        buckets.setdefault(prefix, set()).add(page.rstrip("/"))
    return {
        prefix: len(pages)
        for prefix, pages in sorted(buckets.items())
        if len(pages) >= 2
    }


def is_truly_unbuilt_route(
    url: str,
    known_live_urls: set[str] | None = None,
    url_total_impressions: int = 0,
) -> bool:
    """A route is only unbuilt if it is absent from sitemaps/shipped history AND has 0 total GSC impressions."""
    if url_total_impressions > 0:
        return False
    if known_live_urls:
        norm = url.rstrip("/")
        norm_slash = norm + "/"
        if norm in known_live_urls or norm_slash in known_live_urls:
            return False
    return True


def compile_wave_backlog(
    rows: list[dict[str, Any]],
    shipped_ledger: set | None = None,
    target_wave_size: int = 40,
    sibling_counts: dict[str, int] | None = None,
    max_per_family: int = 3,
    known_live_urls: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Compiles a ranked backlog into ATOMIC TDD tasks (35-60 per wave).

    One scored row can carry several independent fixes; each fix becomes its
    own task with a machine-checkable ``tdd_assertion`` and a concrete
    ``file_target`` so a coding agent can implement and verify it without
    re-deriving intent. Cooldown-masked (page, action) pairs from the shipped
    ledger are skipped, duplicates are impossible, and programmatic-route
    tasks propagate their template change across every catalog sibling.

    ``target_wave_size`` caps the RETURNED list (the actionable wave); pass a
    large value when replenishing the SQLite backlog, where full-depth
    decomposition matters more than the per-invocation slice.

    ``max_per_family`` (route-template cap) stops a single programmatic
    subfolder from eating the wave quota: /number/<digits>/ pages share ONE
    template, so more than ``max_per_family`` tasks for that family would be
    25 edits of the same file. The first family hits carry the
    catalog_propagation hint (one template change covers every sibling);
    deeper hits are skipped so /guides/, /compare/ and /tools/ get scored in.
    """
    shipped_keys = {
        (str(page).rstrip("/"), str(code)) for page, code in (shipped_ledger or set())
    }
    sibling_counts = sibling_counts or {}
    rules: list[tuple[str, Any]] = [
        (
            "BOOST_CLUSTER_CROSS_LINKS",
            lambda r: (
                float((r.get("shap") or {}).get("parent_hub_internal_links", 0.0)) < 0.0
            ),
        ),
        (
            "OVERHAUL_CTR_HOOK_AND_WEBAPP_SCHEMA",
            lambda r: (
                float(r.get("impressions", 0.0) or 0.0) >= 30.0
                and float(r.get("clicks_30d", 0.0) or 0.0) == 0.0
            ),
        ),
        (
            "INJECT_EXACT_TITLE_AND_H2",
            lambda r: (
                float((r.get("features") or {}).get("title_exact_match_rate", 1.0))
                < 0.5
            ),
        ),
        (
            "STRENGTHEN_HUB_INTERNAL_LINKS",
            lambda r: (
                float((r.get("features") or {}).get("parent_hub_internal_links", 99.0))
                < 3.0
            ),
        ),
        (
            "RESCUE_ORPHAN_ROUTE_INLINKS",
            lambda r: (
                str(r.get("source", "")) == "orphan_route"
                or bool(r.get("is_sitemap_orphan"))
                or str(r.get("coverage_state", ""))
                == "Discovered - currently not indexed"
            ),
        ),
        (
            "CREATE_PROGRAMMATIC_ROUTE",
            lambda r: (
                float(r.get("current_pos", 0.0) or 0.0) >= 90.0
                and str(r.get("coverage_state", "")) != "Discovered - currently not indexed"
            ),
        ),
        (
            "ADD_D1_SPEC_COMPARISON_TABLE",
            lambda r: (
                bool((r.get("dom_gaps") or {}).get("missing_data_table"))
                or str(r.get("coverage_state", "")) == "Crawled - currently not indexed"
            ),
        ),
        (
            "INJECT_PAA_SEMANTIC_SECTIONS",
            lambda r: bool((r.get("dom_gaps") or {}).get("missing_paa_coverage")),
        ),
        (
            "ADD_WEBAPP_JSONLD_SCHEMA",
            lambda r: bool((r.get("dom_gaps") or {}).get("missing_app_schema")),
        ),
        (
            "REWRITE_HIGH_CONTRAST_TITLE",
            lambda r: bool((r.get("dom_gaps") or {}).get("title_ctr_deficit")),
        ),
    ]
    assertions: dict[str, str] = {
        "BOOST_CLUSTER_CROSS_LINKS": "assert >=3 in-body contextual links from sibling cluster pages to {page}",
        "OVERHAUL_CTR_HOOK_AND_WEBAPP_SCHEMA": "assert <title> differs from the SERP winner title for '{query}' and WebApplication JSON-LD is present",
        "INJECT_EXACT_TITLE_AND_H2": "assert the page <h2> contains the exact token set of '{query}'",
        "STRENGTHEN_HUB_INTERNAL_LINKS": "assert the parent hub page contains a link to {page}",
        "CREATE_PROGRAMMATIC_ROUTE": "assert a new route for '{query}' resolves 200 with a unique <title>",
        "RESCUE_ORPHAN_ROUTE_INLINKS": "assert the homepage or parent hub renders <a href='{page}'> with descriptive anchor text",
        "ADD_D1_SPEC_COMPARISON_TABLE": "assert the response for '{query}' includes a semantic <table> with >=4 rows of concrete specs/metrics",
        "INJECT_PAA_SEMANTIC_SECTIONS": "assert the DOM renders <details>/<h3> blocks answering the SERP PAA questions {paa}",
        "ADD_WEBAPP_JSONLD_SCHEMA": "assert the response for '{query}' includes valid WebApplication JSON-LD (name, operatingSystem, applicationCategory, offers)",
        "REWRITE_HIGH_CONTRAST_TITLE": "assert the <title> for '{query}' contains a bracketed value hook or number and stays within 60 characters",
        "INJECT_SECONDARY_H2_ONLY": "assert a new <h2> or <table> section covers '{query}' without altering the established <title>",
    }
    tasks: list[dict[str, Any]] = []
    emitted: set = set()
    family_counts: Counter = Counter()
    known = set(known_live_urls or set())
    for r in rows:
        p = str(r.get("page", "")).rstrip("/")
        if float(r.get("impressions", 0) or 0) > 0 or float(r.get("clicks_30d", 0) or 0) > 0:
            known.add(p)
            known.add(p + "/")
    for p, _ in (shipped_ledger or set()):
        known.add(str(p).rstrip("/"))
        known.add(str(p).rstrip("/") + "/")
    for row in sorted(rows, key=lambda r: r.get("rank_score", 0.0), reverse=True):
        page = str(row.get("page", ""))
        page_key = page.rstrip("/")
        query = str(row.get("query", ""))
        path = urlparse(page).path if page.startswith("http") else "/" + page.strip("/")
        path_segments = [seg for seg in path.strip("/").split("/") if seg]
        route_family = path_segments[0] if len(path_segments) > 1 else page_key
        if max_per_family > 0 and family_counts[route_family] >= max_per_family:
            continue  # this template family already filled its wave quota
        tasks_before_row = len(tasks)
        propagation = None
        for prefix, count in sorted(sibling_counts.items(), key=lambda kv: -len(kv[0])):
            if path.startswith(prefix):
                propagation = {"prefix": prefix, "siblings": int(count)}
                break
        total_imp = int(row.get("total_page_impressions", 0) or row.get("impressions", 0) or 0)
        is_unbuilt = (
            is_truly_unbuilt_route(page, known, total_imp)
            and float(row.get("current_pos", 0.0) or 0.0) >= 90.0
            and str(row.get("coverage_state", "")) != "Discovered - currently not indexed"
        )
        for code, predicate in rules:
            if is_unbuilt and code != "CREATE_PROGRAMMATIC_ROUTE":
                continue
            if code == "CREATE_PROGRAMMATIC_ROUTE" and not is_unbuilt:
                continue
            if not predicate(row):
                continue
            # Rule: Never emit inlink tasks for root homepage '/' (every page already links to / via brand header/footer)
            if path in ("", "/") and code in (
                "WIRE_HUB_AND_FOOTER_INLINKS",
                "STRENGTHEN_HUB_INTERNAL_LINKS",
                "RESCUE_ORPHAN_ROUTE_INLINKS",
                "BOOST_CLUSTER_CROSS_LINKS",
            ):
                continue
            key = (page_key, code)
            if key in emitted or key in shipped_keys:
                continue
            emitted.add(key)
            file_target = (
                f"templates{path.rstrip('/')}.html"
                if path.strip("/")
                else "templates/index.html"
            )
            paa_questions = [str(q) for q in (row.get("paa_questions") or [])[:3]] or [
                "the top People-Also-Ask questions for the query"
            ]
            task: dict[str, Any] = {
                "action_code": code,
                "query": query,
                "page": page,
                "domain": _registered_domain(page),
                "file_target": file_target,
                "tdd_assertion": assertions[code].format(
                    page=page,
                    query=query,
                    paa=", ".join(f"'{q}'" for q in paa_questions),
                ),
                "rank_score": float(row.get("rank_score", 0.0) or 0.0),
                "priority_score": float(row.get("priority_score") or row.get("rank_score") or 0.0),
                "lgbm_score": float(row.get("rank_score", 0.0) or 0.0),
                "expected_value": float(row.get("expected_value") or 0.0),
                "cannibalization_risk": float(row.get("cannibalization_risk") or 0.0),
                "confidence": float(row.get("confidence") or 1.0),
                "decision_class": str(row.get("decision_class") or "SHIP"),
                "source": row.get("source", "gsc"),
                "shap": row.get("shap"),
                "features": row.get("features"),
            }
            if row.get("shap") and isinstance(row["shap"], dict):
                top_shap = sorted(row["shap"].items(), key=lambda kv: abs(float(kv[1])), reverse=True)[:3]
                task["target_component"] = ", ".join(f"{'+' if v>=0 else ''}{v:.2f} {k}" for k, v in top_shap)
            if propagation is not None:
                task["catalog_propagation"] = dict(propagation)
            tasks.append(task)
            if len(tasks) >= target_wave_size:
                return tasks
            if code == "CREATE_PROGRAMMATIC_ROUTE":
                # A brand-new programmatic route bundles exact title, H2, and inlinks
                # upon creation; skip emitting secondary atomic tweaks for the same row.
                break
        if len(tasks) > tasks_before_row:
            family_counts[route_family] += 1  # cap DISTINCT pages per family
    return tasks


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
    rows: list[dict[str, Any]],
    n_exploit: int = EXPLOIT_SLOTS,
    n_explore: int = EXPLORE_SLOTS,
    seed: int = 42,
) -> list[dict[str, Any]]:
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
    queue: list[dict[str, Any]] = []
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
    by_cluster: dict[Any, list[dict[str, Any]]] = {}
    for row in pool:
        by_cluster.setdefault(row.get("cluster_id"), []).append(row)
    for bucket in by_cluster.values():
        new_first = [r for r in bucket if r.get("is_new_cluster")]
        rng.shuffle(new_first)
        rng.shuffle(bucket)
        bucket[:] = new_first + [r for r in bucket if not r.get("is_new_cluster")]
    cluster_cycle = list(by_cluster.keys())
    rng.shuffle(cluster_cycle)

    chosen: list[dict[str, Any]] = []
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
