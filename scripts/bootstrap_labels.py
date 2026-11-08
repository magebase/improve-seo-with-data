#!/usr/bin/env python3
"""
bootstrap_labels.py - DataForSEO SERP-to-Relevance Bootstrapping Engine.

Replaces click-dependent label generation so LGBMRanker trains on Day 1
with ZERO GSC clicks. Every DataForSEO Top-10 fetch is free ground truth:
the live SERP is literally what Google rewarded for that query, so SERP
STRUCTURE (forum/UGC share, competitor title exact-match rate, feature
crowding) x demand (search volume) x position band yields integer
relevance grades 0-4 without any of our own click history.

Grading modes (automatic, per call):
  fleet_clicks     - the pooled fleet history has >= FLEET_CLICK_ROWS rows
                     with real clicks: labels become the canonical click
                     buckets (clicks_to_relevance_grade) and the loop has
                     transitioned to self-supervised reality.
  serp_bootstrap   - no click variance yet: opportunity scores are
                     quantile-binned into grades 1-4 (0 = dead), with
                     deep-head traps hard-graded 0.

Deep-head trap definition (verified against the live 'average cost of car
insurance' row at position 207): current_pos > 50, zero forum/UGC results
in the Top 10, and >= 60% of incumbents exact-matching the query in their
titles. High volume makes these rows LOOK attractive; the trap grade keeps
them pinned at the bottom of every action queue.

Pure numpy. No pandas / sklearn / joblib.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

import numpy as np

from ltr_ranker import clicks_to_relevance_grade  # noqa: E402

# SERP-structure grading constants (pinned by tests/test_fleet_bootstrap_ranker.py).
STRIKING_DISTANCE_BAND = (4.0, 25.0)   # position band with the 2.0x opportunity weight
MIDFIELD_BAND = (26.0, 50.0)           # position band with the 0.8x weight
POS_WEIGHT_STRIKING = 2.0
POS_WEIGHT_MIDFIELD = 0.8
POS_WEIGHT_DEEP = 0.25

FORUM_OPENNESS_WEIGHT = 2.0            # each weak-forum Top-10 slot doubles openness contribution
CROWDING_PENALTY_FLOOR = 0.2           # crowding can claw back at most 80% of the score
CROWDING_PENALTY_SCALE = 0.2

DEEP_HEAD_TRAP_POS = 50.0              # deeper than page 5
DEEP_HEAD_TRAP_FORUM_RATIO = 0.0       # zero weak/UGC slots in the Top 10
DEEP_HEAD_TRAP_TITLE_MATCH = 0.6       # most incumbents exact-match the query
DEEP_HEAD_TRAP_VOLUME_FLOOR = 0.0      # volume gate kept as a pinned tuning knob

# Quantile cut points for opportunity-score binning (grades 1-4).
GRADE_QUANTILES = (0.50, 0.75, 0.90, 0.97)

# Pooled fleet rows with clicks>0 needed before SERP quantile labels are
# replaced by real click-bucket labels.
FLEET_CLICK_ROWS = 50


def opportunity_score(rows: List[Dict[str, Any]]) -> np.ndarray:
    """DataForSEO opportunity potential per candidate row.

    opportunity = search_volume_log * serp_openness * crowding_penalty
                  * pos_weight * domain_centroid_sim

    - serp_openness  = (1 - title_exact_match_rate) + forum_ratio * 2.0
    - crowding_pen.  = clip(1 - 0.2 * pixel_crowding, 0.2, 1.0)
    - pos_weight     = 2.0 striking (4-25) | 0.8 midfield (26-50) | 0.25 deep
    Deep-head traps score 0.0 outright (high volume + entrenched exact-match
    incumbents + zero forum relief = unwinnable on Day 1).
    """
    vec = _feature_vectors(rows)
    pos, forum, title_match, crowding, vol_log, centroid = vec

    serp_openness = (1.0 - title_match) + (forum * FORUM_OPENNESS_WEIGHT)
    crowding_penalty = np.clip(1.0 - (crowding * CROWDING_PENALTY_SCALE), CROWDING_PENALTY_FLOOR, 1.0)

    pos_weight = np.full(len(rows), POS_WEIGHT_DEEP)
    striking = (pos >= STRIKING_DISTANCE_BAND[0]) & (pos <= STRIKING_DISTANCE_BAND[1])
    midfield = (pos >= MIDFIELD_BAND[0]) & (pos <= MIDFIELD_BAND[1])
    pos_weight = np.where(midfield, POS_WEIGHT_MIDFIELD, pos_weight)
    pos_weight = np.where(striking, POS_WEIGHT_STRIKING, pos_weight)

    score = vol_log * serp_openness * crowding_penalty * pos_weight * centroid
    trap = deep_head_trap_mask(vec)
    return np.where(trap, 0.0, score)


def deep_head_trap_mask(vec: Tuple[np.ndarray, ...]) -> np.ndarray:
    """Rows the skill must never spend engineering time on: deep positions,
    zero forum relief, entrenched exact-match incumbents."""
    pos, forum, title_match, _, vol_log, _ = vec
    return (pos > DEEP_HEAD_TRAP_POS) & (forum <= DEEP_HEAD_TRAP_FORUM_RATIO) & (
        title_match >= DEEP_HEAD_TRAP_TITLE_MATCH
    ) & (vol_log >= DEEP_HEAD_TRAP_VOLUME_FLOOR)


def _feature_vectors(rows: List[Dict[str, Any]]) -> Tuple[np.ndarray, ...]:
    """Extracts aligned feature vectors from feature-row dicts (collect_features
    output shape). Missing features degrade to neutral values."""

    def feat(row: Dict[str, Any], key: str, default: float) -> float:
        value = row.get("features", {}).get(key, row.get(key, default))
        try:
            return float(value)
        except (TypeError, ValueError):
            return float(default)

    pos = np.array([feat(r, "current_pos", 99.0) for r in rows])
    forum = np.array([feat(r, "serp_forum_ratio", 0.0) for r in rows])
    title_match = np.array([feat(r, "title_exact_match_rate", 0.0) for r in rows])
    crowding = np.array([feat(r, "serp_pixel_crowding", 0.0) for r in rows])
    vol_log = np.array([feat(r, "search_volume_log", 1.0) for r in rows])
    centroid = np.array([feat(r, "domain_centroid_sim", 0.0) for r in rows])
    return pos, forum, title_match, crowding, vol_log, centroid


def generate_bootstrap_grades(
    rows: List[Dict[str, Any]],
    clicked_threshold: int = FLEET_CLICK_ROWS,
) -> Tuple[np.ndarray, Dict[str, Any]]:
    """Computes integer 0-4 relevance grades for a pooled candidate/history.

    Returns (grades, meta). meta["label_mode"] reports which labeling
    authority won:
      "fleet_clicks"   - >= clicked_threshold rows carry real clicks; grades
                         are the canonical click buckets (exponential gains).
      "serp_bootstrap" - not enough click variance; grades are SERP
                         structure quantiles (with traps hard-graded 0).
    """
    if not rows:
        return np.zeros(0, dtype=int), {"label_mode": "empty", "trap_count": 0}

    clicks = np.array([float(r.get("clicks_30d", 0) or 0) for r in rows])
    clicked_rows = int((clicks > 0).sum())
    vec = _feature_vectors(rows)
    trap_count = int(deep_head_trap_mask(vec).sum())

    if clicked_rows >= clicked_threshold:
        conversions = np.array([float(r.get("conversions_30d", 0) or 0) for r in rows])
        grades = clicks_to_relevance_grade(clicks, conversions)
        return grades.astype(int), {
            "label_mode": "fleet_clicks",
            "trap_count": trap_count,
            "clicked_rows": clicked_rows,
        }

    scores = opportunity_score(rows)
    grades = np.zeros(len(rows), dtype=int)
    valid = scores[scores > 0]
    if len(valid) >= 8:
        q50, q75, q90, q97 = np.quantile(valid, GRADE_QUANTILES)
        grades = np.where(scores > q50, 1, grades)
        grades = np.where(scores > q75, 2, grades)
        grades = np.where(scores > q90, 3, grades)
        grades = np.where(scores > q97, 4, grades)
    elif len(valid) > 0:
        # Tiny cohorts: rank-order binning instead of quantiles so variance
        # still exists for the trees to split on.
        order = np.argsort(np.argsort(scores, kind="stable"))
        grades = np.where(scores > 0, (order * 4 // max(1, len(scores) - 1)).astype(int) + 1, 1)
        grades = np.where(scores > 0, np.clip(grades, 1, 4), 0)
    trap = deep_head_trap_mask(vec)
    grades = np.where(trap, 0, grades)
    return grades.astype(int), {
        "label_mode": "serp_bootstrap",
        "trap_count": trap_count,
        "clicked_rows": clicked_rows,
        "opportunity_quantiles": [round(float(q), 6) for q in np.quantile(valid, GRADE_QUANTILES)] if len(valid) >= 8 else None,
    }
