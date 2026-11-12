#!/usr/bin/env python3
"""experiment_power_calculator.py - Statistical Power & MDE Engine for SEO DiD (v2.3 P1).

Eliminates inconclusive tests by estimating statistical power and Minimum Detectable Effect (MDE)
BEFORE shipping interventions. Distinguishes between:
1. Strong evidence of improvement
2. Strong evidence of deterioration
3. Evidence of no meaningful effect (equivalence within ROPE)
4. Insufficient evidence / underpowered test
"""

from __future__ import annotations

import math
from typing import Any
from scipy import stats  # type: ignore[import-untyped]


def calculate_minimum_detectable_effect(
    base_mu: float,
    base_std: float,
    n_t: int,
    n_c: int,
    alpha: float = 0.05,
    power: float = 0.80,
    df: float | None = None,
) -> dict[str, Any]:
    """Calculates Minimum Detectable Effect (MDE) in absolute units and percentage lift.

    Formula for DiD MDE:
    MDE = (t_{alpha/2, df} + t_{beta, df}) * SE_DiD
    SE_DiD = sqrt(sigma_t^2 / n_t + sigma_c^2 / n_c)
    """
    n_t = max(1, int(n_t))
    n_c = max(2, int(n_c))
    mu = max(1.0, float(base_mu))
    sigma = max(0.1, float(base_std))

    if df is None:
        # Conservative effective df
        df = max(1.0, float(n_c - 1))

    t_alpha = float(stats.t.ppf(1.0 - (alpha / 2.0), df))
    t_beta = float(stats.t.ppf(power, df))

    # Standard error of Difference-in-Differences estimator
    # Assuming pooled variance across treatment and control cohorts
    se_did = sigma * math.sqrt((1.0 / n_t) + (1.0 / n_c))

    mde_absolute = (t_alpha + t_beta) * se_did
    mde_percentage = mde_absolute / mu

    return {
        "mde_absolute_clicks": round(mde_absolute, 2),
        "mde_percentage_lift": round(mde_percentage, 4),
        "standard_error": round(se_did, 4),
        "critical_t_alpha": round(t_alpha, 3),
        "critical_t_beta": round(t_beta, 3),
        "effective_df": round(df, 1),
        "n_treatment": n_t,
        "n_control": n_c,
        "base_mean": mu,
        "base_std": sigma,
        "target_power": power,
        "alpha": alpha,
    }


def calculate_required_sample_size(
    base_mu: float,
    base_std: float,
    target_percentage_lift: float = 0.10,
    control_to_treatment_ratio: float = 4.0,
    alpha: float = 0.05,
    power: float = 0.80,
) -> dict[str, Any]:
    """Solves for required number of treatment and control URLs to detect a target lift."""
    mu = max(1.0, float(base_mu))
    sigma = max(0.1, float(base_std))
    delta = max(0.01, float(target_percentage_lift)) * mu
    r = max(1.0, float(control_to_treatment_ratio))

    z_alpha = float(stats.norm.ppf(1.0 - (alpha / 2.0)))
    z_beta = float(stats.norm.ppf(power))

    # Solve: delta = (z_a + z_b) * sigma * sqrt(1/n_t + 1/(r*n_t))
    # n_t = ((z_a + z_b) * sigma / delta)^2 * (1 + 1/r)
    n_t_required = math.ceil((((z_alpha + z_beta) * sigma / delta) ** 2) * (1.0 + (1.0 / r)))
    n_c_required = math.ceil(n_t_required * r)

    return {
        "required_treatment_urls": max(1, n_t_required),
        "required_control_urls": max(2, n_c_required),
        "target_percentage_lift": target_percentage_lift,
        "control_ratio": r,
        "achieved_power": power,
    }


def classify_experiment_outcome(
    point_estimate: float,
    ci_lower_95: float,
    ci_upper_95: float,
    mde_percentage: float = 0.05,
    achieved_power: float = 0.80,
) -> dict[str, Any]:
    """Classifies DiD outcome into 4 causal categories using ROPE (Region of Practical Equivalence).

    Categories:
    1. STRONG_IMPROVEMENT: CI_lower > 0 and point_estimate >= mde_percentage
    2. STRONG_DETERIORATION: CI_upper < 0 and point_estimate <= -mde_percentage
    3. EVIDENCE_OF_NO_EFFECT: CI is completely contained within [-mde, +mde] with adequate power
    4. UNDERPOWERED_INCONCLUSIVE: CI spans 0 and exceeds ROPE margin
    """
    rope_margin = max(0.01, float(mde_percentage))

    if ci_lower_95 > 0.0 and point_estimate >= rope_margin:
        decision = "STRONG_IMPROVEMENT"
        action = "SCALE_DEPLOYMENT"
    elif ci_upper_95 < 0.0 and point_estimate <= -rope_margin:
        decision = "STRONG_DETERIORATION"
        action = "ROLLBACK_INTERVENTION"
    elif (-rope_margin <= ci_lower_95) and (ci_upper_95 <= rope_margin) and (achieved_power >= 0.80):
        decision = "EVIDENCE_OF_NO_EFFECT"
        action = "DISCARD_HYPOTHESIS_PRECISION_NULL"
    else:
        decision = "UNDERPOWERED_INCONCLUSIVE"
        action = "CONTINUE_OBSERVATION_OR_EXPAND_COHORT"

    return {
        "decision": decision,
        "recommended_action": action,
        "point_estimate": round(point_estimate, 4),
        "ci_lower_95": round(ci_lower_95, 4),
        "ci_upper_95": round(ci_upper_95, 4),
        "rope_margin": round(rope_margin, 4),
        "is_statistically_significant": bool(ci_lower_95 > 0.0 or ci_upper_95 < 0.0),
    }
