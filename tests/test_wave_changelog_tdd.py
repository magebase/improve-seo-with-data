"""tests/test_wave_changelog_tdd.py - TDD Suite for Standardized Wave Changelog Contract (v2.1.1).

Tests:
1. Automated generation of compliant Markdown wave reports (generate_wave_changelog.py).
2. Automated wave-close verification gate (validate_wave_close.py).
3. Invariant P6 enforcement: Part 2 SEO grade must be 'NOT YET MEASURED' prior to 28-day window.
4. Task ID reconciliation against database / backlog.
5. Git commit existence and changed-file inventory reconciliation (Negative tests for omitted files).
6. Worker deployment version authenticity (Negative test for placeholder versions).
7. Issue state resolution semantics (Prohibits claiming RESOLVED on planned/deferred issues).
8. Scorecard mathematical exactness (Detects mathematical discrepancies in weighted score).
9. Rule 32 strict emoji ban enforcement.
10. Markdown syntax and run-on header detection.
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
    calculate_engineering_score,
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
            "current_impressions": 251.0,
            "current_clicks": 1.0,
            "current_pos": 97.0,
        },
        {
            "id": 987,
            "query": "money management",
            "page": "https://incomecanvas.com/article/wacc-capital-structure-optimization-after-tax-debt-spreads/",
            "action_code": "INJECT_SECONDARY_H2_ONLY",
            "status": "SHIPPED",
            "applied_desc": "Injected Corporate Money Management section",
            "current_impressions": 21.0,
            "current_clicks": 0.0,
            "current_pos": 94.9,
        },
    ]


@pytest.fixture
def valid_report_markdown(sample_shipped_tasks):
    strategic_notes = [
        {
            "title": "WACC vs Personal Finance Intent Overlap",
            "status": "REMEDIATION_PLANNED",
            "issue": "Money management query mapped to corporate WACC article.",
            "provenance": "GSC query cluster contains personal budgeting intent.",
            "resolution": "Dedicated personal finance hub planned for Wave 16.",
        }
    ]
    file_diffs = [
        {
            "path": "apps/seo_alpha_site/views.py",
            "description": "Added default dict bindings.",
            "diff": "@@ -1,3 +1,4 @@\n+article.setdefault('section_heading', 'Analysis')",
        }
    ]
    changed_files = ["apps/seo_alpha_site/views.py"]

    return generate_wave_changelog_markdown(
        domain="incomecanvas.com",
        wave=15,
        skill_commit="6f762219",
        repo_commit="0af3b6c1",
        worker_version="a9f097fd-b397-4ebf-bea8-6ab0d0ce4e56",
        tasks=sample_shipped_tasks,
        app_target="apps/seo_alpha_site/",
        rewarmed_count=22,
        changed_files=changed_files,
        file_diffs=file_diffs,
        strategic_notes=strategic_notes,
    )


def test_generate_wave_changelog_structure(valid_report_markdown):
    md = valid_report_markdown

    # Asserts 8 mandatory sections exist
    assert "## 1. Executive Summary & Authoritative Two-Part Scorecard" in md
    assert "### Part 1: Engineering Execution Quality" in md
    assert "### Part 1.1: Machine Learning Model Decisions & Feature Attributions" in md
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


def test_validate_wave_close_detects_missing_mandatory_section(valid_report_markdown):
    # Remove Rollback Runbook
    corrupted_md = re.sub(r"## 7\. Rollback Runbook.*?(?=## 8\.)", "", valid_report_markdown, flags=re.DOTALL)

    passed, errors, warnings = validate_report_content(
        content=corrupted_md,
        domain="incomecanvas.com",
        wave=15,
    )
    assert passed is False
    assert any("Rollback Runbook" in e for e in errors)


def test_validate_wave_close_invariant_p6_blocks_premature_score(valid_report_markdown):
    # Inject premature numerical grade into Part 2
    corrupted_md = valid_report_markdown.replace(
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


def test_validate_wave_close_rejects_placeholder_worker_version(valid_report_markdown):
    # Replace valid worker version with placeholder
    corrupted_md = valid_report_markdown.replace(
        "a9f097fd-b397-4ebf-bea8-6ab0d0ce4e56",
        "live-worker-version",
    )

    passed, errors, warnings = validate_report_content(
        content=corrupted_md,
        domain="incomecanvas.com",
        wave=15,
        allow_worker_placeholder=False,
    )
    assert passed is False
    assert any("Worker deployment version is a placeholder" in e for e in errors)


def test_validate_wave_close_rejects_omitted_git_files(valid_report_markdown, monkeypatch):
    # Mock git changed files returning 2 files, while report only documents 1
    monkeypatch.setattr(
        "validate_wave_close.verify_git_commit_exists",
        lambda repo, sha: True,
    )
    monkeypatch.setattr(
        "validate_wave_close.get_git_changed_files",
        lambda repo, sha: ["apps/seo_alpha_site/views.py", "apps/seo_alpha_site/financial_engine.py"],
    )

    passed, errors, warnings = validate_report_content(
        content=valid_report_markdown,
        domain="incomecanvas.com",
        wave=15,
        repo_path=Path("/fake/repo"),
        commit_sha="0af3b6c1",
    )
    assert passed is False
    assert any("Git diff reconciliation failure" in e and "financial_engine.py" in e for e in errors)


def test_validate_wave_close_prohibits_resolved_on_planned_issue(valid_report_markdown):
    # Corrupt report to claim VERIFIED_RESOLVED on an issue that has status REMEDIATION_PLANNED
    corrupted_md = valid_report_markdown.replace(
        "- **Current Resolution Status:** `REMEDIATION_PLANNED`",
        "- **Current Resolution Status:** `VERIFIED_RESOLVED`\n- Note: remediation scheduled for Wave 16",
    )

    passed, errors, warnings = validate_report_content(
        content=corrupted_md,
        domain="incomecanvas.com",
        wave=15,
    )
    assert passed is False
    assert any("Issue State Semantics Violation" in e for e in errors)


def test_validate_wave_close_detects_scorecard_math_mismatch(valid_report_markdown):
    # Corrupt claimed score to 8.0 while weights sum to 9.4
    corrupted_md = re.sub(
        r"### Part 1: Engineering Execution Quality \(Score: [\d\.]+ / 10\.0\)",
        "### Part 1: Engineering Execution Quality (Score: 8.0 / 10.0)",
        valid_report_markdown,
    )

    passed, errors, warnings = validate_report_content(
        content=corrupted_md,
        domain="incomecanvas.com",
        wave=15,
    )
    assert passed is False
    assert any("Scorecard Math Discrepancy" in e for e in errors)


def test_validate_wave_close_detects_mangled_markdown_header(valid_report_markdown):
    # Inject a run-on header without spaces
    corrupted_md = valid_report_markdown + "\n\n### 3.3 100kPersonalLoanScenario(Task543)\nSome content.\n"

    passed, errors, warnings = validate_report_content(
        content=corrupted_md,
        domain="incomecanvas.com",
        wave=15,
    )
    assert passed is False
    assert any("Malformed Markdown Header detected" in e for e in errors)


def test_validate_wave_close_enforces_rule_32_emoji_ban(valid_report_markdown):
    corrupted_md = valid_report_markdown + "\n\n🚀 Deploy successful! ✨\n"

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


def test_validate_wave_close_rejects_missing_test_evidence(valid_report_markdown):
    """Negative test: Section 5 missing passing test execution counts is rejected."""
    corrupted_md = re.sub(
        r"## 5\. Standardized Test Classification.*?(?=## 6\.)",
        "## 5. Standardized Test Classification & Quality Verification\n\nAll tests were supposedly run offline.\n\n",
        valid_report_markdown,
        flags=re.DOTALL,
    )
    passed, errors, warnings = validate_report_content(
        content=corrupted_md,
        domain="incomecanvas.com",
        wave=15,
    )
    assert passed is False
    assert any("Test Evidence Missing" in e for e in errors)


def test_validate_wave_close_rejects_nonexistent_git_commit(valid_report_markdown, monkeypatch):
    """Negative test: Commit SHA not found in repo is rejected."""
    monkeypatch.setattr(
        "validate_wave_close.verify_git_commit_exists",
        lambda repo, sha: False,
    )
    passed, errors, warnings = validate_report_content(
        content=valid_report_markdown,
        domain="incomecanvas.com",
        wave=15,
        repo_path=Path("/fake/repo"),
        commit_sha="badc0ffee",
    )
    assert passed is False
    assert any("Git commit verification failed" in e for e in errors)


def test_validate_wave_close_rejects_dirty_worktree(valid_report_markdown, monkeypatch):
    """Negative test: Uncommitted changes in git worktree block wave sign-off."""
    monkeypatch.setattr(
        "validate_wave_close.check_git_worktree_clean",
        lambda repo: (False, " M apps/seo_alpha_site/views.py\n?? untracked.py"),
    )
    passed, errors, warnings = validate_report_content(
        content=valid_report_markdown,
        domain="incomecanvas.com",
        wave=15,
        repo_path=Path("/fake/repo"),
        allow_dirty=False,
    )
    assert passed is False
    assert any("Git worktree dirty check failed" in e for e in errors)


def test_validate_wave_close_rejects_missing_task_ids(valid_report_markdown):
    """Negative test: Expected task IDs not documented in task table are rejected."""
    passed, errors, warnings = validate_report_content(
        content=valid_report_markdown,
        domain="incomecanvas.com",
        wave=15,
        expected_task_ids=[543, 987, 88888],  # 88888 is missing
    )
    assert passed is False
    assert any("Task reconciliation failure" in e and "88888" in e for e in errors)


def test_validate_wave_close_cli_version():
    """Verifies validate_wave_close.py reports v2.3.0 via CLI."""
    import subprocess
    cmd = [sys.executable, str(SCRIPTS_DIR / "validate_wave_close.py"), "--version"]
    res = subprocess.run(cmd, capture_output=True, text=True, check=True)
    assert "validate_wave_close.py v2.3.0" in res.stdout


def test_validate_wave_close_detects_missing_model_decisions_section(valid_report_markdown):
    """Negative test: Missing Part 1.1 Model Decisions section is rejected."""
    corrupted_md = re.sub(
        r"### Part 1\.1: Machine Learning Model Decisions.*?(?=### Part 2:)",
        "",
        valid_report_markdown,
        flags=re.DOTALL,
    )
    passed, errors, warnings = validate_report_content(
        content=corrupted_md,
        domain="incomecanvas.com",
        wave=15,
    )
    assert passed is False
    assert any("Machine Learning Model Decisions" in e for e in errors)


def test_validate_wave_close_detects_missing_shap_table(valid_report_markdown):
    """Negative test: Part 1.1 lacking task attribution table is rejected."""
    corrupted_md = re.sub(
        r"#### Task Selection & Feature Attribution Inventory.*?(?=### Part 2:)",
        "#### Task Selection & Feature Attribution Inventory\n\nNo attribution data provided.\n\n",
        valid_report_markdown,
        flags=re.DOTALL,
    )
    passed, errors, warnings = validate_report_content(
        content=corrupted_md,
        domain="incomecanvas.com",
        wave=15,
    )
    assert passed is False
    assert any("missing Task Selection & Feature Attribution table" in e for e in errors)


def test_validate_wave_close_supports_commit_range(valid_report_markdown, monkeypatch):
    """Verifies multi-commit range reconciliation in validate_report_content."""
    from validate_wave_close import get_git_changed_files

    # Mock get_git_changed_files to return files matching Section 4 of valid_report_markdown
    monkeypatch.setattr(
        "validate_wave_close.verify_git_commit_exists",
        lambda repo, commit_or_range: True,
    )
    monkeypatch.setattr(
        "validate_wave_close.get_git_changed_files",
        lambda repo, commit_or_range: [
            "apps/seo_alpha_site/views.py",
        ],
    )
    monkeypatch.setattr(
        "validate_wave_close.check_git_worktree_clean",
        lambda repo: (True, ""),
    )

    passed, errors, warnings = validate_report_content(
        content=valid_report_markdown,
        domain="incomecanvas.com",
        wave=15,
        repo_path="/fake/repo",
        commit_range="abc1234..def5678",
    )
    assert passed is True
    assert not errors
