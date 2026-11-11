"""tests/test_v21_refinements_tdd.py - Comprehensive TDD Suite for Outcome Engine v2.1.

Verifies:
1. Recrawl Proof vs. GSC Impression Exposure (P0)
2. Calibrated Bayesian Economic Expected Value (EV) (P0)
3. Difference-in-Differences (DiD) Statistical Safeguards (P0)
4. Multi-Dimensional Query Ownership & Risk Scoring (P1)
5. Boilerplate Stripping & Page-Type Depth in Content Gate (P1)
6. Authority Claim Recognition for Regulatory / Technical Specs (P1)
7. Technical SEO 10-Point Gate & Soft-404 Detection (P1)
8. Uncertainty-Aware Beta-Binomial Fleet Learning (P1)
"""

from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

# Ensure scripts dir is on sys.path
SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from content_usefulness_gate import (
    _strip_boilerplate,
    compute_shingle_distinctiveness,
    verify_content_usefulness,
)
from evaluate_experiments import evaluate_domain_experiments
from fleet_state import (
    connect_state_db,
    get_action_effectiveness,
    get_query_owner,
    record_action_effectiveness,
    record_experiment,
    record_gsc_exposure,
    update_experiment_outcomes,
    update_experiment_recrawl,
    upsert_query_ownership,
)
from score_backlog import compute_opportunity_intelligence
from verify_technical_seo import audit_html_technical_seo


@pytest.fixture
def temp_db(tmp_path: Path) -> sqlite3.Connection:
    db_path = tmp_path / "fleet_test_v21.db"
    conn = connect_state_db(str(db_path))
    return conn


# -----------------------------------------------------------------------------
# 1. Recrawl Proof vs. GSC Impression Exposure (P0)
# -----------------------------------------------------------------------------

def test_gsc_exposure_does_not_confirm_recrawl(temp_db: sqlite3.Connection):
    """Impressions from Google's cache must NOT be treated as proof of Googlebot recrawl."""
    dep_time = datetime(2026, 10, 1, 10, 0, tzinfo=timezone.utc)
    now_time = datetime(2026, 10, 2, 12, 0, tzinfo=timezone.utc)

    record_experiment(
        temp_db,
        task_id=101,
        domain="openfileconverter.com",
        page="https://openfileconverter.com/convert/las-to-xyz/",
        target_query="las to xyz converter",
        action_code="CREATE_PROGRAMMATIC_ROUTE",
        deployed_at=dep_time,
        baseline_clicks_28d=0.0,
        baseline_impressions_28d=0.0,
    )

    # Fresh GSC shows impressions, but Googlebot has NOT recrawled yet
    exposed = record_gsc_exposure(
        temp_db,
        domain="openfileconverter.com",
        exposed_pages={"https://openfileconverter.com/convert/las-to-xyz/"},
        now=now_time,
    )
    assert exposed == 1

    cur = temp_db.execute(
        "SELECT status, exposure_detected_at, recrawl_confirmed_at FROM experiment_ledger WHERE task_id = 101"
    )
    status, exp_at, recrawl_at = cur.fetchone()
    # Must remain CRAWL_PENDING
    assert status == "CRAWL_PENDING"
    assert exp_at is not None
    assert recrawl_at is None


def test_url_inspection_confirms_recrawl(temp_db: sqlite3.Connection):
    """Verified URL inspection lastCrawlTime > deployed_at transitions state to RECRAWL_CONFIRMED."""
    dep_time = datetime(2026, 10, 1, 10, 0, tzinfo=timezone.utc)
    crawl_time = datetime(2026, 10, 3, 14, 30, tzinfo=timezone.utc)

    record_experiment(
        temp_db,
        task_id=102,
        domain="openfileconverter.com",
        page="https://openfileconverter.com/convert/step-to-stl/",
        target_query="convert step to stl",
        action_code="INJECT_EXACT_TITLE_AND_H2",
        deployed_at=dep_time,
    )

    confirmed = update_experiment_recrawl(
        temp_db,
        domain="openfileconverter.com",
        recrawled_pages={"https://openfileconverter.com/convert/step-to-stl/": {"lastCrawlTime": crawl_time.isoformat(), "verdict": "PASS"}},
        evidence_type="url_inspection",
        now=crawl_time,
    )
    assert confirmed == 1

    cur = temp_db.execute(
        "SELECT status, recrawl_confirmed_at, recrawl_evidence_type FROM experiment_ledger WHERE task_id = 102"
    )
    status, recrawl_at, ev_type = cur.fetchone()
    assert status == "RECRAWL_CONFIRMED"
    assert recrawl_at is not None
    assert ev_type == "url_inspection"


# -----------------------------------------------------------------------------
# 2. Calibrated Bayesian Economic Expected Value (EV) (P0)
# -----------------------------------------------------------------------------

def test_calibrated_bayesian_expected_value(temp_db: sqlite3.Connection):
    """Verifies that Bayesian EV penalizes tail ranks and discounts via empirical win-rates and costs."""
    # Striking distance (pos 8.0) tool query vs Deep tail (pos 45.0) query
    striking_task = {
        "domain": "openfileconverter.com",
        "page": "https://openfileconverter.com/convert/psd-to-png/",
        "query": "psd to png converter",
        "action_code": "CREATE_PROGRAMMATIC_ROUTE",
        "clicks": 10.0,
        "impressions": 1200.0,
        "position": 8.0,
        "ctr": 0.0083,
    }
    tail_task = {
        "domain": "openfileconverter.com",
        "page": "https://openfileconverter.com/convert/obscure-format/",
        "query": "obscure format converter",
        "action_code": "CREATE_PROGRAMMATIC_ROUTE",
        "clicks": 0.0,
        "impressions": 50.0,
        "position": 45.0,
        "ctr": 0.0,
    }

    # Register high win-rate for CREATE_PROGRAMMATIC_ROUTE in fleet_state
    record_action_effectiveness(
        temp_db,
        domain="openfileconverter.com",
        action_code="CREATE_PROGRAMMATIC_ROUTE",
        route_family="convert",
        is_success=True,
        click_lift=0.45,
        impression_lift=0.60,
        rank_delta=3.0,
    )

    scored_striking = compute_opportunity_intelligence(striking_task, conn=temp_db)
    scored_tail = compute_opportunity_intelligence(tail_task, conn=temp_db)

    # Striking distance should have significantly higher EV and success probability
    assert scored_striking["expected_value"] > scored_tail["expected_value"]
    assert scored_striking["confidence"] > scored_tail["confidence"]
    # Striking position (8.0) yields higher rank probability than position 45.0
    assert scored_striking["decision_class"] == "SHIP"
    assert scored_tail["decision_class"] == "OBSERVE"


# -----------------------------------------------------------------------------
# 3. Difference-in-Differences (DiD) Statistical Safeguards (P0)
# -----------------------------------------------------------------------------

def test_did_statistical_safeguards_cohort_size_and_parallel_trends(temp_db: sqlite3.Connection):
    """Verifies that DiD flags INSUFFICIENT_EVIDENCE if control cohort size < 3 or parallel trends fail."""
    dep_time = datetime(2026, 9, 1, 10, 0, tzinfo=timezone.utc)
    eval_time = datetime(2026, 10, 5, 10, 0, tzinfo=timezone.utc)  # > 28 days

    # Exp 1: Insufficient controls (< 3)
    record_experiment(
        temp_db,
        task_id=201,
        domain="openfileconverter.com",
        page="https://openfileconverter.com/convert/epub-to-pdf/",
        target_query="epub to pdf",
        action_code="INJECT_SECONDARY_H2_ONLY",
        deployed_at=dep_time,
        baseline_clicks_28d=10.0,
        baseline_impressions_28d=500.0,
        control_cohort_page="https://openfileconverter.com/convert/mobi-to-pdf/",
        control_baseline_clicks=10.0,
    )

    fresh_gsc = {
        "epub to pdf\nhttps://openfileconverter.com/convert/epub-to-pdf/": {
            "page": "https://openfileconverter.com/convert/epub-to-pdf/",
            "query": "epub to pdf",
            "clicks": 25.0,
            "impressions": 800.0,
            "position": 4.0,
        },
        "mobi to pdf\nhttps://openfileconverter.com/convert/mobi-to-pdf/": {
            "page": "https://openfileconverter.com/convert/mobi-to-pdf/",
            "query": "mobi to pdf",
            "clicks": 11.0,
            "impressions": 520.0,
            "position": 5.0,
        },
    }

    update_experiment_outcomes(temp_db, "openfileconverter.com", fresh_gsc, days_elapsed=34, now=eval_time)

    cur = temp_db.execute(
        "SELECT did_outcome_class, attribution_limitations, attribution_confidence FROM experiment_ledger WHERE task_id = 201"
    )
    outcome_class, limitations, conf = cur.fetchone()
    assert outcome_class == "INSUFFICIENT_EVIDENCE"
    assert "Control cohort size (1) < 3" in limitations
    assert conf <= 0.40


def test_did_excludes_contaminated_controls(temp_db: sqlite3.Connection):
    """Control URLs modified post-treatment are contaminated and must be filtered out."""
    dep_time = datetime(2026, 9, 1, 10, 0, tzinfo=timezone.utc)
    eval_time = datetime(2026, 10, 5, 10, 0, tzinfo=timezone.utc)

    # Treatment URL
    record_experiment(
        temp_db,
        task_id=301,
        domain="openfileconverter.com",
        page="https://openfileconverter.com/convert/flac-to-mp3/",
        target_query="flac to mp3",
        action_code="CREATE_PROGRAMMATIC_ROUTE",
        deployed_at=dep_time,
        baseline_clicks_28d=5.0,
        control_cohort_page="https://openfileconverter.com/convert/wav-to-mp3/",
        control_baseline_clicks=8.0,
    )

    # Simulate that wav-to-mp3 was also deployed as an experiment AFTER flac-to-mp3 (making it contaminated)
    record_experiment(
        temp_db,
        task_id=302,
        domain="openfileconverter.com",
        page="https://openfileconverter.com/convert/wav-to-mp3/",
        target_query="wav to mp3",
        action_code="CREATE_PROGRAMMATIC_ROUTE",
        deployed_at=datetime(2026, 9, 15, 10, 0, tzinfo=timezone.utc),
        baseline_clicks_28d=8.0,
    )

    fresh_gsc = {
        "flac to mp3\nhttps://openfileconverter.com/convert/flac-to-mp3/": {
            "page": "https://openfileconverter.com/convert/flac-to-mp3/",
            "query": "flac to mp3",
            "clicks": 20.0,
            "impressions": 900.0,
            "position": 3.0,
        },
        "wav to mp3\nhttps://openfileconverter.com/convert/wav-to-mp3/": {
            "page": "https://openfileconverter.com/convert/wav-to-mp3/",
            "query": "wav to mp3",
            "clicks": 30.0,
            "impressions": 1100.0,
            "position": 2.5,
        },
    }

    update_experiment_outcomes(temp_db, "openfileconverter.com", fresh_gsc, days_elapsed=34, now=eval_time)

    cur = temp_db.execute(
        "SELECT attribution_limitations FROM experiment_ledger WHERE task_id = 301"
    )
    limitations = cur.fetchone()[0]
    # Since wav-to-mp3 is contaminated, valid controls count is 0 < 3
    assert "Control cohort size (0) < 3" in limitations


# -----------------------------------------------------------------------------
# 4. Multi-Dimensional Query Ownership & Risk Scoring (P1)
# -----------------------------------------------------------------------------

def test_multidimensional_query_ownership(temp_db: sqlite3.Connection):
    """Queries with distinct intents mapping to the same route family are classified as DISTINCT_INTENT."""
    # Register existing page for conversion
    upsert_query_ownership(
        temp_db,
        domain="openfileconverter.com",
        query_cluster="las converter online",
        canonical_url="https://openfileconverter.com/convert/las-to-xyz/",
        primary_query="las converter online",
        secondary_queries=["convert las to xyz", "las file converter"],
        intent_category="tool",
    )

    # Query 1: Exact overlap on same URL -> OWNED
    res_owned = get_query_owner(
        temp_db,
        domain="openfileconverter.com",
        query="las converter online",
        candidate_page="https://openfileconverter.com/convert/las-to-xyz/",
    )
    assert res_owned is not None
    assert res_owned["ownership_risk_classification"] == "OWNED"
    assert res_owned["cannibalization_risk"] == 0.0

    # Query 2: Distinct intent ("las viewer" vs "las converter") -> DISTINCT_INTENT, low risk
    res_distinct = get_query_owner(
        temp_db,
        domain="openfileconverter.com",
        query="las converter online",
        candidate_page="https://openfileconverter.com/view/las/",
        candidate_intent="viewer",
    )
    assert res_distinct is not None
    assert res_distinct["ownership_risk_classification"] == "DISTINCT_INTENT"
    assert res_distinct["cannibalization_risk"] <= 0.15

    # Query 3: Competing candidate for the same intent on an unowned URL -> CONFIRMED_COMPETITION
    res_competing = get_query_owner(
        temp_db,
        domain="openfileconverter.com",
        query="las converter online",
        candidate_page="https://openfileconverter.com/tools/las-convert/",
        candidate_intent="tool",
    )
    assert res_competing is not None
    assert res_competing["ownership_risk_classification"] == "CONFIRMED_COMPETITION"
    assert res_competing["cannibalization_risk"] >= 0.80


# -----------------------------------------------------------------------------
# 5. Boilerplate Stripping & Page-Type Depth in Content Gate (P1)
# -----------------------------------------------------------------------------

def test_boilerplate_stripping_and_shingle_distinctiveness():
    """Boilerplate elements (<header>, <nav>, <footer>) must be stripped before distinctiveness scoring."""
    boilerplate = """
    <header><nav><a href='/'>Home</a><a href='/about'>About</a><a href='/contact'>Contact</a></nav></header>
    <footer><p>Copyright 2026 OpenFileConverter. Privacy Policy. Terms of Service.</p></footer>
    """
    page1 = f"""
    <html><body>
    {boilerplate}
    <main>
        <h1>Convert DOCX to PDF</h1>
        <p>Convert your Word documents to standard PDF/A format directly in the browser.</p>
        <div id='dropzone'>Drop file here</div>
    </main>
    </body></html>
    """
    page2 = f"""
    <html><body>
    {boilerplate}
    <main>
        <h1>Convert XLSX to CSV</h1>
        <p>Extract spreadsheet tables into comma-separated values format securely client-side.</p>
        <div id='dropzone'>Drop file here</div>
    </main>
    </body></html>
    """

    stripped1 = _strip_boilerplate(page1)
    stripped2 = _strip_boilerplate(page2)

    assert "Privacy Policy" not in stripped1
    assert "Home" not in stripped1
    assert "Convert DOCX to PDF" in stripped1

    dist = compute_shingle_distinctiveness(stripped1, [stripped2])
    # Stripped main content should have healthy distinctiveness (> 0.20)
    assert dist > 0.20


def test_tool_page_type_specific_content_depth():
    """Interactive tool pages with dropzone require only 40 words, not editorial 200 words."""
    tool_html = """
    <html><body>
        <h1>TIFF to PDF Converter</h1>
        <div id="dropzone" class="file-drop">
            <input type="file" id="file-input" />
            <button id="convert-btn">Convert Now</button>
        </div>
        <p>Convert multi-page TIFF image archives to standard PDF documents client-side using WebAssembly.
           All image rendering runs locally in your browser isolate with zero cloud data transmission.
           Preserves original resolution, compression tags, and color profiles without quality degradation.</p>
    </body></html>
    """
    report = verify_content_usefulness(
        tool_html,
        target_query="tiff to pdf converter",
        page_url="https://openfileconverter.com/convert/tiff-to-pdf/",
    )
    # 47 words + functional inputs -> valid tool page
    assert report.is_valid is True
    assert report.page_archetype == "tool"
    assert report.score >= 8.0


# -----------------------------------------------------------------------------
# 6. Authority Claim Recognition for Regulatory & Technical Specs (P1)
# -----------------------------------------------------------------------------

def test_regulatory_and_technical_authority_claims():
    """Recognizes IRS, IRC, CFR, and ISO technical standards in authority claim verification."""
    financial_html = """
    <html><body>
        <h1>Section 179 Depreciation Calculator</h1>
        <p>Under IRS Section 179 and Internal Revenue Code IRC 168(k), businesses can deduct the full purchase
           price of qualifying equipment for tax year 2026 up to the inflation-adjusted cap. Governed by 26 CFR 1.179
           regulations across US federal tax jurisdictions for commercial assets.</p>
        <div id="calculator-form">
            <input type="number" id="cost" placeholder="Asset cost" />
            <button id="calc-btn">Calculate Deduction</button>
        </div>
    </body></html>
    """
    evidence = {
        "Section 179": "IRS Publication 946 (2026)",
        "IRC 168": "26 U.S. Code § 168",
        "tax year 2026": "IRS Revenue Procedure 2025-32",
    }
    report = verify_content_usefulness(
        financial_html,
        target_query="section 179 depreciation calculator",
        page_url="https://incomecanvas.com/calculator/section-179/",
        claim_evidence_ledger=evidence,
    )
    assert report.is_valid is True
    assert len(report.verified_claims) >= 2


# -----------------------------------------------------------------------------
# 7. Technical SEO 10-Point Gate & Soft-404 Detection (P1)
# -----------------------------------------------------------------------------

def test_soft_404_detection_on_http_200():
    """HTTP 200 containing soft-404 signatures must fail the technical SEO gate."""
    soft_404_html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Page Not Found - OpenFileConverter</title>
        <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    </head>
    <body>
        <h1>Error 404: File or Route Not Found</h1>
        <p>The tool or conversion route you requested does not exist or has been removed.</p>
    </body>
    </html>
    """
    report = audit_html_technical_seo(
        url="https://openfileconverter.com/convert/nonexistent-route/",
        html=soft_404_html,
        status_code=200,
    )
    assert report.all_passed is False
    assert any("Soft 404" in err for err in report.errors)


def test_title_pixel_width_over_580_is_advisory_warning():
    """Title exceeding 580px produces an advisory warning, not a fatal failure."""
    long_title = "Convert High-Definition STEP 3D CAD Geometry Models to STL Mesh Online — OpenFile"
    valid_tool_html = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <title>{long_title}</title>
        <meta name="viewport" content="width=device-width, initial-scale=1.0" />
        <link rel="canonical" href="https://openfileconverter.com/convert/step-to-stl/" />
    </head>
    <body>
        <h1>Convert STEP to STL</h1>
        <div id="dropzone"><input type="file" /><button>Convert</button></div>
        <p>Client-side 3D model converter running in WebAssembly. Securely convert CAD boundary representation to polygon meshes directly in the browser with zero cloud storage.</p>
        <nav>
            <a href="/convert/stl-to-step/">STL to STEP</a>
            <a href="/compare/step-vs-stl/">STEP vs STL Comparison</a>
        </nav>
    </body>
    </html>
    """
    report = audit_html_technical_seo(
        url="https://openfileconverter.com/convert/step-to-stl/",
        html=valid_tool_html,
        status_code=200,
    )
    # Passed should be True because title pixel width > 580px is advisory warning
    assert report.all_passed is True
    assert any("Title display width" in w for w in report.warnings)


# -----------------------------------------------------------------------------
# 8. Uncertainty-Aware Beta-Binomial Fleet Learning (P1)
# -----------------------------------------------------------------------------

def test_beta_binomial_smoothing_penalizes_small_samples(temp_db: sqlite3.Connection):
    """Small sample size (4/5 = 80%) has lower confidence-weighted effectiveness than high evidence (60/100 = 60%)."""
    # Action A: 4 successes out of 5 experiments (80% raw win-rate, small sample)
    for _ in range(4):
        record_action_effectiveness(
            temp_db,
            domain="openfileconverter.com",
            action_code="ACTION_SMALL_SAMPLE",
            route_family="convert",
            is_success=True,
        )
    record_action_effectiveness(
        temp_db,
        domain="openfileconverter.com",
        action_code="ACTION_SMALL_SAMPLE",
        route_family="convert",
        is_success=False,
    )

    # Action B: 60 successes out of 100 experiments (60% raw win-rate, high sample)
    for _ in range(60):
        record_action_effectiveness(
            temp_db,
            domain="openfileconverter.com",
            action_code="ACTION_HIGH_EVIDENCE",
            route_family="convert",
            is_success=True,
        )
    for _ in range(40):
        record_action_effectiveness(
            temp_db,
            domain="openfileconverter.com",
            action_code="ACTION_HIGH_EVIDENCE",
            route_family="convert",
            is_success=False,
        )

    eff_small = get_action_effectiveness(temp_db, "openfileconverter.com", "ACTION_SMALL_SAMPLE", "convert")
    eff_high = get_action_effectiveness(temp_db, "openfileconverter.com", "ACTION_HIGH_EVIDENCE", "convert")

    # High evidence has significantly higher confidence weight
    assert eff_high["confidence_weight"] > eff_small["confidence_weight"]
    assert eff_high["confidence_weight"] >= 0.90
    assert eff_small["confidence_weight"] < 0.60
