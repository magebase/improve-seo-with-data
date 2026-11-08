#!/usr/bin/env python3
"""
fleet_ingest.py - Multi-Property Fleet Ingestion & Harmonization Pipeline.

Pools GSC (query, page) rows across ALL authenticated Search Console
properties into ONE domain-agnostic training schema, so LGBMRanker trains
on real click variance from Day 1 instead of waiting for a single young
domain to accumulate 300 outcomes on its own.

Input: JSON files, each shaped like either
  {"domain": "example.com", "rows": [{query, page, clicks, impressions,
                                      position, ctr?, features?, ...}]}
or a collect_features.py snapshot:
  {"site": "example.com", "rows": [{query, page, features, clicks_30d, ...}]}

Harmonization contract:
- unified 8-feature vector per row; missing SERP features fill neutral 0.0
- search_volume_log falls back to log10(impressions + 1) when DataForSEO
  volume has not been enriched yet
- cluster_id from the URL path segment (domain-agnostic topical grouping)
- rows dedupe on (domain, query, page); the max-click duplicate wins
- every row carries "domain" for per-property attribution and the fleet
  transition check in bootstrap_labels.generate_bootstrap_grades

Usage:
    python3 scripts/fleet_ingest.py --inputs "data/fleet/*.json" \\
        --output data/ltr_training_history.jsonl
"""

from __future__ import annotations

import argparse
import glob
import json
import math
import os
import sys
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ltr_ranker import FEATURES  # noqa: E402


def _domain_of(payload: Dict[str, Any], fallback_index: int) -> str:
    domain = payload.get("domain") or payload.get("site")
    if domain:
        return str(domain).replace("sc-domain:", "").replace("https://", "").rstrip("/").lower()
    return f"property-{fallback_index}"


def _cluster_from_page(page: str) -> str:
    path = str(page).split("://", 1)[-1]
    parts = [p for p in path.split("/") if p]
    return parts[1] if len(parts) > 1 else "root"


def _normalize_row(raw: Dict[str, Any], domain: str) -> Dict[str, Any]:
    features_in = dict(raw.get("features") or {})
    impressions = float(raw.get("impressions", raw.get("impressions_30d", 0)) or 0)
    volume = features_in.get("search_volume_log")
    if volume is None:
        raw_volume = raw.get("search_volume")
        if raw_volume:
            volume_log = math.log10(float(raw_volume) + 1.0)
        else:
            # Domain-agnostic demand floor: impressions proxy at the plain
            # log scale (no cross-domain multiplier games).
            volume_log = math.log10(impressions + 1.0)
    else:
        volume_log = float(volume)

    features = {
        # Neutral 0.5 fill: unknown similarity must NOT zero the bootstrap
        # opportunity score the way a maximally-off-topic 0.0 fill would.
        "domain_centroid_sim": float(features_in.get("domain_centroid_sim", 0.5) or 0.5),
        "serp_forum_ratio": float(features_in.get("serp_forum_ratio", 0.0) or 0.0),
        "title_exact_match_rate": float(features_in.get("title_exact_match_rate", 0.0) or 0.0),
        "serp_pixel_crowding": float(features_in.get("serp_pixel_crowding", 0.0) or 0.0),
        "parent_hub_internal_links": float(features_in.get("parent_hub_internal_links", 0.0) or 0.0),
        "current_pos": float(raw.get("position", raw.get("current_pos", features_in.get("current_pos", 99.0))) or 99.0),
        "search_volume_log": round(volume_log, 6),
        "conversion_intent_score": float(features_in.get("conversion_intent_score", 0.0) or 0.0),
    }
    clicks = float(raw.get("clicks_30d", raw.get("clicks", 0)) or 0)
    return {
        "query": str(raw.get("query", "")).lower(),
        "page": str(raw.get("page", "")),
        "domain": domain,
        "cluster_id": str(raw.get("cluster_id") or _cluster_from_page(raw.get("page", ""))),
        "features": features,
        "clicks_30d": clicks,
        "conversions_30d": float(raw.get("conversions_30d", 0) or 0),
        "impressions": impressions,
        "current_pos": features["current_pos"],
        "current_ctr": float(raw.get("ctr", raw.get("current_ctr", 0)) or 0),
        "conv_value": float(raw.get("conv_value", 1.0) or 1.0),
        "window_days": int(raw.get("window_days", 90)),
        "source": "fleet_pool",
    }


def harmonize_fleet_history(property_payloads: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Pools per-property row exports into the unified training schema.

    Dedupe key is (domain, query, page); the duplicate with the most clicks
    wins (later rows break ties). Missing SERP features fill neutral 0.0 so
    the pooled matrix trains before DataForSEO enrichment has run.
    """
    pooled: Dict[tuple, Dict[str, Any]] = {}
    for idx, payload in enumerate(property_payloads):
        domain = _domain_of(payload, idx)
        for raw in payload.get("rows", []):
            if "keys" in raw and not raw.get("query"):
                keys = raw.get("keys") or []
                if len(keys) < 2:
                    continue
                raw = dict(raw)
                raw["query"], raw["page"] = keys[0], keys[1]
            if not raw.get("query") or not raw.get("page"):
                continue
            row = _normalize_row(raw, domain)
            key = (domain, row["query"], row["page"])
            existing = pooled.get(key)
            if existing is None or row["clicks_30d"] > existing["clicks_30d"]:
                pooled[key] = row
    rows = list(pooled.values())
    rows.sort(key=lambda r: (r["domain"], r["cluster_id"], r["query"]))
    return rows


def load_payloads(paths: List[str]) -> List[Dict[str, Any]]:
    payloads: List[Dict[str, Any]] = []
    for pattern in paths:
        matches = sorted(glob.glob(pattern))
        if not matches and os.path.exists(pattern):
            matches = [pattern]
        if not matches:
            raise FileNotFoundError(f"no files match fleet input pattern: {pattern}")
        for path in matches:
            with open(path, encoding="utf-8") as fh:
                payload = json.load(fh)
            if isinstance(payload, list):
                payload = {"domain": os.path.basename(path), "rows": payload}
            payloads.append(payload)
    return payloads


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--inputs", nargs="+", required=True,
                        help="per-property JSON files or glob patterns")
    parser.add_argument("--output", default="data/ltr_training_history.jsonl")
    args = parser.parse_args(argv)

    try:
        payloads = load_payloads(args.inputs)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}")
        return 1

    pooled = harmonize_fleet_history(payloads)
    if not pooled:
        print("ERROR: no harvestable (query, page) rows in the given inputs.")
        return 1

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as fh:
        for row in pooled:
            fh.write(json.dumps(row) + "\n")

    by_domain: Dict[str, Dict[str, int]] = {}
    for row in pooled:
        stats = by_domain.setdefault(row["domain"], {"rows": 0, "clicked": 0})
        stats["rows"] += 1
        if row["clicks_30d"] > 0:
            stats["clicked"] += 1
    clicked_total = sum(s["clicked"] for s in by_domain.values())
    print(f"Pooled {len(pooled)} harmonized rows from {len(by_domain)} properties -> {args.output}")
    for domain, stats in sorted(by_domain.items()):
        print(f"  {domain:<32} rows={stats['rows']:<6} clicked={stats['clicked']}")
    print(f"Fleet clicked rows: {clicked_total} "
          f"(label authority flips to fleet_clicks at "
          f"{__import__('bootstrap_labels').FLEET_CLICK_ROWS})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
