"""Wave 113 TDD: an expected loss is never shippable work.

Empirical driver: the 2026-11-16 scoring run on smsrvier.com produced 13
"actionable" rows (2 SHIP + 11 EXPERIMENT) and **every one had negative net
expected value** (-$1.22 to -$2.49). `priority_score` substitutes a positive
proxy whenever EV < 0:

    priority_score = max(0.01, ev if ev > 0 else delta_clicks * p_success) * ...

so a row that loses money can still clear the SHIP threshold. Those rows are
what the compiler turns into wave tasks, which is why consecutive waves shipped
edits to 1-impression queries that cannot repay their own labor.

Contract: `decision_class` must respect the sign of `net_expected_value`.
SHIP and EXPERIMENT describe work with positive expected return; a negative-EV
row is OBSERVE regardless of how it ranks.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from score_backlog import (
    EconomicConfig,
    compute_opportunity_intelligence,
)


def _task(**overrides) -> dict:
    row = {
        "domain": "smsriver.com",
        "page": "https://smsriver.com/receive-sms/gb/",
        "query": "receive sms",
        "action_code": "INJECT_EXACT_TITLE_AND_H2",
        "prescribed_action": "INJECT_EXACT_TITLE_AND_H2",
        "clicks_30d": 0.0,
        "impressions": 15.0,
        "ctr": 0.0,
        "features": {"current_pos": 27.6},
    }
    row.update(overrides)
    return row


def test_negative_expected_value_is_never_ship_or_experiment():
    """The live 15-impression row that shipped at -$1.22 must become OBSERVE."""
    scored = compute_opportunity_intelligence(_task())

    assert scored["expected_value"] < 0, "fixture must reproduce the live loss"
    assert scored["decision_class"] == "OBSERVE"


def test_deep_tail_loss_is_observe():
    """Position 45 with 50 impressions and no clicks cannot repay its labor."""
    scored = compute_opportunity_intelligence(
        _task(
            impressions=50.0,
            query="obscure format converter",
            action_code="CREATE_PROGRAMMATIC_ROUTE",
            prescribed_action="CREATE_PROGRAMMATIC_ROUTE",
            features={"current_pos": 45.0},
        )
    )

    assert scored["expected_value"] < 0
    assert scored["decision_class"] == "OBSERVE"


def test_striking_distance_row_with_real_impressions_ships_at_fleet_rates():
    """At the fleet's $5/h labor rate a 300-impression page-1 query pays back."""
    scored = compute_opportunity_intelligence(
        _task(
            query="pdf to docx converter",           # tool intent -> 5% conversion
            action_code="INJECT_EXACT_TITLE_AND_H2",
            prescribed_action="INJECT_EXACT_TITLE_AND_H2",
            impressions=300.0,
            clicks_30d=0.0,
            features={"current_pos": 8.0},
        ),
        config=EconomicConfig(labor_hourly_rate=5.0, value_per_conversion=10.0),
    )

    assert scored["expected_value"] > 0, scored["ev_decomposition"]
    assert scored["decision_class"] in {"SHIP", "EXPERIMENT"}
    assert scored["ev_gate_blocked"] is False


def test_gate_reports_which_rows_it_blocked():
    scored = compute_opportunity_intelligence(
        _task(impressions=26.0, features={"current_pos": 27.6}),
        config=EconomicConfig(labor_hourly_rate=5.0, value_per_conversion=10.0),
    )
    assert scored["decision_class"] == "OBSERVE"
    assert scored["ev_gate_blocked"] is True


def test_positive_expected_value_can_still_ship():
    """The gate must not suppress genuinely profitable work."""
    scored = compute_opportunity_intelligence(
        _task(
            query="sms api converter",          # tool intent -> 5% conversion
            action_code="INJECT_EXACT_TITLE_AND_H2",  # 0.5h labour
            impressions=4000.0,
            features={"current_pos": 8.0},
        ),
        config=EconomicConfig(labor_hourly_rate=50.0, value_per_conversion=10.0),
    )

    assert scored["expected_value"] > 0, scored["ev_decomposition"]
    assert scored["decision_class"] in {"SHIP", "EXPERIMENT"}


def test_zero_value_is_observe_not_ship():
    """Break-even is not a mandate to act; it is an absence of return."""
    scored = compute_opportunity_intelligence(
        _task(
            impressions=0.0,
            clicks_30d=0.0,
            query="nothing at all",
            features={"current_pos": 80.0},
        )
    )

    assert scored["expected_value"] <= 0
    assert scored["decision_class"] == "OBSERVE"


@pytest.mark.parametrize("impressions", [1.0, 7.0, 15.0, 26.0])
def test_small_impression_rows_never_ship(impressions: float):
    scored = compute_opportunity_intelligence(_task(impressions=impressions))
    assert scored["decision_class"] == "OBSERVE", (impressions, scored["expected_value"])


def test_preflight_hygiene_rejects_negative_ev_rows(tmp_path: Path):
    """Pending rows carrying strictly negative expected value must be scrubbed."""
    from cursor_hygiene import preflight_hygiene
    from fleet_state import connect_state_db, enqueue_tasks

    conn = connect_state_db(str(tmp_path / "ev_hygiene.db"))
    enqueue_tasks(
        conn,
        [
            {
                "domain": "smsriver.com",
                "page": "https://smsriver.com/receive-sms/pl/",
                "query": "sms recive",
                "action_code": "INJECT_SECONDARY_H2_ONLY",
                "expected_value": -2.4838,
                "decision_class": "EXPERIMENT",
            },
            {
                "domain": "smsriver.com",
                "page": "https://smsriver.com/status/",
                "query": "online sms status",
                "action_code": "BOOST_CLUSTER_CROSS_LINKS",
                "expected_value": 15.0,
                "decision_class": "SHIP",
            },
        ],
    )
    report = preflight_hygiene(conn, domain="smsriver.com")
    assert report["rejected"] == 1
    statuses = {r[0]: r[1] for r in conn.execute("SELECT query, status FROM atomic_task_backlog")}
    assert statuses["sms recive"] == "REJECTED"
    assert statuses["online sms status"] == "PENDING"

