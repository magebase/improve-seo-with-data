#!/usr/bin/env python3
"""
score_backlog.py - Stage 3 of the Learning-to-Rank closed loop. ALWAYS-ON.

Scores the collected candidate backlog (data/ltr_features.json) with the
trained model bundle (models/seo_lgbm_ranker.txt), prescribes an executable
action per candidate from SHAP drivers, calibrates margins into Expected
30-Day Clicks, and emits the 85/15 exploration/exploitation queue:

    data/action_queue.json

Always-on behavior: when no model bundle exists yet, this stage AUTO-TRAINS
a rank_xendcg ranker on the candidate rows themselves — labels come from
DataForSEO SERP-structure bootstrap grades (bootstrap_labels.py), never
from the linear proxy. The deterministic formula survives ONLY as the
init_score residual baseline inside training. If there is genuinely nothing
to train on (< MIN_TRAINABLE_ROWS candidate rows), the stage exits 2 with
pooling instructions instead of emitting proxy-ranked guesses.

Usage:
    python3 scripts/score_backlog.py
    python3 scripts/score_backlog.py --features data/ltr_features.json \\
        --models-dir models/ --queue-size 20
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from dataclasses import dataclass, field
from typing import Any

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from bootstrap_labels import generate_bootstrap_grades
from fleet_state import (
    DEFAULT_TYPE_CAPS,
    DEFAULT_TYPE_CAP_FALLBACK,
    enqueue_tasks,
    lease_tasks,
    pending_count,
)
from ltr_ranker import (
    EXPLOIT_SLOTS,
    EXPLORE_SLOTS,
    FEATURES,
    MIN_TRAINABLE_ROWS,
    compile_wave_backlog,
    detect_cannibalization,
    filter_cooldown,
    heuristic_base_score,
    load_bundle,
    load_cooldown_keys,
    prescribe_action,
    prescribe_all_actions,
    record_shipped,
    save_bundle,
    slice_per_domain,
    split_action_queue,
    train_seo_ranker,
    derive_sibling_counts,
)


def _train_on_the_fly(rows: list[dict[str, Any]], models_dir: str) -> dict[str, Any]:
    """Always-on fallback: trains a bootstrap-grade ranker on the very rows
    being scored (and persists it so later runs reuse the bundle)."""
    if len(rows) < MIN_TRAINABLE_ROWS:
        raise RuntimeError(
            f"Only {len(rows)} candidate rows — below the {MIN_TRAINABLE_ROWS}-row "
            "training floor. Run collect_features.py (more candidates), pool the "
            "fleet (fleet_ingest.py), and rerun. The linear proxy is retired; "
            "guess-ranked queues are no longer emitted."
        )
    grades, label_meta = generate_bootstrap_grades(rows)
    X = np.array([[float(r["features"][f]) for f in FEATURES] for r in rows])
    clusters = np.array([str(r.get("cluster_id", "root")) for r in rows])
    init_score = np.array(
        [
            heuristic_base_score(
                impressions=r.get("impressions", 0),
                current_pos=r.get("current_pos", 50),
                current_ctr=r.get("current_ctr", 0.0),
                conv_value=r.get("conv_value", 1.0),
            )
            for r in rows
        ]
    )
    booster, meta = train_seo_ranker(
        X, grades, clusters, objective="rank_xendcg", init_score=init_score
    )
    os.makedirs(models_dir, exist_ok=True)
    save_bundle(models_dir, booster, meta, None)
    print(
        f"Auto-trained rank_xendcg bundle on {len(rows)} rows "
        f"(label_mode={label_meta['label_mode']}, "
        f"best_iteration={meta['best_iteration']}) -> {models_dir}"
    )
    return {"label_mode": label_meta["label_mode"]}


@dataclass
class EconomicConfig:
    """Configurable economic and Bayesian calibration parameters (v2.2)."""
    labor_hourly_rate: float = 50.0           # Normalized labor cost $/hour
    value_per_conversion: float = 10.0        # Expected dollar value per conversion
    currency: str = "USD"
    time_horizon_days: int = 90               # Economic time horizon for payback (days)
    cold_start_alpha: float = 1.5             # Prior alpha for Beta(1.5, 3.5) -> mean 0.30
    cold_start_beta: float = 3.5              # Prior beta
    success_click_growth_threshold: float = 0.10  # Minimum 10% lift for organic intervention success


def compute_opportunity_intelligence(
    row: dict[str, Any],
    conn: Any = None,
    domain: str | None = None,
    config: EconomicConfig | None = None,
) -> dict[str, Any]:
    """Computes calibrated economic expected value (EV), cannibalization risk, confidence, and decision class.

    Mathematical Architecture (v2.2):
    1. Distinguishes empirical posterior probabilities from cold-start priors.
    2. Computes 95% Bayesian credible intervals via Beta distribution variance.
    3. Separates evidence weight from decision confidence and economic value.
    4. Explicitly discounts implementation labor costs and expected cannibalization risk.

    EV(a) = P(success) * IncrementalBusinessValue - ImplementationCost - ExpectedRiskCost
    """
    cfg = config or EconomicConfig()
    feats = row.get("features") or {}
    cur_pos = float(feats.get("current_pos", 100.0) or 100.0)
    impr = float(row.get("impressions", 0.0) or feats.get("impressions", 0.0) or 0.0)
    clicks = float(row.get("clicks_30d", 0.0) or feats.get("clicks_30d", 0.0) or 0.0)
    page = str(row.get("page") or "")
    query = str(row.get("query") or "")
    action = str(row.get("prescribed_action") or "INJECT_SECONDARY_H2_ONLY")
    route_family = str(row.get("route_family") or "root")

    # 1. Distinguish Empirical Posterior from Cold-Start Priors
    p_success = 0.30
    conf_stat = 0.0
    is_cold_start = True
    alpha_post = cfg.cold_start_alpha
    beta_post = cfg.cold_start_beta

    if conn and domain:
        try:
            from fleet_state import get_action_effectiveness
            eff = get_action_effectiveness(conn, domain, action, route_family)
            if eff.get("has_empirical_evidence"):
                p_success = float(eff.get("smoothed_win_rate", 0.30))
                conf_stat = float(eff.get("confidence_weight", 0.0))
                is_cold_start = False
                alpha_post = float(eff.get("alpha_prior", cfg.cold_start_alpha)) + float(eff.get("success_count", 0.0))
                beta_post = float(eff.get("beta_prior", cfg.cold_start_beta)) + float(eff.get("failure_count", 0.0))
            else:
                # Cross-fleet prior pooling
                from fleet_state import get_fleet_action_effectiveness
                fleet_eff = get_fleet_action_effectiveness(conn, action, route_family)
                if fleet_eff.get("total_experiments", 0) > 0:
                    p_success = float(fleet_eff.get("smoothed_win_rate", 0.30))
                    conf_stat = float(fleet_eff.get("confidence_weight", 0.0)) * 0.70
                    is_cold_start = False
                    alpha_post = float(fleet_eff.get("alpha_prior", cfg.cold_start_alpha)) + float(fleet_eff.get("success_count", 0.0))
                    beta_post = float(fleet_eff.get("beta_prior", cfg.cold_start_beta)) + float(fleet_eff.get("failure_count", 0.0))
        except Exception:
            pass

    # Position-adjusted cold-start prior when no empirical trials exist
    if is_cold_start:
        if 4.0 <= cur_pos <= 15.0:
            p_success = 0.45  # Striking distance benchmark prior
        elif cur_pos < 4.0:
            p_success = 0.35  # Top-3 protected CTR prior
        elif 15.0 < cur_pos <= 30.0:
            p_success = 0.25  # Mid-tail prior
        else:
            p_success = 0.15  # Deep tail prior

    # 2. Uncertainty: 95% Bayesian Credible Interval
    beta_total = max(alpha_post + beta_post, 1.0)
    mean_p = alpha_post / beta_total
    var_p = (alpha_post * beta_post) / ((beta_total ** 2) * max(beta_total + 1.0, 1.0))
    sigma_p = math.sqrt(max(var_p, 1e-6))
    ci_lower = max(0.0, mean_p - 1.96 * sigma_p)
    ci_upper = min(1.0, mean_p + 1.96 * sigma_p)

    # 3. Incremental Clicks estimation via mathematical CTR curve
    cur_ctr = clicks / max(impr, 1.0)
    if cur_pos < 4.0:
        target_ctr = min(0.35, cur_ctr * 1.4 + 0.05)
    elif cur_pos <= 15.0:
        target_ctr = 0.12
    elif cur_pos <= 30.0:
        target_ctr = 0.05
    else:
        target_ctr = 0.02
    delta_clicks = max(0.2, impr * max(0.005, target_ctr - cur_ctr))

    # 4. Intent-specific Conversion Probability
    q_lower = query.lower()
    if any(tok in q_lower for tok in ("convert", "viewer", "calculator", "tool")):
        p_conv = 0.05
    elif any(tok in q_lower for tok in ("compare", "vs", "alternative")):
        p_conv = 0.035
    elif any(tok in q_lower for tok in ("directory", "list", "formats")):
        p_conv = 0.02
    else:
        p_conv = 0.015

    # Incremental business value over configurable economic time horizon
    time_factor = cfg.time_horizon_days / 90.0
    incremental_business_value = delta_clicks * p_conv * cfg.value_per_conversion * time_factor

    # 5. Implementation Cost in resource value ($)
    labor_rate = cfg.labor_hourly_rate
    if "CREATE" in action or "LAUNCH" in action:
        labor_hours = 2.5
    elif "ADD_D1_SPEC" in action:
        labor_hours = 1.25
    elif "INJECT" in action:
        labor_hours = 0.5
    else:
        labor_hours = 0.25
    implementation_cost = labor_hours * labor_rate

    # 6. Multi-dimensional Query Ownership & Cannibalization Risk
    cann_risk = 0.0
    if conn and domain:
        try:
            from fleet_state import get_query_owner
            owner_info = get_query_owner(conn, domain, query, candidate_page=page)
            if owner_info:
                cann_risk = float(owner_info.get("cannibalization_risk", 0.0))
        except Exception:
            pass

    # Expected Risk Cost ($)
    expected_risk_cost = cann_risk * (clicks * 1.0)

    # 7. Economic Expected Value EV(a)
    ev = (p_success * incremental_business_value) - implementation_cost - expected_risk_cost

    # EV Decomposition (v2.2.1 P0.2)
    ev_decomposition = {
        "expected_delta_clicks": round(delta_clicks, 4),
        "conversion_rate": round(p_conv, 4),
        "value_per_conversion": round(cfg.value_per_conversion, 2),
        "time_horizon_days": cfg.time_horizon_days,
        "gross_business_value": round(incremental_business_value, 4),
        "labor_hours": round(labor_hours, 2),
        "labor_hourly_rate": round(labor_rate, 2),
        "implementation_labor_cost": round(implementation_cost, 4),
        "cannibalization_risk": round(cann_risk, 4),
        "expected_risk_cost": round(expected_risk_cost, 4),
        "posterior_success_probability": round(p_success, 4),
        "net_expected_value": round(ev, 4),
    }

    # 8. Telemetry Confidence and Decision Confidence
    telemetry_conf = 0.50
    if impr >= 100:
        telemetry_conf += 0.20
    elif impr >= 20:
        telemetry_conf += 0.10
    if clicks >= 3:
        telemetry_conf += 0.15
    decision_confidence = min(1.0, telemetry_conf + 0.15 * conf_stat)

    # 9. Priority Score
    priority_score = (max(0.01, ev if ev > 0 else (delta_clicks * p_success)) * (1.0 - cann_risk) * decision_confidence) / (implementation_cost / 50.0)

    # 10. Explicit Decision Classes: SHIP, EXPERIMENT, OBSERVE, NO_ACTION
    if cann_risk >= 0.75:
        decision_class = "NO_ACTION"
    elif cur_pos <= 3.0 and cur_ctr >= target_ctr:
        decision_class = "NO_ACTION"  # Protect winners
    elif impr < 10 and cur_pos > 30.0:
        decision_class = "OBSERVE"
    elif priority_score >= 1.5 and cann_risk < 0.40 and decision_confidence >= 0.40:
        decision_class = "SHIP"
    elif priority_score >= 0.4:
        decision_class = "EXPERIMENT"
    else:
        decision_class = "OBSERVE"

    return {
        "expected_value": round(ev, 4),
        "cannibalization_risk": round(cann_risk, 4),
        "confidence": round(decision_confidence, 4),
        "priority_score": round(priority_score, 4),
        "decision_class": decision_class,
        # Statistical Decomposition (v2.2):
        "posterior_success_prob": round(p_success, 4),
        "is_cold_start": is_cold_start,
        "credible_interval_95": [round(ci_lower, 4), round(ci_upper, 4)],
        "evidence_weight": round(conf_stat, 4),
        "model_type": "bayesian_smoothed_empirical" if not is_cold_start else "bayesian_cold_start_prior",
        "calibration_status": "EMPIRICALLY_ESTIMATED" if not is_cold_start else "AWAITING_HOLDOUT_TEST",
        "currency": cfg.currency,
        "ev_decomposition": ev_decomposition,
    }


def determine_canonical_outcome(
    did_outcome_class: str,
    baseline_clicks: float,
    post_clicks: float,
    ci_lower: float,
    ci_upper: float,
    min_incremental_clicks: float = 2.0,
    growth_threshold: float = 0.10,
) -> str:
    """Reconciles causal DiD estimation with empirical growth thresholds into canonical outcome categories.

    Categories:
    - STATISTICALLY_SIGNIFICANT_LIFT: Lower 95% bound > 0.05 and incremental clicks >= min_incremental_clicks.
    - COMMERCIALLY_WORTHWHILE_LIFT: Incremental clicks >= min_incremental_clicks and relative lift >= growth_threshold.
    - COMMERCIALLY_NEGLIGIBLE_LIFT: Positive lift or lower bound > 0.0, but incremental clicks < min_incremental_clicks.
    - STATISTICALLY_SIGNIFICANT_DROP: Upper 95% bound < -0.05.
    - INCONCLUSIVE_EVIDENCE: Confidence interval spans zero or control cohort < 3.
    - NEUTRAL_NO_EFFECT: Confidence interval tightly bounds zero.
    """
    b_clicks = float(baseline_clicks or 0.0)
    p_clicks = float(post_clicks or 0.0)
    delta_clicks = p_clicks - b_clicks
    rel_growth = delta_clicks / max(b_clicks, 1.0)

    if ci_lower > 0.05 and delta_clicks >= min_incremental_clicks:
        return "STATISTICALLY_SIGNIFICANT_LIFT"
    if ci_upper < -0.05:
        return "STATISTICALLY_SIGNIFICANT_DROP"
    if delta_clicks >= min_incremental_clicks and rel_growth >= growth_threshold:
        return "COMMERCIALLY_WORTHWHILE_LIFT"
    if (ci_lower > 0.0 or delta_clicks > 0.0) and delta_clicks < min_incremental_clicks:
        return "COMMERCIALLY_NEGLIGIBLE_LIFT"
    if did_outcome_class in ("INSUFFICIENT_EVIDENCE", "PARALLEL_TRENDS_VIOLATION"):
        return "INCONCLUSIVE_EVIDENCE"
    return "NEUTRAL_NO_EFFECT"


def evaluate_temporal_holdout_calibration(
    conn: Any,
    domain: str | None = None,
    config: EconomicConfig | None = None,
    min_sample_size: int = 20,
) -> dict[str, Any]:
    """Evaluates probability calibration on matured experiments using temporal holdout validation (v2.2.2 P0).

    Strictly prevents data leakage: base rate is trained exclusively on historical training observations
    and frozen before evaluating out-of-sample Brier Skill Score (BSS), Log Loss, and reliability bins.
    """
    cfg = config or EconomicConfig()
    query = """
        SELECT id, domain, page, target_query, action_code, deployed_at,
               baseline_clicks_28d, post_28d_clicks, did_outcome_class
        FROM experiment_ledger
        WHERE status IN ('GRADED', 'EVALUATED_28D', 'EVALUATED_56D', 'TERMINAL_EVALUATED')
    """
    params: list[Any] = []
    if domain:
        query += " AND domain = ?"
        params.append(domain)
    query += " ORDER BY deployed_at ASC"

    try:
        cur = conn.execute(query, tuple(params))
        rows = cur.fetchall()
    except Exception:
        rows = []

    if not rows:
        return {
            "status": "INSUFFICIENT_MATURED_EXPERIMENTS",
            "maturity_classification": "PRIOR_ONLY",
            "sample_size": 0,
            "training_sample_size": 0,
            "holdout_sample_size": 0,
            "total_matured_experiments": 0,
            "min_sample_size_required": min_sample_size,
            "brier_score": None,
            "brier_skill_score": None,
            "baseline_brier_score": None,
            "log_loss": None,
            "baseline_log_loss": None,
            "calibration_intercept": None,
            "calibration_slope": None,
            "reliability_bins": [],
            "reliability_diagram_bins": [],
            "verdict": f"AWAITING_MATURED_EXPERIMENTS: Minimum {min_sample_size} matured experiments required for calibration.",
        }

    y_all: list[int] = []
    p_all: list[float] = []

    for r in rows:
        exp_id, dom, pg, t_query, act, dep_str, base_clicks, post_clicks, did_class = r
        base_c = float(base_clicks or 0.0)
        post_c = float(post_clicks or 0.0)

        is_success = (
            did_class == "STATISTICALLY_SIGNIFICANT_LIFT"
            or (post_c > base_c and (post_c - base_c) / max(base_c, 1.0) >= cfg.success_click_growth_threshold)
        )
        y_all.append(1 if is_success else 0)

        opp = compute_opportunity_intelligence(
            {
                "page": pg,
                "query": t_query,
                "prescribed_action": act,
                "clicks_30d": base_c,
                "impressions": 100.0,
            },
            conn=conn,
            domain=dom,
            config=cfg,
        )
        p_all.append(float(opp.get("posterior_success_prob", 0.30)))

    n_total = len(y_all)
    if n_total < min_sample_size:
        # Sample too small for temporal holdout
        brier_score = sum((p - y) ** 2 for p, y in zip(p_all, y_all)) / max(n_total, 1)
        eps = 1e-15
        log_loss = -sum(
            y * math.log(max(p, eps)) + (1 - y) * math.log(max(1.0 - p, eps))
            for p, y in zip(p_all, y_all)
        ) / max(n_total, 1)
        base_rate = sum(y_all) / max(n_total, 1)
        bs_baseline = base_rate * (1.0 - base_rate)
        ll_baseline = -(
            base_rate * math.log(max(base_rate, eps))
            + (1.0 - base_rate) * math.log(max(1.0 - base_rate, eps))
        )
        bins_def = [(0.0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.0)]
        reliability_bins = []
        for low, high in bins_def:
            b_idx = [i for i, p in enumerate(p_all) if (low <= p < high) or (high == 1.0 and p == 1.0)]
            mean_p = sum(p_all[i] for i in b_idx) / len(b_idx) if b_idx else (low + high) / 2.0
            obs_w = sum(y_all[i] for i in b_idx) / len(b_idx) if b_idx else 0.0
            reliability_bins.append({
                "bin_range": [low, high],
                "count": len(b_idx),
                "mean_predicted": round(mean_p, 4),
                "observed_win_rate": round(obs_w, 4),
                "calibration_error": round(abs(mean_p - obs_w), 4),
            })
        return {
            "status": "INSUFFICIENT_SAMPLE",
            "maturity_classification": "PRIOR_ONLY",
            "sample_size": n_total,
            "total_matured_experiments": n_total,
            "min_sample_size_required": min_sample_size,
            "brier_score": round(brier_score, 4),
            "brier_skill_score": round(1.0 - (brier_score / max(bs_baseline, 1e-6)), 4) if bs_baseline > 1e-6 else 0.0,
            "baseline_brier_score": round(bs_baseline, 4),
            "log_loss": round(log_loss, 4),
            "baseline_log_loss": round(ll_baseline, 4),
            "calibration_intercept": 0.0,
            "calibration_slope": 1.0,
            "reliability_bins": reliability_bins,
            "reliability_diagram_bins": reliability_bins,
            "verdict": f"INSUFFICIENT_SAMPLE_SIZE_FOR_CALIBRATION: N={n_total} < {min_sample_size} minimum matured experiments.",
        }

    # Strict Temporal Split: Train on first 60% of timeline, evaluate out-of-sample on later 40%
    n_train = max(5, int(n_total * 0.60))
    y_train = y_all[:n_train]
    y_holdout = y_all[n_train:]
    p_holdout = p_all[n_train:]
    n_holdout = len(y_holdout)

    # 1. Base rate trained exclusively on training period (ZERO holdout data leakage)
    frozen_base_rate = sum(y_train) / max(len(y_train), 1)

    # 2. Holdout performance evaluation
    brier_score = sum((p - y) ** 2 for p, y in zip(p_holdout, y_holdout)) / max(n_holdout, 1)
    bs_baseline = sum((frozen_base_rate - y) ** 2 for y in y_holdout) / max(n_holdout, 1)

    eps = 1e-15
    log_loss = -sum(
        y * math.log(max(p, eps)) + (1 - y) * math.log(max(1.0 - p, eps))
        for p, y in zip(p_holdout, y_holdout)
    ) / max(n_holdout, 1)
    ll_baseline = -sum(
        y * math.log(max(frozen_base_rate, eps)) + (1 - y) * math.log(max(1.0 - frozen_base_rate, eps))
        for y in y_holdout
    ) / max(n_holdout, 1)

    if bs_baseline > 1e-6:
        brier_skill_score = 1.0 - (brier_score / bs_baseline)
    else:
        brier_skill_score = 0.0 if brier_score < 1e-6 else -1.0

    # Calibration intercept (a) and slope (b) on holdout
    cal_a, cal_b = 0.0, 1.0
    if n_holdout >= 5 and 0.0 < frozen_base_rate < 1.0 and sum(y_holdout) > 0 and sum(y_holdout) < n_holdout:
        try:
            logits = [math.log(max(min(p, 1.0 - eps), eps) / max(min(1.0 - p, 1.0 - eps), eps)) for p in p_holdout]
            beta = np.array([0.0, 1.0])
            X_mat = np.array([[1.0, z] for z in logits])
            Y_vec = np.array(y_holdout, dtype=float)
            for _ in range(15):
                lin = X_mat @ beta
                p_hat = 1.0 / (1.0 + np.exp(-np.clip(lin, -20.0, 20.0)))
                w = np.clip(p_hat * (1.0 - p_hat), 1e-5, 0.25)
                W_diag = np.diag(w)
                grad = X_mat.T @ (Y_vec - p_hat)
                hess = -X_mat.T @ W_diag @ X_mat - (1e-4 * np.eye(2))
                delta = np.linalg.solve(-hess, grad)
                beta += delta
                if np.max(np.abs(delta)) < 1e-4:
                    break
            cal_a = float(beta[0])
            cal_b = float(beta[1])
        except Exception:
            cal_a, cal_b = 0.0, 1.0

    # 5 Reliability bins on holdout
    bins_def = [(0.0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.0)]
    reliability_bins = []
    all_bins_occupied = True
    for low, high in bins_def:
        b_idx = [i for i, p in enumerate(p_holdout) if (low <= p < high) or (high == 1.0 and p == 1.0)]
        if not b_idx:
            all_bins_occupied = False
        mean_p = sum(p_holdout[i] for i in b_idx) / len(b_idx) if b_idx else (low + high) / 2.0
        obs_w = sum(y_holdout[i] for i in b_idx) / len(b_idx) if b_idx else 0.0
        reliability_bins.append({
            "bin_range": [low, high],
            "count": len(b_idx),
            "mean_predicted": round(mean_p, 4),
            "observed_win_rate": round(obs_w, 4),
            "calibration_error": round(abs(mean_p - obs_w), 4),
        })

    # Maturity classification: PRIOR_ONLY -> PRELIMINARILY_CALIBRATED -> WELL_CALIBRATED
    if n_total < min_sample_size or n_holdout < 10:
        maturity = "PRIOR_ONLY"
        verdict = f"INSUFFICIENT_SAMPLE_SIZE_FOR_CALIBRATION: N={n_total} < {min_sample_size} minimum matured experiments."
    elif brier_skill_score > 0.0 and brier_score <= 0.25 and all_bins_occupied and (0.7 <= cal_b <= 1.3):
        maturity = "WELL_CALIBRATED"
        verdict = "WELL_CALIBRATED"
    elif brier_skill_score > 0.0:
        maturity = "PRELIMINARILY_CALIBRATED"
        verdict = "WELL_CALIBRATED"
    else:
        maturity = "PRELIMINARILY_CALIBRATED"
        verdict = "NEEDS_CALIBRATION"

    return {
        "status": "EVALUATED",
        "maturity_classification": maturity,
        "sample_size": n_total,
        "training_sample_size": n_train,
        "holdout_sample_size": n_holdout,
        "total_matured_experiments": n_total,
        "min_sample_size_required": min_sample_size,
        "frozen_training_base_rate": round(frozen_base_rate, 4),
        "brier_score": round(brier_score, 4),
        "brier_skill_score": round(brier_skill_score, 4),
        "baseline_brier_score": round(bs_baseline, 4),
        "log_loss": round(log_loss, 4),
        "baseline_log_loss": round(ll_baseline, 4),
        "calibration_intercept": round(cal_a, 4),
        "calibration_slope": round(cal_b, 4),
        "reliability_bins": reliability_bins,
        "reliability_diagram_bins": reliability_bins,
        "verdict": verdict,
    }


def score_rows(
    rows: list[dict[str, Any]],
    models_dir: str,
    conn: Any = None,
    domain: str | None = None,
) -> dict[str, Any]:
    """Scores rows with the bundle when present, else auto-trains one."""
    bundle = None
    if os.path.exists(os.path.join(models_dir, "seo_lgbm_ranker.txt")):
        bundle = load_bundle(models_dir)
    label_mode = None

    if bundle is None:
        print(
            "No trained bundle found -> AUTO-TRAINING a rank_xendcg ranker on "
            "bootstrap grades (the linear proxy is retired)."
        )
        label_mode = _train_on_the_fly(rows, models_dir)["label_mode"]
        bundle = load_bundle(models_dir)

    print(
        f"Scoring {len(rows)} candidates with trained {bundle['objective']} model ..."
    )
    X = np.array([[float(r["features"][f]) for f in bundle["features"]] for r in rows])
    raw_scores = bundle["model"].predict(X)

    # SHAP contributions: (n, n_features + 1); last column is the bias term.
    shap_matrix = bundle["model"].predict(X, pred_contrib=True)
    has_calibrator = bundle["calibrator"] is not None
    for i, row in enumerate(rows):
        feats = row["features"]
        row["rank_score"] = float(raw_scores[i])
        if has_calibrator:
            row["expected_clicks_30d"] = float(
                bundle["calibrator"].transform(np.array([raw_scores[i]]))[0]
            )
        else:
            row["expected_clicks_30d"] = None
        shap_row = shap_matrix[i][: len(FEATURES)]
        shap = dict(zip(FEATURES, (float(v) for v in shap_row)))
        row["shap"] = {k: round(v, 6) for k, v in shap.items()}
        row["prescribed_action"] = prescribe_action(
            current_pos=feats["current_pos"],
            title_match_rate=feats["title_exact_match_rate"],
            hub_links_shap=shap["parent_hub_internal_links"],
            centroid_sim=feats["domain_centroid_sim"],
            forum_ratio=feats["serp_forum_ratio"],
            shap=shap,
        )
        # Multi-prescription explosion: one row can carry several atomic
        # bottlenecks; each becomes its own TDD work item (primary first).
        # Rows arriving with an explicit prescription set (orphan routes) keep
        # it — their routes exist, so the generic pos=100 explosion is wrong.
        if not row.get("actions"):
            row["actions"] = prescribe_all_actions(
                current_pos=feats["current_pos"],
                title_match_rate=feats["title_exact_match_rate"],
                hub_links_shap=shap["parent_hub_internal_links"],
                centroid_sim=feats["domain_centroid_sim"],
                forum_ratio=feats["serp_forum_ratio"],
                impressions=float(row.get("impressions", 0) or 0),
                clicks=float(row.get("clicks_30d", 0) or 0),
                shap=shap,
            )

        # Outcome-Driven Opportunity Intelligence v2
        row_domain = domain or row.get("domain") or (feats.get("domain") if isinstance(feats, dict) else None)
        intel = compute_opportunity_intelligence(row, conn=conn, domain=row_domain)
        row.update(intel)
    return {"mode": "trained_model", "label_mode": label_mode, "rows": rows}


def merge_leased_into_output(output_path: str, leased: list, hygiene: dict) -> None:
    """Records the slow-path lease + preflight results in the output JSON.

    The fast path already embeds ``leased``/``hygiene`` in its output; the
    slow path writes the queue JSON BEFORE the lease runs (the queue file is
    the artifact), so this re-opens it and attaches the lease. The executor
    adjudicates from this file - a wave whose lease is invisible cannot be
    audited (wave-63 gap).
    """
    if not leased and not hygiene:
        return
    with open(output_path, encoding="utf-8") as fh:
        payload = json.load(fh)
    payload["leased"] = leased
    payload["hygiene"] = hygiene
    with open(output_path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--features", default="data/ltr_features.json")
    parser.add_argument("--models-dir", default="models/")
    parser.add_argument("--output", default="data/action_queue.json")
    parser.add_argument("--queue-size", type=int, default=20)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--ledger",
        default="data/shipped_actions.jsonl",
        help="cooldown ledger; (page, action) pairs shipped within --cooldown-days are filtered from this queue",
    )
    parser.add_argument(
        "--cooldown-days",
        type=int,
        default=30,
        help="cooldown window in days (0 disables filtering)",
    )
    parser.add_argument(
        "--per-domain-top",
        type=int,
        default=0,
        help="cap the final queue at N tasks per registered domain (0 = no per-domain quota)",
    )
    parser.add_argument(
        "--record",
        action="store_true",
        help="append the emitted queue to the cooldown ledger",
    )
    parser.add_argument(
        "--compile-wave",
        type=int,
        default=0,
        metavar="N",
        help="additionally compile an atomic TDD wave of N tasks (compile_wave_backlog) into the output",
    )
    parser.add_argument(
        "--state-db",
        default="",
        help="SQLite fleet state DB; when set, emitted tasks are enqueued and leased (PENDING -> LEASED)",
    )
    parser.add_argument(
        "--lease-size",
        type=int,
        default=35,
        help="tasks leased per invocation from the state-DB cursor (the "
        "backlog is replenished at FULL depth regardless; 0 leases everything "
        "enqueued this run). When the cursor already holds >= "
        "--replenish-below PENDING tasks, this invocation takes the fast "
        "path: lease only, no collection/scoring.",
    )
    parser.add_argument(
        "--replenish-below",
        type=int,
        default=70,
        help="replenish (full-depth compile + enqueue) whenever the pending "
        "backlog holds fewer than this many tasks; at or above it the "
        "invocation is a pure <1s cursor lease (2 waves of buffer)",
    )
    parser.add_argument(
        "--intent-map",
        default="~/.seo_fleet/route_intent_map.json",
        help="JSON map {page: rendered_text} used by cursor hygiene to "
        "graduate INJECT_* tasks whose query tokens the page already covers "
        "(empty string disables graduation)",
    )
    parser.add_argument(
        "--domain",
        default="",
        help="scope lease and pending count checks to a specific domain (e.g. figiva.com)",
    )
    parser.add_argument(
        "--no-lock-registry",
        action="store_true",
        help="skip the multi-worktree lock registry (~/.seo_fleet/"
        "worktree_locks.json) when picking locked route prefixes",
    )
    args = parser.parse_args(argv)

    def _hygiene_context():
        from cursor_hygiene import active_locked_prefixes

        intent_map: dict = {}
        if args.intent_map:
            map_path = os.path.expanduser(args.intent_map)
            if os.path.exists(map_path):
                with open(map_path, encoding="utf-8") as fh:
                    intent_map = json.load(fh)
        locked = () if args.no_lock_registry else active_locked_prefixes()
        return intent_map, locked

    # Fast path (the 50x/day cursor): when the backlog holds at least two
    # waves of PENDING tasks, lease and return in well under a second — no
    # feature file, no model, no network.
    if args.state_db and args.lease_size > 0:
        from fleet_state import (
            connect_state_db as _connect,
            lease_tasks as _lease,
            pending_count as _pending,
        )

        domain = args.domain or None
        fast_conn = _connect(args.state_db)
        if _pending(fast_conn, domain=domain) >= max(args.replenish_below, args.lease_size):
            # Pre-lease hygiene: junk queries -> REJECTED (terminal), intent
            # tasks already covered by the route/country maps -> SHIPPED,
            # other worktrees' locked prefixes -> skipped this invocation.
            from cursor_hygiene import preflight_hygiene

            intent_map, locked = _hygiene_context()
            hygiene = preflight_hygiene(
                fast_conn,
                route_intent_map=intent_map,
                locked_path_prefixes=locked,
            )
            leased = _lease(
                fast_conn,
                domain=domain,
                limit=args.lease_size,
                family_caps={"number": 3},
                default_family_cap=10,
                type_caps=DEFAULT_TYPE_CAPS,
                default_type_cap=DEFAULT_TYPE_CAP_FALLBACK,
            )
            os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
            with open(args.output, "w", encoding="utf-8") as fh:
                json.dump(
                    {"fast_path": True, "hygiene": hygiene, "leased": leased},
                    fh,
                    indent=2,
                )
            print(
                f"Fast path: leased {len(leased)} tasks from the backlog cursor "
                f"(no collection/scoring; {_pending(fast_conn, domain=domain)} still pending)."
            )
            if any(
                hygiene[k] for k in ("rejected", "graduated", "locked", "intent_capped")
            ):
                print(
                    f"  Hygiene: {hygiene['rejected']} junk REJECTED, "
                    f"{hygiene['graduated']} intent tasks graduated to SHIPPED, "
                    f"{hygiene['locked']} locked by other worktrees, "
                    f"{hygiene['intent_capped']} intent-capped."
                )
            for task in leased[:5]:
                print(
                    f"  LEASED {task['action_code']} -> {task['page']}"
                    + (f" ({task['file_target']})" if task.get("file_target") else "")
                )
            fast_conn.close()
            return 0
        fast_conn.close()

    if not os.path.exists(args.features):
        print(f"ERROR: {args.features} not found. Run collect_features.py first.")
        return 1

    with open(args.features, encoding="utf-8") as fh:
        payload = json.load(fh)
    rows = payload.get("rows") or []
    if not rows:
        print("ERROR: feature file contains no rows.")
        return 1

    state_conn = None
    if args.state_db:
        try:
            state_conn = connect_state_db(args.state_db)
        except Exception:
            state_conn = None

    target_domain = args.domain or payload.get("site")
    result = score_rows(rows, args.models_dir, conn=state_conn, domain=target_domain)
    if state_conn:
        state_conn.close()
    all_scored = list(result["rows"])
    scored = list(result["rows"])

    # Cannibalization detector: BEFORE the per-query collapse (which discards
    # the competitor rows), flag queries carried by >= 2 distinct pages all
    # ranking beyond position 10. The keeper row gains the
    # CONSOLIDATE_CANNIBALIZED_URLS action; full competing-URL sets are
    # emitted alongside the queue for the implementing agent.
    scored, consolidation_tasks = detect_cannibalization(scored)

    # One action per query: cannibalised (query, page) pairs collapse onto the
    # best-scoring row (the URL-ownership model allows a single owner per task).
    by_query: dict[str, dict[str, Any]] = {}
    for row in scored:
        keeper = by_query.get(row["query"])
        if keeper is None or row.get("rank_score", 0.0) > keeper.get("rank_score", 0.0):
            by_query[row["query"]] = row
    scored = list(by_query.values())

    # Orphan-route rows already prescribe BOOST_INTERNAL_LINKS /
    # EXPAND_THIN_ROUTE (the routes exist); preserve that override instead of
    # letting the generic pos=100 -> LAUNCH_PSEO_ROUTE mapping win.
    for row in scored:
        if row.get("source") == "orphan_route" and row.get("actions"):
            row["prescribed_action"] = row["actions"][0]

    # Cooldown: drop (page, action) pairs already shipped recently so back-to-
    # back runs surface the NEXT wave of unoptimized pages instead of the
    # same recommendations.
    if args.cooldown_days > 0:
        cooled = load_cooldown_keys(args.ledger, within_days=args.cooldown_days)
        if cooled:
            fresh_count = len(scored)
            scored, skipped = filter_cooldown(scored, cooled)
            print(
                f"Cooldown ledger ({args.ledger}): {fresh_count - len(skipped)} rows fresh, "
                f"{len(skipped)} fully cooled rows dropped."
            )
    else:
        print("Cooldown disabled (--cooldown-days 0).")

    n_exploit = max(
        1, int(args.queue_size * EXPLOIT_SLOTS / (EXPLOIT_SLOTS + EXPLORE_SLOTS))
    )
    n_explore = max(1, args.queue_size - n_exploit)
    queue = split_action_queue(
        scored, n_exploit=n_exploit, n_explore=n_explore, seed=args.seed
    )

    # Per-domain quota: a big property must not crowd young properties out of
    # the queue; slice the globally ranked queue per registered domain.
    if args.per_domain_top > 0:
        pre_slice = len(queue)
        queue = slice_per_domain(queue, per_domain_top=args.per_domain_top)
        print(
            f"Per-domain quota (top {args.per_domain_top}/domain): {pre_slice} -> {len(queue)} tasks."
        )

    if args.record:
        written = record_shipped(queue, args.ledger)
        print(f"Recorded {written} task(s) -> {args.ledger} (cooldown ledger).")

    # Atomic TDD wave compiler: decompose the scored backlog into 35-60
    # file-targeted tasks (multi-action per row, cooldown-masked, deduped).
    wave_tasks: list[dict[str, Any]] = []
    if args.compile_wave > 0:
        cooled_keys = (
            load_cooldown_keys(args.ledger, within_days=args.cooldown_days)
            if args.cooldown_days > 0
            else set()
        )
        known_live_urls: set[str] = set()
        if args.state_db:
            try:
                temp_conn = connect_state_db(args.state_db)
                for (p,) in temp_conn.execute(
                    "SELECT DISTINCT page FROM atomic_task_backlog WHERE status = 'SHIPPED'"
                ):
                    if p:
                        known_live_urls.add(str(p).rstrip("/"))
                        known_live_urls.add(str(p).rstrip("/") + "/")
                temp_conn.close()
            except Exception:
                pass
        # FULL-depth decomposition: the SQLite backlog gets EVERY rule hit
        # across ALL scored rows (600-900 tasks), so runs 2..50 lease from the
        # cursor without re-running collection/scoring. The JSON output keeps
        # only the actionable --compile-wave slice of that inventory.
        full_backlog = compile_wave_backlog(
            all_scored,
            shipped_ledger=cooled_keys,
            target_wave_size=10_000_000,
            # Catalog families are derived from the rows themselves so a
            # top-ranked child route propagates its fix across every sibling
            # without a hand-maintained prefix map.
            sibling_counts=derive_sibling_counts(all_scored),
            known_live_urls=known_live_urls,
        )
        wave_tasks = full_backlog[: max(0, args.compile_wave)]
        print(
            f"Compiled {len(full_backlog)}-task backlog inventory; "
            f"{len(wave_tasks)} in this wave slice (--compile-wave "
            f"{args.compile_wave})."
        )

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as fh:
        json.dump(
            {
                "site": payload.get("site"),
                "scoring_mode": result["mode"],
                "queue": queue,
                "consolidation": consolidation_tasks,
                "wave_tasks": wave_tasks,
            },
            fh,
            indent=2,
        )

    # Fleet state machine: enqueue the FULL backlog inventory, then lease only
    # --lease-size tasks so the next invocations lease fresh work (#36-70,
    # #71-105, ...) instead of draining the cursor dry.
    if args.state_db:
        from fleet_state import connect_state_db

        conn = connect_state_db(args.state_db)
        pending = full_backlog + queue if args.compile_wave > 0 else queue
        added = enqueue_tasks(conn, pending)
        # Pre-lease hygiene on the freshly enqueued backlog too (junk from the
        # compile never reaches the lease), then the stratified lease with
        # BOTH diversity axes: route-family caps AND task-type quotas.
        from cursor_hygiene import preflight_hygiene

        intent_map, locked = _hygiene_context()
        hygiene = preflight_hygiene(
            conn,
            route_intent_map=intent_map,
            locked_path_prefixes=locked,
        )
        lease_n = args.lease_size if args.lease_size > 0 else len(pending)
        # Stratified lease: /number/* (or any single template family) can
        # never take more than 3 slots of a 35-task wave; other families cap
        # at 10 so no one family monopolizes the wave either. Task-type
        # quotas force the wave to carry D1 tables, inlinks, CTR hooks and
        # route builds (8/8/6/5/3 split) instead of 30 heading checks.
        leased = lease_tasks(
            conn,
            domain=args.domain or None,
            limit=lease_n,
            family_caps={"number": 3},
            default_family_cap=10,
            type_caps=DEFAULT_TYPE_CAPS,
            default_type_cap=DEFAULT_TYPE_CAP_FALLBACK,
        )
        still_pending = pending_count(conn, domain=args.domain or None)
        print(
            f"State DB {args.state_db}: enqueued {added} new, leased {len(leased)} "
            f"(PENDING -> LEASED), {still_pending} still pending."
        )
        if any(
            hygiene[k] for k in ("rejected", "graduated", "locked", "intent_capped")
        ):
            print(
                f"      Hygiene: {hygiene['rejected']} junk REJECTED, "
                f"{hygiene['graduated']} intent tasks graduated to SHIPPED, "
                f"{hygiene['locked']} locked by other worktrees, "
                f"{hygiene['intent_capped']} intent-capped."
            )
        if 0 < still_pending < 100:
            print(
                "      NOTE: backlog below 100 pending - the next collection "
                "run will replenish it (waterfall + matrix + surrogate)."
            )
        for task in leased[:5]:
            print(
                f"  LEASED {task['action_code']} -> {task['page']}"
                + (f" ({task['file_target']})" if task.get("file_target") else "")
            )
        # Wave-63 gap fix: the fast path records leased tasks in its output
        # JSON; the slow path must too (the executor adjudicates from this
        # file, and a wave whose lease is invisible cannot be audited).
        merge_leased_into_output(args.output, leased, hygiene)
        conn.close()
    if consolidation_tasks:
        print(
            f"\nCannibalization: {len(consolidation_tasks)} CONSOLIDATE_CANNIBALIZED_URLS task(s):"
        )
        for task in consolidation_tasks:
            print(
                f"  {task['query'][:50]!r}: {len(task['pages'])} competing URLs {task['positions']}"
            )

    print(f"\nAction queue ({result['mode']}, {len(queue)} tasks) -> {args.output}")
    print(f"{'slot':<9} {'action':<32} {'score':>8} {'exp30d':>8}  query")
    for entry in queue:
        exp = entry.get("expected_clicks_30d")
        exp_s = f"{exp:.1f}" if isinstance(exp, float) else "-"
        extra = len(entry.get("actions") or [1]) - 1
        extra_s = f" (+{extra} more)" if extra > 0 else ""
        print(
            f"{entry['slot']:<9} {entry['prescribed_action'][:32]:<32} "
            f"{entry['rank_score']:>8.3f} {exp_s:>8}  {entry['query'][:52]}{extra_s}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
