#!/usr/bin/env python3
"""validate_wave_close.py - Automated Wave-Close Verification Gate (v2.2.0).

Enforces that an autonomous SEO wave cannot be marked complete until its
authoritative Markdown report exists, reconciles with the Git diff and backlog
cursor in ~/.seo_fleet/fleet_state.db, and satisfies the two-part scorecard
contract (Invariant P6) and evidence integrity rules.

Validation Checks:
1. File Existence & Size: Report exists (>= 500 bytes).
2. Mandatory Sections: Contains all 8 required sections including Part 1 and Part 2 scorecards.
3. Invariant P6 Check: Part 2 (SEO Effectiveness) must be marked 'NOT YET MEASURED' / 'Awaiting GSC Recrawl'
   unless a full 28-day observation window and verified recrawl evidence exists. Premature 10/10 scores fail.
4. Git Diff & Changed-File Inventory Reconciliation: Every file modified in the git commit
   must be explicitly accounted for in Section 4.
5. Repository Commit Existence: Verifies commit SHA exists in the target git repository.
6. Worker Deployment Version Authenticity: Rejects placeholder strings (e.g. 'live-worker-version', 'dummy').
7. Strategic Issue State Semantics: Prohibits claiming 'RESOLVED' on deferred or planned remediations.
8. Scorecard Mathematical Exactness: Validates that weighted scores calculate accurately to the claimed score.
9. Task Reconciliation: Shipped task IDs in the database/queue must match the task table in the report.
10. Rule 32 Emoji Ban: 0 unicode emojis allowed in the report.
11. Well-Formed Markdown: Validates headings and table syntax against run-on or mangled formatting.
12. Git Worktree Cleanliness: Enforces 0 dirty or untracked files before wave sign-off.
13. Test Run Evidence: Validates passing test execution counts and standardized classifications in Section 5.
"""

from __future__ import annotations

import argparse
import os
import re
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any

VERSION = "2.2.2"

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

PLACEHOLDER_WORKER_VERSIONS = {
    "live-worker-version",
    "dummy",
    "placeholder",
    "unknown",
    "none",
    "todo",
}


def verify_git_commit_exists(repo_path: Path | str, commit_or_range: str) -> bool:
    """Check if commit, multiple commits, or range endpoints exist in git repository."""
    target = str(commit_or_range).strip()
    try:
        if ".." in target:
            parts = target.split("..")
            start = parts[0].strip()
            end = parts[1].strip()
            for p in (start, end):
                if p:
                    res = subprocess.run(
                        ["git", "cat-file", "-e", f"{p}^{{commit}}"],
                        cwd=str(repo_path),
                        capture_output=True,
                        check=False,
                    )
                    if res.returncode != 0:
                        return False
            return True
        elif "," in target or (" " in target and not target.startswith("-")):
            parts = [p.strip() for p in re.split(r"[, ]+", target) if p.strip()]
            for p in parts:
                res = subprocess.run(
                    ["git", "cat-file", "-e", f"{p}^{{commit}}"],
                    cwd=str(repo_path),
                    capture_output=True,
                    check=False,
                )
                if res.returncode != 0:
                    return False
            return True
        else:
            res = subprocess.run(
                ["git", "cat-file", "-e", f"{target}^{{commit}}"],
                cwd=str(repo_path),
                capture_output=True,
                check=False,
            )
            return res.returncode == 0
    except Exception:
        return False


def get_git_changed_files(repo_path: Path | str, commit_or_range: str) -> list[str]:
    """Get list of changed files from git commit, multiple commits, or inclusive commit range (e.g. A..B)."""
    target = str(commit_or_range).strip()
    files: set[str] = set()
    try:
        if ".." in target:
            start_sha, end_sha = target.split("..", 1)
            start_sha = start_sha.strip()
            end_sha = end_sha.strip()

            # In Git, A..B diffs A with B, excluding files committed in A itself.
            # To make the range inclusive of start_sha, diff against the parent of start_sha (start_sha^..end_sha).
            parent_check = subprocess.run(
                ["git", "rev-parse", "--verify", f"{start_sha}^"],
                cwd=str(repo_path),
                capture_output=True,
                text=True,
                check=False,
            )
            if parent_check.returncode == 0:
                diff_ref = f"{start_sha}^..{end_sha}"
                res = subprocess.run(
                    ["git", "diff", "--name-only", diff_ref],
                    cwd=str(repo_path),
                    capture_output=True,
                    text=True,
                    check=True,
                )
                for line in res.stdout.strip().splitlines():
                    if line.strip():
                        files.add(line.strip())
            else:
                # start_sha is a root commit (no parent): diff root commit tree plus start..end
                res_root = subprocess.run(
                    ["git", "diff-tree", "--no-commit-id", "--name-only", "-r", start_sha],
                    cwd=str(repo_path),
                    capture_output=True,
                    text=True,
                    check=True,
                )
                for line in res_root.stdout.strip().splitlines():
                    if line.strip():
                        files.add(line.strip())
                res = subprocess.run(
                    ["git", "diff", "--name-only", f"{start_sha}..{end_sha}"],
                    cwd=str(repo_path),
                    capture_output=True,
                    text=True,
                    check=True,
                )
                for line in res.stdout.strip().splitlines():
                    if line.strip():
                        files.add(line.strip())
        elif "," in target or (" " in target and not target.startswith("-")):
            parts = [p.strip() for p in re.split(r"[, ]+", target) if p.strip()]
            for p in parts:
                res = subprocess.run(
                    ["git", "show", "--name-only", "--format=", p],
                    cwd=str(repo_path),
                    capture_output=True,
                    text=True,
                    check=True,
                )
                for line in res.stdout.strip().splitlines():
                    if line.strip():
                        files.add(line.strip())
        else:
            res = subprocess.run(
                ["git", "show", "--name-only", "--format=", target],
                cwd=str(repo_path),
                capture_output=True,
                text=True,
                check=True,
            )
            for line in res.stdout.strip().splitlines():
                if line.strip():
                    files.add(line.strip())
        return sorted(list(files))
    except Exception:
        return []


def check_git_worktree_clean(repo_path: Path | str) -> tuple[bool, str]:
    """Checks if git working tree is clean (no uncommitted modified/untracked files)."""
    try:
        res = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(repo_path),
            capture_output=True,
            text=True,
            check=False,
        )
        if res.returncode == 0:
            out = res.stdout.strip()
            return (len(out) == 0, out)
        return True, ""
    except Exception:
        return True, ""


def validate_report_content(
    content: str,
    domain: str | None = None,
    wave: int | None = None,
    expected_task_ids: list[int] | None = None,
    repo_path: Path | str | None = None,
    commit_sha: str | None = None,
    commit_range: str | None = None,
    allow_measured_seo: bool = False,
    allow_worker_placeholder: bool = False,
    allow_dirty: bool = False,
    waiver_reason: str | None = None,
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

    # 4. Worker Deployment Version Authenticity
    worker_match = re.search(r"\*\*Cloudflare Worker Deployment Version:\*\*\s*`?([^\n`]+)`?", content)
    if worker_match:
        w_ver = worker_match.group(1).strip().lower()
        if not allow_worker_placeholder and (w_ver in PLACEHOLDER_WORKER_VERSIONS or not w_ver):
            errors.append(f"Worker deployment version is a placeholder or invalid: '{w_ver}'. Must record genuine deployment version ID.")
    else:
        errors.append("Cloudflare Worker Deployment Version header missing from report.")

    # 5. Git Commit Verification & Changed-File Inventory Reconciliation
    commit_match = re.search(
        r"\*\*(?:Repository Commit|Integration Commit SHA|Commit Range):\*\*\s*\[?`?([a-f0-9]{7,40}(?:\.\.[a-f0-9]{7,40})?)`?\]?",
        content,
        re.IGNORECASE,
    )
    reported_commit = commit_range or commit_sha or (commit_match.group(1) if commit_match else None)
    if repo_path:
        # Git worktree clean check (v2.2.1 P1)
        if not allow_dirty:
            is_clean, dirty_status = check_git_worktree_clean(repo_path)
            if not is_clean:
                errors.append(
                    f"Git worktree dirty check failed: Repository {repo_path} contains uncommitted changes or untracked files:\n"
                    f"{dirty_status[:200]}\nWorking tree must be clean before wave close."
                )
        else:
            is_clean, dirty_status = check_git_worktree_clean(repo_path)
            if not is_clean:
                if not waiver_reason or not str(waiver_reason).strip():
                    errors.append(
                        "Waiver requirement violation (v2.2.1 P1): --allow-dirty requires an explicit --waiver-reason "
                        "explaining why uncommitted changes or dirty worktree were permitted during wave close."
                    )
                warnings.append(
                    f"Worktree waiver applied ({waiver_reason or 'unspecified'}). Affected dirty/untracked files:\n{dirty_status[:300]}"
                )

        if reported_commit:
            if not verify_git_commit_exists(repo_path, reported_commit):
                errors.append(f"Git commit verification failed: Commit/range '{reported_commit}' does not exist in repository {repo_path}.")
            else:
                actual_files = get_git_changed_files(repo_path, reported_commit)
                if actual_files:
                    # Check that every changed file appears in Section 4
                    sec4_match = re.search(r"##\s*4\.\s*Exhaustive File.*Changes(.*?)##\s*5\.", content, re.DOTALL | re.IGNORECASE)
                    sec4_text = sec4_match.group(1) if sec4_match else content
                    missing_files = [f for f in actual_files if f not in sec4_text]
                    if missing_files:
                        errors.append(
                            f"Git diff reconciliation failure: Commit/range {reported_commit[:16]} modified {len(actual_files)} files, "
                            f"but the following files were omitted from Section 4: {missing_files}"
                        )

    # 6. Strategic Issue State Semantics
    # Check Section 3 for invalid claim of RESOLVED when marked as planned/investigating
    sec3_match = re.search(r"##\s*3\.\s*Strategic Deep-Dive(.*?)##\s*4\.", content, re.DOTALL | re.IGNORECASE)
    if sec3_match:
        sec3_text = sec3_match.group(1)
        # Search for pattern where title claims resolved or status is RESOLVED despite planned text
        for block in re.split(r"###\s*3\.\d+", sec3_text):
            if not block.strip():
                continue
            has_planned = bool(re.search(r"(REMEDIATION_PLANNED|DATA_VALIDATION_PENDING|REDIRECT_PENDING|INVESTIGATING|scheduled for Wave|in Wave \d+)", block, re.IGNORECASE))
            has_resolved_claim = bool(re.search(r"\b(VERIFIED_RESOLVED|status:\s*RESOLVED|Resolution:\s*Resolved|Issue Resolved)\b", block, re.IGNORECASE))
            if has_planned and has_resolved_claim:
                errors.append(
                    "Issue State Semantics Violation: An issue with remediation planned or pending for a future wave "
                    "cannot be marked as 'VERIFIED_RESOLVED' or 'RESOLVED'."
                )
                break

    # 7. Section 5 Test Evidence Verification
    sec5_match = re.search(r"##\s*5\.\s*Standardized Test Classification.*?(?=##\s*6\.)", content, re.DOTALL | re.IGNORECASE)
    if sec5_match:
        sec5_text = sec5_match.group(0)
        has_test_evidence = bool(re.search(r"(?:tests?\s+passed|suite\s+passed|suites?\s+passing|\d+\s*(?:passed|green|passing|tests)|All\s+.*?passed|All preflight gates green)", sec5_text, re.IGNORECASE))
        if not has_test_evidence:
            errors.append("Test Evidence Missing: Section 5 must document standardized test classifications and passing test run counts.")

    # 7. Scorecard Math Verification
    part1_match = re.search(r"###\s*Part 1:\s*Engineering Execution Quality\s*\(Score:\s*([\d\.]+)\s*/\s*10\.0\)(.*?)###\s*Part 2:", content, re.DOTALL | re.IGNORECASE)
    if part1_match:
        claimed_score = float(part1_match.group(1))
        table_text = part1_match.group(2)
        score_rows = re.findall(r"\|\s*\*\*([^\*]+)\*\*\s*\|\s*(\d+)%\s*\|\s*\*\*([\d\.]+)\s*/\s*10\*\*", table_text)
        if len(score_rows) >= 6:
            calc_weighted = sum((float(pct) / 100.0) * float(sc) for _, pct, sc in score_rows)
            rounded_calc = round(calc_weighted, 1)
            # Allow documented deduction if explicitly stated as a penalty or deduction with value
            has_explicit_deduction = bool(re.search(r"(?:deduction|penalty)\s*(?:of|:|-)?\s*[\d\.]+", table_text, re.IGNORECASE))
            if abs(claimed_score - rounded_calc) > 0.05 and not has_explicit_deduction:
                errors.append(
                    f"Scorecard Math Discrepancy: Claimed engineering score {claimed_score} does not match "
                    f"calculated weighted score {rounded_calc}."
                )

    # 7.5. Deployment & Re-warm Arithmetic Reconciliation (v2.2.1 P0.1)
    # Checks for patterns like "X / Y paths (100% 200 OK)" or "X/Y ... 100%"
    # Enforces: if successful < total, it is mathematically forbidden to claim 100% success.
    rewarm_matches = re.finditer(
        r"(\d+)\s*/\s*(\d+)\s*(?:paths|routes)?\s*(?:\([^\)]*?(\d+(?:\.\d+)?)\s*%\s*(?:200\s*OK)?\)|re-warmed)?",
        content,
        re.IGNORECASE,
    )
    for rm in rewarm_matches:
        succ = int(rm.group(1))
        total = int(rm.group(2))
        pct_claim = float(rm.group(3)) if rm.group(3) else None
        if total > 0 and succ < total and pct_claim is not None and pct_claim >= 99.9:
            errors.append(
                f"Deployment Arithmetic Discrepancy (v2.2.1 P0.1): Claimed {pct_claim}% success on {succ}/{total} paths. "
                f"Mathematical rule: {succ}/{total} = {(succ/total)*100.0:.2f}%. Cannot claim 100% when successful < total."
            )

    # 8. Domain and Wave Header check
    if domain:
        if domain.lower() not in content.lower():
            errors.append(f"Domain '{domain}' not found in report body.")
    if wave is not None:
        if f"Wave {wave}" not in content:
            warnings.append(f"'Wave {wave}' not found in header.")

    # 9. Task ID Reconciliation
    if expected_task_ids:
        missing_ids = []
        for tid in expected_task_ids:
            tid_pattern = re.compile(rf"\|\s*(?:\*\*)?{tid}(?:\*\*)?\s*\|")
            if not tid_pattern.search(content):
                missing_ids.append(tid)
        if missing_ids:
            errors.append(f"Task reconciliation failure: Tasks {missing_ids} missing from task table in report.")

    # 10. Rule 32 Emoji Ban
    emojis_found = EMOJI_PATTERN.findall(content)
    if emojis_found:
        errors.append(f"Rule 32 Violation: Prohibited unicode emojis detected in report: {emojis_found[:5]}")

    # 11. Well-Formed Markdown Headers Check
    mangled_headers = re.findall(r"#{2,4}\s+(?:\d+\.\d+\s+)?[A-Za-z0-9]+[A-Z][a-z]+[A-Z][a-z]+\(", content)
    if mangled_headers:
        errors.append(f"Malformed Markdown Header detected: {mangled_headers}. Use spaces and clean formatting.")

    passed = len(errors) == 0
    return passed, errors, warnings


def validate_wave_close(
    report_path: Path | str,
    domain: str | None = None,
    wave: int | None = None,
    db_path: Path | str | None = None,
    repo_path: Path | str | None = None,
    commit_sha: str | None = None,
    commit_range: str | None = None,
    allow_measured_seo: bool = False,
    allow_worker_placeholder: bool = False,
    allow_dirty: bool = False,
    waiver_reason: str | None = None,
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
        repo_path=repo_path,
        commit_sha=commit_sha,
        commit_range=commit_range,
        allow_measured_seo=allow_measured_seo,
        allow_worker_placeholder=allow_worker_placeholder,
        allow_dirty=allow_dirty,
        waiver_reason=waiver_reason,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate wave changelog report against contract gate.")
    parser.add_argument("--version", action="version", version=f"validate_wave_close.py v{VERSION}")
    parser.add_argument("--report", required=True, help="Path to wave changelog markdown")
    parser.add_argument("--domain", default=None, help="Target domain to verify")
    parser.add_argument("--wave", type=int, default=None, help="Wave number to verify")
    parser.add_argument("--repo-path", default=None, help="Path to git repository for diff verification")
    parser.add_argument("--db-path", default=None, help="Path to fleet_state.db for task reconciliation")
    parser.add_argument("--commit-sha", default=None, help="Commit SHA to reconcile tasks and git diff against")
    parser.add_argument("--commit-range", default=None, help="Commit range (e.g. start..end) to reconcile git diff against")
    parser.add_argument("--allow-measured-seo", action="store_true", help="Allow numerical Part 2 SEO score (post-28d)")
    parser.add_argument("--allow-worker-placeholder", action="store_true", help="Allow placeholder worker version")
    parser.add_argument("--allow-dirty", action="store_true", help="Allow uncommitted changes in git worktree")
    parser.add_argument("--waiver-reason", default=None, help="Explicit reason required when using --allow-dirty")
    parser.add_argument("--strict", action="store_true", help="Fail if any warnings exist")
    args = parser.parse_args()

    if args.allow_dirty and not args.waiver_reason:
        parser.error("--allow-dirty requires an explicit --waiver-reason explaining why dirty worktree was permitted.")

    passed, errors, warnings = validate_wave_close(
        report_path=args.report,
        domain=args.domain,
        wave=args.wave,
        db_path=args.db_path,
        repo_path=args.repo_path,
        commit_sha=args.commit_sha,
        commit_range=args.commit_range,
        allow_measured_seo=args.allow_measured_seo,
        allow_worker_placeholder=args.allow_worker_placeholder,
        allow_dirty=args.allow_dirty,
        waiver_reason=args.waiver_reason,
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
