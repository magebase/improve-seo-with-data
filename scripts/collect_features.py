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

Candidate-pipeline upgrades (queue volume on every run):

    # Inject net-new candidates from DataForSEO Labs suggestions (LIVE cost)
    python3 scripts/collect_features.py --site crewelo.com \\
        --suggest-seeds "sms verification,disposable number" --suggest-limit 200

    # Bootstrap a 0-row site from 2-3 niche competitors' ranked keywords
    python3 scripts/collect_features.py --site mintok.adstim.net \\
        --seed-from-competitors "competitor1.com,competitor2.com"

    # One-time 365-day backfill pull to fast-forward the clicked-row
    # graduation counter (25/50 -> fleet-clicks label mode)
    python3 scripts/collect_features.py --site smsriver.com --backfill-days 365
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime, timedelta
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dataforseo_client import DataForSEOClient, resolve_credentials
from gsc_analyzer import find_seo_binary, run_seo_report

STOP_TOKENS = {
    "the",
    "a",
    "an",
    "for",
    "to",
    "of",
    "in",
    "on",
    "and",
    "or",
    "is",
    "it",
    "how",
    "what",
    "best",
    "vs",
    "with",
    "at",
    "by",
    "from",
    "my",
    "your",
}


def find_performance_rows(payload: Any) -> list[dict[str, Any]]:
    """Recursively locates GSC rows (query/page/clicks/impressions) in a report."""
    found: list[dict[str, Any]] = []

    def walk(node: Any) -> None:
        if isinstance(node, list):
            if node and all(isinstance(r, dict) for r in node):
                keys = set().union(*(set(r.keys()) for r in node))
                if (
                    keys & {"query", "keyword"}
                    and keys & {"clicks"}
                    and keys & {"impressions"}
                ):
                    found.extend([r for r in node if isinstance(r, dict)])
            for item in node:
                walk(item)
        elif isinstance(node, dict):
            for value in node.values():
                walk(value)

    walk(payload)
    return found


def synthesize_unseen_rows(
    items: list[dict[str, Any]],
    domain: str,
    source: str,
    min_volume: float = 50.0,
    max_difficulty: float = 35.0,
) -> list[dict[str, Any]]:
    """Converts DataForSEO Labs items into scoreable unseen candidates.

    Unseen candidates have no GSC history yet: they carry current_pos=100
    (-> prescribe_action routes them to LAUNCH_PSEO_ROUTE) and their search
    volume stands in for impressions so the volume-log feature is real.
    Rows failing the volume/difficulty gate are dropped here.
    """
    domain = domain.replace("sc-domain:", "").strip().lower()
    rows: list[dict[str, Any]] = []
    for item in items:
        keyword = str(item.get("keyword") or "").strip()
        if not keyword:
            continue
        volume = float(
            item.get("volume")
            or (item.get("keyword_info") or {}).get("search_volume")
            or 0
        )
        difficulty = item.get("difficulty")
        if difficulty is None:
            difficulty = (item.get("keyword_info") or {}).get("keyword_difficulty")
        if volume < min_volume:
            continue
        if difficulty is not None and float(difficulty) > max_difficulty:
            continue
        slug = "-".join(tokenize(keyword)) or "unseen"
        rows.append(
            {
                "query": keyword,
                "page": f"https://{domain}/{slug}/",
                "clicks_30d": 0.0,
                "impressions": volume,
                "current_pos": 100.0,
                "ctr": 0.0,
                "window_days": 0,
                "source": source,
            }
        )
    return rows


def pull_gsc_window(site: str, start: str, end: str) -> list[dict[str, Any]]:
    """Pulls a (query, page) GSC window via `seo gsc-query` subprocess.

    Used for the 365-day clicked-row backfill (fast-forwards the bootstrap ->
    fleet-clicks label-mode graduation) and for post-deploy recrawl-verification
    windows (Stage 4 recrawl-lag guard). Returns collect_features-shaped
    candidate dicts.
    """
    seo_bin = find_seo_binary()
    if not seo_bin:
        raise RuntimeError("seo binary not found; cannot pull GSC window")
    cmd = [
        seo_bin,
        "gsc-query",
        "--site",
        f"sc-domain:{site.replace('sc-domain:', '')}",
        "--dimensions",
        "query,page",
        "--start-date",
        start,
        "--end-date",
        end,
        "--json",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if proc.returncode != 0:
        raise RuntimeError(
            f"seo gsc-query failed: {(proc.stderr or proc.stdout)[:200]}"
        )
    payload = json.loads(proc.stdout)
    if payload.get("ok") is False:
        raise RuntimeError(f"seo gsc-query error: {str(payload.get('error'))[:200]}")
    rows: list[dict[str, Any]] = []
    for row in payload.get("rows") or []:
        keys = row.get("keys") or []
        if len(keys) < 2:
            continue
        rows.append(
            {
                "query": str(keys[0]),
                "page": str(keys[1]),
                "clicks_30d": float(row.get("clicks", 0) or 0),
                "impressions": float(row.get("impressions", 0) or 0),
                "current_pos": float(row.get("position", 99) or 99),
                "ctr": float(row.get("ctr", 0) or 0),
                "window_days": 0,
                "source": "gsc_window",
            }
        )
    return rows


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
    "reddit",
    "quora",
    "forum",
    "stackoverflow",
    "stackexchange",
    "medium",
    "substack",
    "discord",
    "community",
    "board.",
)


def compute_serp_features(
    serp_items: list[dict[str, Any]], query: str
) -> dict[str, float]:
    """Derives forum ratio / title match / pixel crowding from a DataForSEO SERP."""
    top10 = [item for item in serp_items[:10] if item.get("type") == "organic"]
    if not top10:
        return {
            "serp_forum_ratio": 0.0,
            "title_exact_match_rate": 0.0,
            "serp_pixel_crowding": 0.0,
        }

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
        # Flag count on the 0-4 scale (cold-start weight -0.15 per block).
        "serp_pixel_crowding": float(min(4, special)),
    }


def extract_special_blocks(serp_items: list[dict[str, Any]]) -> int:
    """Counts distinct above-the-fold crowding blocks in the SERP.

    Semantic contract (reference doc section 4): `serp_pixel_crowding` is a
    FLAG COUNT on the 0-4 scale the cold-start/LTR weights expect — one point
    per block type that pushes the organic fold down the viewport. Verified
    live 2026-11 via the advanced endpoint; bottom-of-page blocks
    (related_searches, people_also_search) do not crowd the organic fold.
    """
    above_fold_types = {
        "ai_overview",
        "featured_snippet",
        "knowledge_graph",
        "local_pack",
        "people_also_ask",
        "discussions_and_forums",
        "video",
        "images",
        "paid",
    }
    present = {str(item.get("type", "")).lower() for item in serp_items}
    return min(4, len(present & above_fold_types))


def load_hub_links(path: str | None) -> dict[str, int]:
    """Loads url_prefix -> internal link count from a 2-column CSV crawl export."""
    mapping: dict[str, int] = {}
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


def load_report_files(paths: list[str]) -> list[dict[str, Any]]:
    """Ingests (query, page, clicks, impressions, position) rows from `seo reports
    run` JSON exports (striking-distance, quick-wins, cannibalisation shapes)."""
    candidates: list[dict[str, Any]] = []
    for path in paths:
        with open(path, encoding="utf-8") as fh:
            payload = json.load(fh)
        if payload.get("ok") is False:
            print(
                f"  WARNING: {path}: {payload.get('error', {}).get('message', 'error')[:80]}"
            )
            continue
        rows = payload.get("items") or []
        days = payload.get("rangeDays", payload.get("range", 90))
        ingested = 0
        for item in rows:
            query = item.get("query")
            pages = item.get("pages") or [
                {
                    "url": item.get("url"),
                    "clicks": item.get("clicks"),
                    "impressions": item.get("impressions"),
                    "position": item.get("position"),
                    "ctr": item.get("ctr"),
                }
            ]
            for page_row in pages:
                page = page_row.get("url")
                if not query or not page:
                    continue
                candidates.append(
                    {
                        "query": str(query),
                        "page": str(page),
                        "clicks_30d": float(page_row.get("clicks", 0) or 0),
                        "impressions": float(page_row.get("impressions", 0) or 0),
                        "current_pos": float(page_row.get("position", 99) or 99),
                        "ctr": float(page_row.get("ctr", 0) or 0),
                        "window_days": int(days) if days else 90,
                    }
                )
                ingested += 1
        print(f"  {path.split('/')[-1]}: {ingested} (query, page) rows ingested")
    return candidates


def expand_candidates(
    candidates: list[dict[str, Any]], args: argparse.Namespace
) -> list[dict[str, Any]]:
    """Injects net-new candidates from DataForSEO Labs (suggestions + competitors).

    Returns the expansion rows (callers extend their candidate list). Fails
    soft: any Labs error degrades to the GSC-only candidate set.
    """
    expansion: list[dict[str, Any]] = []
    if args.gsc_only or not (args.suggest_seeds or args.seed_from_competitors):
        return expansion
    try:
        login, password = resolve_credentials(env=dict(os.environ))
    except RuntimeError as exc:
        print(f"      DataForSEO unavailable ({exc}); candidate expansion skipped.")
        return expansion
    client = DataForSEOClient(login, password)
    if args.suggest_seeds:
        seeds = [s.strip() for s in args.suggest_seeds.split(",") if s.strip()]
        try:
            items = client.keyword_suggestions(
                seeds,
                limit=args.suggest_limit,
                min_volume=args.suggest_min_volume,
                max_difficulty=args.suggest_max_difficulty,
            )
            injected = synthesize_unseen_rows(
                items,
                args.site,
                "dfseo_suggest",
                min_volume=args.suggest_min_volume,
                max_difficulty=args.suggest_max_difficulty,
            )
            print(
                f"      keyword_suggestions: {len(injected)} unseen candidates injected."
            )
            expansion.extend(injected)
        except Exception as exc:  # noqa: BLE001 - degrade to GSC-only
            print(f"      keyword_suggestions failed ({exc}); continuing.")
    if args.seed_from_competitors:
        competitors = [
            c.strip() for c in args.seed_from_competitors.split(",") if c.strip()
        ]
        try:
            comp_rows = client.domain_intersection(
                competitors,
                limit=args.suggest_limit,
                min_volume=args.suggest_min_volume,
            )
            injected = synthesize_unseen_rows(
                comp_rows,
                args.site,
                "dfseo_competitor",
                min_volume=args.suggest_min_volume,
                max_difficulty=args.suggest_max_difficulty,
            )
            print(
                f"      domain_intersection: {len(injected)} competitor candidates injected."
            )
            expansion.extend(injected)
        except Exception as exc:  # noqa: BLE001 - degrade to GSC-only
            print(f"      domain_intersection failed ({exc}); continuing.")
    return expansion


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--site", required=True, help="GSC property, e.g. smsriver.com")
    parser.add_argument("--top", type=int, default=150, help="max keywords to enrich")
    parser.add_argument(
        "--gsc-only", action="store_true", help="skip DataForSEO enrichment"
    )
    parser.add_argument("--report", default="search-performance-overview")
    parser.add_argument(
        "--gsc-json",
        action="append",
        default=[],
        help="ingest rows from a `seo reports run` JSON export (repeatable)",
    )
    parser.add_argument("--hub-links", help="CSV export: url_prefix,internal_links")
    parser.add_argument("--output", default="data/ltr_features.json")
    parser.add_argument("--max-serp-cost", type=float, default=5.0, help="USD cap")
    parser.add_argument(
        "--queue-wait-mins",
        type=int,
        default=12,
        help="minutes to poll the DataForSEO queue before falling back",
    )
    parser.add_argument(
        "--suggest-seeds",
        default="",
        help="CSV of 3-5 domain seed terms for DataForSEO Labs "
        "keyword_suggestions (injects net-new candidates; LIVE cost)",
    )
    parser.add_argument("--suggest-limit", type=int, default=100)
    parser.add_argument("--suggest-min-volume", type=int, default=50)
    parser.add_argument("--suggest-max-difficulty", type=int, default=35)
    parser.add_argument(
        "--seed-from-competitors",
        default="",
        help="CSV of 2-3 niche competitor domains for Labs domain_intersection (bootstraps 0-row sites; LIVE cost)",
    )
    parser.add_argument(
        "--backfill-days",
        type=int,
        default=0,
        help="one-time (query, page) GSC backfill window in days (e.g. 365) to fast-forward clicked-row graduation",
    )
    args = parser.parse_args(argv)

    if args.gsc_json:
        print(f"[1/3] Ingesting {len(args.gsc_json)} GSC report export(s) ...")
        candidates = load_report_files(list(args.gsc_json))
    else:
        if not find_seo_binary():
            print(
                "ERROR: seo binary not found; GSC data is unavailable.", file=sys.stderr
            )
            return 1

        print(f"[1/3] Pulling GSC performance for {args.site} via seo binary ...")
        report = run_seo_report(args.report, args.site)
        if not report.get("ok", True) and "error" in report:
            print(f"ERROR: seo report failed: {report['error']}", file=sys.stderr)
            return 1
        rows = find_performance_rows(report)
        if not rows:
            print(
                "ERROR: report contained no query/page performance rows.",
                file=sys.stderr,
            )
            return 1

        candidates = []
        for row in rows:
            query = row.get("query", row.get("keyword"))
            page = row.get("page", row.get("url", row.get("landing_page", "")))
            if not query or not page:
                continue
            candidates.append(
                {
                    "query": str(query),
                    "page": str(page),
                    "clicks_30d": float(row.get("clicks", 0) or 0),
                    "impressions": float(row.get("impressions", 0) or 0),
                    "current_pos": float(
                        row.get("position", row.get("avg_position", 99)) or 99
                    ),
                    "ctr": float(row.get("ctr", 0) or 0),
                    "window_days": 28,
                }
            )
        if args.backfill_days > 0:
            end = datetime.now().date()
            start = end - timedelta(days=args.backfill_days)
            try:
                backfill = pull_gsc_window(
                    args.site, start.isoformat(), end.isoformat()
                )
                print(
                    f"      backfill ({args.backfill_days}d): {len(backfill)} (query, page) rows pulled."
                )
                candidates.extend(backfill)
            except RuntimeError as exc:
                print(
                    f"      backfill failed ({exc}); continuing with the report window."
                )

    # Candidate-pipeline expansion: net-new rows from DataForSEO Labs so thin
    # and 0-row properties surface dozens of LAUNCH_PSEO_ROUTE tasks per run.
    candidates.extend(expand_candidates(candidates, args))

    # Deduplicate on (query, page), keep max impressions.
    best: dict[tuple, dict[str, Any]] = {}
    for cand in candidates:
        key = (cand["query"], cand["page"])
        if key not in best or cand["impressions"] > best[key]["impressions"]:
            best[key] = cand
    candidates = sorted(best.values(), key=lambda c: c["impressions"], reverse=True)[
        : args.top
    ]
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
            print(
                f"[2/3] DataForSEO unavailable ({exc}) -> GSC-only mode "
                "(SERP features fall back to neutral 0.0, volume falls back to impressions)."
            )
    client = DataForSEOClient(login, password) if login and password else None

    hub_links = load_hub_links(args.hub_links)
    serp_by_query: dict[str, list[dict[str, Any]]] = {}
    if client:
        serp_cache_path = os.path.abspath(".serp_cache.json")
        cache: dict[str, list[dict[str, Any]]] = {}
        if os.path.exists(serp_cache_path):
            with open(serp_cache_path, encoding="utf-8") as fh:
                cache = json.load(fh)
        missing = [c["query"] for c in candidates if c["query"] not in cache]
        print(
            f"[2/3] DataForSEO: {len(cache)} cached, {len(missing)} to fetch (budget cap ${args.max_serp_cost:.2f}) ..."
        )
        unit_cost = 0.0006
        affordable = (
            missing[: int(args.max_serp_cost / unit_cost)] if unit_cost else missing
        )
        if affordable:
            try:
                client.post_serp_tasks(affordable, depth=10)
            except Exception as exc:  # noqa: BLE001 - degrade to cache-only
                print(f"      task_post failed ({exc}).")
        poll_deadline = time.time() + args.queue_wait_mins * 60
        while affordable and time.time() < poll_deadline:
            if not [q for q in affordable if q not in cache]:
                break
            time.sleep(60)
            try:
                entries = client.collect_ready_tasks()
            except Exception as exc:  # noqa: BLE001
                print(f"      queue sweep failed ({exc}); retrying.")
                continue
            for entry in entries:
                keyword = str(entry.get("keyword", ""))
                items = entry.get("items") or []
                if keyword in affordable and items and keyword not in cache:
                    cache[keyword] = items
            got = sum(1 for q in affordable if q in cache)
            print(f"      {got}/{len(affordable)} fetched ...")
        with open(serp_cache_path, "w", encoding="utf-8") as fh:
            json.dump(cache, fh)
        serp_by_query = {
            c["query"]: cache[c["query"]] for c in candidates if c["query"] in cache
        }
        print(
            f"      SERP features available for {len(serp_by_query)}/{len(candidates)} candidates."
        )
    else:
        print("[2/3] Skipping DataForSEO enrichment (GSC-only mode).")

    print("[3/3] Computing 8-feature matrix ...")
    feature_rows: list[dict[str, Any]] = []
    for cand in candidates:
        serp_items = serp_by_query.get(cand["query"], [])
        serp_feats = (
            compute_serp_features(serp_items, cand["query"])
            if serp_items
            else {
                "serp_forum_ratio": 0.0,
                "title_exact_match_rate": 0.0,
                "serp_pixel_crowding": 0.0,
            }
        )
        volume = None
        for item in serp_items:
            if item.get("type") == "keyword_info" or "keyword_volume" in item:
                volume = (
                    float(item.get("keyword_volume") or item.get("vol") or 0) or None
                )
                break
        volume_log = (
            math.log10(volume + 1)
            if volume
            else math.log10(cand["impressions"] + 1) * 2.0
        )

        cluster_path = cand["page"].split("://", 1)[-1].split("/")
        cluster_id = cluster_path[1] if len(cluster_path) > 1 else "root"
        prefix = ("/" + "/".join(cluster_path[:2])).rstrip("/").lower()
        hub_count = hub_links.get(
            prefix, hub_links.get(cand["page"].rstrip("/").lower(), 0.0)
        )

        feature_rows.append(
            {
                "query": cand["query"],
                "page": cand["page"],
                "cluster_id": cluster_id,
                "clicks_30d": cand["clicks_30d"],
                "impressions": cand["impressions"],
                "current_pos": cand["current_pos"],
                "ctr": cand["ctr"],
                "features": {
                    "domain_centroid_sim": round(
                        cosine(tokenize(cand["query"]), domain_counter), 6
                    ),
                    "serp_forum_ratio": round(serp_feats["serp_forum_ratio"], 6),
                    "title_exact_match_rate": round(
                        serp_feats["title_exact_match_rate"], 6
                    ),
                    "serp_pixel_crowding": serp_feats["serp_pixel_crowding"],
                    "parent_hub_internal_links": float(hub_count),
                    "current_pos": cand["current_pos"],
                    "search_volume_log": round(volume_log, 6),
                    "conversion_intent_score": 0.0,
                },
            }
        )

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as fh:
        json.dump(
            {
                "site": args.site,
                "generated_at": __import__("datetime").datetime.now().isoformat(),
                "gsc_rows": len(candidates),
                "dataforseo_enriched": len(serp_by_query),
                "rows": feature_rows,
            },
            fh,
            indent=2,
        )
    print(f"Wrote {len(feature_rows)} feature rows -> {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
