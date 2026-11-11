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
import subprocess
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
    """Degrees of freedom critical values apply for control cohorts N_c with df = N_c - 1 (v2.2.1 P0.3)."""
    assert get_t_critical_value(n_controls=31) == 1.960
    assert get_t_critical_value(n_controls=6) == 2.571
    assert get_t_critical_value(n_controls=5) == 2.776
    assert get_t_critical_value(n_controls=4) == 3.182
    assert get_t_critical_value(n_controls=3) == 4.303
    assert get_t_critical_value(n_controls=2) == 12.706
    assert get_t_critical_value(n_controls=1) == 12.706


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
    """Section 179 calculator checks 2026 statutory limits: $2,560,000 cap & $4,090,000 phaseout (v2.2.1 P0.1)."""
    valid_sec179 = """
    <html>
    <body>
        <h1>Section 179 Depreciation Calculator (Tax Year 2026)</h1>
        <p>2026 Maximum Deduction Cap: $2,560,000. Phaseout begins at $4,090,000.</p>
        <p>Qualifying SUV deduction limit is $32,000.</p>
        <p>Dollar-for-dollar reduction formula: deduction = Math.max(0, cap - (cost - phaseout)).</p>
    </body>
    </html>
    """
    res = verify_calculator_functionality("https://incomecanvas.com/tools/section-179-calculator-2026/", valid_sec179)
    assert res.passed is True

    # Stale 2025 limits on 2026 calculator must fail (v2.2.1 P0.1)
    stale_sec179 = """
    <html>
    <body>
        <h1>Section 179 Depreciation Calculator (2026)</h1>
        <p>2026 Maximum Deduction Cap: $1,250,000. Phaseout begins at $3,130,000.</p>
        <p>Deduction formula: reduction = cost - phaseout.</p>
    </body>
    </html>
    """
    res_stale = verify_calculator_functionality("https://incomecanvas.com/tools/section-179-calculator-2026/", stale_sec179)
    assert res_stale.passed is False
    assert any("Section 179 Stale Limit Invariant Failure" in err for err in res_stale.issues)

    bad_sec179 = "<html><body><h1>Section 179</h1><p>Deduction cap is $1,000,000.</p></body></html>"
    res_bad = verify_calculator_functionality("https://incomecanvas.com/tools/section-179-calculator/", bad_sec179)
    assert res_bad.passed is False
    assert any("Section 179" in err for err in res_bad.issues)


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


def test_deployment_arithmetic_reconciliation():
    """Validates that reports cannot claim 100% success when successful paths < total paths."""
    from validate_wave_close import validate_report_content

    # Inconsistent report: claims 36/38 paths (100% 200 OK)
    inconsistent_content = """
# Test Report
## 1. Executive Summary & Two-Part Scorecard
### Part 1: Engineering Execution Quality (Score: 10.0 / 10.0)
| **Category** | 100% | **10.0 / 10** |
### Part 2: Measured SEO & Business Effectiveness
Status: NOT YET MEASURED (Awaiting GSC Recrawl & 28-Day Observation Window)
---
## 2. Reconciled Task Inventory
| Task | Description |
## 3. Strategic Deep-Dive
Deep dive notes.
## 4. Exhaustive File & Configuration Changes
Modified files.
## 5. Standardized Test Classification & Quality Verification
All 20 tests passed.
## 6. Deployment, Edge Cache & Invariant Compliance
**Cloudflare Worker Deployment Version:** `ver-12345`
Edge cache re-warm complete: 36 / 38 paths (100% 200 OK).
## 7. Rollback Runbook & Disaster Recovery
Rollback notes.
## 8. Actionable Recommendations
Recommendations.
"""
    passed, errors, _ = validate_report_content(inconsistent_content, allow_dirty=True)
    assert not passed
    assert any("Deployment Arithmetic Discrepancy" in e for e in errors)

    # Consistent report: 38 / 38 paths (100% 200 OK)
    consistent_content = inconsistent_content.replace("36 / 38 paths (100% 200 OK)", "38 / 38 paths (100% 200 OK)")
    passed2, errors2, _ = validate_report_content(consistent_content, allow_dirty=True)
    assert not any("Deployment Arithmetic Discrepancy" in e for e in errors2)


# =============================================================================
# Outcome-Driven SEO Engine v2.2.1 Tests (Evidence and Statistical Integrity)
# =============================================================================

def test_section_179_mathematical_engine_2025_vs_2026():
    """Validates Section 179 calculations across statutory 2025 and 2026 limits."""
    from verify_product_functionality import calculate_section_179_deduction

    # 2026: max deduction $2,560,000, phaseout threshold $4,090,000, SUV limit $32,000
    # Case 1: Cost below phaseout threshold
    r1 = calculate_section_179_deduction(cost=2_000_000, tax_year=2026)
    assert r1["final_deduction"] == 2_000_000
    assert r1["reduction"] == 0

    # Case 2: Cost above deduction cap, below phaseout threshold
    r2 = calculate_section_179_deduction(cost=3_500_000, tax_year=2026)
    assert r2["final_deduction"] == 2_560_000
    assert r2["reduction"] == 0

    # Case 3: Cost in phaseout zone ($5,000,000):
    # Reduction = 5,000,000 - 4,090,000 = 910,000
    # Available Cap = 2,560,000 - 910,000 = 1,650,000
    r3 = calculate_section_179_deduction(cost=5_000_000, tax_year=2026)
    assert r3["reduction"] == 910_000
    assert r3["available_cap"] == 1_650_000
    assert r3["final_deduction"] == 1_650_000

    # Case 4: Full phaseout ceiling ($6,650,000): deduction = 0
    r4 = calculate_section_179_deduction(cost=6_650_000, tax_year=2026)
    assert r4["available_cap"] == 0
    assert r4["final_deduction"] == 0

    # Case 5: Cost above full phaseout ($7,000,000)
    r5 = calculate_section_179_deduction(cost=7_000_000, tax_year=2026)
    assert r5["final_deduction"] == 0

    # Case 6: Qualifying SUV limit for 2026 ($32,000)
    r6 = calculate_section_179_deduction(cost=90_000, tax_year=2026, is_suv=True)
    assert r6["final_deduction"] == 32_000

    # Case 7: Business income limitation
    r7 = calculate_section_179_deduction(cost=1_000_000, tax_year=2026, business_income=650_000)
    assert r7["final_deduction"] == 650_000
    assert r7["carryforward"] == 350_000
    assert r7["income_limitation_applied"] is True

    # Case 8: 2025 Statutory Limits ($1,250,000 cap, $3,130,000 phaseout, $30,500 SUV)
    r8 = calculate_section_179_deduction(cost=2_000_000, tax_year=2025)
    assert r8["final_deduction"] == 1_250_000

    r9 = calculate_section_179_deduction(cost=80_000, tax_year=2025, is_suv=True)
    assert r9["final_deduction"] == 30_500


def test_aca_excess_aptc_repayment_statutory_engine():
    """Validates 2026 full repayment rule vs 2025 statutory limitation caps."""
    from verify_product_functionality import calculate_aca_excess_aptc_repayment

    # 2026 Invariant: 100% full repayment regardless of FPL percent
    r2026 = calculate_aca_excess_aptc_repayment(excess_aptc=3500.0, household_income_fpl_pct=250.0, tax_year=2026)
    assert r2026["repayment_amount"] == 3500.0
    assert r2026["repayment_cap"] is None

    # 2025 Statutory caps: 250% FPL single has $950 cap
    r2025 = calculate_aca_excess_aptc_repayment(excess_aptc=3500.0, household_income_fpl_pct=250.0, tax_year=2025, filing_status="single")
    assert r2025["repayment_cap"] == 950.0
    assert r2025["repayment_amount"] == 950.0


def test_corporate_wacc_formula_engine():
    """Validates Weighted Average Cost of Capital with interest tax shield."""
    from verify_product_functionality import calculate_wacc

    # Firm: Equity $600k, Debt $400k (V = $1M)
    # Re = 10% (0.10), Rd = 6% (0.06), Tc = 25% (0.25)
    # WACC = 0.6 * 0.10 + 0.4 * 0.06 * (1 - 0.25) = 0.06 + 0.018 = 0.078
    res = calculate_wacc(equity=600_000, debt=400_000, cost_of_equity=0.10, cost_of_debt=0.06, corporate_tax_rate=0.25)
    assert pytest.approx(res["wacc"], 0.0001) == 0.078
    assert res["weight_equity"] == 0.6
    assert res["weight_debt"] == 0.4


def test_figiva_gpa_collegiate_engine():
    """Validates collegiate weighted cumulative GPA scale."""
    from verify_product_functionality import calculate_figiva_gpa

    courses = [
        {"grade": "A", "credits": 4.0},   # 4.0 * 4 = 16.0
        {"grade": "B+", "credits": 3.0},  # 3.3 * 3 = 9.9
        {"grade": "A-", "credits": 3.0},  # 3.7 * 3 = 11.1
    ]
    # Total points = 37.0, Total credits = 10.0 -> GPA = 3.70
    res = calculate_figiva_gpa(courses)
    assert res["total_credits"] == 10.0
    assert pytest.approx(res["cumulative_gpa"], 0.001) == 3.70


def test_execute_converter_pipeline():
    """Validates genuine byte conversion and magic byte inspection."""
    import struct
    from verify_product_functionality import execute_converter_pipeline

    # BMP to PNG
    mock_bmp = b"BM" + struct.pack("<IHHI", 58, 0, 0, 54) + struct.pack("<IIIHHIIIIII", 40, 1, 1, 1, 24, 0, 4, 2835, 2835, 0, 0) + b"\x00\x00\x00\x00"
    png_bytes = execute_converter_pipeline("bmp", "png", mock_bmp)
    assert png_bytes.startswith(b"\x89PNG\r\n\x1a\n")

    # STEP to STL
    mock_step = b"ISO-10303-21;\nHEADER;\nFILE_DESCRIPTION(('STEP'),'2;1');\nENDSEC;\nDATA;\nENDSEC;\nEND-ISO-10303-21;\n"
    stl_bytes = execute_converter_pipeline("step", "stl", mock_step)
    assert b"solid openfileconverter_mesh" in stl_bytes

    # DOCX to PDF
    mock_docx = b"PK\x03\x04" + (b"\x00" * 26)
    pdf_bytes = execute_converter_pipeline("docx", "pdf", mock_docx)
    assert pdf_bytes.startswith(b"%PDF-1.4")

    # Malformed BMP input
    with pytest.raises(ValueError, match="missing 'BM'"):
        execute_converter_pipeline("bmp", "png", b"NOT_BMP_DATA")


def test_smsriver_operational_pipeline():
    """Validates E.164 phone verification and JSON message polling structure."""
    from verify_product_functionality import verify_smsriver_operational_pipeline

    payload = {
        "messages": [
            {"from": "WhatsApp", "text": "Your code is 849201", "timestamp": "2026-11-11T12:00:00Z"},
            {"from": "Google", "text": "G-123456 is your verification code", "timestamp": "2026-11-11T12:01:00Z"},
        ]
    }
    res = verify_smsriver_operational_pipeline("+12025550199", payload)
    assert res["is_e164"] is True
    assert res["active_messages_count"] == 2
    assert res["messages"][0]["extracted_otp"] == "849201"
    assert res["messages"][1]["extracted_otp"] == "123456"

    with pytest.raises(ValueError, match="Invalid E.164"):
        verify_smsriver_operational_pipeline("invalid_number", payload)


def test_ev_decomposition_arithmetic():
    """Validates that compute_opportunity_intelligence provides full arithmetic EV derivation."""
    from score_backlog import EconomicConfig, compute_opportunity_intelligence

    row = {
        "page": "https://openfileconverter.com/convert/step-to-stl/",
        "query": "step to stl converter",
        "prescribed_action": "CREATE_PROGRAMMATIC_ROUTE",
        "impressions": 1000.0,
        "clicks_30d": 10.0,
        "features": {"current_pos": 8.0},
    }
    cfg = EconomicConfig(labor_hourly_rate=60.0, value_per_conversion=15.0)
    intel = compute_opportunity_intelligence(row, config=cfg)

    assert "ev_decomposition" in intel
    decomp = intel["ev_decomposition"]
    assert decomp["labor_hours"] == 2.5
    assert decomp["labor_hourly_rate"] == 60.0
    assert decomp["implementation_labor_cost"] == 150.0  # 2.5 * 60
    assert decomp["value_per_conversion"] == 15.0
    # Net EV formula: (p_success * gross_val) - impl_cost - risk_cost
    expected_ev = (decomp["posterior_success_probability"] * decomp["gross_business_value"]) - decomp["implementation_labor_cost"] - decomp["expected_risk_cost"]
    assert pytest.approx(decomp["net_expected_value"], 0.01) == expected_ev


def test_brier_skill_score_and_sample_size_verdict(temp_db: sqlite3.Connection):
    """Validates that Brier Skill Score > 0 and N >= 20 are required for WELL_CALIBRATED status."""
    from score_backlog import evaluate_temporal_holdout_calibration

    # Clean ledger
    temp_db.execute("DELETE FROM experiment_ledger")
    now = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)

    # Seed 10 experiments (N < 20)
    for i in range(10):
        is_succ = (i % 2 == 0)
        exp_id = record_experiment(
            temp_db,
            domain="openfileconverter.com",
            page=f"https://openfileconverter.com/page-{i}/",
            target_query=f"query {i}",
            action_code="INJECT_EXACT_TITLE_AND_H2",
            deployed_at=now,
            baseline_clicks_28d=5.0,
            baseline_impressions_28d=100.0,
            control_cohort_page="https://openfileconverter.com/ctrl/",
            control_baseline_clicks=5.0,
        )
        temp_db.execute(
            """
            UPDATE experiment_ledger
            SET status = 'GRADED', did_outcome_class = ?, post_28d_clicks = ?
            WHERE id = ?
            """,
            ("STATISTICALLY_SIGNIFICANT_LIFT" if is_succ else "NEUTRAL_NO_EFFECT", 10.0 if is_succ else 5.0, exp_id),
        )
    temp_db.commit()

    # N = 10 should yield INSUFFICIENT_SAMPLE_SIZE_FOR_CALIBRATION
    res_10 = evaluate_temporal_holdout_calibration(temp_db, domain="openfileconverter.com", min_sample_size=20)
    assert res_10["sample_size"] == 10
    assert "INSUFFICIENT_SAMPLE_SIZE_FOR_CALIBRATION" in res_10["verdict"]

    # Seed 15 more experiments -> N = 25 (N >= 20)
    for i in range(10, 25):
        is_succ = (i % 3 == 0)
        exp_id = record_experiment(
            temp_db,
            domain="openfileconverter.com",
            page=f"https://openfileconverter.com/page-{i}/",
            target_query=f"query {i}",
            action_code="INJECT_EXACT_TITLE_AND_H2",
            deployed_at=now,
            baseline_clicks_28d=5.0,
            baseline_impressions_28d=100.0,
            control_cohort_page="https://openfileconverter.com/ctrl/",
            control_baseline_clicks=5.0,
        )
        temp_db.execute(
            """
            UPDATE experiment_ledger
            SET status = 'GRADED', did_outcome_class = ?, post_28d_clicks = ?
            WHERE id = ?
            """,
            ("STATISTICALLY_SIGNIFICANT_LIFT" if is_succ else "NEUTRAL_NO_EFFECT", 12.0 if is_succ else 5.0, exp_id),
        )
    temp_db.commit()

    res_25 = evaluate_temporal_holdout_calibration(temp_db, domain="openfileconverter.com", min_sample_size=20)
    assert res_25["sample_size"] == 25
    assert "brier_skill_score" in res_25
    assert "baseline_brier_score" in res_25
    assert "calibration_intercept" in res_25
    assert "calibration_slope" in res_25
    assert res_25["verdict"] in ("WELL_CALIBRATED", "NEEDS_CALIBRATION")


def test_determine_canonical_outcome():
    """Validates reconciliation of DiD causal intervals and commercial thresholds."""
    from score_backlog import determine_canonical_outcome

    # Statistically significant lift
    out1 = determine_canonical_outcome(
        did_outcome_class="STATISTICALLY_SIGNIFICANT_LIFT",
        baseline_clicks=10.0,
        post_clicks=20.0,
        ci_lower=0.10,
        ci_upper=0.50,
        min_incremental_clicks=2.0,
    )
    assert out1 == "STATISTICALLY_SIGNIFICANT_LIFT"

    # Statistically significant drop
    out2 = determine_canonical_outcome(
        did_outcome_class="STATISTICALLY_SIGNIFICANT_DROP",
        baseline_clicks=20.0,
        post_clicks=10.0,
        ci_lower=-0.60,
        ci_upper=-0.10,
        min_incremental_clicks=2.0,
    )
    assert out2 == "STATISTICALLY_SIGNIFICANT_DROP"

    # Commercially negligible lift (small gain < 2.0 clicks)
    out3 = determine_canonical_outcome(
        did_outcome_class="COMMERCIALLY_NEGLIGIBLE_LIFT",
        baseline_clicks=5.0,
        post_clicks=6.2,
        ci_lower=0.01,
        ci_upper=0.30,
        min_incremental_clicks=2.0,
    )
    assert out3 == "COMMERCIALLY_NEGLIGIBLE_LIFT"


def test_event_study_parallel_trends():
    """Validates multi-period event study parallel trends diagnostic."""
    from fleet_state import check_event_study_parallel_trends

    # Parallel growth: treatment and control grow ~10% each period
    t_counts = [100.0, 110.0, 121.0, 133.0]
    c_counts = [200.0, 220.0, 242.0, 266.0]
    res_parallel = check_event_study_parallel_trends(t_counts, c_counts, divergence_threshold=0.30)
    assert res_parallel["parallel_trends_hold"] is True
    assert res_parallel["max_divergence"] < 0.05
    assert res_parallel["periods_evaluated"] == 4

    # Divergent growth: treatment spikes 50% while control drops
    t_divergent = [100.0, 150.0, 220.0]
    c_divergent = [200.0, 190.0, 180.0]
    res_div = check_event_study_parallel_trends(t_divergent, c_divergent, divergence_threshold=0.30)
    assert res_div["parallel_trends_hold"] is False
    assert res_div["max_divergence"] > 0.30


def test_validate_wave_close_waiver_reason(tmp_path: Path):
    """Validates that --allow-dirty requires an explicit waiver reason when dirty files exist."""
    import subprocess
    from validate_wave_close import validate_report_content

    # Valid report markdown
    report = """
# Test Report
## 1. Executive Summary & Two-Part Scorecard
### Part 1: Engineering Execution Quality (Score: 10.0 / 10.0)
| **Category** | 100% | **10.0 / 10** |
### Part 2: Measured SEO & Business Effectiveness
Status: NOT YET MEASURED (Awaiting GSC Recrawl & 28-Day Observation Window)
---
## 2. Reconciled Task Inventory
| Task | Description |
## 3. Strategic Deep-Dive
Deep dive notes.
## 4. Exhaustive File & Configuration Changes
Modified files.
## 5. Standardized Test Classification & Quality Verification
| Test Suite | Passed | Failed | Skipped | Total |
| Unit Tests | 25 | 0 | 0 | 25 |
All 25 tests passed.
## 6. Deployment, Edge Cache & Invariant Compliance
**Cloudflare Worker Deployment Version:** `ver-12345`
Edge cache re-warm complete: 10 / 10 paths (100% 200 OK).
## 7. Rollback Runbook & Disaster Recovery
Rollback notes.
## 8. Actionable Recommendations
Recommendations.
"""
    # Create fake git repo with a dirty file
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Tester"], cwd=repo, capture_output=True)
    (repo / "f.txt").write_text("initial")
    subprocess.run(["git", "add", "f.txt"], cwd=repo, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, capture_output=True)

    # Make it dirty
    (repo / "f.txt").write_text("modified")

    # allow_dirty=True without waiver reason -> must fail
    passed1, errors1, _ = validate_report_content(report, repo_path=repo, allow_dirty=True, waiver_reason=None)
    assert not passed1
    assert any("Waiver requirement violation" in e for e in errors1)

    # allow_dirty=True with waiver reason -> passes with warning listing dirty file
    passed2, errors2, warnings2 = validate_report_content(report, repo_path=repo, allow_dirty=True, waiver_reason="Waiver for ongoing TDD tests")
    assert passed2
    assert any("Worktree waiver applied" in w for w in warnings2)


