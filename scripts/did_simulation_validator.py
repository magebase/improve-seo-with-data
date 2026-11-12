#!/usr/bin/env python3
"""did_simulation_validator.py - Monte Carlo Simulation & Coverage Validation for SEO DiD (v2.3 P0).

Rigorous empirical validation of Difference-in-Differences confidence interval coverage,
Type I error control, and degrees-of-freedom adjustments across 7 real-world web traffic conditions:
1. Strict Null Effect (tau = 0.0)
2. True Positive Lift (tau = +0.25)
3. True Negative Lift (tau = -0.20)
4. Overdispersed Traffic Counts (Negative Binomial distribution)
5. Serially Correlated Observations (AR(1) temporal shocks)
6. Clustered Domain Random Effects (multiple URLs within the same domain)
7. Unequal Treatment and Control Group Sizes (N_t != N_c)
"""

from __future__ import annotations

import math
from typing import Any
import numpy as np
from scipy import stats  # type: ignore[import-untyped]


def compute_welch_satterthwaite_df(
    var_t: float,
    n_t: int,
    var_c: float,
    n_c: int,
) -> float:
    """Calculates effective degrees of freedom via the Welch-Satterthwaite equation.

    Accounts for unequal sample variances and unequal group sizes between treatment
    and control cohorts, avoiding naive N_c - 1 assumptions.
    """
    n_t = max(2, int(n_t))
    n_c = max(2, int(n_c))
    v_t = max(1e-6, float(var_t)) / n_t
    v_c = max(1e-6, float(var_c)) / n_c

    numerator = (v_t + v_c) ** 2
    denominator = ((v_t ** 2) / (n_t - 1)) + ((v_c ** 2) / (n_c - 1))

    if denominator <= 0.0:
        return float(max(1, n_c - 1))
    return float(max(1.0, numerator / denominator))


def get_did_critical_value(
    df: float,
    alpha: float = 0.05,
) -> float:
    """Returns two-tailed Student's t critical value for exact degrees of freedom."""
    clean_df = max(1.0, float(df))
    return float(stats.t.ppf(1.0 - (alpha / 2.0), clean_df))


def simulate_single_did_trial(
    n_t: int = 1,
    n_c: int = 20,
    base_mu: float = 50.0,
    true_tau: float = 0.0,
    overdispersion_alpha: float = 0.0,
    ar1_rho: float = 0.0,
    domain_shock_std: float = 0.0,
    rng: np.random.Generator | None = None,
) -> dict[str, Any]:
    """Simulates a single DiD trial generating pre/post traffic for treatment and control cohorts.

    Supports Poisson, Negative Binomial overdispersion, AR(1) serial correlation,
    and domain-level clustered shocks.
    """
    if rng is None:
        rng = np.random.default_rng()

    # Domain shock affecting both pre and post periods
    domain_shock_pre = float(rng.normal(0.0, domain_shock_std)) if domain_shock_std > 0 else 0.0
    domain_shock_post = float(rng.normal(0.0, domain_shock_std)) if domain_shock_std > 0 else 0.0

    def generate_count(base: float, shock: float, prev_err: float) -> tuple[float, float]:
        # AR(1) error component
        if ar1_rho > 0.0:
            innov = float(rng.normal(0.0, math.sqrt(max(0.001, base))))
            err = (ar1_rho * prev_err) + (math.sqrt(1.0 - (ar1_rho ** 2)) * innov)
        else:
            err = 0.0

        expected_rate = max(1.0, base + shock + err)

        if overdispersion_alpha > 0.0:
            # Negative Binomial parameterization: Var = mu + alpha * mu^2
            # scipy nbinom: n = 1/alpha, p = 1 / (1 + alpha * mu)
            n_param = max(0.1, 1.0 / overdispersion_alpha)
            p_param = n_param / (n_param + expected_rate)
            count = float(rng.negative_binomial(n_param, p_param))
        else:
            count = float(rng.poisson(expected_rate))

        return count, err

    # Pre-period treatment
    y_t0_list = []
    err_t_list = []
    for _ in range(n_t):
        cnt, err = generate_count(base_mu, domain_shock_pre, 0.0)
        y_t0_list.append(cnt)
        err_t_list.append(err)

    # Post-period treatment: subject to true_tau lift
    y_t1_list = []
    for i in range(n_t):
        target_base = base_mu * (1.0 + true_tau)
        cnt, _ = generate_count(target_base, domain_shock_post, err_t_list[i])
        y_t1_list.append(cnt)

    # Pre and Post control cohort
    y_c0_list = []
    y_c1_list = []
    for _ in range(n_c):
        c0, err_c = generate_count(base_mu, domain_shock_pre, 0.0)
        c1, _ = generate_count(base_mu, domain_shock_post, err_c)
        y_c0_list.append(c0)
        y_c1_list.append(c1)

    mean_t0 = sum(y_t0_list) / max(1, n_t)
    mean_t1 = sum(y_t1_list) / max(1, n_t)
    mean_c0 = sum(y_c0_list) / max(1, n_c)
    mean_c1 = sum(y_c1_list) / max(1, n_c)

    # Estimated lifts
    t_lift = (mean_t1 - mean_t0) / max(1.0, mean_t0)
    c_lift = (mean_c1 - mean_c0) / max(1.0, mean_c0)
    did_point_estimate = t_lift - c_lift

    # Control cohort empirical lift variance
    ctrl_lifts = [(c1 - c0) / max(1.0, c0) for c0, c1 in zip(y_c0_list, y_c1_list)]
    if n_c > 1:
        var_c = float(np.var(ctrl_lifts, ddof=1))
    else:
        var_c = max(0.01, abs(c_lift) * 0.1)

    # Treatment variance
    if n_t > 1:
        trt_lifts = [(t1 - t0) / max(1.0, t0) for t0, t1 in zip(y_t0_list, y_t1_list)]
        var_t = float(np.var(trt_lifts, ddof=1))
    else:
        var_t = (mean_t1 + mean_t0) / (max(1.0, mean_t0) ** 2)

    se = math.sqrt(max(1e-6, (var_t / max(1, n_t)) + (var_c / max(1, n_c))))

    # 1. Welch-Satterthwaite effective df
    df_ws = compute_welch_satterthwaite_df(var_t, n_t, var_c, n_c)
    t_crit_ws = get_did_critical_value(df_ws, alpha=0.05)
    ci_lower_ws = did_point_estimate - (t_crit_ws * se)
    ci_upper_ws = did_point_estimate + (t_crit_ws * se)
    covers_ws = (ci_lower_ws <= true_tau <= ci_upper_ws)

    # 2. Naive df = N_c - 1
    df_naive = max(1.0, float(n_c - 1))
    t_crit_naive = get_did_critical_value(df_naive, alpha=0.05)
    ci_lower_naive = did_point_estimate - (t_crit_naive * se)
    ci_upper_naive = did_point_estimate + (t_crit_naive * se)
    covers_naive = (ci_lower_naive <= true_tau <= ci_upper_naive)

    # 3. Asymptotic Standard Normal (z = 1.960)
    z_crit = 1.95996
    ci_lower_z = did_point_estimate - (z_crit * se)
    ci_upper_z = did_point_estimate + (z_crit * se)
    covers_z = (ci_lower_z <= true_tau <= ci_upper_z)

    # False positive under null: 95% CI excludes zero
    reject_null = (ci_lower_ws > 0.0) or (ci_upper_ws < 0.0)

    return {
        "point_estimate": did_point_estimate,
        "standard_error": se,
        "true_tau": true_tau,
        "df_ws": df_ws,
        "df_naive": df_naive,
        "covers_ws": covers_ws,
        "covers_naive": covers_naive,
        "covers_z": covers_z,
        "ci_width_ws": ci_upper_ws - ci_lower_ws,
        "ci_width_naive": ci_upper_naive - ci_lower_naive,
        "ci_width_z": ci_upper_z - ci_lower_z,
        "reject_null": reject_null,
    }


def run_did_monte_carlo_battery(
    n_sims: int = 500,
    seed: int = 42,
) -> dict[str, dict[str, float]]:
    """Runs a comprehensive 7-scenario Monte Carlo coverage evaluation battery."""
    rng = np.random.default_rng(seed)

    scenarios = {
        "SCENARIO_1_STRICT_NULL": {
            "n_t": 1, "n_c": 20, "base_mu": 50.0, "true_tau": 0.0,
            "overdispersion_alpha": 0.0, "ar1_rho": 0.0, "domain_shock_std": 0.0,
        },
        "SCENARIO_2_POSITIVE_LIFT": {
            "n_t": 1, "n_c": 20, "base_mu": 50.0, "true_tau": 0.25,
            "overdispersion_alpha": 0.0, "ar1_rho": 0.0, "domain_shock_std": 0.0,
        },
        "SCENARIO_3_NEGATIVE_LIFT": {
            "n_t": 1, "n_c": 20, "base_mu": 50.0, "true_tau": -0.20,
            "overdispersion_alpha": 0.0, "ar1_rho": 0.0, "domain_shock_std": 0.0,
        },
        "SCENARIO_4_OVERDISPERSED_NB": {
            "n_t": 1, "n_c": 20, "base_mu": 50.0, "true_tau": 0.0,
            "overdispersion_alpha": 0.3, "ar1_rho": 0.0, "domain_shock_std": 0.0,
        },
        "SCENARIO_5_SERIAL_CORRELATION": {
            "n_t": 1, "n_c": 20, "base_mu": 50.0, "true_tau": 0.0,
            "overdispersion_alpha": 0.0, "ar1_rho": 0.4, "domain_shock_std": 0.0,
        },
        "SCENARIO_6_CLUSTERED_DOMAIN_SHOCK": {
            "n_t": 1, "n_c": 20, "base_mu": 50.0, "true_tau": 0.0,
            "overdispersion_alpha": 0.0, "ar1_rho": 0.0, "domain_shock_std": 5.0,
        },
        "SCENARIO_7_UNEQUAL_SIZES": {
            "n_t": 4, "n_c": 25, "base_mu": 40.0, "true_tau": 0.0,
            "overdispersion_alpha": 0.1, "ar1_rho": 0.0, "domain_shock_std": 0.0,
        },
    }

    results: dict[str, dict[str, float]] = {}

    for name, params in scenarios.items():
        covers_ws_count = 0
        covers_naive_count = 0
        covers_z_count = 0
        rejections = 0
        widths_ws = []
        widths_z = []

        for _ in range(n_sims):
            trial = simulate_single_did_trial(
                n_t=int(params["n_t"]),
                n_c=int(params["n_c"]),
                base_mu=float(params["base_mu"]),
                true_tau=float(params["true_tau"]),
                overdispersion_alpha=float(params["overdispersion_alpha"]),
                ar1_rho=float(params["ar1_rho"]),
                domain_shock_std=float(params["domain_shock_std"]),
                rng=rng,
            )
            if trial["covers_ws"]:
                covers_ws_count += 1
            if trial["covers_naive"]:
                covers_naive_count += 1
            if trial["covers_z"]:
                covers_z_count += 1
            if trial["reject_null"]:
                rejections += 1
            widths_ws.append(trial["ci_width_ws"])
            widths_z.append(trial["ci_width_z"])

        results[name] = {
            "coverage_welch_satterthwaite": round(covers_ws_count / n_sims, 4),
            "coverage_naive_nc_minus_one": round(covers_naive_count / n_sims, 4),
            "coverage_standard_normal_z": round(covers_z_count / n_sims, 4),
            "rejection_rate": round(rejections / n_sims, 4),
            "mean_ci_width_ws": round(float(np.mean(widths_ws)), 4),
            "mean_ci_width_z": round(float(np.mean(widths_z)), 4),
        }

    return results
