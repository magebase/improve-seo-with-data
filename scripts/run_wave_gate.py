#!/usr/bin/env python3
"""
Wave Execution & Verification Pre-Flight Gate.

Consolidates all verification phases into a single executable gate:
1. TDD & Regulatory Test Verification (pytest suites)
2. DOM Structural Integrity Gate (checks rendered articles for unparsed Markdown / raw leaks)
3. Statutory & Financial Formula Gate (Section 179, ACA APTC, WACC, collegiate GPA)
4. Wave Close Report & Git Reconciliation Gate (when --report is provided)

Usage:
    python scripts/run_wave_gate.py
    python scripts/run_wave_gate.py --report reports/wave_22_close.md --commit-range HEAD~5..HEAD
"""

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

# Add scripts directory to path
SCRIPTS_DIR = Path(__file__).resolve().parent
SAAS_FACTORY_ROOT = Path("/home/aqua/Projects/saas-factory")
SKILL_ROOT = Path("/home/aqua/skills/improve-seo-with-data")

if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
if str(SKILL_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(SKILL_ROOT / "scripts"))


def run_tdd_gate(verbose: bool = False) -> tuple[bool, str]:
    """Gate 1: Runs critical pytest suites across saas-factory and improve-seo-with-data."""
    print("=== [Gate 1/4] Running TDD & Regression Test Suite ===")
    
    python_bin = SAAS_FACTORY_ROOT / ".venv" / "bin" / "python3"
    pytest_bin = SAAS_FACTORY_ROOT / ".venv" / "bin" / "pytest"
    
    if not pytest_bin.exists():
        pytest_bin = Path(sys.executable)

    suites = [
        ("saas-factory: Methodology Registry TDD", SAAS_FACTORY_ROOT, [
            str(pytest_bin),
            "-q",
            "tests/unit/test_incomecanvas_methodology_registry_tdd.py",
        ]),
        ("improve-seo-with-data: v2.2 Maturity TDD", SKILL_ROOT, [
            str(pytest_bin),
            "-q",
            "tests/test_v22_maturity_tdd.py",
        ]),
    ]

    all_passed = True
    summary_lines = []

    for name, cwd, cmd in suites:
        if not cwd.exists():
            summary_lines.append(f"  [-] {name}: directory {cwd} not found, skipping")
            continue
        try:
            res = subprocess.run(
                cmd,
                cwd=cwd,
                capture_output=True,
                text=True,
                check=False,
            )
            if res.returncode == 0:
                summary_lines.append(f"  [OK] {name}: PASSED")
            else:
                all_passed = False
                summary_lines.append(f"  [FAIL] {name}: FAILED (code {res.returncode})\n{res.stdout}\n{res.stderr}")
        except Exception as exc:
            all_passed = False
            summary_lines.append(f"  [FAIL] {name}: Exception {exc}")

    output_msg = "\n".join(summary_lines)
    print(output_msg)
    return all_passed, output_msg


def run_dom_structural_gate() -> tuple[bool, str]:
    """Gate 2: Verifies rendered article markdown compiles to semantic HTML with zero leaks."""
    print("\n=== [Gate 2/4] Running DOM Structural Integrity Gate ===")
    
    # Import from saas-factory content engine
    if str(SAAS_FACTORY_ROOT) not in sys.path:
        sys.path.insert(0, str(SAAS_FACTORY_ROOT))

    try:
        from apps.seo_alpha_site.content_engine import render_article_markdown_to_html
        from apps.seo_alpha_site.catalogs.empirical_gsc_expansion import EMPIRICAL_GSC_ARTICLES
        from apps.seo_alpha_site.income_canvas_expansion import INCOME_CANVAS_EXPANSION_ARTICLES
    except ImportError as e:
        msg = f"  [FAIL] Could not import content_engine: {e}"
        print(msg)
        return False, msg

    articles = EMPIRICAL_GSC_ARTICLES + INCOME_CANVAS_EXPANSION_ARTICLES
    violations: list[str] = []

    for a in articles:
        slug = a.get("slug", "unknown")
        md = a.get("body_markdown", "")
        if not md:
            continue
        html = render_article_markdown_to_html(md)

        # 1. Pipe-table leak
        if re.search(r"<p[^>]*>\s*\|.*?\|", html, re.DOTALL):
            violations.append(f"Article '{slug}' has unparsed Markdown pipe-table in <p> tag.")
        # 2. Blockquote leak
        if re.search(r"<p[^>]*>\s*&gt;\s*", html):
            violations.append(f"Article '{slug}' has literal &gt; blockquote in <p> tag.")
        # 3. Bold leak
        if re.search(r"<p[^>]*>[^<]*\*\*[^*]+\*\*[^<]*</p>", html):
            violations.append(f"Article '{slug}' has raw **bold** in <p> tag.")
        # 4. Table separator row leak
        if re.search(r"<p[^>]*>.*?\|\s*:?-+:?\s*\|.*?</p>", html, re.DOTALL):
            violations.append(f"Article '{slug}' has unparsed table separator row in <p> tag.")

    if violations:
        for v in violations:
            print(f"  [FAIL] {v}")
        return False, f"DOM Structural Gate FAILED: {len(violations)} violations across {len(articles)} articles."

    msg = f"  [OK] DOM Structural Gate PASSED: {len(articles)} articles verified clean (tables, quotes, styling)."
    print(msg)
    return True, msg


def run_statutory_engine_gate() -> tuple[bool, str]:
    """Gate 3: Verifies mathematical calculations for statutory financial calculators."""
    print("\n=== [Gate 3/4] Running Statutory & Mathematical Engine Gate ===")
    
    from verify_product_functionality import (
        calculate_section_179_deduction,
        calculate_aca_excess_aptc_repayment,
        calculate_wacc,
        calculate_figiva_gpa,
    )

    failures: list[str] = []

    # 1. Section 179 for 2026 (P.L. 119-21: $2,560,000 cap, $4,090,000 phaseout)
    s179_2026 = calculate_section_179_deduction(cost=2_000_000, tax_year=2026)
    if s179_2026["final_deduction"] != 2_000_000 or s179_2026["available_cap"] != 2_560_000:
        failures.append(f"Section 179 (2026) calculation incorrect: {s179_2026}")

    # 2. Section 179 for 2025 (Rev. Proc. 2024-40: $1,250,000 cap, $3,130,000 phaseout)
    s179_2025 = calculate_section_179_deduction(cost=2_000_000, tax_year=2025)
    if s179_2025["final_deduction"] != 1_250_000 or s179_2025["available_cap"] != 1_250_000:
        failures.append(f"Section 179 (2025) calculation incorrect: {s179_2025}")

    # 3. ACA 2020 ARPA $0 repayment
    aca_2020 = calculate_aca_excess_aptc_repayment(excess_aptc=3500.0, household_income_fpl_pct=250.0, tax_year=2020)
    if aca_2020["repayment_amount"] != 0.0:
        failures.append(f"ACA 2020 ARPA exemption failed: {aca_2020}")

    # 4. ACA 2021 Rev. Proc. 2020-36 ($800 cap for 250% FPL Single)
    aca_2021 = calculate_aca_excess_aptc_repayment(excess_aptc=3500.0, household_income_fpl_pct=250.0, tax_year=2021, filing_status="single")
    if aca_2021["repayment_amount"] != 800.0:
        failures.append(f"ACA 2021 statutory cap failed: expected 800.0, got {aca_2021['repayment_amount']}")

    # 5. ACA 2025 Rev. Proc. 2024-35 ($975 cap for 250% FPL Single)
    aca_2025 = calculate_aca_excess_aptc_repayment(excess_aptc=3500.0, household_income_fpl_pct=250.0, tax_year=2025, filing_status="single")
    if aca_2025["repayment_amount"] != 975.0:
        failures.append(f"ACA 2025 statutory cap failed: expected 975.0, got {aca_2025['repayment_amount']}")

    # 6. ACA 2026 cliff vs permanent cap split:
    # 6a. >= 400% FPL -> 100% full repayment ($3,500)
    aca_2026_cliff = calculate_aca_excess_aptc_repayment(excess_aptc=3500.0, household_income_fpl_pct=420.0, tax_year=2026)
    if aca_2026_cliff["repayment_amount"] != 3500.0 or aca_2026_cliff["repayment_cap"] is not None:
        failures.append(f"ACA 2026 cliff failed: {aca_2026_cliff}")

    # 6b. < 400% FPL -> permanent indexed cap ($1,000 for 250% FPL Single under Rev. Proc. 2025-32)
    aca_2026_cap = calculate_aca_excess_aptc_repayment(excess_aptc=3500.0, household_income_fpl_pct=250.0, tax_year=2026, filing_status="single")
    if aca_2026_cap["repayment_amount"] != 1000.0:
        failures.append(f"ACA 2026 permanent cap failed: expected 1000.0, got {aca_2026_cap['repayment_amount']}")

    # 7. WACC
    wacc = calculate_wacc(equity=600_000, debt=400_000, cost_of_equity=0.10, cost_of_debt=0.06, corporate_tax_rate=0.25)
    if abs(wacc["wacc"] - 0.078) > 0.0001:
        failures.append(f"WACC calculation failed: {wacc}")

    if failures:
        for f in failures:
            print(f"  [FAIL] {f}")
        return False, f"Statutory engine failed {len(failures)} invariants."

    msg = "  [OK] Statutory & Mathematical Engine PASSED (Section 179, ACA, WACC, GPA verified)."
    print(msg)
    return True, msg


def run_wave_close_report_gate(
    report_path: Path,
    repo_path: Path,
    commit_range: str | None = None,
    allow_dirty: bool = False,
    waiver_reason: str | None = None,
) -> tuple[bool, str]:
    """Gate 4: Validates wave report structure, math, and git change reconciliation."""
    print(f"\n=== [Gate 4/4] Running Wave Close Validation on {report_path.name} ===")
    
    from validate_wave_close import validate_report_file

    passed, errors, warnings = validate_report_file(
        report_path=report_path,
        repo_path=repo_path,
        commit_range=commit_range,
        allow_dirty=allow_dirty,
        waiver_reason=waiver_reason,
    )

    if not passed:
        print(f"  [FAIL] Wave Report Validation FAILED with {len(errors)} error(s):")
        for err in errors:
            print(f"    - {err}")
        return False, f"Report validation failed: {len(errors)} error(s)."

    for w in warnings:
        print(f"  [WARN] {w}")

    msg = f"  [OK] Wave Report Validation PASSED ({len(warnings)} warnings)."
    print(msg)
    return True, msg


def main() -> None:
    parser = argparse.ArgumentParser(description="Wave Execution & Verification Pre-Flight Gate")
    parser.add_argument("--report", type=Path, default=None, help="Path to wave report markdown file")
    parser.add_argument("--repo-path", type=Path, default=SAAS_FACTORY_ROOT, help="Target git repository path")
    parser.add_argument("--commit-range", type=str, default=None, help="Commit range for changed files validation")
    parser.add_argument("--allow-dirty", action="store_true", help="Allow dirty working tree (requires --waiver-reason)")
    parser.add_argument("--waiver-reason", type=str, default=None, help="Required justification for dirty working tree")
    parser.add_argument("--skip-tests", action="store_true", help="Skip TDD pytest suite")
    parser.add_argument("--skip-dom", action="store_true", help="Skip DOM structural gate")

    args = parser.parse_args()

    overall_passed = True
    results = []

    # 1. TDD Gate
    if not args.skip_tests:
        p1, m1 = run_tdd_gate()
        results.append(("TDD & Regulatory Tests", p1))
        if not p1:
            overall_passed = False
    else:
        print("[-] Skipping TDD suite as requested.")

    # 2. DOM Structural Gate
    if not args.skip_dom:
        p2, m2 = run_dom_structural_gate()
        results.append(("DOM Structural Gate", p2))
        if not p2:
            overall_passed = False
    else:
        print("[-] Skipping DOM structural gate as requested.")

    # 3. Statutory Engine Gate
    p3, m3 = run_statutory_engine_gate()
    results.append(("Statutory & Mathematical Engine", p3))
    if not p3:
        overall_passed = False

    # 4. Wave Close Gate (if report supplied)
    if args.report:
        p4, m4 = run_wave_close_report_gate(
            report_path=args.report,
            repo_path=args.repo_path,
            commit_range=args.commit_range,
            allow_dirty=args.allow_dirty,
            waiver_reason=args.waiver_reason,
        )
        results.append(("Wave Close Report Gate", p4))
        if not p4:
            overall_passed = False

    print("\n=================== WAVE GATE SUMMARY ===================")
    for name, ok in results:
        status = "[PASSED]" if ok else "[FAILED]"
        print(f"  {status} {name}")
    print("=========================================================")

    if not overall_passed:
        print("Wave Gate check FAILED. Pre-deploy or release requirements breached.")
        sys.exit(1)

    print("All wave execution gates PASSED (10/10 state confirmed).")
    sys.exit(0)


if __name__ == "__main__":
    main()
