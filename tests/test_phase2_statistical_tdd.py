"""Phase 2 statistical, causal, and model-quality validation tests."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from did_simulation_validator import run_did_monte_carlo_battery
from evaluate_experiments import evaluate_domain_experiments
from fleet_state import connect_state_db, record_experiment
from growth_loop import (
    CORE_UPDATE_WINDOWS,
    _window_overlaps_core_update,
    detect_volatility_quarantine,
)
from ltr_ranker import FEATURES
from train_ranker import train_from_history


def test_did_monte_carlo_overdispersion_coverage_and_power():
    res = run_did_monte_carlo_battery(n_sims=200, seed=42)
    s1 = res["SCENARIO_1_STRICT_NULL"]
    s2 = res["SCENARIO_2_POSITIVE_LIFT"]
    s4 = res["SCENARIO_4_OVERDISPERSED_NB"]

    assert s1["coverage_welch_satterthwaite"] >= 0.90
    assert s1["mean_ci_width_ws"] < 1.5
    assert s4["coverage_welch_satterthwaite"] >= 0.90
    assert s4["rejection_rate"] <= 0.10
    assert s2["rejection_rate"] > 0.05


def test_evaluate_domain_experiments_wires_fdr_power_and_horizon():
    conn = connect_state_db(":memory:")
    record_experiment(
        conn,
        task_id=1,
        domain="example.com",
        page="https://example.com/p1/",
        target_query="q1",
        action_code="REWRITE_SNIPPET_AND_TOP_300PX",
        baseline_clicks_28d=20.0,
        baseline_impressions_28d=500.0,
        baseline_ctr=0.04,
        baseline_position=6.0,
        control_cohort_page="https://example.com/c1/",
        control_baseline_clicks=20.0,
        deployed_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
    )
    conn.execute(
        """
        UPDATE experiment_ledger
        SET status = 'STATISTICALLY_SIGNIFICANT_LIFT',
            recrawl_detected_at = '2026-10-05T00:00:00Z',
            did_ci_lower = 0.15,
            did_ci_upper = 0.65
        WHERE domain = 'example.com'
        """
    )
    conn.commit()
    out = evaluate_domain_experiments(conn, "example.com")
    assert len(out["fdr_summary"]) == 1
    assert len(out["rope_classifications"]) == 1
    assert len(out["horizon_status"]) == 1
    assert out["fdr_summary"][0]["is_significant_fdr"] is True
    conn.close()


def test_train_ranker_flags_degenerate_model(tmp_path: Path):
    hist = tmp_path / "hist.jsonl"
    rows = []
    for i in range(70):
        feats = {f: 0.0 for f in FEATURES}
        feats["current_pos"] = float((i % 20) + 1)
        feats["search_volume_log"] = 1.0 + (i % 3) * 0.5
        rows.append(
            {
                "query": f"q{i}",
                "page": f"https://example.com/p{i}/",
                "cluster_id": f"c{i % 4}",
                "features": feats,
                "clicks_30d": float((i % 5) * 3),
                "impressions": 100.0,
                "current_pos": feats["current_pos"],
                "current_ctr": 0.05 if i % 5 else 0.0,
                "conv_value": 1.0,
            }
        )
    hist.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    models_dir = tmp_path / "models"
    result = train_from_history(str(hist), str(models_dir), warm_start=False)
    assert result is not None
    assert result["degraded"] is True
    assert any("active_features=" in reason for reason in result["degrade_reasons"])


def test_core_update_windows_dynamic_and_volatility_detector(monkeypatch):
    assert _window_overlaps_core_update("2027-03-05T00:00:00+00:00", "2027-03-20T00:00:00+00:00") is False
    monkeypatch.setenv("SEO_CORE_UPDATE_WINDOWS", '[["2027-03-01","2027-03-15"]]')
    assert _window_overlaps_core_update("2027-03-05T00:00:00+00:00", "2027-03-20T00:00:00+00:00") is True
    monkeypatch.setenv("SEO_CORE_UPDATE_WINDOWS", "[]")
    assert _window_overlaps_core_update("2026-12-05T00:00:00+00:00", "2026-12-20T00:00:00+00:00") is False

    shocked_obs = {f"p{i}": {"baseline_clicks": 100.0, "clicks": 40.0} for i in range(6)}
    calm_obs = {f"p{i}": {"baseline_clicks": 100.0, "clicks": 102.0} for i in range(6)}
    assert detect_volatility_quarantine(shocked_obs) is True
    assert detect_volatility_quarantine(calm_obs) is False
