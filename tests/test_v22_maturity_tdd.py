"""tests/test_v22_maturity_tdd.py - Comprehensive TDD Suite for Outcome Engine v2.2.

Covers:
1. P0 — Genuine Bayesian Expected Value Calibration (score_backlog.py)
   - EconomicConfig customizable parameters (labor rate, conversion value, currency, horizon)
   - Opportunity intelligence decomposition: posterior success prob, cold-start priors, 95% CI
   - Temporal holdout evaluation: Brier score, log loss, 5-bin reliability diagram
2. P0 — Difference-in-Differences Small-Sample Reliability & Parallel Trends (fleet_state.py)
   - Pre-treatment parallel trends divergence formula |(T_P2-T_P1)/max(T_P1,1) - (C_P2-C_P1)/max(C_P1,1)|
   - PARALLEL_TRENDS_VIOLATION flag for divergence > 0.30
   - Small-sample Student's t critical values for N_c < 5 (df <= 4)
   - COMMERCIALLY_NEGLIGIBLE_LIFT (< 2.0 incremental clicks over 28d) vs STATISTICALLY_SIGNIFICANT_LIFT
3. P0 — Real Functional Product Verification (verify_product_functionality.py & verify_technical_seo.py)
   - OpenFileConverter client execution pipeline & format pairing
   - IncomeCanvas Tax Year 2026 ACA 100% full repayment under IRC § 36B (caps sunset)
   - IncomeCanvas statutory 130h full-time threshold (IRC § 4980H(c)(4)) and 120h FTE divisor (IRC § 4980H(c)(2)(E))
   - IncomeCanvas Section 179 $1,250,000 / $3,130,000 caps & WACC formulas
   - SMSRiver active number inventory & poller check
   - Gate 10 integration into verify_technical_seo
4. P1 — Multi-Dimensional Query Ownership & SERP Jaccard Overlap
   - calculate_serp_jaccard_overlap (>= 0.50 = identical intent)
   - Harmless dual-ranking in top 5 vs harmful cannibalization (>25% CTR drop or rank bounce)
5. P1 — 3-Tier Hierarchical Bayesian Fleet Learning
   - Tier 1 Global fleet prior Beta(1.5, 3.5)
   - Tier 2 Property-specific prior
   - Tier 3 Action/family stratified by baseline position band (top_3, striking_4_15, tail_15_30, deep_tail_30_plus)
   - Immature (<28d) and unmeasured experiments excluded from learning
"""

from __future__ import annotations

import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

# Ensure scripts dir is on sys.path
SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from fleet_state import (
    calculate_pre_trend_divergence,
    calculate_serp_jaccard_overlap,
    classify_cannibalization_risk,
    connect_state_db,
    enqueue_tasks,
    get_action_effectiveness,
    get_fleet_action_effectiveness,
    get_position_tier,
    get_query_owner,
    get_t_critical_value,
    lease_tasks,
    record_action_effectiveness,
    record_experiment,
    update_experiment_outcomes,
    update_experiment_recrawl,
)
from score_backlog import (
    EconomicConfig,
    compute_opportunity_intelligence,
    evaluate_temporal_holdout_calibration,
)
from verify_product_functionality import (
    FunctionalTestResult,
    verify_calculator_functionality,
    verify_converter_functionality,
    verify_directory_functionality,
    verify_product_functionality,
    verify_smsriver_functionality,
)
from verify_technical_seo import audit_html_technical_seo


@pytest.fixture
def temp_db(tmp_path: Path) -> sqlite3.Connection:
    db_file = tmp_path / "test_v22_state.db"
    conn = connect_state_db(str(db_file))
    yield conn
    conn.close()


# =============================================================================
# 1. Calibrated Expected Value & Holdout Evaluation (P0)
# =============================================================================

def test_economic_config_defaults_and_customization():
    """EconomicConfig supports configurable labor rate, conversion value, currency, and horizon."""
    default_cfg = EconomicConfig()
    assert default_cfg.labor_hourly_rate == 50.0
    assert default_cfg.value_per_conversion == 10.0
    assert default_cfg.currency == "USD"
    assert default_cfg.time_horizon_days == 90
    assert default_cfg.cold_start_alpha == 1.5
    assert default_cfg.cold_start_beta == 3.5

    custom_cfg = EconomicConfig(
        labor_hourly_rate=75.0,
        value_per_conversion=25.0,
        currency="EUR",
        time_horizon_days=180,
    )
    assert custom_cfg.labor_hourly_rate == 75.0
    assert custom_cfg.value_per_conversion == 25.0
    assert custom_cfg.currency == "EUR"
    assert custom_cfg.time_horizon_days == 180


def test_compute_opportunity_intelligence_returns_statistical_decomposition():
    """Opportunity intelligence distinguishes empirical posterior, cold-start priors, 95% CI, and economic value."""
    task = {
        "id": 101,
        "domain": "openfileconverter.com",
        "page": "https://openfileconverter.com/convert/step-to-stl/",
        "query": "step to stl",
        "action_code": "INJECT_EXACT_TITLE_AND_H2",
        "route_family": "convert",
        "current_impressions": 5000.0,
        "current_clicks": 50.0,
        "current_pos": 7.5,
        "current_ctr": 0.01,
        "search_volume": 6000.0,
        "priority_score": 8.0,
    }

    intel = compute_opportunity_intelligence(task)
    assert "expected_value" in intel
    assert "posterior_success_prob" in intel
    assert "is_cold_start" in intel
    assert "credible_interval_95" in intel
    assert "evidence_weight" in intel
    assert "model_type" in intel
    assert "currency" in intel
    assert intel["currency"] == "USD"

    # Prior for striking distance (pos 7.5) has prior mean ~0.45
    ci_lower, ci_upper = intel["credible_interval_95"]
    assert 0.0 <= ci_lower < intel["posterior_success_prob"] < ci_upper <= 1.0


def test_evaluate_temporal_holdout_calibration(temp_db: sqlite3.Connection):
    """Temporal holdout evaluation calculates Brier score, log loss, and 5 reliability diagram bins."""
    now = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)
    # Seed 10 evaluated experiments
    for i in range(10):
        is_succ = (i % 2 == 0)
        exp_id = record_experiment(
            temp_db,
            task_id=200 + i,
            domain="openfileconverter.com",
            page=f"https://openfileconverter.com/page-{i}/",
            target_query=f"query {i}",
            action_code="INJECT_EXACT_TITLE_AND_H2",
            deployed_at=now - timedelta(days=35),
            status="GRADED",
        )
        temp_db.execute(
            """
            UPDATE experiment_ledger
            SET did_outcome_class = ?, incremental_clicks_est = ?, status = 'GRADED'
            WHERE id = ?
            """,
            ("STATISTICALLY_SIGNIFICANT_LIFT" if is_succ else "NEUTRAL_NO_EFFECT", 5.0 if is_succ else 0.0, exp_id),
        )
    temp_db.commit()

    eval_result = evaluate_temporal_holdout_calibration(temp_db, domain="openfileconverter.com")
    assert eval_result["total_matured_experiments"] == 10
    assert 0.0 <= eval_result["brier_score"] <= 1.0
    assert eval_result["log_loss"] >= 0.0
    assert len(eval_result["reliability_diagram_bins"]) == 5


# =============================================================================
# 2. Difference-in-Differences Small-Sample Reliability & Parallel Trends (P0)
# =============================================================================

def test_calculate_pre_trend_divergence_formula():
    """Formula |(T_P2 - T_P1)/max(T_P1, 1) - (C_P2 - C_P1)/max(C_P1, 1)| identifies parallel trends violations."""
    # Treatment: P1=100, P2=110 (+10% growth). Control: P1=100, P2=112 (+12% growth). Divergence = |0.10 - 0.12| = 0.02
    div_clean = calculate_pre_trend_divergence(t_p1=100.0, t_p2=110.0, c_p1=100.0, c_p2=112.0)
    assert pytest.approx(div_clean, 0.001) == 0.02
    assert div_clean <= 0.30

    # Parallel trends violation: Treatment grew +50% pre-intervention while Control was flat 0%
    div_violation = calculate_pre_trend_divergence(t_p1=100.0, t_p2=150.0, c_p1=100.0, c_p2=100.0)
    assert pytest.approx(div_violation, 0.001) == 0.50
    assert div_violation > 0.30


def test_did_small_sample_students_t_correction():
    """Degrees of freedom critical values apply for control cohorts N_c < 5."""
    assert get_t_critical_value(n_controls=6) == 1.96
    assert get_t_critical_value(n_controls=5) == 1.96
    assert get_t_critical_value(n_controls=4) == 2.776
    assert get_t_critical_value(n_controls=3) == 3.182
    assert get_t_critical_value(n_controls=2) == 4.303
    assert get_t_critical_value(n_controls=1) == 4.303


def test_commercially_negligible_lift_classification(temp_db: sqlite3.Connection):
    """Statistically non-zero lift with < 2.0 incremental clicks is classified as COMMERCIALLY_NEGLIGIBLE_LIFT."""
    dep_time = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
    eval_time = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)

    # 5 valid control cohorts
    controls = [f"https://openfileconverter.com/ctrl-{i}/" for i in range(5)]
    record_experiment(
        temp_db,
        domain="openfileconverter.com",
        page="https://openfileconverter.com/convert/flac-to-mp3/",
        target_query="flac mp3",
        action_code="INJECT_EXACT_TITLE_AND_H2",
        deployed_at=dep_time,
        baseline_clicks_28d=1.0,
        baseline_impressions_28d=100.0,
        control_cohort_pages=controls,
        control_baseline_clicks=10.0,
        pre_trend_divergence=0.05,
    )

    # Fresh GSC: Treatment got 2.8 clicks (+1.8 incremental clicks, statistically non-zero lift but < 2.0)
    fresh_gsc = {
        "flac mp3\nhttps://openfileconverter.com/convert/flac-to-mp3/": {
            "page": "https://openfileconverter.com/convert/flac-to-mp3/",
            "clicks": 2.8,
            "impressions": 150.0,
            "position": 8.0,
        }
    }
    for c in controls:
        fresh_gsc[f"query\n{c}"] = {"page": c, "clicks": 10.0, "impressions": 200.0}

    outcomes = update_experiment_outcomes(temp_db, "openfileconverter.com", fresh_gsc, now=eval_time)
    assert outcomes["graded"] == 1

    row = temp_db.execute(
        "SELECT did_outcome_class, incremental_clicks_est FROM experiment_ledger WHERE page LIKE '%flac-to-mp3%'"
    ).fetchone()
    assert row[0] == "COMMERCIALLY_NEGLIGIBLE_LIFT"
    assert row[1] < 2.0


def test_statistically_significant_lift_classification(temp_db: sqlite3.Connection):
    """Substantial lift with >= 2.0 incremental clicks is classified as STATISTICALLY_SIGNIFICANT_LIFT."""
    dep_time = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
    eval_time = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)

    controls = [f"https://openfileconverter.com/c-{i}/" for i in range(5)]
    record_experiment(
        temp_db,
        domain="openfileconverter.com",
        page="https://openfileconverter.com/convert/docx-to-pdf/",
        target_query="docx to pdf",
        action_code="CREATE_PROGRAMMATIC_ROUTE",
        deployed_at=dep_time,
        baseline_clicks_28d=10.0,
        baseline_impressions_28d=500.0,
        control_cohort_pages=controls,
        control_baseline_clicks=20.0,
        pre_trend_divergence=0.04,
    )

    # Fresh GSC: Treatment jumped from 10 -> 35 clicks (+25 clicks)
    fresh_gsc = {
        "docx to pdf\nhttps://openfileconverter.com/convert/docx-to-pdf/": {
            "page": "https://openfileconverter.com/convert/docx-to-pdf/",
            "clicks": 35.0,
            "impressions": 1500.0,
            "position": 3.5,
        }
    }
    for c in controls:
        fresh_gsc[f"q\n{c}"] = {"page": c, "clicks": 21.0, "impressions": 550.0}

    outcomes = update_experiment_outcomes(temp_db, "openfileconverter.com", fresh_gsc, now=eval_time)
    assert outcomes["graded"] == 1

    row = temp_db.execute(
        "SELECT did_outcome_class, incremental_clicks_est FROM experiment_ledger WHERE page LIKE '%docx-to-pdf%'"
    ).fetchone()
    assert row[0] == "STATISTICALLY_SIGNIFICANT_LIFT"
    assert row[1] >= 2.0


# =============================================================================
# 3. Real Functional Product Verification (P0)
# =============================================================================

def test_verify_converter_functionality_valid_and_invalid():
    """OpenFileConverter verification checks interactive dropzone, client execution pipeline, and format pairing."""
    valid_html = """
    <html>
    <body>
        <h1>Convert STEP to STL Online</h1>
        <div id="dropzone" class="converter-dropzone">
            <input type="file" id="file-input" />
            <button id="convert-btn">Convert STEP to STL</button>
        </div>
        <script>
            const reader = new FileReader();
            reader.readAsArrayBuffer(file);
            const wasm = new Worker('/static/wasm-worker.js');
        </script>
    </body>
    </html>
    """
    res_valid = verify_converter_functionality("https://openfileconverter.com/convert/step-to-stl/", valid_html)
    assert res_valid.passed is True
    assert res_valid.product_type == "converter"

    invalid_html = """
    <html><body><h1>Convert STEP to STL</h1><p>Just upload your file here soon.</p></body></html>
    """
    res_invalid = verify_converter_functionality("https://openfileconverter.com/convert/step-to-stl/", invalid_html)
    assert res_invalid.passed is False
    assert any("dropzone" in err for err in res_invalid.issues)


def test_verify_calculator_aca_2026_repayment_rule():
    """IncomeCanvas ACA calculator enforces 100% full repayment of excess APTC under IRC § 36B (caps sunset)."""
    # 2026 compliant HTML: states 100% full repayment and statutory 130h / 120h definitions
    compliant_html = """
    <html>
    <body>
        <h1>ACA Premium Tax Credit & FTE Calculator (Tax Year 2026)</h1>
        <p>Under IRC § 36B, statutory repayment limitation caps sunset for tax year 2026: 100% full repayment of excess advance credits is required.</p>
        <p>Full-time threshold: 130 hours per month pursuant to IRC § 4980H(c)(4).</p>
        <p>FTE calculation divisor: 120 hours monthly pursuant to IRC § 4980H(c)(2)(E).</p>
        <input type="number" id="household-income" />
        <button id="calc-btn">Calculate</button>
    </body>
    </html>
    """
    res = verify_calculator_functionality("https://incomecanvas.com/tools/aca-calculator/", compliant_html)
    assert res.passed is True
    assert res.math_checks_passed == 3

    # Non-compliant HTML: missing 2026 repayment sunset invariant
    non_compliant_html = """
    <html>
    <body>
        <h1>ACA Calculator</h1>
        <p>Repayment limitation caps limit repayment to $1,500.</p>
        <p>130 hours per month full-time. 120 hours divisor.</p>
    </body>
    </html>
    """
    res_bad = verify_calculator_functionality("https://incomecanvas.com/tools/aca-calculator/", non_compliant_html)
    assert res_bad.passed is False
    assert any("Repayment Cap Invariant Failure" in err for err in res_bad.issues)


def test_verify_calculator_section_179_caps():
    """Section 179 calculator checks 2026 statutory limits: $1,250,000 cap & $3,130,000 phaseout."""
    valid_sec179 = """
    <html>
    <body>
        <h1>Section 179 Depreciation Calculator</h1>
        <p>2026 Maximum Deduction Cap: $1,250,000. Phaseout begins at $3,130,000.</p>
        <p>Dollar-for-dollar reduction formula: deduction = Math.max(0, cap - (cost - phaseout)).</p>
    </body>
    </html>
    """
    res = verify_calculator_functionality("https://incomecanvas.com/tools/section-179-calculator/", valid_sec179)
    assert res.passed is True

    bad_sec179 = "<html><body><h1>Section 179</h1><p>Deduction cap is $1,000,000.</p></body></html>"
    res_bad = verify_calculator_functionality("https://incomecanvas.com/tools/section-179-calculator/", bad_sec179)
    assert res_bad.passed is False
    assert any("Section 179 Cap Invariant Failure" in err for err in res_bad.issues)


def test_verify_smsriver_active_inventory():
    """SMSRiver checks active number table and message polling listener."""
    valid_sms = """
    <html>
    <body>
        <h1>Receive SMS Online Free</h1>
        <table class="number-grid">
            <tr><td>US</td><td>+1 (202) 555-0199</td></tr>
        </table>
        <script>
            setInterval(() => fetch('/api/messages/?num=+12025550199'), 3000);
        </script>
    </body>
    </html>
    """
    res = verify_smsriver_functionality("https://smsriver.com/numbers/us/", valid_sms)
    assert res.passed is True

    bad_sms = "<html><body><h1>Receive SMS</h1><p>No numbers available currently.</p></body></html>"
    res_bad = verify_smsriver_functionality("https://smsriver.com/numbers/us/", bad_sms)
    assert res_bad.passed is False
    assert any("SMSRiver Inventory Failure" in err for err in res_bad.issues)


def test_technical_seo_gate_10_integration():
    """verify_technical_seo Gate 10 fails if a converter page lacks functional conversion logic."""
    bad_converter_html = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="utf-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <title>Convert STEP to STL Online — OpenFile</title>
        <meta name="description" content="Convert STEP 3D CAD files to STL mesh online with high fidelity." />
        <link rel="canonical" href="https://openfileconverter.com/convert/step-to-stl/" />
    </head>
    <body>
        <h1>Convert STEP to STL</h1>
        <p>This is placeholder content without any converter tool.</p>
    </body>
    </html>
    """
    report = audit_html_technical_seo("https://openfileconverter.com/convert/step-to-stl/", bad_converter_html, status_code=200)
    assert report.all_passed is False
    assert any(g.name == "functional_product_utility" and not g.passed for g in report.gates)


# =============================================================================
# 4. Multi-Dimensional Query Ownership & SERP Jaccard Overlap (P1)
# =============================================================================

def test_calculate_serp_jaccard_overlap():
    """SERP Jaccard overlap >= 0.50 identifies identical search intent."""
    top10_a = [f"https://domain.com/page-{i}" for i in range(10)]
    # Exactly 5 shared URLs out of 15 total unique URLs -> 5/15 = 0.333
    top10_b = [f"https://domain.com/page-{i}" for i in range(5, 15)]
    overlap = calculate_serp_jaccard_overlap(top10_a, top10_b)
    assert pytest.approx(overlap, 0.01) == 0.333

    # 7 shared out of 13 unique -> 7/13 = 0.538 (>= 0.50 identical intent)
    top10_c = [f"https://domain.com/page-{i}" for i in range(3, 13)]
    overlap_high = calculate_serp_jaccard_overlap(top10_a, top10_c)
    assert overlap_high >= 0.50


def test_classify_cannibalization_risk_harmless_dual_ranking():
    """Both pages in top 5 with stable CTR is classified as HARMLESS_DUAL_RANKING."""
    risk_class, score, rationale = classify_cannibalization_risk(
        serp_overlap=0.60,
        lexical_overlap=0.85,
        intent_a="tool",
        intent_b="tool",
        page_a_position=2.1,
        page_b_position=4.0,
        ctr_drop_pct=0.05,
    )
    assert risk_class == "HARMLESS_DUAL_RANKING"
    assert score == 0.05
    assert "top 5" in rationale


def test_classify_cannibalization_risk_confirmed_competition():
    """Identical intent with CTR drop > 25% is classified as CONFIRMED_COMPETITION."""
    risk_class, score, rationale = classify_cannibalization_risk(
        serp_overlap=0.65,
        lexical_overlap=0.90,
        intent_a="tool",
        intent_b="tool",
        ctr_drop_pct=0.35,
    )
    assert risk_class == "CONFIRMED_COMPETITION"
    assert score == 0.85


# =============================================================================
# 5. 3-Tier Hierarchical Bayesian Fleet Learning (P1)
# =============================================================================

def test_three_tier_hierarchical_priors(temp_db: sqlite3.Connection):
    """3-tier hierarchical structure: Tier 1 global -> Tier 2 property -> Tier 3 position-stratified."""
    # Tier 1 Global fallback when no data exists
    eff_global = get_action_effectiveness(temp_db, "figiva.com", "ACTION_UNKNOWN", "root")
    assert eff_global["hierarchy_tier"] == "tier_1_global_prior"
    assert eff_global["smoothed_win_rate"] == 0.30

    # Seed property data (Tier 2)
    for _ in range(5):
        record_action_effectiveness(
            temp_db,
            domain="openfileconverter.com",
            action_code="INJECT_EXACT_TITLE_AND_H2",
            route_family="convert",
            position_tier="striking_4_15",
            is_success=True,
        )

    eff_tier3 = get_action_effectiveness(
        temp_db,
        domain="openfileconverter.com",
        action_code="INJECT_EXACT_TITLE_AND_H2",
        route_family="convert",
        position_tier="striking_4_15",
    )
    assert eff_tier3["hierarchy_tier"] == "tier_3_position_stratified"
    assert eff_tier3["total_experiments"] == 5
    assert eff_tier3["win_rate"] == 1.0


def test_immature_experiments_excluded_from_learning(temp_db: sqlite3.Connection):
    """Experiments with < 28 days elapsed remain OBSERVING and are excluded from action effectiveness."""
    now = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)
    deployed_at = now - timedelta(days=12)  # 12 days elapsed (< 28d)

    record_experiment(
        temp_db,
        domain="openfileconverter.com",
        page="https://openfileconverter.com/convert/tiff-to-pdf/",
        target_query="tiff to pdf",
        action_code="CREATE_PROGRAMMATIC_ROUTE",
        deployed_at=deployed_at,
        baseline_clicks_28d=5.0,
        baseline_impressions_28d=200.0,
        control_cohort_page="https://openfileconverter.com/convert/bmp-to-png/",
        control_baseline_clicks=10.0,
    )

    fresh_gsc = {
        "tiff to pdf\nhttps://openfileconverter.com/convert/tiff-to-pdf/": {
            "page": "https://openfileconverter.com/convert/tiff-to-pdf/",
            "clicks": 15.0,
            "impressions": 400.0,
            "position": 4.0,
        }
    }

    outcomes = update_experiment_outcomes(temp_db, "openfileconverter.com", fresh_gsc, now=now)
    assert outcomes["graded"] == 0
    assert outcomes["observing"] == 1

    # Learning stats not populated
    eff = get_action_effectiveness(temp_db, "openfileconverter.com", "CREATE_PROGRAMMATIC_ROUTE", "convert")
    assert eff["has_empirical_evidence"] is False
