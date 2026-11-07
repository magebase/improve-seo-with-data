#!/usr/bin/env python3
"""
collect_features.py - Stage 1 of the Learning-to-Rank closed loop.

Pulls REAL Search Console performance data through the `seo` binary, enriches
the top candidates with DataForSEO SERP intelligence (cost-routed Standard
Queue), computes the 8-feature ranking matrix, and persists:

    data/ltr_features.json

Feature vector (order = ltr_ranker.FEATURES, constraints map 1:1):
    domain_centroid_sim        cosine(query tokens, domain topical centroid)
    serp_forum_ratio           share of Top-10 results from UGC/forum domains
    title_exact_match_rate     share of Top-10 titles containing the exact query
    serp_pixel_crowding        SERP features above organic (pixel-equivalent proxy)
    parent_hub_internal_links  links into the page's parent hub (from crawl export
                               via --hub-links; 0.0 when no export is supplied)
    current_pos                current average GSC position
    search_volume_log          log10(volume + 1); falls back to log10(impressions+1)
                               scaled by 2.0 when DataForSEO volume is unavailable
    conversion_intent_score    historical conversions / clicks for the landing page
                               (0.0 before any conversion history exists)

Usage:
    python3 scripts/collect_features.py --site smsriver.com --top 150
    python3 scripts/collect_features.py --site figiva.com --top 150 --gsc-only
    python3 scripts/collect_features.py --site smsriver.com \\
        --hub-links crawl_export/hub_links.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sys
import time
from collections import Counter
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dataforseo_client import DataForSEOClient, resolve_credentials  # noqa: E402
from gsc_analyzer import find_seo_binary, run_seo_report  # noqa: E402

STOP_TOKENS = {
    "the", "a", "an", "for", "to", "of", "in", "on", "and", "or", "is", "it",
    "how", "what", "best", "vs", "with", "at", "by", "from", "my", "your",
}


def find_performance_rows(payload: Any) -> List[Dict[str, Any]]:
    """Recursively locates GSC rows (query/page/clicks/impressions) in a report."""
    found: List[Dict[str, Any]] = []

    def walk(node: Any) -> None:
        if isinstance(node, list):
            if node and all(isinstance(r, dict) for r in node):
                keys = set().union(*(set(r.keys()) for r in node))
                if keys & {"query", "keyword"} and keys & {"clicks"} and keys & {"impressions"}:
                    found.extend([r for r in node if isinstance(r, dict)])
            for item in node:
                walk(item)
        elif isinstance(node, dict):
            for value in node.values():
                walk(value)

    walk(payload)
    return found


def tokenize(text: str) -> Counter:
    tokens = []
    for raw in str(text).lower().replace("-", " ").split():
        token = "".join(ch for ch in raw if ch.isalnum())
        if len(token) > 2 and token not in STOP_TOKENS:
            tokens.append(token)
    return Counter(tokens)


def cosine(counter_a: Counter, counter_b: Counter) -> float:
    if not counter_a or not counter_b:
        return 0.0
    common = set(counter_a) & set(counter_b)
    dot = sum(counter_a[t] * counter_b[t] for t in common)
    norm_a = math.sqrt(sum(v * v for v in counter_a.values()))
    norm_b = math.sqrt(sum(v * v for v in counter_b.values()))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


FORUM_HINTS = (
    "reddit", "quora", "forum", "stackoverflow", "stackexchange", "medium",
    "substack", "discord", "community", "board.",
)


def compute_serp_features(serp_items: List[Dict[str, Any]], query: str) -> Dict[str, float]:
    """Derives forum ratio / title match / pixel crowding from a DataForSEO SERP."""
    top10 = [item for item in serp_items[:10] if item.get("type") == "organic"]
    if not top10:
        return {"serp_forum_ratio": 0.0, "title_exact_match_rate": 0.0, "serp_pixel_crowding": 0.0}

    query_tokens = set(tokenize(query))
    forum = 0
    exact = 0
    for item in top10:
        url = str(item.get("url", "")).lower()
        title = str(item.get("title", "")).lower()
        title_tokens = set(tokenize(title))
        if any(hint in url for hint in FORUM_HINTS):
            forum += 1
        if query_tokens and query_tokens.issubset(title_tokens):
            exact += 1

    special = extract_special_blocks(serp_items)
    return {
        "serp_forum_ratio": forum / len(top10),
        "title_exact_match_rate": exact / len(top10),
        "serp_pixel_crowding": float(special),
    }


def extract_special_blocks(serp_items: List[Dict[str, Any]]) -> int:
    """Counts SERP real-estate blocks above the organic fold (pixel proxy)."""
    weights = {"featured_snippet": 400, "ai_overview": 600, "knowledge_graph": 350,
               "local_pack": 300, "video": 250, "images": 200, "ads": 150,
               "people_also_ask": 250, "related_searches": 150, "top_serp_features": 1}
    total = 0
    for item in serp_items:
        if item.get("type") != "serp_features":
            continue
        block_type = str(item.get("title", item.get("block", ""))).lower()
        for key, weight in weights.items():
            if key in block_type:
                total += weight
                break
        else:
            total += weights["top_serp_features"]
    return total


def load_hub_links(path: Optional[str]) -> Dict[str, int]:
    """Loads url_prefix -> internal link count from a 2-column CSV crawl export."""
    mapping: Dict[str, int] = {}
    if not path:
        return mapping
    with open(path, newline="", encoding="utf-8") as fh:
        for row in csv.reader(fh):
            if len(row) < 2 or row[0].startswith("#"):
                continue
            try:
                mapping[row[0].rstrip("/").lower()] = int(float(row[1]))
            except ValueError:
                continue
    return mapping


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--site", required=True, help="GSC property, e.g. smsriver.com")
    parser.add_argument("--top", type=int, default=150, help="max keywords to enrich")
    parser.add_argument("--gsc-only", action="store_true", help="skip DataForSEO enrichment")
    parser.add_argument("--report", default="search-performance-overview")
    parser.add_argument("--hub-links", help="CSV export: url_prefix,internal_links")
    parser.add_argument("--output", default="data/ltr_features.json")
    parser.add_argument("--max-serp-cost", type=float, default=5.0, help="USD cap")
    parser.add_argument("--queue-wait-mins", type=int, default=12,
                        help="minutes to poll the DataForSEO queue before falling back")
    args = parser.parse_args(argv)

    if not find_seo_binary():
        print("ERROR: seo binary not found; GSC data is unavailable.", file=sys.stderr)
        return 1

    print(f"[1/3] Pulling GSC performance for {args.site} via seo binary ...")
    report = run_seo_report(args.report, args.site)
    if not report.get("ok", True) and "error" in report:
        print(f"ERROR: seo report failed: {report['error']}", file=sys.stderr)
        return 1
    rows = find_performance_rows(report)
    if not rows:
        print("ERROR: report contained no query/page performance rows.", file=sys.stderr)
        return 1

    # Normalize + keep the strongest candidates by impressions.
    candidates: List[Dict[str, Any]] = []
    for row in rows:
        query = row.get("query", row.get("keyword"))
        page = row.get("page", row.get("url", row.get("landing_page", "")))
        if not query or not page:
            continue
        candidates.append({
            "query": str(query),
            "page": str(page),
            "clicks_30d": float(row.get("clicks", 0) or 0),
            "impressions": float(row.get("impressions", 0) or 0),
            "current_pos": float(row.get("position", row.get("avg_position", 99)) or 99),
            "ctr": float(row.get("ctr", 0) or 0),
        })
    # Deduplicate on (query, page), keep max impressions.
    best: Dict[tuple, Dict[str, Any]] = {}
    for cand in candidates:
        key = (cand["query"], cand["page"])
        if key not in best or cand["impressions"] > best[key]["impressions"]:
            best[key] = cand
    candidates = sorted(best.values(), key=lambda c: c["impressions"], reverse=True)[: args.top]
    print(f"      {len(candidates)} unique (query, page) candidates retained.")

    # Domain topical centroid: token profile of our own winning pages' queries.
    domain_counter: Counter = Counter()
    for cand in candidates:
        if cand["clicks_30d"] >= 1:
            domain_counter.update(tokenize(cand["query"]))

    login, password = (None, None)
    if not args.gsc_only:
        try:
            login, password = resolve_credentials(env=dict(os.environ))
        except RuntimeError as exc:
            print(f"[2/3] DataForSEO unavailable ({exc}) -> GSC-only mode "
                  "(SERP features fall back to neutral 0.0, volume falls back to impressions).")
    client = DataForSEOClient(login, password) if login and password else None

    hub_links = load_hub_links(args.hub_links)
    serp_by_query: Dict[str, List[Dict[str, Any]]] = {}
    if client:
        unit_cost = 0.0006
        affordable = min(len(candidates), int(args.max_serp_cost / unit_cost) if unit_cost else len(candidates))
        if affordable < len(candidates):
            print(f"      Budget cap ${args.max_serp_cost:.2f} allows {affordable} SERPs.")
        keywords = [c["query"] for c in candidates[:affordable]]
        print(f"[2/3] DataForSEO Standard Queue: posting {len(keywords)} SERP tasks ...")
        try:
            client.post_serp_tasks(keywords, depth=10)
        except Exception as exc:  # noqa: BLE001 - degrade to GSC-only
            print(f"      task_post failed ({exc}); continuing GSC-only.")
        remaining = dict.fromkeys(keywords)
        poll_deadline = time.time() + args.queue_wait_mins * 60
        while remaining and time.time() < poll_deadline:
            time.sleep(60)
            try:
                entries = client.collect_ready_tasks()
            except Exception as exc:  # noqa: BLE001
                print(f"      queue sweep failed ({exc}); retrying.")
                continue
            for entry in entries:
                keyword = str(entry.get("keyword", ""))
                items = entry.get("items") or []
                if keyword in remaining and items:
                    serp_by_query[keyword] = items
                    remaining.pop(keyword, None)
            if client.last_queue_state.get("pending"):
                print(f"      {len(serp_by_query)}/{len(keywords)} SERPs ready, "
                      f"{client.last_queue_state['pending']} pending ...")
        if remaining:
            print(f"      {len(remaining)} SERPs still pending -> GSC-only fallback for those.")
    else:
        print("[2/3] Skipping DataForSEO enrichment (GSC-only mode).")

    print("[3/3] Computing 8-feature matrix ...")
    feature_rows: List[Dict[str, Any]] = []
    for cand in candidates:
        serp_items = serp_by_query.get(cand["query"], [])
        serp_feats = compute_serp_features(serp_items, cand["query"]) if serp_items else {
            "serp_forum_ratio": 0.0, "title_exact_match_rate": 0.0, "serp_pixel_crowding": 0.0,
        }
        volume = None
        for item in serp_items:
            if item.get("type") == "keyword_info" or "keyword_volume" in item:
                volume = float(item.get("keyword_volume") or item.get("vol") or 0) or None
                break
        volume_log = math.log10(volume + 1) if volume else math.log10(cand["impressions"] + 1) * 2.0

        cluster_path = cand["page"].split("://", 1)[-1].split("/")
        cluster_id = cluster_path[1] if len(cluster_path) > 1 else "root"
        prefix = ("/" + "/".join(cluster_path[:2])).rstrip("/").lower()
        hub_count = hub_links.get(prefix, hub_links.get(cand["page"].rstrip("/").lower(), 0.0))

        feature_rows.append({
            "query": cand["query"],
            "page": cand["page"],
            "cluster_id": cluster_id,
            "clicks_30d": cand["clicks_30d"],
            "impressions": cand["impressions"],
            "current_pos": cand["current_pos"],
            "ctr": cand["ctr"],
            "features": {
                "domain_centroid_sim": round(cosine(tokenize(cand["query"]), domain_counter), 6),
                "serp_forum_ratio": round(serp_feats["serp_forum_ratio"], 6),
                "title_exact_match_rate": round(serp_feats["title_exact_match_rate"], 6),
                "serp_pixel_crowding": serp_feats["serp_pixel_crowding"],
                "parent_hub_internal_links": float(hub_count),
                "current_pos": cand["current_pos"],
                "search_volume_log": round(volume_log, 6),
                "conversion_intent_score": 0.0,
            },
        })

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as fh:
        json.dump({
            "site": args.site,
            "generated_at": __import__("datetime").datetime.now().isoformat(),
            "gsc_rows": len(rows),
            "dataforseo_enriched": len(serp_by_query),
            "rows": feature_rows,
        }, fh, indent=2)
    print(f"Wrote {len(feature_rows)} feature rows -> {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
