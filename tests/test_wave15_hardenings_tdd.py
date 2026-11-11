"""TDD test suite for Wave 15 hardenings:
1. 21-Day URL Title Lock (enforce_url_title_lock)
2. is_truly_unbuilt_route & compile_wave_backlog route classification
3. is_valid_property_host strictly blocking foreign subdomains
4. DailyBudgetGate dynamic floor math at max_domain_floor = 35
"""

from __future__ import annotations

import sqlite3
import pytest

from candidate_hygiene import is_valid_property_host
from cursor_hygiene import enforce_url_title_lock, preflight_hygiene
from fleet_state import DailyBudgetGate, connect_state_db
from ltr_ranker import is_truly_unbuilt_route, compile_wave_backlog


@pytest.fixture
def mem_db():
    return connect_state_db(":memory:")


def test_21_day_url_title_lock(mem_db):
    """Pending title mutations on URLs shipped in the last 21 days downgrade to INJECT_SECONDARY_H2_ONLY and merge queries."""
    # Seed a shipped title task on /convert/pdf-to-docx/ 5 days ago
    mem_db.execute(
        """
        INSERT INTO atomic_task_backlog (domain, page, query, action_code, status, created_at, shipped_at)
        VALUES ('openfileconverter.com', 'https://openfileconverter.com/convert/pdf-to-docx/', 'pdf to docx', 'INJECT_EXACT_TITLE_AND_H2', 'SHIPPED', datetime('now', '-5 days'), datetime('now', '-5 days'))
        """
    )
    # Seed TWO pending secondary tasks on the same page with different queries and priorities
    mem_db.execute(
        """
        INSERT INTO atomic_task_backlog (domain, page, query, action_code, status, priority_score, created_at)
        VALUES ('openfileconverter.com', 'https://openfileconverter.com/convert/pdf-to-docx/', 'file converter pdf to docx', 'INJECT_EXACT_TITLE_AND_H2', 'PENDING', 0.5, datetime('now'))
        """
    )
    mem_db.execute(
        """
        INSERT INTO atomic_task_backlog (domain, page, query, action_code, status, priority_score, created_at)
        VALUES ('openfileconverter.com', 'https://openfileconverter.com/convert/pdf-to-docx/', 'convert pdf to docx free', 'CREATE_PROGRAMMATIC_ROUTE', 'PENDING', 0.9, datetime('now'))
        """
    )
    # Seed another pending task on a different page that has NOT shipped
    mem_db.execute(
        """
        INSERT INTO atomic_task_backlog (domain, page, query, action_code, status, created_at)
        VALUES ('openfileconverter.com', 'https://openfileconverter.com/convert/fresh-pair/', 'fresh pair', 'INJECT_EXACT_TITLE_AND_H2', 'PENDING', datetime('now'))
        """
    )
    mem_db.commit()

    downgraded = enforce_url_title_lock(mem_db, cooldown_days=21)
    assert downgraded == 2

    # Verify exactly ONE pending row remains for /convert/pdf-to-docx/
    rows = mem_db.execute(
        "SELECT action_code, query, priority_score, tdd_assertion FROM atomic_task_backlog WHERE page = 'https://openfileconverter.com/convert/pdf-to-docx/' AND status = 'PENDING'"
    ).fetchall()
    assert len(rows) == 1
    action_code, query, priority_score, assertion = rows[0]
    assert action_code == "INJECT_SECONDARY_H2_ONLY"
    assert priority_score == 0.9
    assert "convert pdf to docx free" in query
    assert "file converter pdf to docx" in query
    assert query in assertion

    # Verify the fresh page remained INJECT_EXACT_TITLE_AND_H2
    fresh_row = mem_db.execute(
        "SELECT action_code FROM atomic_task_backlog WHERE page = 'https://openfileconverter.com/convert/fresh-pair/' AND status = 'PENDING'"
    ).fetchone()
    assert fresh_row[0] == "INJECT_EXACT_TITLE_AND_H2"


def test_is_truly_unbuilt_route():
    """Live sitemap routes or routes with impressions are never classified as unbuilt."""
    known = {"https://openfileconverter.com/convert/pdf-to-docx/", "https://openfileconverter.com/convert/docx-to-pdf/"}

    # Absent and 0 impressions -> truly unbuilt
    assert is_truly_unbuilt_route("https://openfileconverter.com/convert/brand-new/", known, url_total_impressions=0) is True

    # In known live URLs -> NOT unbuilt
    assert is_truly_unbuilt_route("https://openfileconverter.com/convert/pdf-to-docx/", known, url_total_impressions=0) is False
    assert is_truly_unbuilt_route("https://openfileconverter.com/convert/pdf-to-docx", known, url_total_impressions=0) is False

    # Has impressions > 0 -> NOT unbuilt (even if not in sitemap)
    assert is_truly_unbuilt_route("https://openfileconverter.com/some/orphan/", set(), url_total_impressions=15) is False


def test_compile_wave_backlog_never_emits_create_route_for_known_live_page():
    """compile_wave_backlog never emits CREATE_PROGRAMMATIC_ROUTE for known live pages."""
    known = {"https://openfileconverter.com/convert/pdf-to-docx/"}
    rows = [
        {
            "page": "https://openfileconverter.com/convert/pdf-to-docx/",
            "query": "file converter pdf to docx",
            "current_pos": 95.0,  # ranks poorly but is ALREADY built
            "impressions": 5.0,
            "rank_score": 0.9,
            "coverage_state": "Submitted and indexed",
        }
    ]
    tasks = compile_wave_backlog(rows, known_live_urls=known, target_wave_size=5)
    action_codes = [t["action_code"] for t in tasks]
    assert "CREATE_PROGRAMMATIC_ROUTE" not in action_codes


def test_is_valid_property_host():
    """is_valid_property_host strictly rejects foreign subdomains while accepting apex and www."""
    assert is_valid_property_host("https://figiva.com/calc/", "sc-domain:figiva.com") is True
    assert is_valid_property_host("https://www.figiva.com/calc/", "sc-domain:figiva.com") is True
    assert is_valid_property_host("https://figiva.com/calc/", "figiva.com") is True

    # Foreign/leak subdomains must be rejected
    assert is_valid_property_host("https://landscaping.figiva.com/lookup/", "sc-domain:figiva.com") is False
    assert is_valid_property_host("https://staging.figiva.com/calc/", "figiva.com") is False
    assert is_valid_property_host("https://otherdomain.com/page/", "figiva.com") is False


def test_daily_budget_gate_dynamic_floor_cap():
    """DailyBudgetGate dynamic floor uses max_domain_floor = 35."""
    gate = DailyBudgetGate(daily_cap=150)
    assert gate.max_domain_floor == 35

    # 1 domain: floor is min(35, 150 // 1) = 35
    assert gate._dynamic_floor(1) == 35

    # 3 domains: floor is min(35, 150 // 3 = 50) = 35 (prevents 3 domains from eating all 150)
    assert gate._dynamic_floor(3) == 35

    # 5 domains: floor is min(35, 150 // 5 = 30) = 30
    assert gate._dynamic_floor(5) == 30
