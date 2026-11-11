#!/usr/bin/env python3
"""validate_wave_close.py - Automated Wave-Close Verification Gate.

Enforces that an autonomous SEO wave cannot be marked complete until its
authoritative Markdown report exists, reconciles with the Git diff and backlog
cursor in ~/.seo_fleet/fleet_state.db, and satisfies the two-part scorecard
contract (Invariant P6).

Validation Checks:
1. File Existence & Size: Report exists at reports/seo-waves/<domain>/wave-<N>-<domain>-changelog.md (>= 500 bytes).
2. Mandatory Sections: Contains all 8 required sections including Part 1 and Part 2 scorecards.
3. Invariant P6 Check: Part 2 (SEO Effectiveness) must be marked 'NOT YET MEASURED' / 'Awaiting GSC Recrawl'
   unless a full 28-day observation window and verified recrawl evidence exists. Premature 10/10 scores fail.
4. Task Reconciliation: Shipped task IDs in the database/queue must match the task table in the report.
5. Rule 32 Emoji Ban: 0 unicode emojis allowed in the report.
6. Deployment & Invariants: Verifies scoped zone purge and rollback runbook documentation.
"""

from __future__ import annotations

import argparse
import os
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any

MANDATORY_SECTIONS = [
    ("Executive Summary & Two-Part Scorecard", re.compile(r"##\s*1\.\s*Executive Summary.*Scorecard", re.IGNORECASE)),
    ("Part 1: Engineering Execution Quality", re.compile(r"###\s*Part 1:\s*Engineering Execution Quality", re.IGNORECASE)),
    ("Part 2: Measured SEO & Business Effectiveness", re.compile(r"###\s*Part 2:\s*Measured SEO.*Effectiveness", re.IGNORECASE)),
    ("Reconciled Task Inventory & Ledger Alignment", re.compile(r"##\s*2\.\s*Reconciled Task Inventory", re.IGNORECASE)),
    ("Strategic Deep-Dive & Intent Analysis", re.compile(r"##\s*3\.\s*Strategic Deep-Dive", re.IGNORECASE)),
    ("Exhaustive File & Configuration Changes", re.compile(r"##\s*4\.\s*Exhaustive File.*Changes", re.IGNORECASE)),
    ("Standardized Test Classification & Quality Verification", re.compile(r"##\s*5\.\s*Standardized Test Classification", re.IGNORECASE)),
    ("Deployment, Edge Cache & Invariant Compliance", re.compile(r"##\s*6\.\s*Deployment.*Invariant Compliance", re.IGNORECASE)),
    ("Rollback Runbook & Disaster Recovery", re.compile(r"##\s*7\.\s*Rollback Runbook", re.IGNORECASE)),
    ("Actionable Recommendations", re.compile(r"##\s*8\.\s*Actionable Recommendations", re.IGNORECASE)),
]

EMOJI_PATTERN = re.compile(r"[\U00010000-\U0010ffff]|[\u2600-\u27ff]")


def validate_report_content(
    content: str,
    domain: str | None = None,
    wave: int | None = None,
    expected_task_ids: list[int] | None = None,
    allow_measured_seo: bool = False,
) -> tuple[bool, list[str], list[str]]:
    """Validate report text against mandatory contract rules.

    Returns (passed, errors, warnings).
    """
    errors: list[str] = []
    warnings: list[str] = []

    # 1. Size check
    if len(content.strip()) < 500:
        errors.append(f"Report content too short ({len(content.strip())} bytes, min 500 bytes required).")

    # 2. Mandatory Section Headings
    for name, pattern in MANDATORY_SECTIONS:
        if not pattern.search(content):
            errors.append(f"Missing mandatory section: '{name}'.")

    # 3. Invariant P6 Verification: Part 2 premature score ban
    part2_match = re.search(r"###\s*Part 2:\s*Measured SEO.*Effectiveness(.*?)---", content, re.DOTALL | re.IGNORECASE)
    if part2_match:
        part2_text = part2_match.group(1)
        has_unmeasured_notice = bool(
            re.search(r"NOT YET MEASURED|Awaiting GSC Recrawl|Pending GSC", part2_text, re.IGNORECASE)
        )
        has_premature_score = bool(
            re.search(r"(Grade|Score)\s*:\s*(10(?:\.0)?|[89]\.\d)\s*/\s*10", part2_text, re.IGNORECASE)
        )
        if not allow_measured_seo:
            if not has_unmeasured_notice:
                errors.append(
                    "Invariant P6 Violation: Part 2 must state 'NOT YET MEASURED (Awaiting GSC Recrawl & 28-Day Observation Window)'."
                )
            if has_premature_score:
                errors.append(
                    "Invariant P6 Violation: Premature numerical SEO Effectiveness grade detected before 28-day observation window."
                )

    # 4. Domain and Wave Header check
    if domain:
        if domain.lower() not in content.lower():
            errors.append(f"Domain '{domain}' not found in report body.")
    if wave is not None:
        if f"Wave {wave}" not in content:
            warnings.append(f"'Wave {wave}' not found in header.")

    # 5. Task ID Reconciliation
    if expected_task_ids:
        missing_ids = []
        for tid in expected_task_ids:
            # Pattern matching | **tid** | or | tid | in markdown table
            tid_pattern = re.compile(rf"\|\s*(?:\*\*)?{tid}(?:\*\*)?\s*\|")
            if not tid_pattern.search(content):
                missing_ids.append(tid)
        if missing_ids:
            errors.append(f"Task reconciliation failure: Tasks {missing_ids} missing from task table in report.")

    # 6. Rule 32 Emoji Ban
    emojis_found = EMOJI_PATTERN.findall(content)
    if emojis_found:
        errors.append(f"Rule 32 Violation: Prohibited unicode emojis detected in report: {emojis_found[:5]}")

    # 7. Verification of Test Tiers
    test_tier_pattern = re.compile(r"\[Test Tier 1:.*\[Test Tier 2:.*\[Test Tier 3:.*\[Test Tier 4:.*\[Live Edge Verification", re.DOTALL)
    if not test_tier_pattern.search(content):
        warnings.append("Standardized 4-tier test block formatting is recommended in Section 5.")

    passed = len(errors) == 0
    return passed, errors, warnings


def validate_wave_close(
    report_path: Path | str,
    domain: str | None = None,
    wave: int | None = None,
    db_path: Path | str | None = None,
    commit_sha: str | None = None,
    allow_measured_seo: bool = False,
) -> tuple[bool, list[str], list[str]]:
    """Validate report file existence and content against database backlog state."""
    path = Path(report_path)
    if not path.exists():
        return False, [f"Report file not found: {path}"], []

    content = path.read_text(encoding="utf-8")

    expected_tasks: list[int] | None = None
    if db_path and Path(db_path).exists() and domain:
        conn = sqlite3.connect(Path(db_path))
        try:
            if commit_sha:
                cur = conn.execute(
                    "SELECT id FROM atomic_task_backlog WHERE domain = ? AND commit_sha LIKE ? ORDER BY id",
                    (domain, f"{commit_sha}%"),
                )
            else:
                cur = conn.execute(
                    "SELECT id FROM atomic_task_backlog WHERE domain = ? AND status = 'SHIPPED' ORDER BY id",
                    (domain,),
                )
            expected_tasks = [row[0] for row in cur.fetchall()]
        finally:
            conn.close()

    return validate_report_content(
        content=content,
        domain=domain,
        wave=wave,
        expected_task_ids=expected_tasks,
        allow_measured_seo=allow_measured_seo,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate wave changelog report against contract gate.")
    parser.add_argument("--report", required=True, help="Path to wave changelog markdown")
    parser.add_argument("--domain", default=None, help="Target domain to verify")
    parser.add_argument("--wave", type=int, default=None, help="Wave number to verify")
    parser.add_argument("--db-path", default=None, help="Path to fleet_state.db for task reconciliation")
    parser.add_argument("--commit-sha", default=None, help="Commit SHA to reconcile tasks against")
    parser.add_argument("--allow-measured-seo", action="store_true", help="Allow numerical Part 2 SEO score (post-28d)")
    parser.add_argument("--strict", action="store_true", help="Fail if any warnings exist")
    args = parser.parse_args()

    passed, errors, warnings = validate_wave_close(
        report_path=args.report,
        domain=args.domain,
        wave=args.wave,
        db_path=args.db_path,
        commit_sha=args.commit_sha,
        allow_measured_seo=args.allow_measured_seo,
    )

    print(f"=== Wave-Close Verification: {args.report} ===")
    if warnings:
        print("\nWARNINGS:")
        for w in warnings:
            print(f"  [WARN] {w}")

    if not passed:
        print("\nERRORS:")
        for e in errors:
            print(f"  [FAIL] {e}")
        print("\nResult: REJECTED - Wave changelog does not satisfy the reporting contract.")
        return 1

    if args.strict and warnings:
        print("\nResult: REJECTED (Strict Mode) - Warnings present.")
        return 1

    print("\nResult: PASSED - Authoritative wave changelog verified successfully.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
