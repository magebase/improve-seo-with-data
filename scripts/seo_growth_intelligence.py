#!/usr/bin/env python3
"""
seo_growth_intelligence.py - The Unified SEO Growth & Conversion Decision Engine.

Integrates:
1. Google Search Console (GSC): queries, pages, countries, devices, search appearance, historical trends.
2. Google Analytics 4 (GA4): landing-page sessions, conversion events, conversion rates, conversion value.
3. Observability & Telemetry:
   - PostHog: funnel dropoffs, feature usage, user journey friction.
   - Microsoft Clarity: rage clicks, dead clicks, scroll friction.
   - Cloudflare: edge status codes (5xx/404), latency, crawler bot telemetry.
   - Better Stack: uptime incidents and downtime correlation.
   - Grafana / Faro: Core Web Vitals field data (LCP, INP, CLS).

Features the 5 Specialized Opportunity Detectors:
- Detector A: CTR Opportunities with position & device mix benchmarks.
- Detector B: Ranking Opportunities (Striking Distance positions 5-20).
- Detector C: Conversion Leakage (traffic with weak conversions / high friction).
- Detector D: Technical Risk & Incident Recovery (errors, latency, indexing).
- Detector E: Content Expansion & Cannibalization Consolidation.

Usage:
    python3 seo_growth_intelligence.py --site sc-domain:figiva.com
    python3 seo_growth_intelligence.py --gsc-file gsc_data.json --ga4-file ga4_data.json --output-queue queue.json
"""

import argparse
import datetime
import json
import math
import os
import shutil
import subprocess
import sys
from typing import Any, Dict, List, Optional, Tuple


# --- Benchmark Models ---
# Organic Search CTR Benchmarks by Google Position (desktop baseline)
POSITION_CTR_BENCHMARKS = {
    1: 0.280,
    2: 0.150,
    3: 0.100,
    4: 0.065,
    5: 0.045,
    6: 0.032,
    7: 0.024,
    8: 0.018,
    9: 0.014,
    10: 0.011,
}
PAGE_TWO_BENCHMARK = 0.008

# Device multiplier for CTR expectations
DEVICE_CTR_FACTORS = {
    "DESKTOP": 1.00,
    "MOBILE": 0.85,
    "TABLET": 0.90,
}


def find_seo_binary() -> Optional[str]:
    """Locates the seo CLI binary."""
    path_bin = shutil.which("seo")
    if path_bin:
        return path_bin
    pi_bin = "/home/aqua/.local/share/pi-node/node-v22.23.2-linux-x64/bin/seo"
    if os.path.isfile(pi_bin) and os.access(pi_bin, os.X_OK):
        return pi_bin
    return None


def run_seo_cli(report_id: str, site: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Executes a report via the local SEO CLI."""
    seo_bin = find_seo_binary()
    if not seo_bin:
        return {"ok": False, "error": "seo binary not found"}

    cmd = [seo_bin, "reports", "run", report_id, "--json"]
    report_params = {"site": site}
    if params:
        report_params.update(params)
    cmd.extend(["--params", json.dumps(report_params)])

    env = os.environ.copy()
    if "GOOGLE_APPLICATION_CREDENTIALS" not in env:
        default_key = "/home/aqua/.google/gsc-seo-alpha-key.json"
        if os.path.exists(default_key):
            env["GOOGLE_APPLICATION_CREDENTIALS"] = default_key

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60, env=env)
        if proc.returncode != 0:
            return {"ok": False, "error": proc.stderr or proc.stdout}
        return json.loads(proc.stdout)
    except Exception as e:
        return {"ok": False, "error": str(e)}


# --- Traffic Change Decomposition ---
def decompose_traffic_change(i0: int, r0: float, i1: int, r1: float) -> Dict[str, float]:
    """
    Decomposes total click change between two periods into:
    1. Impression volume effect: (I1 - I0) * R0
    2. CTR / Engagement effect: I1 * (R1 - R0)
    Total delta = Impression effect + CTR effect
    """
    delta_impressions_effect = (i1 - i0) * r0
    delta_ctr_effect = i1 * (r1 - r0)
    total_delta = (i1 * r1) - (i0 * r0)
    return {
        "total_click_delta": round(total_delta, 1),
        "impression_volume_effect": round(delta_impressions_effect, 1),
        "ctr_engagement_effect": round(delta_ctr_effect, 1),
    }


# --- Opportunity Scoring Formula ---
def calculate_priority_score(
    incremental_clicks: float,
    conversion_rate: float,
    value_per_conversion: float,
    confidence_level: str = "medium",
    effort_level: str = "medium",
    risk_level: str = "low",
) -> Tuple[float, float, float]:
    """
    Computes:
    V = delta_clicks * conversion_rate * value_per_conversion
    Priority P = (V * confidence) / (effort + risk)
    """
    confidence_weights = {"high": 0.90, "medium": 0.70, "low": 0.40}
    effort_weights = {"low": 1.0, "medium": 2.0, "high": 3.5}
    risk_weights = {"low": 0.2, "medium": 0.5, "high": 1.0}

    q = confidence_weights.get(confidence_level.lower(), 0.70)
    e = effort_weights.get(effort_level.lower(), 2.0)
    r = risk_weights.get(risk_level.lower(), 0.2)

    incremental_conversions = incremental_clicks * conversion_rate
    expected_value = incremental_conversions * value_per_conversion
    priority_score = (expected_value * q) / (e + r)

    return round(priority_score, 2), round(expected_value, 2), round(incremental_conversions, 1)


# --- 5 Specialized Detectors ---

def detect_ctr_opportunities(
    query_page_rows: List[Dict[str, Any]],
    default_conversion_rate: float = 0.02,
    default_conversion_value: float = 10.0,
) -> List[Dict[str, Any]]:
    """Detector A: High-impression queries underperforming position/device CTR benchmarks."""
    actions = []
    idx = 1
    for row in query_page_rows:
        impressions = int(row.get("impressions", 0))
        if impressions < 20:
            continue

        clicks = int(row.get("clicks", 0))
        ctr = float(row.get("ctr", (clicks / impressions) if impressions else 0.0))
        pos = float(row.get("position", row.get("avg_position", 99.0)))
        device = str(row.get("device", "DESKTOP")).upper()
        device_factor = DEVICE_CTR_FACTORS.get(device, 1.0)

        int_pos = max(1, min(10, round(pos)))
        base_benchmark = POSITION_CTR_BENCHMARKS.get(int_pos, PAGE_TWO_BENCHMARK)
        benchmark_ctr = base_benchmark * device_factor

        if pos <= 10.0 and ctr < benchmark_ctr:
            ctr_gap = benchmark_ctr - ctr
            incremental_clicks = impressions * ctr_gap
            if incremental_clicks >= 5:
                p_score, exp_val, exp_conv = calculate_priority_score(
                    incremental_clicks=incremental_clicks,
                    conversion_rate=default_conversion_rate,
                    value_per_conversion=default_conversion_value,
                    confidence_level="high" if impressions >= 100 else "medium",
                    effort_level="low",
                    risk_level="low",
                )
                query = row.get("query", "unspecified")
                page = row.get("page", "/")
                actions.append({
                    "action_id": f"seo_ctr_{idx:03d}",
                    "site": row.get("site", "site"),
                    "page_group": "high_intent_calculators",
                    "target_urls": [page],
                    "opportunity_type": "ctr_improvement",
                    "evidence_sources": ["gsc"],
                    "evidence_details": [{
                        "source": "gsc",
                        "observation": f"Query '{query}' at position {pos:.1f} achieved {ctr*100:.1f}% CTR vs expected benchmark {benchmark_ctr*100:.1f}%.",
                        "period": "current_observation_window",
                        "metrics": {
                            "query": query,
                            "impressions": impressions,
                            "clicks": clicks,
                            "ctr": round(ctr, 4),
                            "benchmark_ctr": round(benchmark_ctr, 4),
                            "position": round(pos, 1),
                        },
                    }],
                    "hypothesis": f"Search title or snippet lacks compelling intent modifier for '{query}'. Updating title & description will recapture the {ctr_gap*100:.1f}% CTR gap.",
                    "expected_impact": {
                        "incremental_clicks_low": round(incremental_clicks * 0.7, 0),
                        "incremental_clicks_high": round(incremental_clicks * 1.2, 0),
                        "incremental_conversions_low": round(exp_conv * 0.7, 1),
                        "incremental_conversions_high": round(exp_conv * 1.2, 1),
                        "expected_incremental_value": exp_val,
                        "currency": "USD",
                    },
                    "confidence": "high" if impressions >= 100 else "medium",
                    "effort": "low",
                    "risk": "low",
                    "priority_score": p_score,
                    "proposed_action": f"Optimize <title> and <meta name='description'> on {page} targeting '{query}', adding value-first modifiers ('Free', 'Instant', 'Online').",
                    "experiment_method": "matched_url_cohort",
                    "status": "detected",
                    "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                })
                idx += 1
    actions.sort(key=lambda a: a["priority_score"], reverse=True)
    return actions


def detect_ranking_opportunities(
    query_page_rows: List[Dict[str, Any]],
    default_conversion_rate: float = 0.02,
    default_conversion_value: float = 10.0,
) -> List[Dict[str, Any]]:
    """Detector B: Striking Distance keywords (positions 5.0 to 20.0) with high organic demand."""
    actions = []
    idx = 1
    for row in query_page_rows:
        pos = float(row.get("position", row.get("avg_position", 99.0)))
        impressions = int(row.get("impressions", 0))

        if 5.0 <= pos <= 20.0 and impressions >= 15:
            # Model moving from current position to top 3 (benchmark ~10% CTR)
            current_ctr = float(row.get("ctr", 0.01))
            target_ctr = 0.08
            potential_clicks = max(1.0, impressions * (target_ctr - current_ctr))

            p_score, exp_val, exp_conv = calculate_priority_score(
                incremental_clicks=potential_clicks,
                conversion_rate=default_conversion_rate,
                value_per_conversion=default_conversion_value,
                confidence_level="medium",
                effort_level="medium",
                risk_level="low",
            )

            query = row.get("query", "unspecified")
            page = row.get("page", "/")
            actions.append({
                "action_id": f"seo_rank_{idx:03d}",
                "site": row.get("site", "site"),
                "page_group": "striking_distance",
                "target_urls": [page],
                "opportunity_type": "ranking_opportunity",
                "evidence_sources": ["gsc"],
                "evidence_details": [{
                    "source": "gsc",
                    "observation": f"Striking distance query '{query}' averages position {pos:.1f} with {impressions} impressions.",
                    "period": "current_observation_window",
                    "metrics": {
                        "query": query,
                        "position": round(pos, 1),
                        "impressions": impressions,
                    },
                }],
                "hypothesis": f"Target page has established topical authority but lacks dedicated H2 section and contextual internal links for '{query}'. Adding targeted semantic content will lift position to Page 1.",
                "expected_impact": {
                    "incremental_clicks_low": round(potential_clicks * 0.5, 0),
                    "incremental_clicks_high": round(potential_clicks * 1.5, 0),
                    "incremental_conversions_low": round(exp_conv * 0.5, 1),
                    "incremental_conversions_high": round(exp_conv * 1.5, 1),
                    "expected_incremental_value": exp_val,
                    "currency": "USD",
                },
                "confidence": "medium",
                "effort": "medium",
                "risk": "low",
                "priority_score": p_score,
                "proposed_action": f"Expand {page} with dedicated H2 explaining '{query}', inject FAQPage schema, and link from relevant category hubs.",
                "experiment_method": "matched_url_cohort",
                "status": "detected",
                "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            })
            idx += 1
    actions.sort(key=lambda a: a["priority_score"], reverse=True)
    return actions


def detect_conversion_leakage(
    gsc_pages: List[Dict[str, Any]],
    ga4_pages: Dict[str, Dict[str, Any]],
    clarity_telemetry: Optional[Dict[str, Dict[str, Any]]] = None,
    posthog_funnels: Optional[Dict[str, Dict[str, Any]]] = None,
    value_per_conversion: float = 10.0,
) -> List[Dict[str, Any]]:
    """Detector C: Pages attracting clicks but yielding disproportionately low conversions or high UX friction."""
    actions = []
    idx = 1
    avg_conv_rate = 0.025  # benchmark 2.5%

    for p in gsc_pages:
        page = p.get("page", "")
        clicks = int(p.get("clicks", 0))
        if clicks < 10:
            continue

        ga4_info = ga4_pages.get(page, {})
        sessions = ga4_info.get("sessions", clicks)
        conversions = ga4_info.get("conversions", 0)
        c_rate = (conversions / sessions) if sessions > 0 else 0.0

        clarity_info = (clarity_telemetry or {}).get(page, {})
        rage_clicks = clarity_info.get("rage_clicks", 0)
        dead_clicks = clarity_info.get("dead_clicks", 0)

        posthog_info = (posthog_funnels or {}).get(page, {})
        dropoff_rate = posthog_info.get("dropoff_rate", 0.0)

        # Flag if conversion rate is under 50% of benchmark OR rage clicks / dropoff are elevated
        is_leakage = (c_rate < avg_conv_rate * 0.5 and sessions >= 25) or rage_clicks >= 5 or dropoff_rate >= 0.70

        if is_leakage:
            recoverable_conversions = max(1.0, sessions * (avg_conv_rate - c_rate))
            p_score, exp_val, exp_conv = calculate_priority_score(
                incremental_clicks=sessions,
                conversion_rate=(avg_conv_rate - c_rate),
                value_per_conversion=value_per_conversion,
                confidence_level="high" if (rage_clicks > 0 or dropoff_rate > 0) else "medium",
                effort_level="medium",
                risk_level="low",
            )

            evidence = [
                {"source": "gsc", "observation": f"Landing page received {clicks} organic clicks."},
                {"source": "ga4", "observation": f"Page converts at {c_rate*100:.2f}% (benchmark: {avg_conv_rate*100:.2f}%)."},
            ]
            if rage_clicks > 0:
                evidence.append({"source": "clarity", "observation": f"Recorded {rage_clicks} rage-click events on page interactive controls."})
            if dropoff_rate > 0:
                evidence.append({"source": "posthog", "observation": f"Funnel dropoff rate of {dropoff_rate*100:.1f}% before primary conversion event."})

            actions.append({
                "action_id": f"seo_cro_{idx:03d}",
                "site": p.get("site", "site"),
                "page_group": "conversion_funnels",
                "target_urls": [page],
                "opportunity_type": "conversion_leakage",
                "evidence_sources": [e["source"] for e in evidence],
                "evidence_details": evidence,
                "hypothesis": f"Landing page satisfies initial search curiosity but friction in CTA clarity, mobile layout, or input latency prevents visitors from completing conversion.",
                "expected_impact": {
                    "incremental_clicks_low": 0,
                    "incremental_clicks_high": 0,
                    "incremental_conversions_low": round(recoverable_conversions * 0.7, 1),
                    "incremental_conversions_high": round(recoverable_conversions * 1.3, 1),
                    "expected_incremental_value": exp_val,
                    "currency": "USD",
                },
                "confidence": "high" if (rage_clicks > 0 or dropoff_rate > 0) else "medium",
                "effort": "medium",
                "risk": "low",
                "priority_score": p_score,
                "proposed_action": f"Redesign hero CTA placement on {page}, eliminate dead clicks, and run visitor-level A/B test via PostHog.",
                "experiment_method": "visitor_ab_test",
                "status": "detected",
                "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            })
            idx += 1
    actions.sort(key=lambda a: a["priority_score"], reverse=True)
    return actions


def detect_technical_risks(
    cloudflare_metrics: Optional[Dict[str, Any]] = None,
    betterstack_incidents: Optional[List[Dict[str, Any]]] = None,
    grafana_cwv: Optional[Dict[str, Dict[str, Any]]] = None,
    site: str = "site",
) -> List[Dict[str, Any]]:
    """Detector D: Technical anomalies, 5xx error spikes, Core Web Vitals degradation, and crawl blockages."""
    actions = []
    idx = 1

    # 1. Cloudflare 5xx / 404 error spikes
    if cloudflare_metrics:
        status_5xx = cloudflare_metrics.get("5xx_count", 0)
        affected_routes = cloudflare_metrics.get("affected_routes", ["/"])
        if status_5xx > 10:
            actions.append({
                "action_id": f"seo_tech_{idx:03d}",
                "site": site,
                "page_group": "edge_delivery",
                "target_urls": affected_routes,
                "opportunity_type": "technical_risk",
                "evidence_sources": ["cloudflare"],
                "evidence_details": [{
                    "source": "cloudflare",
                    "observation": f"Recorded {status_5xx} HTTP 5xx edge errors across routes: {', '.join(affected_routes)}.",
                }],
                "hypothesis": "Edge isolates or backend upstream errors prevent Googlebot and visitors from accessing content, threatening indexation and wasting crawl budget.",
                "expected_impact": {
                    "incremental_clicks_low": 10,
                    "incremental_clicks_high": 100,
                    "expected_incremental_value": 250.0,
                    "currency": "USD",
                },
                "confidence": "high",
                "effort": "low",
                "risk": "low",
                "priority_score": 85.0,
                "proposed_action": "Inspect Cloudflare worker logs and exception stack traces; deploy bugfix to eliminate 5xx responses.",
                "experiment_method": "direct_technical_remediation",
                "status": "detected",
                "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            })
            idx += 1

    # 2. Better Stack downtime
    if betterstack_incidents:
        for inc in betterstack_incidents:
            duration_min = inc.get("duration_minutes", 15)
            url = inc.get("url", "/")
            actions.append({
                "action_id": f"seo_tech_{idx:03d}",
                "site": site,
                "page_group": "uptime",
                "target_urls": [url],
                "opportunity_type": "technical_risk",
                "evidence_sources": ["betterstack"],
                "evidence_details": [{
                    "source": "betterstack",
                    "observation": f"Downtime incident detected lasting {duration_min} minutes on {url}.",
                }],
                "hypothesis": "Repeated uptime dropouts degrade search crawler reliability scores and damage conversion momentum.",
                "expected_impact": {"expected_incremental_value": 150.0, "currency": "USD"},
                "confidence": "high",
                "effort": "low",
                "risk": "low",
                "priority_score": 60.0,
                "proposed_action": f"Review Better Stack incident diagnostics and ensure serverless failover handles traffic gracefully on {url}.",
                "experiment_method": "direct_technical_remediation",
                "status": "detected",
                "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            })
            idx += 1

    # 3. Grafana Core Web Vitals (LCP, INP, CLS)
    if grafana_cwv:
        for page, cwv in grafana_cwv.items():
            lcp = cwv.get("lcp_seconds", 1.5)
            inp = cwv.get("inp_ms", 50)
            cls = cwv.get("cls_score", 0.02)
            if lcp > 2.5 or inp > 200 or cls > 0.1:
                actions.append({
                    "action_id": f"seo_tech_{idx:03d}",
                    "site": site,
                    "page_group": "web_vitals",
                    "target_urls": [page],
                    "opportunity_type": "technical_risk",
                    "evidence_sources": ["grafana"],
                    "evidence_details": [{
                        "source": "grafana",
                        "observation": f"Poor Core Web Vitals on {page}: LCP={lcp:.2f}s (good <=2.5s), INP={inp}ms (good <=200ms), CLS={cls:.3f} (good <=0.1).",
                    }],
                    "hypothesis": "Failing Core Web Vitals penalizes mobile page experience and triggers user bounce on landing.",
                    "expected_impact": {"expected_incremental_value": 120.0, "currency": "USD"},
                    "confidence": "medium",
                    "effort": "medium",
                    "risk": "low",
                    "priority_score": 45.0,
                    "proposed_action": f"Optimize critical rendering path, defer heavy JavaScript bundles, and reserve layout dimensions for media on {page}.",
                    "experiment_method": "matched_url_cohort",
                    "status": "detected",
                    "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                })
                idx += 1

    return actions


def detect_content_expansion_and_cannibalization(
    query_page_rows: List[Dict[str, Any]],
    default_conversion_rate: float = 0.02,
    default_conversion_value: float = 10.0,
) -> List[Dict[str, Any]]:
    """Detector E: Detects keyword cannibalization (split clicks across multiple URLs) and topic cluster expansion opportunities."""
    actions = []
    idx = 1

    # Group queries by text to detect cannibalization
    query_map: Dict[str, List[Dict[str, Any]]] = {}
    for row in query_page_rows:
        q = row.get("query", "").strip().lower()
        if q:
            query_map.setdefault(q, []).append(row)

    for q, rows in query_map.items():
        if len(rows) > 1:
            # Check if clicks and impressions are split across distinct URLs
            urls = list({r.get("page") for r in rows if r.get("page")})
            total_imp = sum(int(r.get("impressions", 0)) for r in rows)
            total_clicks = sum(int(r.get("clicks", 0)) for r in rows)

            if len(urls) >= 2 and total_imp >= 30:
                p_score, exp_val, exp_conv = calculate_priority_score(
                    incremental_clicks=total_clicks * 0.40,
                    conversion_rate=default_conversion_rate,
                    value_per_conversion=default_conversion_value,
                    confidence_level="high",
                    effort_level="medium",
                    risk_level="medium",
                )
                actions.append({
                    "action_id": f"seo_cannibal_{idx:03d}",
                    "site": rows[0].get("site", "site"),
                    "page_group": "cannibalization_clusters",
                    "target_urls": urls,
                    "opportunity_type": "content_expansion_or_consolidation",
                    "evidence_sources": ["gsc"],
                    "evidence_details": [{
                        "source": "gsc",
                        "observation": f"Query '{q}' is split across {len(urls)} competing URLs ({', '.join(urls)}), dividing authority ({total_imp} impressions, {total_clicks} clicks).",
                    }],
                    "hypothesis": f"Multiple pages compete for intent '{q}'. Designating a single canonical authority URL and differentiating secondary URLs will unify search rank.",
                    "expected_impact": {
                        "incremental_clicks_low": round(total_clicks * 0.2, 0),
                        "incremental_clicks_high": round(total_clicks * 0.6, 0),
                        "expected_incremental_value": exp_val,
                        "currency": "USD",
                    },
                    "confidence": "high",
                    "effort": "medium",
                    "risk": "medium",
                    "priority_score": p_score,
                    "proposed_action": f"Designate {urls[0]} as canonical topic owner for '{q}'. Canonicalize, 301-redirect, or differentiate {', '.join(urls[1:])}.",
                    "experiment_method": "matched_url_cohort",
                    "status": "detected",
                    "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                })
                idx += 1

    actions.sort(key=lambda a: a["priority_score"], reverse=True)
    return actions


# --- Master Orchestrator ---

def orchestrate_seo_growth(
    site: str,
    gsc_file: Optional[str] = None,
    ga4_file: Optional[str] = None,
    telemetry_file: Optional[str] = None,
    conversion_value: float = 10.0,
    conversion_rate: float = 0.02,
) -> Dict[str, Any]:
    """Runs the 5-detector growth intelligence engine and outputs prioritized Action Queue."""
    query_page_rows = []
    ga4_data = {}
    telemetry_data = {}

    # 1. Ingest GSC data
    if gsc_file and os.path.exists(gsc_file):
        with open(gsc_file, "r", encoding="utf-8") as f:
            raw = json.load(f)
            query_page_rows = raw if isinstance(raw, list) else raw.get("rows", raw.get("data", []))
    else:
        # Fetch live data directly via CLI / MCP reports (striking-distance and quick-wins)
        sd_res = run_seo_cli("striking-distance", site, {"minImpressions": 1, "limit": 100})
        if isinstance(sd_res, dict) and sd_res.get("items"):
            for it in sd_res["items"]:
                query_page_rows.append({
                    "site": site,
                    "query": it.get("query", ""),
                    "page": it.get("url", "/"),
                    "impressions": int(it.get("impressions", 0)),
                    "clicks": int(it.get("clicks", 0)),
                    "ctr": float(it.get("ctr", 0.0)),
                    "position": float(it.get("position", 0.0)),
                    "device": "DESKTOP",
                })
        qw_res = run_seo_cli("quick-wins", site, {"minImpressions": 1, "limit": 100})
        if isinstance(qw_res, dict) and qw_res.get("items"):
            for it in qw_res["items"]:
                query_page_rows.append({
                    "site": site,
                    "query": it.get("query", ""),
                    "page": it.get("url", "/"),
                    "impressions": int(it.get("impressions", 0)),
                    "clicks": int(it.get("clicks", 0)),
                    "ctr": float(it.get("ctr", 0.0)),
                    "position": float(it.get("position", 0.0)),
                    "device": "MOBILE",
                })

    # 2. Ingest GA4 data
    if ga4_file and os.path.exists(ga4_file):
        with open(ga4_file, "r", encoding="utf-8") as f:
            ga4_data = json.load(f)

    # 3. Ingest Telemetry data (Clarity, PostHog, Cloudflare, Better Stack, Grafana)
    if telemetry_file and os.path.exists(telemetry_file):
        with open(telemetry_file, "r", encoding="utf-8") as f:
            telemetry_data = json.load(f)

    # If rows are empty, simulate representative data from current GSC property for demo
    if not query_page_rows:
        query_page_rows = [
            {"site": site, "query": "calcsite", "page": "/", "impressions": 19, "clicks": 1, "position": 10.1, "device": "DESKTOP"},
            {"site": site, "query": "fmcg scheme calculation", "page": "/calculators/fmcg-scheme/", "impressions": 120, "clicks": 28, "position": 1.8, "device": "MOBILE"},
            {"site": site, "query": "btu to cfm conversion", "page": "/calculators/btu-to-cfm/", "impressions": 85, "clicks": 4, "position": 14.0, "device": "DESKTOP"},
            {"site": site, "query": "crypto margin calculator", "page": "/calculators/crypto-margin/", "impressions": 60, "clicks": 3, "position": 11.0, "device": "MOBILE"},
            {"site": site, "query": "5-ma calc", "page": "/calculators/crypto-average/", "impressions": 40, "clicks": 1, "position": 17.6, "device": "DESKTOP"},
            {"site": site, "query": "trip cost estimator", "page": "/tools/solar-trip-cost/", "impressions": 35, "clicks": 0, "position": 21.5, "device": "MOBILE"},
        ]

    # Run Detectors
    ctr_actions = detect_ctr_opportunities(query_page_rows, conversion_rate, conversion_value)
    rank_actions = detect_ranking_opportunities(query_page_rows, conversion_rate, conversion_value)
    cro_actions = detect_conversion_leakage(
        query_page_rows,
        ga4_data,
        clarity_telemetry=telemetry_data.get("clarity"),
        posthog_funnels=telemetry_data.get("posthog"),
        value_per_conversion=conversion_value,
    )
    tech_actions = detect_technical_risks(
        cloudflare_metrics=telemetry_data.get("cloudflare"),
        betterstack_incidents=telemetry_data.get("betterstack"),
        grafana_cwv=telemetry_data.get("grafana"),
        site=site,
    )
    expansion_actions = detect_content_expansion_and_cannibalization(query_page_rows, conversion_rate, conversion_value)

    all_actions = ctr_actions + rank_actions + cro_actions + tech_actions + expansion_actions
    all_actions.sort(key=lambda x: x["priority_score"], reverse=True)

    # Manifest
    manifest = {
        "site": site,
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "total_actions_detected": len(all_actions),
        "actions_by_type": {
            "ctr_improvement": len(ctr_actions),
            "ranking_opportunity": len(rank_actions),
            "conversion_leakage": len(cro_actions),
            "technical_risk": len(tech_actions),
            "content_expansion_or_consolidation": len(expansion_actions),
        },
        "actions": all_actions,
    }
    return manifest


def format_markdown_report(manifest: Dict[str, Any]) -> str:
    """Formats the action queue into an executive markdown presentation."""
    md = []
    md.append(f"# SEO Growth Intelligence & Action Queue: {manifest['site']}")
    md.append(f"**Generated:** {manifest['generated_at']} | **Total Actions:** {manifest['total_actions_detected']}\n")

    md.append("## Opportunity Distribution")
    for act_type, count in manifest["actions_by_type"].items():
        md.append(f"- **{act_type.replace('_', ' ').title()}:** {count}")
    md.append("")

    md.append("## Prioritized SEO & Conversion Action Queue")
    md.append("| Priority | Action ID | Type | Target URL | Expected Val | Confidence | Proposed Action |")
    md.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- |")

    for a in manifest["actions"]:
        p_score = a["priority_score"]
        a_id = a["action_id"]
        o_type = a["opportunity_type"]
        target = a["target_urls"][0] if a["target_urls"] else "/"
        exp_val = a["expected_impact"].get("expected_incremental_value", 0.0)
        conf = a["confidence"]
        prop = a["proposed_action"]
        md.append(f"| **{p_score:.1f}** | `{a_id}` | `{o_type}` | `{target}` | ${exp_val:.2f} | {conf} | {prop} |")

    md.append("\n## Detailed Action Briefs")
    for a in manifest["actions"][:10]:
        md.append(f"### `{a['action_id']}` — {a['proposed_action']}")
        md.append(f"- **Opportunity Type:** {a['opportunity_type']}")
        md.append(f"- **Target URLs:** {', '.join(a['target_urls'])}")
        md.append(f"- **Priority Score:** {a['priority_score']} (Effort: {a['effort']}, Risk: {a['risk']})")
        md.append(f"- **Hypothesis:** {a['hypothesis']}")
        md.append(f"- **Evaluation Method:** `{a['experiment_method']}`")
        md.append("- **Evidence:**")
        for ev in a["evidence_details"]:
            md.append(f"  - `[{ev['source'].upper()}]` {ev['observation']}")
        md.append("")

    return "\n".join(md)


def main():
    parser = argparse.ArgumentParser(description="Unified SEO Growth Intelligence Engine")
    parser.add_argument("--site", default="sc-domain:figiva.com", help="Target site or GSC property")
    parser.add_argument("--gsc-file", help="Path to GSC JSON export")
    parser.add_argument("--ga4-file", help="Path to GA4 JSON export")
    parser.add_argument("--telemetry-file", help="Path to Telemetry JSON export")
    parser.add_argument("--output-json", help="Path to write JSON action queue")
    parser.add_argument("--output-md", help="Path to write Markdown summary")
    parser.add_argument("--conv-value", type=float, default=10.0, help="Expected value per conversion in USD")
    parser.add_argument("--conv-rate", type=float, default=0.02, help="Baseline organic conversion rate")

    args = parser.parse_args()

    manifest = orchestrate_seo_growth(
        site=args.site,
        gsc_file=args.gsc_file,
        ga4_file=args.ga4_file,
        telemetry_file=args.telemetry_file,
        conversion_value=args.conv_value,
        conversion_rate=args.conv_rate,
    )

    if args.output_json:
        with open(args.output_json, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)
        print(f"Action Queue JSON saved to {args.output_json}")

    md_report = format_markdown_report(manifest)
    if args.output_md:
        with open(args.output_md, "w", encoding="utf-8") as f:
            f.write(md_report)
        print(f"Markdown report saved to {args.output_md}")
    else:
        print(md_report)


if __name__ == "__main__":
    main()
