#!/usr/bin/env python3
"""test_v23_statistical_rigor_tdd.py - Comprehensive Statistical & Methodological Rigor Suite (v2.3).

Verifies the 5 pillars of the Outcome-Driven SEO Engine v2.3 upgrade:
1. Monte Carlo DiD Coverage Validation & Welch-Satterthwaite Effective Degrees of Freedom.
2. Benjamini-Hochberg False Discovery Rate (FDR) & Holm-Bonferroni FWER Control.
3. Sequential Testing Evaluation Horizon Guard (prevents continuous significance peeking).
4. Right-Censored Kaplan-Meier Survival Analytics for Crawl & Indexation Latency.
5. Analytical Experiment Power, Minimum Detectable Effect (MDE), and Bayesian Prior Sensitivity.
"""

from __future__ import annotations

import datetime
import math
import numpy as np
import pytest

from did_simulation_validator import (
    compute_welch_satterthwaite_df,
    get_did_critical_value,
    simulate_single_did_trial,
    run_did_monte_carlo_battery,
)
from multiple_testing import (
    apply_benjamini_hochberg,
    apply_holm_bonferroni,
    evaluate_cluster_effectiveness_with_fdr,
    SequentialEvaluationHorizonGuard,
)
from crawl_survival_analytics import (
    compute_kaplan_meier_survival,
    analyze_fleet_crawl_survival,
)
from experiment_power_calculator import (
    calculate_minimum_detectable_effect,
    calculate_required_sample_size,
    classify_experiment_outcome,
)
from score_backlog import compute_prior_sensitivity_analysis


# ==============================================================================
# 1. DiD Simulation & Welch-Satterthwaite Effective Degrees of Freedom
# ==============================================================================


def test_welch_satterthwaite_effective_df_calculation():
    """Verifies that Welch-Satterthwaite df handles unequal sample sizes and variances."""
    # Equal sizes and variances: df = (v + v)^2 / (v^2/9 + v^2/9) = 4v^2 / (2v^2/9) = 18
    df_equal = compute_welch_satterthwaite_df(var_t=1.0, n_t=10, var_c=1.0, n_c=10)
    assert abs(df_equal - 18.0) < 0.1

    # Unequal cohort sizes: N_t = 3, N_c = 30 with unequal variance
    # Treatment variance higher: df should be dragged toward N_t - 1 = 2
    df_unequal = compute_welch_satterthwaite_df(var_t=10.0, n_t=3, var_c=1.0, n_c=30)
    assert df_unequal < 10.0
    assert df_unequal >= 2.0


def test_did_critical_value_bounds():
    """Verifies exact Student-t critical values from Welch-Satterthwaite df."""
    assert abs(get_did_critical_value(df=30, alpha=0.05) - 2.042) < 0.002
    assert abs(get_did_critical_value(df=1, alpha=0.05) - 12.706) < 0.01
    assert abs(get_did_critical_value(df=1000, alpha=0.05) - 1.960) < 0.005


def test_did_monte_carlo_simulation_battery():
    """Runs Monte Carlo battery across challenging DGPs and verifies empirical coverage."""
    results = run_did_monte_carlo_battery(n_sims=120, seed=123)

    # Scenario 1 (Strict Null): Nominal coverage >= 90%
    s1 = results["SCENARIO_1_STRICT_NULL"]
    assert s1["coverage_welch_satterthwaite"] >= 0.90
    assert s1["rejection_rate"] <= 0.10

    # Scenario 2 (Positive Lift tau = +0.25): High coverage
    s2 = results["SCENARIO_2_POSITIVE_LIFT"]
    assert s2["coverage_welch_satterthwaite"] >= 0.90

    # Scenario 7 (Unequal Sizes N_t=4, N_c=25): Welch-Satterthwaite out-performs naive z
    s7 = results["SCENARIO_7_UNEQUAL_SIZES"]
    assert s7["coverage_welch_satterthwaite"] >= 0.88


# ==============================================================================
# 2. Benjamini-Hochberg False Discovery Rate & Holm-Bonferroni FWER
# ==============================================================================


def test_benjamini_hochberg_fdr_control():
    """Verifies BH procedure correctly identifies true signals while controlling FDR."""
    # Synthetic p-values: 3 strong signals, 7 pure nulls (high p-values)
    raw_p = [0.001, 0.004, 0.009, 0.25, 0.35, 0.50, 0.65, 0.80, 0.90, 0.95]
    bh = apply_benjamini_hochberg(raw_p, fdr_q=0.05)

    assert len(bh) == 10
    # First 3 should be significant under FDR q = 0.05
    assert bh[0]["is_significant_fdr"] is True
    assert bh[1]["is_significant_fdr"] is True
    assert bh[2]["is_significant_fdr"] is True
    # Non-signals should not be significant
    assert bh[3]["is_significant_fdr"] is False
    assert bh[9]["is_significant_fdr"] is False


def test_holm_bonferroni_fwer_control():
    """Verifies Holm-Bonferroni step-down cutoff thresholds."""
    raw_p = [0.002, 0.008, 0.06, 0.30]
    holm = apply_holm_bonferroni(raw_p, alpha=0.05)

    assert holm[0]["is_significant_fwer"] is True  # 0.002 <= 0.05 / 4 = 0.0125
    assert holm[1]["is_significant_fwer"] is True  # 0.008 <= 0.05 / 3 = 0.0167
    assert holm[2]["is_significant_fwer"] is False # 0.06 > 0.05 / 2 = 0.0250


def test_evaluate_cluster_effectiveness_with_fdr():
    """Verifies 5-tier classification across fleet clusters."""
    clusters = [
        # Mature strong positive lift
        {"mature_samples": 25, "avg_click_lift": 0.35, "p_value": 0.001, "ci_lower_95": 0.15, "ci_upper_95": 0.55},
        # Exploratory lift (small sample N=4 < 20)
        {"mature_samples": 4, "avg_click_lift": 0.20, "p_value": 0.03, "ci_lower_95": 0.02, "ci_upper_95": 0.38},
        # Estimated null (tight CI around 0 within MMES [-0.05, 0.05])
        {"mature_samples": 30, "avg_click_lift": 0.01, "p_value": 0.85, "ci_lower_95": -0.03, "ci_upper_95": 0.04},
        # Cold start (N=0)
        {"mature_samples": 0, "avg_click_lift": 0.0, "ci_lower_95": 0.0, "ci_upper_95": 1.0},
    ]

    evaled = evaluate_cluster_effectiveness_with_fdr(clusters, fdr_q=0.05, mmes_threshold=0.05)
    assert evaled[0]["decision_classification"] == "CONFIRMATORY_SIGNIFICANT"
    assert evaled[1]["decision_classification"] == "EXPLORATORY_PROMISING"
    assert evaled[2]["decision_classification"] == "ESTIMATED_NULL"
    assert evaled[3]["decision_classification"] == "COLD_START_PRIOR_ONLY"


# ==============================================================================
# 3. Sequential Testing Evaluation Horizon Guard
# ==============================================================================


def test_sequential_evaluation_horizon_guard():
    """Verifies that early peeking is strictly blocked prior to Day 28."""
    now = datetime.datetime(2026, 11, 12, 12, 0, 0, tzinfo=datetime.timezone.utc)

    # 1. Un-recrawled
    can_eval, msg = SequentialEvaluationHorizonGuard.can_evaluate_statistically(None, now)
    assert can_eval is False
    assert "CRAWL_PENDING" in msg

    # 2. Recrawled 10 days ago (in premature peeking window)
    recrawl_10d = (now - datetime.timedelta(days=10)).isoformat()
    can_eval, msg = SequentialEvaluationHorizonGuard.can_evaluate_statistically(recrawl_10d, now)
    assert can_eval is False
    assert "MEASUREMENT_PENDING" in msg
    assert "18 days remaining" in msg

    # 3. Recrawled 29 days ago (mature evaluation window reached)
    recrawl_29d = (now - datetime.timedelta(days=29)).isoformat()
    can_eval, msg = SequentialEvaluationHorizonGuard.can_evaluate_statistically(recrawl_29d, now)
    assert can_eval is True
    assert "EVALUATION_PERMITTED" in msg


# ==============================================================================
# 4. Right-Censored Kaplan-Meier Survival Analytics
# ==============================================================================


def test_kaplan_meier_survival_right_censoring():
    """Verifies that un-recrawled URLs are treated as right-censored observations."""
    # 5 URLs: 2 recrawled at day 3 and day 7; 3 right-censored at day 10, 14, 20
    durations = [3.0, 7.0, 10.0, 14.0, 20.0]
    events = [1, 1, 0, 0, 0]

    km = compute_kaplan_meier_survival(durations, events)
    assert km["n_total"] == 5
    assert km["n_events"] == 2
    assert km["n_censored"] == 3
    assert km["censoring_rate"] == 0.60
    # Survival probability drops at event times only
    assert km["survival_probabilities"][0] == 1.0
    assert km["survival_probabilities"][1] == 0.8  # 1 - 1/5
    assert km["survival_probabilities"][2] == 0.6  # 0.8 * (1 - 1/4)


def test_fleet_crawl_survival_analysis():
    """Verifies fleet crawl survival breakdown by property and route family."""
    now = datetime.datetime(2026, 11, 12, tzinfo=datetime.timezone.utc)
    records = [
        {"domain": "smsriver.com", "route_family": "receive-sms", "shipped_at": "2026-11-01T00:00:00Z", "recrawl_detected_at": "2026-11-05T00:00:00Z"},
        {"domain": "smsriver.com", "route_family": "receive-sms", "shipped_at": "2026-11-01T00:00:00Z", "recrawl_detected_at": None},
        {"domain": "incomecanvas.com", "route_family": "calculators", "shipped_at": "2026-11-02T00:00:00Z", "recrawl_detected_at": None},
    ]

    survival = analyze_fleet_crawl_survival(records, now_dt=now)
    assert "fleet_survival" in survival
    assert "domain_survival" in survival
    assert "smsriver.com" in survival["domain_survival"]
    assert "incomecanvas.com" in survival["domain_survival"]
    assert survival["fleet_survival"]["n_total"] == 3
    assert survival["fleet_survival"]["n_censored"] == 2


# ==============================================================================
# 5. Power, MDE, and Prior Sensitivity Analysis
# ==============================================================================


def test_minimum_detectable_effect_calculation():
    """Verifies DiD analytical MDE calculation and sample size scaling."""
    mde = calculate_minimum_detectable_effect(
        base_mu=100.0,
        base_std=20.0,
        n_t=5,
        n_c=25,
        alpha=0.05,
        power=0.80,
    )
    assert mde["mde_absolute_clicks"] > 0.0
    assert 0.05 <= mde["mde_percentage_lift"] <= 0.60
    assert mde["n_treatment"] == 5
    assert mde["n_control"] == 25


def test_required_sample_size_solver():
    """Verifies required treatment URLs to detect a 10% lift with 80% power."""
    sizes = calculate_required_sample_size(
        base_mu=100.0,
        base_std=25.0,
        target_percentage_lift=0.15,
        control_to_treatment_ratio=4.0,
        alpha=0.05,
        power=0.80,
    )
    assert sizes["required_treatment_urls"] >= 1
    assert sizes["required_control_urls"] == sizes["required_treatment_urls"] * 4


def test_classify_experiment_outcome_four_way_boundary():
    """Verifies four-way decision boundary against ROPE."""
    # 1. Strong improvement
    o1 = classify_experiment_outcome(point_estimate=0.15, ci_lower_95=0.04, ci_upper_95=0.26, mde_percentage=0.05)
    assert o1["decision"] == "STRONG_IMPROVEMENT"
    assert o1["recommended_action"] == "SCALE_DEPLOYMENT"

    # 2. Strong deterioration
    o2 = classify_experiment_outcome(point_estimate=-0.12, ci_lower_95=-0.22, ci_upper_95=-0.02, mde_percentage=0.05)
    assert o2["decision"] == "STRONG_DETERIORATION"
    assert o2["recommended_action"] == "ROLLBACK_INTERVENTION"

    # 3. Equivalence / Precise null
    o3 = classify_experiment_outcome(point_estimate=0.01, ci_lower_95=-0.03, ci_upper_95=0.04, mde_percentage=0.05, achieved_power=0.85)
    assert o3["decision"] == "EVIDENCE_OF_NO_EFFECT"
    assert o3["recommended_action"] == "DISCARD_HYPOTHESIS_PRECISION_NULL"

    # 4. Underpowered inconclusive
    o4 = classify_experiment_outcome(point_estimate=0.06, ci_lower_95=-0.08, ci_upper_95=0.20, mde_percentage=0.05, achieved_power=0.40)
    assert o4["decision"] == "UNDERPOWERED_INCONCLUSIVE"


def test_bayesian_prior_sensitivity_analysis():
    """Verifies prior sensitivity across Uniform, Jeffreys, Domain, and Empirical priors."""
    # 0 mature trials: all priors reflect their respective prior means
    sens_zero = compute_prior_sensitivity_analysis(mature_successes=0, mature_trials=0)
    assert sens_zero["sensitivity_verdict"] == "HIGHLY_SENSITIVE_TO_PRIOR"
    priors_zero = sens_zero["priors_evaluated"]
    assert priors_zero["UNIFORM"]["posterior_mean"] == 0.50
    assert priors_zero["JEFFREYS"]["posterior_mean"] == 0.50
    assert priors_zero["DOMAIN_INFORMATIVE"]["posterior_mean"] == 0.30

    # 50 mature trials with 15 successes: data dominates and priors converge
    sens_mature = compute_prior_sensitivity_analysis(mature_successes=15, mature_trials=50)
    assert sens_mature["sensitivity_verdict"] == "ROBUST_DATA_DOMINATED"
    assert sens_mature["posterior_spread_across_priors"] < 0.05
