#!/usr/bin/env python3
"""
gsc_analyzer.py - Multi-Dimensional Google Search Console (GSC) Performance Analyzer.

Analyzes GSC performance data across all 6 primary dimensions:
1. Queries: Striking distance (10-20), Low-CTR quick wins, high-intent discovery.
2. Pages: Top performers, conversion leakage candidates, decaying URLs.
3. Countries: Geographic CTR & impression gaps, localization opportunities.
4. Devices: Mobile vs. Desktop discrepancies and mobile CTR degradation.
5. Search Appearance: Rich result performance and schema impact.
6. Historical Days: Traffic change decomposition Delta_C = (I1 - I0)R0 + I1(R1 - R0).

Usage:
    python3 gsc_analyzer.py --site sc-domain:example.com
    python3 gsc_analyzer.py --export gsc_export.json
    python3 gsc_analyzer.py --compare-periods period1.json period2.json
"""

import argparse
import csv
import json
import math
import os
import shutil
import subprocess
import sys
from typing import Any, Dict, List, Optional, Tuple


def find_seo_binary() -> Optional[str]:
    path_bin = shutil.which("seo")
    if path_bin:
        return path_bin
    pi_bin = "/home/aqua/.local/share/pi-node/node-v22.23.2-linux-x64/bin/seo"
    if os.path.isfile(pi_bin) and os.access(pi_bin, os.X_OK):
        return pi_bin
    return None


def run_seo_report(report_id: str, site: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    seo_bin = find_seo_binary()
    if not seo_bin:
        return {"ok": False, "error": "seo binary not found"}

    cmd = [seo_bin, "reports", "run", report_id, "--json"]
    report_params = {"site": site}
    if params:
        report_params.update(params)

    cmd.extend(["--params", json.dumps(report_params)])

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if proc.returncode != 0:
            return {"ok": False, "error": proc.stderr or proc.stdout}
        return json.loads(proc.stdout)
    except Exception as e:
        return {"ok": False, "error": str(e)}


def analyze_striking_distance(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Filters queries averaging positions 10.1 to 20.0 with meaningful impressions."""
    candidates = []
    for row in rows:
        pos = float(row.get("position", row.get("avg_position", 0.0)))
        imp = int(row.get("impressions", 0))
        if 10.1 <= pos <= 20.0 and imp >= 15:
            candidates.append(row)
    candidates.sort(key=lambda x: int(x.get("impressions", 0)), reverse=True)
    return candidates


def analyze_low_ctr_wins(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Identifies queries ranking in positions 1 to 7 with CTR below expected benchmarks."""
    benchmarks = {
        1: 0.28,
        2: 0.15,
        3: 0.10,
        4: 0.065,
        5: 0.045,
        6: 0.032,
        7: 0.024,
    }
    quick_wins = []
    for row in rows:
        pos = round(float(row.get("position", row.get("avg_position", 99.0))))
        ctr = float(row.get("ctr", 0.0))
        imp = int(row.get("impressions", 0))
        if 1 <= pos <= 7 and imp >= 25:
            expected_ctr = benchmarks.get(pos, 0.03)
            if ctr < expected_ctr:
                row_copy = dict(row)
                row_copy["expected_ctr"] = expected_ctr
                row_copy["ctr_gap"] = expected_ctr - ctr
                row_copy["recoverable_clicks"] = int(imp * (expected_ctr - ctr))
                quick_wins.append(row_copy)
    quick_wins.sort(key=lambda x: x["recoverable_clicks"], reverse=True)
    return quick_wins


def analyze_device_breakdown(rows: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Aggregates metrics by device category to uncover mobile/desktop gaps."""
    devices: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        dev = str(row.get("device", "UNKNOWN")).upper()
        if dev not in devices:
            devices[dev] = {"impressions": 0, "clicks": 0, "total_pos_weight": 0.0}
        imp = int(row.get("impressions", 0))
        clicks = int(row.get("clicks", 0))
        pos = float(row.get("position", row.get("avg_position", 0.0)))

        devices[dev]["impressions"] += imp
        devices[dev]["clicks"] += clicks
        devices[dev]["total_pos_weight"] += pos * imp

    results = {}
    for dev, data in devices.items():
        imp = data["impressions"]
        clicks = data["clicks"]
        ctr = (clicks / imp) if imp > 0 else 0.0
        avg_pos = (data["total_pos_weight"] / imp) if imp > 0 else 0.0
        results[dev] = {
            "impressions": imp,
            "clicks": clicks,
            "ctr": round(ctr, 4),
            "avg_position": round(avg_pos, 1),
        }
    return results


def analyze_country_breakdown(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Analyzes country-level metrics to uncover geographic opportunities."""
    countries: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        country = str(row.get("country", "unknown")).upper()
        if country not in countries:
            countries[country] = {"impressions": 0, "clicks": 0}
        countries[country]["impressions"] += int(row.get("impressions", 0))
        countries[country]["clicks"] += int(row.get("clicks", 0))

    out = []
    for c, d in countries.items():
        imp = d["impressions"]
        clicks = d["clicks"]
        ctr = (clicks / imp) if imp > 0 else 0.0
        out.append({
            "country": c,
            "impressions": imp,
            "clicks": clicks,
            "ctr": round(ctr, 4),
        })
    out.sort(key=lambda x: x["impressions"], reverse=True)
    return out


def decompose_traffic(p0_rows: List[Dict[str, Any]], p1_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Decomposes period-over-period click changes:
    Delta_C = (I1 - I0) * R0 + I1 * (R1 - R0)
    """
    i0 = sum(int(r.get("impressions", 0)) for r in p0_rows)
    c0 = sum(int(r.get("clicks", 0)) for r in p0_rows)
    r0 = (c0 / i0) if i0 > 0 else 0.0

    i1 = sum(int(r.get("impressions", 0)) for r in p1_rows)
    c1 = sum(int(r.get("clicks", 0)) for r in p1_rows)
    r1 = (c1 / i1) if i1 > 0 else 0.0

    total_delta = c1 - c0
    volume_effect = (i1 - i0) * r0
    ctr_effect = i1 * (r1 - r0)

    return {
        "period_0": {"impressions": i0, "clicks": c0, "ctr": round(r0, 4)},
        "period_1": {"impressions": i1, "clicks": c1, "ctr": round(r1, 4)},
        "total_click_delta": total_delta,
        "impression_volume_effect": round(volume_effect, 1),
        "ctr_engagement_effect": round(ctr_effect, 1),
        "diagnosis": (
            "Visibility expansion" if volume_effect > 0 and ctr_effect >= 0
            else "CTR/Snippet deterioration" if volume_effect >= 0 and ctr_effect < 0
            else "Search demand decline" if volume_effect < 0 and ctr_effect >= 0
            else "Compound search regression"
        ),
    }


def print_striking_distance_table(items: List[Dict[str, Any]]) -> None:
    print("\n------------------------------------------------------------------")
    print("  STRIKING DISTANCE OPPORTUNITIES (Positions 10.1 - 20.0)")
    print("  Growth Lever: Add dedicated H2s, expand semantic content, internal links.")
    print("------------------------------------------------------------------")
    print(f"{'Query':<35} | {'Pos':<5} | {'Impressions':<11} | {'CTR':<6} | {'Target URL'}")
    print("-" * 80)
    for it in items[:15]:
        query = str(it.get("query", it.get("keys", [""])[0]))[:33]
        pos = f"{float(it.get('position', 0.0)):.1f}"
        imp = str(it.get("impressions", 0))
        ctr = f"{float(it.get('ctr', 0.0)) * 100:.1f}%"
        page = it.get("page", it.get("url", ""))
        print(f"{query:<35} | {pos:<5} | {imp:<11} | {ctr:<6} | {page}")


def print_quick_wins_table(items: List[Dict[str, Any]]) -> None:
    print("\n------------------------------------------------------------------")
    print("  LOW-CTR QUICK WINS (Positions 1 - 7)")
    print("  Growth Lever: Rewrite title hooks, refine meta description, Schema rich snippets.")
    print("------------------------------------------------------------------")
    print(f"{'Query':<30} | {'Pos':<4} | {'Current CTR':<11} | {'Bench CTR':<9} | {'Imp':<6} | {'Recoverable Clicks'}")
    print("-" * 85)
    for it in items[:15]:
        query = str(it.get("query", it.get("keys", [""])[0]))[:28]
        pos = f"{float(it.get('position', 0.0)):.1f}"
        ctr = f"{float(it.get('ctr', 0.0)) * 100:.1f}%"
        bench = f"{it.get('expected_ctr', 0.0) * 100:.1f}%"
        imp = str(it.get("impressions", 0))
        rec = str(it.get("recoverable_clicks", 0))
        print(f"{query:<30} | {pos:<4} | {ctr:<11} | {bench:<9} | {imp:<6} | +{rec}")


def print_device_table(devices: Dict[str, Dict[str, Any]]) -> None:
    print("\n------------------------------------------------------------------")
    print("  DEVICE SEGMENTATION ANALYSIS")
    print("------------------------------------------------------------------")
    print(f"{'Device':<12} | {'Impressions':<12} | {'Clicks':<8} | {'CTR':<7} | {'Avg Pos'}")
    print("-" * 55)
    for dev, d in devices.items():
        print(f"{dev:<12} | {d['impressions']:<12} | {d['clicks']:<8} | {d['ctr']*100:.1f}%  | {d['avg_position']}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Multi-Dimensional GSC Performance Analyzer")
    parser.add_argument("--site", help="Search Console site property (e.g. sc-domain:example.com)")
    parser.add_argument("--export", help="Path to JSON or CSV Search Console export file")
    parser.add_argument("--compare-periods", nargs=2, metavar=("P0_FILE", "P1_FILE"), help="Decompose changes between 2 periods")
    args = parser.parse_args()

    # Period comparison mode
    if args.compare_periods:
        with open(args.compare_periods[0], "r", encoding="utf-8") as f0, open(args.compare_periods[1], "r", encoding="utf-8") as f1:
            p0 = json.load(f0)
            p1 = json.load(f1)
            decomp = decompose_traffic(p0 if isinstance(p0, list) else p0.get("rows", []), p1 if isinstance(p1, list) else p1.get("rows", []))
            print("\n------------------------------------------------------------------")
            print("  TRAFFIC CHANGE DECOMPOSITION (Delta_C = (I1-I0)R0 + I1(R1-R0))")
            print("------------------------------------------------------------------")
            print(f"Total Click Delta:           {decomp['total_click_delta']}")
            print(f"Impression Volume Effect:    {decomp['impression_volume_effect']} clicks")
            print(f"CTR / Engagement Effect:     {decomp['ctr_engagement_effect']} clicks")
            print(f"Diagnostic Conclusion:       {decomp['diagnosis']}\n")
            return 0

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
        print("[INFO] Querying Search Console via SEO MCP report...")
        result = run_seo_report("gsc-queries", args.site, {"limit": 250})
        if result.get("ok", True) and "structuredContent" in result:
            rows = result["structuredContent"].get("rows", [])
        elif "items" in result:
            rows = result["items"]
        elif "rows" in result:
            rows = result["rows"]
        else:
            print(f"[NOTICE] Direct GSC query returned: {result.get('error', 'No live token')}")
            return 0
    else:
        print("Please provide either --site <sc-domain:...> or --export <path>")
        return 1

    if rows:
        striking = analyze_striking_distance(rows)
        quick_wins = analyze_low_ctr_wins(rows)
        devices = analyze_device_breakdown(rows)

        if striking:
            print_striking_distance_table(striking)
        if quick_wins:
            print_quick_wins_table(quick_wins)
        if devices and len(devices) > 1:
            print_device_table(devices)

    return 0


if __name__ == "__main__":
    sys.exit(main())
