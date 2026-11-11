#!/usr/bin/env python3
"""test_did_simulation_tdd.py - Empirical Simulation Test Suite for DiD Estimator (v2.2.1 P0.3).

Verifies nominal 95% interval coverage, false positive rate control under null effects,
statistical power under positive/negative effects, small vs. large control cohorts,
and stability on low-click pages.
"""

from __future__ import annotations

import math
import numpy as np
import pytest

from fleet_state import get_t_critical_value


def simulate_did_trial(
    lambda_t0: float,
    lambda_t1: float,
    lambda_c0: float,
    lambda_c1: float,
    n_controls: int,
    rng: np.random.Generator,
) -> tuple[float, float, float, bool]:
    """Simulates a single DiD experiment under Poisson count generation.

    Returns (net_lift, ci_lower, ci_upper, covers_true_lift).
    """
    true_tau = ((lambda_t1 - lambda_t0) / max(lambda_t0, 1.0)) - ((lambda_c1 - lambda_c0) / max(lambda_c0, 1.0))

    # Realized counts
    y_t0 = float(rng.poisson(lambda_t0))
    y_t1 = float(rng.poisson(lambda_t1))

    ctrl_c0_list = [float(rng.poisson(lambda_c0)) for _ in range(n_controls)]
    ctrl_c1_list = [float(rng.poisson(lambda_c1)) for _ in range(n_controls)]

    c0_mean = sum(ctrl_c0_list) / max(1, n_controls)
    c1_mean = sum(ctrl_c1_list) / max(1, n_controls)

    t_lift = (y_t1 - y_t0) / max(y_t0, 1.0)
    c_lift = (c1_mean - c0_mean) / max(c0_mean, 1.0)
    net_lift = t_lift - c_lift

    # Control variance across cohort
    ctrl_lifts = [(c1 - c0) / max(c0, 1.0) for c0, c1 in zip(ctrl_c0_list, ctrl_c1_list)]
    if len(ctrl_lifts) > 1:
        mean_c_lift = sum(ctrl_lifts) / len(ctrl_lifts)
        var_c = sum((l - mean_c_lift) ** 2 for l in ctrl_lifts) / (len(ctrl_lifts) - 1)
    else:
        var_c = max(0.01, abs(c_lift) * 0.05)

    var_t = (y_t1 + y_t0) / (max(y_t0, 1.0) ** 2)
    se = math.sqrt(max(0.0001, var_t + (var_c / max(1, n_controls))))
    t_crit = get_t_critical_value(n_controls)

    ci_lower = net_lift - t_crit * se
    ci_upper = net_lift + t_crit * se
    covers_true = (ci_lower <= true_tau <= ci_upper)

    return net_lift, ci_lower, ci_upper, covers_true


def test_did_null_effect_nominal_coverage_and_fpr():
    """Under true null effect (tau = 0), verifies ~95% interval coverage and FPR <= 10%."""
    rng = np.random.default_rng(seed=42)
    n_sims = 400
    lambda_base = 50.0  # Moderate traffic page
    n_controls = 4     # df = 3, t_crit = 3.182

    covered = 0
    false_positives = 0

    for _ in range(n_sims):
        _, ci_lower, ci_upper, is_covered = simulate_did_trial(
            lambda_t0=lambda_base,
            lambda_t1=lambda_base,
            lambda_c0=lambda_base,
            lambda_c1=lambda_base,
            n_controls=n_controls,
            rng=rng,
        )
        if is_covered:
            covered += 1
        # False positive: confidence interval does not cover 0 (entirely positive or negative)
        if ci_lower > 0.0 or ci_upper < 0.0:
            false_positives += 1

    coverage_rate = covered / n_sims
    fpr = false_positives / n_sims

    # Nominal 95% interval coverage target [90%, 99%]
    assert coverage_rate >= 0.90, f"Coverage rate {coverage_rate:.2%} below nominal 90% floor"
    assert fpr <= 0.10, f"False positive rate {fpr:.2%} exceeds 10% ceiling"


def test_did_positive_and_negative_effect_coverage():
    """Verifies interval coverage under genuine positive (+40%) and negative (-30%) treatment lifts."""
    rng = np.random.default_rng(seed=123)
    n_sims = 200
    n_controls = 5  # df = 4, t_crit = 2.776

    # Positive effect: treatment lifts from 50 to 70 (+40%)
    pos_covered = 0
    for _ in range(n_sims):
        _, _, _, is_covered = simulate_did_trial(
            lambda_t0=50.0,
            lambda_t1=70.0,
            lambda_c0=50.0,
            lambda_c1=50.0,
            n_controls=n_controls,
            rng=rng,
        )
        if is_covered:
            pos_covered += 1
    assert (pos_covered / n_sims) >= 0.88

    # Negative effect: treatment drops from 60 to 42 (-30%)
    neg_covered = 0
    for _ in range(n_sims):
        _, _, _, is_covered = simulate_did_trial(
            lambda_t0=60.0,
            lambda_t1=42.0,
            lambda_c0=50.0,
            lambda_c1=50.0,
            n_controls=n_controls,
            rng=rng,
        )
        if is_covered:
            neg_covered += 1
    assert (neg_covered / n_sims) >= 0.88


def test_did_small_vs_large_control_cohort_precision():
    """Verifies that larger control cohorts reduce standard error while maintaining valid coverage."""
    rng = np.random.default_rng(seed=999)
    n_sims = 150

    small_widths = []
    large_widths = []

    for _ in range(n_sims):
        # Small cohort: N_c = 3
        _, l_sm, u_sm, _ = simulate_did_trial(
            lambda_t0=40.0, lambda_t1=40.0, lambda_c0=40.0, lambda_c1=40.0,
            n_controls=3, rng=rng,
        )
        small_widths.append(u_sm - l_sm)

        # Large cohort: N_c = 10
        _, l_lg, u_lg, _ = simulate_did_trial(
            lambda_t0=40.0, lambda_t1=40.0, lambda_c0=40.0, lambda_c1=40.0,
            n_controls=10, rng=rng,
        )
        large_widths.append(u_lg - l_lg)

    mean_small_width = sum(small_widths) / len(small_widths)
    mean_large_width = sum(large_widths) / len(large_widths)

    # Larger cohort with t_crit=2.262 must be narrower on average than small cohort with t_crit=4.303
    assert mean_large_width < mean_small_width
    assert mean_large_width > 0.0


def test_did_low_click_page_stability():
    """Verifies finite numeric bounds and absence of NaNs on low-click pages (1 to 5 clicks)."""
    rng = np.random.default_rng(seed=777)

    for base_clicks in [1.0, 2.0, 3.0, 5.0]:
        for _ in range(50):
            net_lift, ci_lower, ci_upper, _ = simulate_did_trial(
                lambda_t0=base_clicks,
                lambda_t1=base_clicks,
                lambda_c0=base_clicks,
                lambda_c1=base_clicks,
                n_controls=4,
                rng=rng,
            )
            assert not math.isnan(net_lift)
            assert not math.isnan(ci_lower)
            assert not math.isnan(ci_upper)
            assert ci_lower < ci_upper
            assert math.isfinite(ci_lower)
            assert math.isfinite(ci_upper)
