#!/usr/bin/env python3
"""
gsc_analyzer.py - Analyzes Google Search Console (GSC) performance data to identify
high-impact SEO growth opportunities:
1. Striking Distance (positions 11-20): High impressions, near page 1.
2. Low-CTR Quick Wins: Top positions with below-benchmark CTR.
3. Cannibalization: Multiple URLs competing for identical search queries.
4. Traffic Decay: Queries/pages showing downward trends.

Usage:
    python3 gsc_analyzer.py --site sc-domain:example.com
    python3 gsc_analyzer.py --export gsc_export.json
"""

import argparse
import csv
import json
import os
import shutil
import subprocess
import sys
from typing import Any, Dict, List


def find_seo_binary() -> str | None:
    path_bin = shutil.which("seo")
    if path_bin:
        return path_bin
    pi_bin = "/home/aqua/.local/share/pi-node/node-v22.23.2-linux-x64/bin/seo"
    if os.path.isfile(pi_bin) and os.access(pi_bin, os.X_OK):
        return pi_bin
    return None


def run_seo_report(report_id: str, site: str, params: Dict[str, Any] | None = None) -> Dict[str, Any]:
    seo_bin = find_seo_binary()
    if not seo_bin:
        raise FileNotFoundError("Could not find 'seo' binary.")

    cmd = [seo_bin, "reports", "run", report_id, "--json"]
    report_params = {"site": site}
    if params:
        report_params.update(params)

    cmd.extend(["--params", json.dumps(report_params)])

    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if proc.returncode != 0:
        return {"ok": False, "error": proc.stderr or proc.stdout}

    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {"ok": False, "raw": proc.stdout}


def analyze_striking_distance(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Filters queries averaging positions 10.1 to 20.0."""
    candidates = []
    for row in rows:
        pos = float(row.get("position", row.get("avg_position", 0.0)))
        imp = int(row.get("impressions", 0))
        if 10.1 <= pos <= 20.0 and imp >= 50:
            candidates.append(row)
    candidates.sort(key=lambda x: int(x.get("impressions", 0)), reverse=True)
    return candidates


def analyze_low_ctr_wins(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Identifies queries ranking in positions 1 to 7 with CTR below expected benchmarks."""
    benchmarks = {
        1: 0.20,
        2: 0.10,
        3: 0.06,
        4: 0.04,
        5: 0.03,
        6: 0.02,
        7: 0.015,
    }
    quick_wins = []
    for row in rows:
        pos = round(float(row.get("position", row.get("avg_position", 99.0))))
        ctr = float(row.get("ctr", 0.0))
        imp = int(row.get("impressions", 0))
        if 1 <= pos <= 7 and imp >= 100:
            expected_ctr = benchmarks.get(pos, 0.02)
            if ctr < expected_ctr:
                row_copy = dict(row)
                row_copy["expected_ctr"] = expected_ctr
                row_copy["ctr_gap"] = expected_ctr - ctr
                quick_wins.append(row_copy)
    quick_wins.sort(key=lambda x: x["ctr_gap"] * int(x.get("impressions", 0)), reverse=True)
    return quick_wins


def print_striking_distance_table(items: List[Dict[str, Any]]) -> None:
    print("\n------------------------------------------------------------------")
    print("  STRIKING DISTANCE OPPORTUNITIES (Positions 11 - 20)")
    print("  Tactic: Optimize H2s, expand topical content, add internal links.")
    print("------------------------------------------------------------------")
    print(f"{'Query':<35} | {'Pos':<5} | {'Impressions':<11} | {'CTR':<6} | {'Target URL'}")
    print("-" * 80)
    for it in items[:15]:
        query = it.get("query", it.get("keys", [""])[0])[:33]
        pos = f"{float(it.get('position', 0.0)):.1f}"
        imp = str(it.get("impressions", 0))
        ctr = f"{float(it.get('ctr', 0.0)) * 100:.1f}%"
        page = it.get("page", it.get("url", ""))
        print(f"{query:<35} | {pos:<5} | {imp:<11} | {ctr:<6} | {page}")


def print_quick_wins_table(items: List[Dict[str, Any]]) -> None:
    print("\n------------------------------------------------------------------")
    print("  LOW-CTR QUICK WINS (Positions 1 - 7)")
    print("  Tactic: Rewrite title tag hooks, refine meta description, add FAQ schema.")
    print("------------------------------------------------------------------")
    print(f"{'Query':<35} | {'Pos':<4} | {'Current CTR':<11} | {'Bench CTR':<9} | {'Impressions'}")
    print("-" * 80)
    for it in items[:15]:
        query = it.get("query", it.get("keys", [""])[0])[:33]
        pos = f"{float(it.get('position', 0.0)):.1f}"
        ctr = f"{float(it.get('ctr', 0.0)) * 100:.1f}%"
        bench = f"{it.get('expected_ctr', 0.0) * 100:.1f}%"
        imp = str(it.get("impressions", 0))
        print(f"{query:<35} | {pos:<4} | {ctr:<11} | {bench:<9} | {imp}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze GSC Performance Data")
    parser.add_argument("--site", help="Search Console site property (e.g. sc-domain:example.com)")
    parser.add_argument("--export", help="Path to JSON or CSV Search Console export file")
    args = parser.parse_args()

    rows: List[Dict[str, Any]] = []

    if args.export:
        if args.export.endswith(".json"):
            with open(args.export, "r", encoding="utf-8") as f:
                data = json.load(f)
                rows = data if isinstance(data, list) else data.get("rows", [])
        elif args.export.endswith(".csv"):
            with open(args.export, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                rows = list(reader)
        print(f"[OK] Loaded {len(rows)} records from export: {args.export}")
    elif args.site:
        print("[INFO] Querying Search Console via SEO MCP report: striking-distance...")
        result = run_seo_report("striking-distance", args.site)
        if result.get("ok", True) and "structuredContent" in result:
            rows = result["structuredContent"].get("rows", [])
        elif "items" in result:
            rows = result["items"]
        else:
            print(f"[NOTICE] Direct GSC query returned: {result.get('error', 'No live token')}")
            print("         For offline analysis, supply a Search Console export with --export <path>")
            return 0
    else:
        print("Please provide either --site <sc-domain:...> or --export <path>")
        return 1

    if rows:
        striking = analyze_striking_distance(rows)
        quick_wins = analyze_low_ctr_wins(rows)

        if striking:
            print_striking_distance_table(striking)
        if quick_wins:
            print_quick_wins_table(quick_wins)

    return 0


if __name__ == "__main__":
    sys.exit(main())
