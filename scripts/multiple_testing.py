#!/usr/bin/env python3
"""multiple_testing.py - False Discovery Rate (FDR) & Sequential Testing Guard (v2.3 P0).

Provides multiple-testing corrections and sequential evaluation rules across
133 action effectiveness clusters to prevent false discoveries:
1. Benjamini-Hochberg (BH) False Discovery Rate (FDR) control at q = 0.05.
2. Holm-Bonferroni Family-Wise Error Rate (FWER) step-down procedure.
3. Minimum Meaningful Effect Size (MMES) gating (ROPE: Region of Practical Equivalence).
4. Fixed Evaluation Horizon Guard preventing continuous significance peeking.
"""

from __future__ import annotations

import math
from typing import Any
import numpy as np
from scipy import stats


def apply_benjamini_hochberg(
    p_values: list[float],
    fdr_q: float = 0.05,
) -> list[dict[str, Any]]:
    """Applies Benjamini-Hochberg procedure to control False Discovery Rate.

    Given m p-values, sorts them p_(1) <= p_(2) <= ... <= p_(m).
    Finds the largest k such that p_(k) <= (k / m) * q.
    Rejects H_0 for all i <= k.
    Also computes adjusted p-values (q-values): q_(i) = min_{j >= i} (m/j * p_(j)).
    """
    m = len(p_values)
    if m == 0:
        return []

    # Pair with original indices
    indexed = sorted(enumerate(p_values), key=lambda x: x[1])
    results = [{} for _ in range(m)]

    # Calculate BH threshold and critical cutoffs
    max_k = -1
    for rank, (orig_idx, p_val) in enumerate(indexed, start=1):
        threshold = (rank / m) * fdr_q
        if p_val <= threshold:
            max_k = rank

    # Compute step-up adjusted q-values
    q_vals = [1.0] * m
    running_min = 1.0
    for rank in range(m, 0, -1):
        orig_idx, p_val = indexed[rank - 1]
        adjusted_p = min(1.0, (m / rank) * p_val)
        running_min = min(running_min, adjusted_p)
        q_vals[rank - 1] = running_min

    for rank, (orig_idx, p_val) in enumerate(indexed, start=1):
        is_rejected = (rank <= max_k)
        results[orig_idx] = {
            "original_index": orig_idx,
            "raw_p_value": float(p_val),
            "rank": rank,
            "bh_threshold": float((rank / m) * fdr_q),
            "adjusted_q_value": float(q_vals[rank - 1]),
            "is_significant_fdr": bool(is_rejected),
        }

    return results


def apply_holm_bonferroni(
    p_values: list[float],
    alpha: float = 0.05,
) -> list[dict[str, Any]]:
    """Applies Holm-Bonferroni step-down procedure to control Family-Wise Error Rate (FWER)."""
    m = len(p_values)
    if m == 0:
        return []

    indexed = sorted(enumerate(p_values), key=lambda x: x[1])
    results = [{} for _ in range(m)]

    rejected = True
    for rank, (orig_idx, p_val) in enumerate(indexed, start=1):
        cutoff = alpha / (m - rank + 1)
        if rejected and (p_val <= cutoff):
            is_sig = True
        else:
            rejected = False
            is_sig = False

        results[orig_idx] = {
            "original_index": orig_idx,
            "raw_p_value": float(p_val),
            "rank": rank,
            "holm_cutoff": float(cutoff),
            "is_significant_fwer": bool(is_sig),
        }

    return results


def evaluate_cluster_effectiveness_with_fdr(
    clusters: list[dict[str, Any]],
    fdr_q: float = 0.05,
    mmes_threshold: float = 0.05,
    min_mature_sample: int = 20,
) -> list[dict[str, Any]]:
    """Evaluates fleet clusters under Benjamini-Hochberg FDR control and MMES.

    Classifies each cluster into:
    - CONFIRMATORY_SIGNIFICANT: Mature samples >= min_mature_sample, passes BH FDR, |tau| >= MMES.
    - EXPLORATORY_PROMISING: raw p < 0.05 or |tau| >= MMES, but mature < min_mature_sample or fails FDR.
    - ESTIMATED_NULL: 95% CI completely contained within [-MMES, +MMES].
    - INCONCLUSIVE_UNDERPOWERED: CI spans zero and exceeds [-MMES, +MMES].
    - COLD_START_PRIOR_ONLY: Mature samples == 0.
    """
    if not clusters:
        return []

    # Extract raw p-values for clusters with mature observations
    p_values = []
    evaluable_indices = []

    for idx, c in enumerate(clusters):
        mature = int(c.get("mature_samples", 0) or 0)
        if mature > 0:
            p_val = float(c.get("p_value", 1.0) or 1.0)
            p_values.append(p_val)
            evaluable_indices.append(idx)

    # Run BH procedure on evaluable subset
    bh_results = apply_benjamini_hochberg(p_values, fdr_q=fdr_q) if p_values else []
    bh_map = {evaluable_indices[i]: bh_results[i] for i in range(len(evaluable_indices))}

    evaluated_clusters = []
    for idx, c in enumerate(clusters):
        cluster_copy = dict(c)
        mature = int(c.get("mature_samples", 0) or 0)
        point_est = float(c.get("avg_click_lift", 0.0) or c.get("avg_rank_delta", 0.0) or 0.0)
        ci_lower = float(c.get("ci_lower_95", 0.0) or 0.0)
        ci_upper = float(c.get("ci_upper_95", 1.0) or 1.0)

        if mature == 0:
            classification = "COLD_START_PRIOR_ONLY"
            fdr_info = None
        else:
            fdr_info = bh_map.get(idx, {})
            is_sig_fdr = fdr_info.get("is_significant_fdr", False)
            raw_p = fdr_info.get("raw_p_value", 1.0)

            if is_sig_fdr and abs(point_est) >= mmes_threshold and mature >= min_mature_sample:
                classification = "CONFIRMATORY_SIGNIFICANT"
            elif (raw_p < 0.05 or abs(point_est) >= mmes_threshold) and mature < min_mature_sample:
                classification = "EXPLORATORY_PROMISING"
            elif (-mmes_threshold <= ci_lower) and (ci_upper <= mmes_threshold):
                classification = "ESTIMATED_NULL"
            else:
                classification = "INCONCLUSIVE_UNDERPOWERED"

        cluster_copy["decision_classification"] = classification
        cluster_copy["fdr_metadata"] = fdr_info
        evaluated_clusters.append(cluster_copy)

    return evaluated_clusters


class SequentialEvaluationHorizonGuard:
    """Enforces fixed evaluation horizons and prevents continuous significance peeking.

    Rules:
    - Pre-recrawl: URL is in CRAWL_PENDING / RECRAWL_CONFIRMED (Strictly un-evaluable).
    - Post-recrawl: URL is in MEASUREMENT_PENDING (Day 0 to Day 27). Continuous peeking is forbidden.
    - Evaluation Horizon: Evaluation is strictly locked until Day 28 (EVALUATED_28D) or Day 56 (EVALUATED_56D).
    - Prevents alpha inflation from repeated daily testing.
    """

    MINIMUM_EVALUATION_DAYS = 28

    @classmethod
    def can_evaluate_statistically(
        cls,
        recrawl_date_iso: str | None,
        now_dt: Any = None,
    ) -> tuple[bool, str]:
        if not recrawl_date_iso:
            return False, "CRAWL_PENDING: Googlebot recrawl not yet confirmed; cannot evaluate."

        import datetime

        try:
            r_dt = datetime.datetime.fromisoformat(recrawl_date_iso.replace("Z", "+00:00"))
        except Exception:
            return False, "INVALID_DATE: Unable to parse recrawl timestamp."

        if now_dt is None:
            now_dt = datetime.datetime.now(datetime.timezone.utc)
        elif getattr(now_dt, "tzinfo", None) is None:
            now_dt = now_dt.replace(tzinfo=datetime.timezone.utc)

        elapsed_days = (now_dt - r_dt).total_seconds() / 86400.0

        if elapsed_days < cls.MINIMUM_EVALUATION_DAYS:
            rem = math.ceil(cls.MINIMUM_EVALUATION_DAYS - elapsed_days)
            return (
                False,
                f"MEASUREMENT_PENDING: Elapsed {elapsed_days:.1f}d / {cls.MINIMUM_EVALUATION_DAYS}d required. "
                f"{rem} days remaining in fixed evaluation window to prevent significance peeking.",
            )

        return True, f"EVALUATION_PERMITTED: Observation window mature ({elapsed_days:.1f}d >= {cls.MINIMUM_EVALUATION_DAYS}d)."
