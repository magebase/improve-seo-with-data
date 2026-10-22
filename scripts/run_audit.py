#!/usr/bin/env python3
"""
run_audit.py - Executes a data-driven technical and on-page SEO audit.
Leverages the 'seo' CLI to perform deep crawls or single-page inspections,
extracting actionable findings with priority scoring.

Usage:
    python3 run_audit.py --url https://example.com [--max-pages 50] [--output audit.json]
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
from typing import Any, Dict, List


def find_seo_binary() -> str:
    path_bin = shutil.which("seo")
    if path_bin:
        return path_bin
    pi_bin = "/home/aqua/.local/share/pi-node/node-v22.23.2-linux-x64/bin/seo"
    if os.path.isfile(pi_bin) and os.access(pi_bin, os.X_OK):
        return pi_bin
    raise FileNotFoundError("Could not locate 'seo' binary. Run: npm i -g seo")


def run_audit(url: str, actions_only: bool = True) -> Dict[str, Any]:
    seo_bin = find_seo_binary()
    cmd = [seo_bin, "report", "--url", url, "--json"]
    if actions_only:
        cmd.append("--actions-only")

    print(f"[INFO] Executing crawl audit on: {url}...")
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

    if proc.returncode != 0 and not proc.stdout:
        print(f"[ERROR] Audit failed: {proc.stderr}", file=sys.stderr)
        return {"ok": False, "error": proc.stderr}

    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        print(f"[ERROR] Failed to parse JSON response: {e}\nRaw output: {proc.stdout[:500]}", file=sys.stderr)
        return {"ok": False, "raw": proc.stdout}


def summarize_findings(audit_data: Dict[str, Any]) -> None:
    findings = audit_data.get("findings", {})
    items: List[Dict[str, Any]] = findings.get("items", [])
    counts = findings.get("counts", {})

    print("\n==================================================================")
    print("  AUDIT FINDINGS SUMMARY")
    print("==================================================================")
    print(f"Total Findings Returned: {counts.get('returned', len(items))}")
    print(f"High Severity: {counts.get('high', 0)} | Medium: {counts.get('medium', 0)} | Low: {counts.get('low', 0)}")
    print("------------------------------------------------------------------")

    for idx, item in enumerate(items, 1):
        finding_id = item.get("id", f"finding-{idx}")
        title = item.get("title", "Untitled finding")
        severity = item.get("severity", "medium").upper()
        category = item.get("category", "technical")
        action = item.get("action", item.get("recommendation", "Review and fix"))

        color_flag = "!" if severity == "HIGH" else "*" if severity == "MEDIUM" else "-"
        print(f"[{color_flag}] [{severity}] ({category}) [{finding_id}] {title}")
        print(f"    Action: {action}")
        affected_count = item.get("affectedCount", 0)
        if affected_count > 0:
            print(f"    Affected URLs: {affected_count}")
        print()

    print("==================================================================")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run technical SEO audit via SEO CLI")
    parser.add_argument("--url", required=True, help="Target URL to audit (e.g. https://example.com)")
    parser.add_argument("--all-findings", action="store_true", help="Include informational findings, not just actions")
    parser.add_argument("--output", help="Optional file path to write JSON output")
    args = parser.parse_args()

    data = run_audit(args.url, actions_only=not args.all_findings)
    summarize_findings(data)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        print(f"[OK] Full audit JSON saved to: {args.output}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
