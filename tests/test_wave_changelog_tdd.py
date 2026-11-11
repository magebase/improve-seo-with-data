"""tests/test_wave_changelog_tdd.py - TDD Suite for Standardized Wave Changelog Contract.

Tests:
1. Automated generation of compliant Markdown wave reports (generate_wave_changelog.py).
2. Automated wave-close verification gate (validate_wave_close.py).
3. Invariant P6 enforcement: Part 2 SEO grade must be 'NOT YET MEASURED' prior to 28-day window.
4. Task ID reconciliation against database / backlog.
5. Rule 32 strict emoji ban enforcement in reports.
6. Detection of missing mandatory report sections.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

# Ensure scripts dir is on sys.path
SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from generate_wave_changelog import (
    generate_wave_changelog_markdown,
)
from validate_wave_close import (
    validate_report_content,
    validate_wave_close,
)


@pytest.fixture
def sample_shipped_tasks():
    return [
        {
            "id": 543,
            "query": "personal loan rates",
            "page": "https://incomecanvas.com/article/unsecured-personal-loan-aprs-underwriting-dti-debt-consolidation/",
            "action_code": "INJECT_EXACT_TITLE_AND_H2",
            "status": "SHIPPED",
            "applied_desc": "Injected Personal Loan Rates & Underwriting APR Benchmarks",
        },
        {
            "id": 987,
            "query": "money management",
            "page": "https://incomecanvas.com/article/wacc-capital-structure-optimization-after-tax-debt-spreads/",
            "action_code": "INJECT_SECONDARY_H2_ONLY",
            "status": "SHIPPED",
            "applied_desc": "Injected Corporate Money Management section",
        },
    ]


def test_generate_wave_changelog_structure(sample_shipped_tasks):
    md = generate_wave_changelog_markdown(
        domain="incomecanvas.com",
        wave=15,
        skill_commit="6f762219",
        repo_commit="0af3b6c1",
        worker_version="a9f097fd",
        tasks=sample_shipped_tasks,
        app_target="apps/seo_alpha_site/",
        rewarmed_count=22,
    )

    # Asserts 8 mandatory sections exist
    assert "## 1. Executive Summary & Authoritative Two-Part Scorecard" in md
    assert "### Part 1: Engineering Execution Quality" in md
    assert "### Part 2: Measured SEO & Business Effectiveness" in md
    assert "## 2. Reconciled Task Inventory & Ledger Alignment" in md
    assert "## 3. Strategic Deep-Dive & Intent Analysis" in md
    assert "## 4. Exhaustive File & Configuration Changes" in md
    assert "## 5. Standardized Test Classification & Quality Verification" in md
    assert "## 6. Deployment, Edge Cache & Invariant Compliance" in md
    assert "## 7. Rollback Runbook & Disaster Recovery" in md
    assert "## 8. Actionable Recommendations for Wave 16" in md

    # Invariant P6 check in generated output
    assert "NOT YET MEASURED (Awaiting GSC Recrawl & 28-Day Observation Window)" in md

    # Zero emojis check
    assert not re.search(r"[\U00010000-\U0010ffff]|[\u2600-\u27ff]", md)

    # Validate passes gate
    passed, errors, warnings = validate_report_content(
        content=md,
        domain="incomecanvas.com",
        wave=15,
        expected_task_ids=[543, 987],
    )
    assert passed is True
    assert len(errors) == 0


def test_validate_wave_close_detects_missing_mandatory_section(sample_shipped_tasks):
    md = generate_wave_changelog_markdown(
        domain="incomecanvas.com",
        wave=15,
        skill_commit="6f762219",
        repo_commit="0af3b6c1",
        worker_version="a9f097fd",
        tasks=sample_shipped_tasks,
    )
    # Remove Rollback Runbook
    corrupted_md = re.sub(r"## 7\. Rollback Runbook.*?(?=## 8\.)", "", md, flags=re.DOTALL)

    passed, errors, warnings = validate_report_content(
        content=corrupted_md,
        domain="incomecanvas.com",
        wave=15,
    )
    assert passed is False
    assert any("Rollback Runbook" in e for e in errors)


def test_validate_wave_close_invariant_p6_blocks_premature_score(sample_shipped_tasks):
    md = generate_wave_changelog_markdown(
        domain="incomecanvas.com",
        wave=15,
        skill_commit="6f762219",
        repo_commit="0af3b6c1",
        worker_version="a9f097fd",
        tasks=sample_shipped_tasks,
    )
    # Inject premature numerical grade into Part 2
    corrupted_md = md.replace(
        "**SEO Effectiveness Grade:** **NOT YET MEASURED (Awaiting GSC Recrawl & 28-Day Observation Window)**",
        "**SEO Effectiveness Grade:** **10.0 / 10.0 (Outstanding Immediate Rank Lift)**",
    )

    passed, errors, warnings = validate_report_content(
        content=corrupted_md,
        domain="incomecanvas.com",
        wave=15,
        allow_measured_seo=False,
    )
    assert passed is False
    assert any("Invariant P6 Violation" in e for e in errors)


def test_validate_wave_close_task_reconciliation_detects_omission(sample_shipped_tasks):
    md = generate_wave_changelog_markdown(
        domain="incomecanvas.com",
        wave=15,
        skill_commit="6f762219",
        repo_commit="0af3b6c1",
        worker_version="a9f097fd",
        tasks=sample_shipped_tasks,
    )

    # Expect task 999 which was not in sample_shipped_tasks
    passed, errors, warnings = validate_report_content(
        content=md,
        domain="incomecanvas.com",
        wave=15,
        expected_task_ids=[543, 987, 999],
    )
    assert passed is False
    assert any("Task reconciliation failure" in e and "999" in e for e in errors)


def test_validate_wave_close_enforces_rule_32_emoji_ban(sample_shipped_tasks):
    md = generate_wave_changelog_markdown(
        domain="incomecanvas.com",
        wave=15,
        skill_commit="6f762219",
        repo_commit="0af3b6c1",
        worker_version="a9f097fd",
        tasks=sample_shipped_tasks,
    )
    # Add an emoji
    corrupted_md = md + "\n\n🚀 Deploy successful! ✨\n"

    passed, errors, warnings = validate_report_content(
        content=corrupted_md,
        domain="incomecanvas.com",
        wave=15,
    )
    assert passed is False
    assert any("Rule 32 Violation: Prohibited unicode emojis detected" in e for e in errors)


def test_validate_wave_close_file_not_found(tmp_path):
    non_existent = tmp_path / "does_not_exist.md"
    passed, errors, warnings = validate_wave_close(non_existent)
    assert passed is False
    assert any("Report file not found" in e for e in errors)
