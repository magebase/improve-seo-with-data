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
import re
import sqlite3
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime, timedelta
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from candidate_hygiene import (
    canonicalize_and_dedupe_candidates,
    resolve_redirects,
)
from dataforseo_client import DataForSEOClient, resolve_credentials
from fleet_state import (
    DEFAULT_DAILY_SERP_BUDGET,
    DailyBudgetGate,
    connect_state_db,
    extract_route_family,
    gsc_snapshot_fresh,
    inspection_calls_remaining,
    load_cached_serps,
    load_gsc_snapshot,
    load_url_inspections,
    record_inspection_calls,
    save_gsc_snapshot,
    save_url_inspections,
    upsert_serp_cache,
)
from gsc_analyzer import find_seo_binary, run_seo_report
from ltr_ranker import ORPHAN_ACTIONS, expected_ctr

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


SITEMAP_URL_TIMEOUT = 30.0


def three_way_matrix_from_sitemap(
    sitemap_urls: list[str],
    family_prefix: str,
    modifiers: list[str],
    templates: list[str],
    max_rows: int = 100,
) -> list[dict[str, Any]]:
    """Exhaustion-guard expansion: entity x modifier long-tail candidates.

    Engaged when the pairwise catalog space is exhausted (every pair already
    built) or when the pending task backlog has burned below the exhaustion
    threshold. Modifiers are semantic long-tail extensions ("free", "without
    verification", "2026", ...) crossed with the family's entity vocabulary —
    still zero network cost; demand is verified later by the surrogate or a
    budget-gated SERP pull.
    """
    domain_match = re.match(
        r"https?://([^/]+)/", (sitemap_urls[0] if sitemap_urls else "")
    )
    domain = (domain_match.group(1) if domain_match else "").lower()
    prefix = family_prefix.strip("/")
    single_pattern = re.compile(rf"/{re.escape(prefix)}/([a-z0-9-]+)/", re.IGNORECASE)
    vocab: list[str] = []
    for url in sitemap_urls:
        single = single_pattern.search(url)
        if single and single.group(1).lower() not in vocab:
            vocab.append(single.group(1).lower())
    vocab.sort()
    rows: list[dict[str, Any]] = []
    for template in templates:
        for modifier in modifiers:
            for entity in vocab:
                query = template.format(entity=entity, modifier=modifier)
                if "{entity}" in query or "{modifier}" in query:
                    continue  # template not three-way compatible
                slug = "-".join(tokenize(query)) or "expansion"
                rows.append(
                    {
                        "query": query,
                        "page": f"https://{domain}/{prefix}/{slug}/",
                        "clicks_30d": 0.0,
                        "impressions": 0.0,
                        "current_pos": 100.0,
                        "ctr": 0.0,
                        "window_days": 0,
                        "source": "three_way_matrix",
                    }
                )
                if len(rows) >= max_rows:
                    return rows
    return rows


def inspect_coverage_states(
    site: str,
    urls: list[str],
    state_conn: Any = None,
    max_calls: int = 40,
    ttl_hours: int = 24 * 7,
    runner: Any = None,
) -> dict[str, dict[str, Any]]:
    """Live GSC URL Inspection enrichment for the highest-value unindexed URLs.

    The 2,000 calls/day/property allowance is free but per-property; the fleet
    state DB caches every result for 7 days and counts every call against a
    daily gate, so repeated invocations never re-inspect a fresh URL. Pass
    ``runner(site, url) -> dict`` to inject a transport (tests); the default
    shells out to the ``seo url-inspect`` CLI. Failures degrade to a skip —
    an inspection outage must never kill collection.
    """
    import subprocess

    targets: list[str] = []
    seen: set = set()
    for url in urls:
        key = str(url).rstrip("/")
        if key not in seen:
            seen.add(key)
            targets.append(str(url))

    results: dict[str, dict[str, Any]] = {}
    pending: list[str] = []
    if state_conn is not None:
        cached = load_url_inspections(state_conn, targets, max_age_hours=ttl_hours)
        results.update(cached)
        pending = [
            u for u in targets if u.rstrip("/") not in {k.rstrip("/") for k in cached}
        ]
    else:
        pending = targets
    pending = pending[: max(0, max_calls)]
    if not pending:
        return results

    if runner is None:
        seo_bin = find_seo_binary()
        if not seo_bin:
            print("      URL inspection skipped: seo binary not found.")
            return results

        def runner(site: str, url: str) -> dict[str, Any]:
            site_param = (
                site
                if site.startswith("http") or site.startswith("sc-domain:")
                else f"sc-domain:{site}"
            )
            proc = subprocess.run(
                [seo_bin, "url-inspect", "--site", site_param, "--url", url, "--json"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if proc.returncode != 0:
                raise RuntimeError(proc.stderr or proc.stdout or "url-inspect failed")
            return json.loads(proc.stdout)

    budget_left = (
        inspection_calls_remaining(state_conn)
        if state_conn is not None
        else len(pending)
    )
    inspected: dict[str, dict[str, Any]] = {}
    for url in pending:
        if budget_left <= 0:
            print(
                "      URL inspection daily budget exhausted - remaining URLs "
                "retried tomorrow (cached results only)."
            )
            break
        try:
            payload = runner(site, url)
        except Exception as exc:  # noqa: BLE001 - single URL failure must not kill the batch
            print(f"      inspection failed for {url} ({exc}).")
            continue
        status = (payload.get("inspectionResult") or {}).get("indexStatusResult") or {}
        inspected[url] = {
            "coverage_state": status.get("coverageState"),
            "indexing_state": status.get("indexingState"),
            "last_crawl_time": status.get("lastCrawlTime"),
        }
        budget_left -= 1

    if inspected and state_conn is not None:
        save_url_inspections(state_conn, site, inspected)
        record_inspection_calls(state_conn, len(inspected))
    results.update(inspected)
    return results


def pairwise_matrix_from_sitemap(
    sitemap_urls: list[str],
    family_prefix: str,
    templates: list[str],
    max_pairs: int = 50,
) -> list[dict[str, Any]]:
    """Tier-3 combinatorial expansion: unbuilt entity pairs from a live family.

    Reads the entity vocabulary from EXISTING sitemap routes under one family
    prefix (e.g. /receive-sms/{cc}/, /convert/{a}-to-{b}/), then proposes the
    pairwise combinations NOT yet built through the caller's modifier
    templates. Zero network cost; demand signals arrive later via the
    surrogate or a SERP pull on the few pairs the ranker promotes.
    """
    domain_match = re.match(
        r"https?://([^/]+)/", (sitemap_urls[0] if sitemap_urls else "")
    )
    domain = (domain_match.group(1) if domain_match else "").lower()
    prefix = family_prefix.strip("/")
    vocab: list[str] = []
    pair_pattern = re.compile(
        rf"/{re.escape(prefix)}/([a-z0-9-]+)-to-([a-z0-9-]+)/", re.IGNORECASE
    )
    single_pattern = re.compile(rf"/{re.escape(prefix)}/([a-z0-9-]+)/", re.IGNORECASE)
    existing_pairs: set = set()
    for url in sitemap_urls:
        pair = pair_pattern.search(url)
        if pair:
            existing_pairs.add((pair.group(1).lower(), pair.group(2).lower()))
            for entity in (pair.group(1), pair.group(2)):
                if entity.lower() not in vocab:
                    vocab.append(entity.lower())
            continue
        single = single_pattern.search(url)
        if single:
            entity = single.group(1).lower()
            if entity not in vocab:
                vocab.append(entity)
    vocab.sort()  # deterministic alphabetical ordering across runs
    rows: list[dict[str, Any]] = []
    for template in templates:
        if "{a}" in template and "{b}" in template:
            combos = [
                (a, b)
                for a in vocab
                for b in vocab
                if a != b and (a, b) not in existing_pairs
            ]
            rendered = [template.format(a=a, b=b) for a, b in combos]
        else:
            rendered = [template.format(entity=e) for e in vocab]
        for rendered_query in rendered[:max_pairs]:
            slug = "-".join(tokenize(rendered_query)) or "pair"
            rows.append(
                {
                    "query": rendered_query,
                    "page": f"https://{domain}/{prefix}/{slug}/",
                    "clicks_30d": 0.0,
                    "impressions": 0.0,
                    "current_pos": 100.0,
                    "ctr": 0.0,
                    "window_days": 0,
                    "source": "catalog_matrix",
                }
            )
    return rows[:max_pairs]


def ensure_candidate_depth(
    domain: str,
    candidates: list[dict[str, Any]],
    sitemap_urls: list[str],
    min_rows: int = 150,
    matrix_fn: Any = None,
    suggest_fn: Any = None,
    three_way_fn: Any = None,
    pending_backlog: int | None = None,
    exhaustion_threshold: int = 200,
    shipped_pairs: set | None = None,
) -> tuple:
    """4-tier waterfall guaranteeing >= min_rows scoreable candidates.

    Tier 1: GSC candidates (minus recently shipped (page, query) pairs).
    Tier 2: zero-impression sitemap orphans (already collected upstream).
    Tier 3: combinatorial entity matrix via ``matrix_fn(need)``.
    Tier 3.5 (exhaustion guard): ``three_way_fn(need)`` semantic modifier
    expansion — engaged when the pairwise space is exhausted (the matrix
    returned nothing) OR when the fleet's pending task backlog has burned
    below ``exhaustion_threshold`` (default 200): high invocation frequency
    consumes the finite pair catalog, so generation shifts to long-tail
    modifiers before any paid tier runs.
    Tier 4: DataForSEO suggestions via ``suggest_fn(need)`` (the only
    potentially-costly tier; callers pass None to stay offline).
    Returns (rows, tier_report) — the report names every tier actually used.
    """
    shipped_pairs = shipped_pairs or set()
    active = [
        c
        for c in candidates
        if (str(c["page"]).rstrip("/"), str(c["query"]).strip().lower())
        not in shipped_pairs
    ]
    tiers_used = ["gsc"] if active else []

    def _need() -> int:
        return max(0, min_rows - len(active))

    if _need() and sitemap_urls:
        gsc_pages = {str(c["page"]).rstrip("/") + "/" for c in candidates}
        orphans = synthesize_orphan_rows(sitemap_urls, gsc_pages, domain=domain)
        if orphans:
            active.extend(orphans[: _need()])
            tiers_used.append("sitemap_orphans")

    matrix_yielded = False
    if _need() and matrix_fn is not None:
        matrix_rows = matrix_fn(_need())[: _need()]
        active.extend(matrix_rows)
        tiers_used.append("catalog_matrix")
        matrix_yielded = bool(matrix_rows)

    exhausted = (
        pending_backlog is not None and pending_backlog < exhaustion_threshold
    ) or (matrix_fn is not None and not matrix_yielded)
    if _need() and exhausted and three_way_fn is not None:
        active.extend(three_way_fn(_need())[: _need()])
        tiers_used.append("three_way_expansion")

    if _need() and suggest_fn is not None:
        active.extend(suggest_fn(_need())[: _need()])
        tiers_used.append("dfseo_suggest")

    return active, {"tiers_used": tiers_used, "rows": len(active), "min_rows": min_rows}


def mine_paa_and_related_from_cache(
    conn_or_cache: Any,
    domain: str,
    sitemap_urls: list[str] | None = None,
    max_candidates: int = 75,
) -> list[dict[str, Any]]:
    """Mines People-Also-Ask (PAA) and related search queries from cached SERP blobs.

    Zero-cost candidate source: reads Google's own PAA questions and related searches
    cached in dfs_serp_cache / .serp_cache.json, filters them for topical relevance
    against the target domain's vocabulary, and maps each query to its best existing
    sitemap route (for H2/FAQ/table enrichments) or a clean programmatic route.
    """
    clean_domain = str(domain).replace("sc-domain:", "").strip().lower()
    if not clean_domain:
        return []

    # 1. Build domain topical vocabulary
    domain_vocab: set[str] = set()
    domain_seed = clean_domain.split(".")[0]
    for tok in tokenize(domain_seed):
        domain_vocab.add(tok)

    if sitemap_urls:
        for u in sitemap_urls:
            domain_vocab.update(tokenize(u))

    domain_vocab.discard("https")
    domain_vocab.discard("http")
    domain_vocab.discard("com")
    domain_vocab.discard("net")
    domain_vocab.discard("org")

    domain_queries: set[str] = set()
    cache_rows: list[tuple[str, Any]] = []

    # 2. Extract from sqlite3 connection, dict, or file
    if hasattr(conn_or_cache, "execute"):
        cur = conn_or_cache.cursor()
        try:
            for (q,) in cur.execute(
                "SELECT DISTINCT lower(trim(query)) FROM atomic_task_backlog WHERE domain = ? AND status = 'SHIPPED' AND query IS NOT NULL",
                (clean_domain,),
            ):
                if q:
                    domain_queries.add(q)
                    domain_vocab.update(tokenize(q))
        except Exception:  # noqa: BLE001
            pass

        try:
            for (rows_json,) in cur.execute(
                "SELECT rows_json FROM gsc_snapshots WHERE site LIKE ? ORDER BY window_end DESC LIMIT 2",
                (f"%{clean_domain}%",),
            ):
                try:
                    for r in json.loads(rows_json):
                        q = str(r.get("query") or "").lower().strip()
                        if q:
                            domain_queries.add(q)
                            domain_vocab.update(tokenize(q))
                except Exception:  # noqa: BLE001
                    pass
        except Exception:  # noqa: BLE001
            pass

        try:
            for sq, items_str in cur.execute("SELECT query, items_json FROM dfs_serp_cache"):
                cache_rows.append((sq, items_str))
        except Exception:  # noqa: BLE001
            pass

    elif isinstance(conn_or_cache, dict):
        for sq, data in conn_or_cache.items():
            if isinstance(data, dict):
                items = data.get("items") or []
                cache_rows.append((sq, items))
            elif isinstance(data, list):
                cache_rows.append((sq, data))

    elif isinstance(conn_or_cache, str) and os.path.isfile(conn_or_cache):
        if conn_or_cache.endswith((".db", ".sqlite")):
            try:
                temp_conn = sqlite3.connect(conn_or_cache)
                return mine_paa_and_related_from_cache(
                    temp_conn, clean_domain, sitemap_urls=sitemap_urls, max_candidates=max_candidates
                )
            except Exception:  # noqa: BLE001
                pass
        else:
            try:
                with open(conn_or_cache, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                if isinstance(data, dict):
                    return mine_paa_and_related_from_cache(
                        data, clean_domain, sitemap_urls=sitemap_urls, max_candidates=max_candidates
                    )
            except Exception:  # noqa: BLE001
                pass

    if not cache_rows:
        return []

    generic_web_tokens = {
        "free", "online", "download", "tool", "tools", "app", "apps",
        "best", "near", "service", "services", "web", "site", "page",
        "guide", "overview", "list", "top", "how", "what", "calculator",
    }

    candidates: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    for serp_q, items_val in cache_rows:
        if isinstance(items_val, str):
            try:
                items = json.loads(items_val)
            except Exception:
                continue
        elif isinstance(items_val, list):
            items = items_val
        else:
            continue

        serp_q_clean = str(serp_q).lower().strip()
        serp_toks = set(tokenize(serp_q_clean))
        is_known_query = (serp_q_clean in domain_queries) or isinstance(conn_or_cache, dict)
        # Multi-tenant fleet barrier: only mine cached SERPs for queries verified to belong to this domain
        if not is_known_query:
            continue

        for it in items:
            if not isinstance(it, dict):
                continue
            t = it.get("type")
            extracted: list[tuple[str, str]] = []
            if t == "people_also_ask":
                for elem in (it.get("items") or []):
                    if isinstance(elem, dict):
                        title = elem.get("title") or elem.get("keyword")
                        if title:
                            extracted.append(("paa", str(title)))
            elif t in ("related_searches", "people_also_search"):
                for elem in (it.get("items") or []):
                    if isinstance(elem, str):
                        extracted.append(("related_search", elem))
                    elif isinstance(elem, dict):
                        title = elem.get("title") or elem.get("keyword")
                        if title:
                            extracted.append(("related_search", str(title)))

            for kind, raw_text in extracted:
                clean_text = raw_text.strip().rstrip("?.!").strip()
                if len(clean_text) < 3:
                    continue
                q_toks = set(tokenize(clean_text))
                if not q_toks:
                    continue

                specific_overlap = (q_toks & domain_vocab) - generic_web_tokens
                if not specific_overlap and len(q_toks & domain_vocab) < 2:
                    continue

                # Map to best existing sitemap URL if high token overlap
                best_url = None
                best_overlap = 0
                if sitemap_urls:
                    for u in sitemap_urls:
                        u_path = u.split("://", 1)[-1].split("?", 1)[0]
                        u_toks = (
                            set(tokenize(u_path))
                            - {"https", "http", "com", "net", "org"}
                            - set(tokenize(clean_domain.split(".")[0]))
                        )
                        ov = len(q_toks & u_toks)
                        if ov > best_overlap and ov >= 2:
                            best_overlap = ov
                            best_url = u

                if not best_url:
                    slug = "-".join(list(tokenize(clean_text).keys())) or "guide"
                    best_url = f"https://{clean_domain}/{slug}/"

                key = (clean_text.lower(), best_url.lower().rstrip("/"))
                if key in seen:
                    continue
                seen.add(key)

                candidates.append(
                    {
                        "query": clean_text,
                        "page": best_url,
                        "clicks_30d": 0.0,
                        "impressions": 50.0 if kind == "paa" else 75.0,
                        "current_pos": 100.0,
                        "ctr": 0.0,
                        "window_days": 0,
                        "source": f"{kind}_expansion",
                    }
                )
                if len(candidates) >= max_candidates:
                    return candidates

    return candidates


def auto_expand_candidates_if_depleted(
    domain: str,
    candidates: list[dict[str, Any]],
    sitemap_urls: list[str] | None = None,
    state_conn: Any = None,
    pending_threshold: int = 15,
    min_rows: int = 150,
    force: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Auto-triggers Tier-2/Tier-3 expansion when domain pending task backlog < threshold.

    Prevents pipeline starvation when high-frequency waves burn down the atomic
    task backlog faster than GSC refreshes. Executes:
      1. Zero-impression sitemap orphan routes (Tier 2.1).
      2. Mined PAA questions and related searches from cached SERPs (Tier 2.2).
      3. Combinatorial entity pairwise and three-way modifier matrices (Tier 3).
    """
    clean_domain = str(domain).replace("sc-domain:", "").strip().lower()
    sitemap_urls = sitemap_urls or []

    pending = 0
    if state_conn is not None and hasattr(state_conn, "execute"):
        try:
            row = state_conn.execute(
                "SELECT COUNT(*) FROM atomic_task_backlog WHERE domain = ? AND status = 'PENDING'",
                (clean_domain,),
            ).fetchone()
            pending = int(row[0]) if row else 0
        except Exception:
            pending = 0

    should_expand = force or (pending < pending_threshold) or (len(candidates) < min_rows)
    if not should_expand:
        return candidates, {
            "expanded": False,
            "pending_before": pending,
            "reason": "backlog_healthy",
            "threshold": pending_threshold,
        }

    # Invariant P0: Property-Specific, Age-Adjusted Expansion Gate (Outcome Engine v2.2.1)
    # Replaces flat cutoff with diagnostic indexation debt assessment (Awaiting Crawl vs Discovered vs Crawled vs Technical)
    if state_conn is not None and hasattr(state_conn, "execute") and not force:
        try:
            insp_rows = state_conn.execute(
                "SELECT coverage_state, last_crawl_time FROM url_inspections WHERE url LIKE ?",
                (f"%{clean_domain}%",),
            ).fetchall()
            if insp_rows:
                total_insp = len(insp_rows)
                indexed = 0
                discovered_not_indexed = 0
                crawled_not_indexed = 0
                duplicate_canonical = 0
                technical_excluded = 0
                awaiting_crawl = 0

                for cov, last_crawl in insp_rows:
                    cov_clean = str(cov or "").strip().lower()
                    if cov_clean == "submitted and indexed":
                        indexed += 1
                    elif "discovered" in cov_clean:
                        discovered_not_indexed += 1
                    elif "crawled" in cov_clean:
                        crawled_not_indexed += 1
                    elif "duplicate" in cov_clean or "canonical" in cov_clean:
                        duplicate_canonical += 1
                    elif "noindex" in cov_clean or "404" in cov_clean or "5" in cov_clean:
                        technical_excluded += 1
                    elif "unknown" in cov_clean or not last_crawl:
                        awaiting_crawl += 1
                    else:
                        awaiting_crawl += 1

                eligible_pool = total_insp - awaiting_crawl
                debt_count = discovered_not_indexed + crawled_not_indexed + duplicate_canonical + technical_excluded
                adjusted_debt_ratio = debt_count / max(1, eligible_pool)

                if eligible_pool >= 10 and adjusted_debt_ratio > 0.50:
                    # Continue candidate discovery, but restrict admission of new programmatic routes
                    return candidates, {
                        "expanded": False,
                        "admission_restricted": True,
                        "pending_before": pending,
                        "reason": "admission_restricted_indexation_debt",
                        "adjusted_debt_ratio": round(adjusted_debt_ratio, 2),
                        "total_inspected": total_insp,
                        "eligible_pool": eligible_pool,
                        "indexed": indexed,
                        "discovered_not_indexed": discovered_not_indexed,
                        "crawled_not_indexed": crawled_not_indexed,
                        "duplicate_canonical": duplicate_canonical,
                        "technical_excluded": technical_excluded,
                        "awaiting_crawl": awaiting_crawl,
                        "message": (
                            f"Programmatic route admission restricted on {clean_domain}: age-adjusted indexation debt "
                            f"{adjusted_debt_ratio:.1%} > 50.0% (Discovered: {discovered_not_indexed}, Crawled unindexed: {crawled_not_indexed}, "
                            f"Technical: {technical_excluded}, Awaiting crawl: {awaiting_crawl}, Indexed: {indexed}). "
                            f"Discovery active; new page publishing paused."
                        ),
                    }
        except Exception:
            pass

    expanded: list[dict[str, Any]] = list(candidates)
    seen_keys: set[tuple[str, str]] = {
        (str(c.get("query", "")).lower().strip(), str(c.get("page", "")).lower().rstrip("/"))
        for c in expanded
    }

    report = {
        "expanded": True,
        "pending_before": pending,
        "orphans_added": 0,
        "mined_paa_added": 0,
        "pairwise_added": 0,
        "three_way_added": 0,
        "threshold": pending_threshold,
    }

    # Tier 2.1: Sitemap orphan routes
    if sitemap_urls:
        gsc_pages = {str(c["page"]).rstrip("/") + "/" for c in expanded} | {
            str(c["page"]).rstrip("/") for c in expanded
        }
        orphans = synthesize_orphan_rows(sitemap_urls, gsc_pages, domain=clean_domain)
        for o in orphans:
            k = (str(o["query"]).lower().strip(), str(o["page"]).lower().rstrip("/"))
            if k not in seen_keys:
                seen_keys.add(k)
                expanded.append(o)
                report["orphans_added"] += 1

    # Tier 2.2: PAA and related searches from cached SERPs
    if state_conn is not None:
        mined = mine_paa_and_related_from_cache(
            state_conn, clean_domain, sitemap_urls=sitemap_urls, max_candidates=75
        )
        for m in mined:
            k = (str(m["query"]).lower().strip(), str(m["page"]).lower().rstrip("/"))
            if k not in seen_keys:
                seen_keys.add(k)
                expanded.append(m)
                report["mined_paa_added"] += 1

    # Tier 3: Combinatorial entity pairwise & three-way modifier matrices
    if sitemap_urls:
        family_counts: Counter = Counter()
        for u in sitemap_urls:
            fam = extract_route_family(u)
            if fam and fam not in ("root", "static", "media", "assets", "api"):
                family_counts[fam] += 1

        top_families = [fam for fam, cnt in family_counts.most_common(3) if cnt >= 2]
        for fam in top_families:
            if fam in ("convert", "compare", "tools"):
                templates = [
                    f"{fam} {{a}} to {{b}}",
                    f"{{a}} to {{b}} {fam}",
                    "{a} vs {b}",
                ]
            else:
                templates = [f"{fam} {{entity}}", f"{{entity}} {fam}"]

            pairs = pairwise_matrix_from_sitemap(sitemap_urls, fam, templates, max_pairs=30)
            for p in pairs:
                k = (str(p["query"]).lower().strip(), str(p["page"]).lower().rstrip("/"))
                if k not in seen_keys:
                    seen_keys.add(k)
                    expanded.append(p)
                    report["pairwise_added"] += 1

            modifiers = ["free", "online", "2026", "calculator", "without verification"]
            three_way = three_way_matrix_from_sitemap(
                sitemap_urls,
                fam,
                modifiers=modifiers,
                templates=["{entity} {modifier}", "best {entity} {modifier}"],
                max_rows=20,
            )
            for tw in three_way:
                k = (str(tw["query"]).lower().strip(), str(tw["page"]).lower().rstrip("/"))
                if k not in seen_keys:
                    seen_keys.add(k)
                    expanded.append(tw)
                    report["three_way_added"] += 1

    report["total_candidates"] = len(expanded)
    return expanded, report


def dom_gap_flags(
    our_html: str,
    serp_items: list[dict[str, Any]],
    query: str,
    internal_inlinks: float | None = None,
    is_tool_route: bool = False,
    ctr: float | None = None,
    current_pos: float | None = None,
) -> dict[str, Any]:
    """Six structural gap flags: our HTML vs the cached SERP winners.

    Zero-cost when fed from an already-fetched page (e.g. the top-N candidates
    the caller chose to crawl). Flags ride OUTSIDE the 8-feature vector as
    row metadata; compile_wave_backlog turns them into atomic TDD tasks.
    ``title_ctr_deficit`` needs the row's realized CTR and position: it fires
    only when the page underperforms its position-impression propensity curve
    (ctr < 0.6 x expected_ctr(pos)) at position <= 12 AND the <title> carries
    no bracketed hook or number.
    """
    html = (our_html or "").lower()
    query_tokens = set(tokenize(query))
    headings = re.findall(
        r"<h[23][^>]*>(.*?)</h[23]>", html, flags=re.DOTALL | re.IGNORECASE
    )
    heading_text = re.sub(r"<[^>]+>", " ", " ".join(headings)).lower()

    paa_questions: list[str] = []
    for item in serp_items or []:
        if (item.get("type") or "") == "people_also_ask" or item.get("questions"):
            for q in item.get("questions") or []:
                paa_questions.append(
                    q if isinstance(q, str) else str(q.get("question", ""))
                )

    title_match = re.search(
        r"<title[^>]*>(.*?)</title>", html, re.DOTALL | re.IGNORECASE
    )
    title_text = re.sub(r"<[^>]+>", " ", title_match.group(1)) if title_match else ""
    has_ctr_hook = bool(title_text) and (
        "[" in title_text or any(c.isdigit() for c in title_text)
    )
    ctr_deficit = (
        current_pos is not None
        and ctr is not None
        and float(current_pos) <= 12.0
        and float(ctr) < 0.6 * expected_ctr(float(current_pos))
        and not has_ctr_hook
    )

    return {
        "missing_exact_h2": bool(query_tokens)
        and not query_tokens.issubset(set(heading_text.split())),
        "missing_data_table": "<table" not in html,
        "missing_paa_coverage": bool(paa_questions)
        and len([q for q in paa_questions if q.lower() in html]) < 2,
        "weak_internal_inlinks": internal_inlinks is not None
        and internal_inlinks < 3.0,
        "missing_app_schema": is_tool_route
        and "webapplication" not in html
        and "softwareapplication" not in html,
        "title_ctr_deficit": ctr_deficit,
    }


def fetch_sitemap_urls(site: str, timeout: float = SITEMAP_URL_TIMEOUT) -> list[str]:
    """Fetches the live /sitemap.xml <loc> URLs (one index level supported).

    Zero-cost candidate source: a sitemap URL Google has NEVER served
    (0 GSC impressions) is an orphaned/unindexed route the codebase already
    deployed — the cheapest internal-link and depth-expansion targets there
    are, before any DataForSEO spend.
    """
    import re
    import urllib.request

    base = site.replace("sc-domain:", "").strip().lower()
    url = f"https://{base}/sitemap.xml"
    req = urllib.request.Request(url, headers={"User-Agent": "seo-growth-skill/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8", errors="replace")
    locs = re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", body)
    if "<sitemapindex" in body:
        nested: list[str] = []
        for child in locs[:20]:  # bound: sitemap indexes rarely exceed this
            try:
                child_req = urllib.request.Request(
                    child, headers={"User-Agent": "seo-growth-skill/1.0"}
                )
                with urllib.request.urlopen(child_req, timeout=timeout) as child_resp:
                    nested.extend(
                        re.findall(
                            r"<loc>\s*([^<\s]+)\s*</loc>",
                            child_resp.read().decode("utf-8", errors="replace"),
                        )
                    )
            except Exception:  # noqa: BLE001 - one dead child sitemap must not kill the sweep
                continue
        locs.extend(nested)
    return [loc.rstrip("/") + "/" for loc in locs if loc.startswith("http")]


def synthesize_orphan_rows(
    sitemap_urls: list[str],
    gsc_pages: set,
    domain: str,
) -> list[dict[str, Any]]:
    """Left-joins sitemap URLs against GSC pages; injects zero-impression orphans.

    Orphan rows carry current_pos=100 and zero impressions (honest: no demand
    signal yet), a slug-synthesized demand proxy query, and the ORPHAN_ACTIONS
    prescription set (the route already exists — it needs links, not launch).
    """
    domain = domain.replace("sc-domain:", "").strip().lower()
    rows: list[dict[str, Any]] = []
    seen: set = set()
    for url in sitemap_urls:
        url = url.strip()
        if not url or url in seen or url in gsc_pages:
            continue
        if url.lower().rstrip("/").endswith(".xml"):
            continue  # sitemap index files are not pages; never emit tasks for them
        seen.add(url)
        path = url.split("://", 1)[-1].split("?", 1)[0].rstrip("/")
        slug = path.rsplit("/", 1)[-1] if "/" in path else path
        rel_path = ("/" + path.split("/", 1)[1]) if "/" in path else "/"
        # Skip top-level category/hub/index routes (e.g. /compare/, /calculators/, /tools/, /articles/)
        hub_paths = {
            "",
            "/",
            "/compare",
            "/calculators",
            "/articles",
            "/tools",
            "/niche",
            "/convert",
            "/studio",
            "/guides",
        }
        if rel_path.rstrip("/") in hub_paths:
            continue
        slug_tokens = tokenize(slug)
        # Never synthesize 1-word queries from hub/category slugs (e.g., /compare/ or /niche/insurance/)
        first_segment = rel_path.strip("/").split("/")[0] if rel_path.strip("/") else ""
        if (
            first_segment in {"compare", "calculators", "articles", "tools", "niche", "convert", "studio", "guides"}
            and len(slug_tokens) < 2
        ):
            continue
        query = " ".join(slug_tokens) or slug
        rows.append(
            {
                "query": query,
                "page": url,
                "clicks_30d": 0.0,
                "impressions": 0.0,
                "current_pos": 100.0,
                "ctr": 0.0,
                "window_days": 0,
                "source": "orphan_route",
                "actions": list(ORPHAN_ACTIONS),
                "prescribed_action": ORPHAN_ACTIONS[0],
            }
        )
    return rows


def serp_item_metadata(
    result_block: dict[str, Any],
    serp_items: list[dict[str, Any]],
    query: str,
) -> dict[str, Any]:
    """Persists DataForSEO ``item_types`` as zero-cost row metadata.

    Every SERP response carries result[0]['item_types'] — the full SERP
    feature list ('organic', 'ai_overview', 'people_also_ask',
    'discussions_and_forums', 'video', ...). Store the flags OUTSIDE the
    canonical 8-feature vector (the vector's order is load-bearing; changing
    it invalidates trained bundles) so prescriptions and triage can consume
    them without retraining.
    """
    types = [str(t) for t in (result_block.get("item_types") or [])]
    return {
        "serp_item_types": types,
        "has_ai_overview": "ai_overview" in types,
        "has_forums": "discussions_and_forums" in types,
        "has_people_also_ask": "people_also_ask" in types,
    }


def gsc_candidates_with_fallback(
    site: str,
    run_report_fn: Any = None,
    pull_window_fn: Any = None,
    window_days: int = 28,
    report_id: str = "search-performance-overview",
) -> tuple:
    """Collects GSC candidates from the composite report, with a window fallback.

    The `seo` binary's report payloads have drifted before (a report that
    carries recommendations but no embedded performance rows). When
    ``find_performance_rows`` finds nothing, this falls back to a raw
    ``gsc-query`` (query, page) window over the last ``window_days`` days —
    the same primitive the backfill and recrawl-verification paths use.
    Returns (candidates, mode) where mode is "report" or "gsc_window".
    """
    report = (run_report_fn or run_seo_report)(report_id, site)
    if not report.get("ok", True) and "error" in report:
        print(
            f"      report failed ({str(report['error'])[:120]}); trying gsc-query window."
        )
        report = {}
    rows = find_performance_rows(report)
    if rows:
        return rows, "report"
    print(
        f"      report carried no performance rows; falling back to a raw "
        f"gsc-query window ({window_days}d)."
    )
    end = datetime.now().date()
    start = end - timedelta(days=window_days)
    window_rows = (pull_window_fn or pull_gsc_window)(
        site, start.isoformat(), end.isoformat()
    )
    if not window_rows:
        raise RuntimeError(
            "no GSC candidates from either the report or the gsc-query window"
        )
    print(f"      gsc-query window: {len(window_rows)} (query, page) rows.")
    return window_rows, "gsc_window"


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
    for raw in (
        str(text)
        .lower()
        .replace("-", " ")
        .replace("/", " ")
        .replace(".", " ")
        .replace("_", " ")
        .split()
    ):
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
        login, password = resolve_credentials()
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
    parser.add_argument(
        "--no-orphans",
        action="store_true",
        help="skip the zero-cost sitemap orphan-route detector",
    )
    parser.add_argument(
        "--no-inspect",
        action="store_true",
        help="skip the GSC URL Inspection coverageState enrichment",
    )
    parser.add_argument(
        "--inspect-limit",
        type=int,
        default=40,
        help="max URL Inspection calls per run (free tier: 2,000/day/property; "
        "results cached 7 days in the state DB)",
    )
    parser.add_argument(
        "--redirect-map",
        action="append",
        default=[],
        help="JSON file mapping legacy/301 URLs to canonical URLs "
        "(repeatable; executor-built from urls.py/RedirectView). Also "
        "auto-loads ~/.seo_fleet/redirect_map.json when it exists",
    )
    parser.add_argument(
        "--no-live-redirects",
        action="store_true",
        help="skip live HTTP redirect probing (file redirect_map only)",
    )
    parser.add_argument(
        "--state-db",
        default="",
        help="SQLite fleet state DB: 24h GSC snapshot fast path, 30d SERP "
        "cache layer, daily DataForSEO budget gate, and the URL Inspection "
        "coverageState cache",
    )
    parser.add_argument(
        "--pending-threshold",
        type=int,
        default=15,
        help="backlog replenishment threshold: when domain pending task count "
        "falls below this (default 15), triggers Tier-2/Tier-3 candidate expansion",
    )
    parser.add_argument(
        "--force-expand",
        action="store_true",
        help="force Tier-2/Tier-3 candidate expansion regardless of pending backlog count",
    )
    args = parser.parse_args(argv)

    state_conn = connect_state_db(args.state_db) if args.state_db else None

    if args.gsc_json:
        print(f"[1/3] Ingesting {len(args.gsc_json)} GSC report export(s) ...")
        candidates = load_report_files(list(args.gsc_json))
        pulled_live = False
    elif state_conn is not None and gsc_snapshot_fresh(
        state_conn, args.site, max_age_hours=24
    ):
        candidates = load_gsc_snapshot(state_conn, args.site, max_age_hours=24)
        pulled_live = False
        print(
            f"[1/3] State DB: fresh (<24h) GSC snapshot for {args.site} "
            f"({len(candidates)} rows) - network pull skipped."
        )
    else:
        pulled_live = True
        if not find_seo_binary():
            print(
                "ERROR: seo binary not found; GSC data is unavailable.", file=sys.stderr
            )
            return 1

        print(f"[1/3] Pulling GSC performance for {args.site} via seo binary ...")
        try:
            rows, source_mode = gsc_candidates_with_fallback(
                args.site, report_id=args.report
            )
        except RuntimeError as exc:
            print(f"ERROR: GSC collection failed: {exc}", file=sys.stderr)
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
                    "clicks_30d": float(
                        row.get("clicks", row.get("clicks_30d", 0)) or 0
                    ),
                    "impressions": float(row.get("impressions", 0) or 0),
                    "current_pos": float(
                        row.get(
                            "position",
                            row.get("current_pos", row.get("avg_position", 99)),
                        )
                        or 99
                    ),
                    "ctr": float(row.get("ctr", 0) or 0),
                    "window_days": row.get("window_days", 28),
                    "source": row.get("source", "gsc"),
                }
            )
        print(f"      GSC source mode: {source_mode} ({len(candidates)} raw rows).")
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
    if pulled_live and state_conn is not None and candidates:
        save_gsc_snapshot(state_conn, args.site, candidates)
        print(f"      State DB: GSC snapshot saved ({len(candidates)} rows, 24h TTL).")
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

    # Orphan route detector: live sitemap URLs Google has never served (0 GSC
    # impressions). Zero-cost candidates for BOOST_INTERNAL_LINKS /
    # EXPAND_THIN_ROUTE work on routes the codebase already deployed.
    if not args.no_orphans:
        try:
            sitemap_urls = fetch_sitemap_urls(args.site)
            gsc_pages = {str(c["page"]).rstrip("/") + "/" for c in candidates} | {
                str(c["page"]).rstrip("/") for c in candidates
            }
            orphans = synthesize_orphan_rows(sitemap_urls, gsc_pages, domain=args.site)
            candidates.extend(orphans)
            print(
                f"      orphan routes: {len(orphans)} zero-impression sitemap URLs injected."
            )
        except Exception as exc:  # noqa: BLE001 - sitemap fetch must never kill collection
            print(f"      orphan detection skipped ({exc}).")

    # Tier-2/Tier-3 auto-expansion when domain pending task backlog < threshold
    if state_conn is not None or args.force_expand:
        try:
            cur_sitemaps = sitemap_urls if not args.no_orphans and "sitemap_urls" in locals() else (
                fetch_sitemap_urls(args.site) if not args.no_orphans else []
            )
            candidates, exp_report = auto_expand_candidates_if_depleted(
                domain=args.site,
                candidates=candidates,
                sitemap_urls=cur_sitemaps,
                state_conn=state_conn,
                pending_threshold=args.pending_threshold,
                min_rows=args.top,
                force=args.force_expand,
            )
            if exp_report.get("expanded"):
                print(
                    f"      candidate expansion (pending={exp_report.get('pending_before', 0)} < {args.pending_threshold}): "
                    f"injected {exp_report.get('orphans_added', 0)} orphans, "
                    f"{exp_report.get('mined_paa_added', 0)} PAA/related queries, "
                    f"{exp_report.get('pairwise_added', 0)} pairwise, "
                    f"{exp_report.get('three_way_added', 0)} 3-way rows "
                    f"({len(candidates)} total candidates)."
                )
            elif exp_report.get("reason") == "expansion_halted_indexation_debt":
                print(f"      [QUALITY GATE] {exp_report.get('message')}")
        except Exception as exc:  # noqa: BLE001 - expansion must never kill collection
            print(f"      candidate expansion skipped ({exc}).")

    # Wave-64 candidate hygiene: resolve 301s, scrub utility/brand-typo rows,
    # and collapse duplicate (page, query) rows BEFORE any SERP enrichment
    # spend or LGBMRanker scoring. Wave-63 leased 4 duplicate legacy URLs and
    # 4 utility/typo rows because this step did not exist upstream.
    try:
        file_map: dict = {}
        map_paths = list(args.redirect_map)
        auto_map = os.path.expanduser("~/.seo_fleet/redirect_map.json")
        if os.path.isfile(auto_map):
            map_paths.append(auto_map)
        for map_path in map_paths:
            with open(map_path, "r", encoding="utf-8") as fh:
                file_map.update(json.load(fh))
        live_map: dict = {}
        if not args.no_live_redirects:
            probe_pages = [
                c["page"]
                for c in sorted(
                    candidates,
                    key=lambda c: -float(c.get("impressions", 0) or 0),
                )
            ]
            probed: set = set()
            probe_list = []
            for pg in probe_pages:
                if pg not in probed and pg.startswith("http"):
                    probed.add(pg)
                    probe_list.append(pg)
            probe_list = probe_list[:200]
            if probe_list:
                live_map = resolve_redirects(probe_list)
        merged, hygiene_report = canonicalize_and_dedupe_candidates(
            candidates, redirect_map={**file_map, **live_map}, domain=args.site
        )
        print(
            f"      candidate hygiene: {hygiene_report['canonicalized']} "
            f"canonicalized, {hygiene_report['scrubbed']} scrubbed, "
            f"{hygiene_report['deduped_away']} deduped "
            f"({len(candidates)} -> {len(merged)} rows)."
        )
        candidates = merged
    except Exception as exc:  # noqa: BLE001 - hygiene must never kill collection
        print(f"      candidate hygiene skipped ({exc}).")

    # URL Inspection coverageState enrichment (2,000 free calls/day/property,
    # 7-day result cache, daily gate): tells the compiler WHY a route has zero
    # impressions - "Crawled - currently not indexed" routes need unique data
    # depth (thin-content gate), "Discovered - currently not indexed" routes
    # need internal links (discovery gate). Requires --state-db so results are
    # cached and budget-counted across invocations.
    if state_conn is not None and not args.no_inspect:
        inspection_targets = [
            str(c["page"])
            for c in candidates
            if float(c.get("impressions", 0) or 0) == 0.0
        ][: max(0, args.inspect_limit)]
        if inspection_targets:
            try:
                inspections = inspect_coverage_states(
                    args.site,
                    inspection_targets,
                    state_conn=state_conn,
                    max_calls=args.inspect_limit,
                )
                enriched = 0
                for cand in candidates:
                    record = inspections.get(str(cand["page"])) or inspections.get(
                        str(cand["page"]).rstrip("/")
                    )
                    if record and record.get("coverage_state"):
                        cand["coverage_state"] = record["coverage_state"]
                        enriched += 1
                print(
                    f"      URL inspection: {enriched} zero-impression candidates "
                    f"enriched with coverageState ({len(inspection_targets)} targeted)."
                )
            except Exception as exc:  # noqa: BLE001 - inspection must never kill collection
                print(f"      URL inspection skipped ({exc}).")

    # Domain topical centroid: token profile of our own winning pages' queries.
    domain_counter: Counter = Counter()
    for cand in candidates:
        if cand["clicks_30d"] >= 1:
            domain_counter.update(tokenize(cand["query"]))

    login, password = (None, None)
    if not args.gsc_only:
        try:
            login, password = resolve_credentials()
        except RuntimeError as exc:
            print(
                f"[2/3] DataForSEO unavailable ({exc}) -> GSC-only mode "
                "(SERP features fall back to neutral 0.0, volume falls back to impressions)."
            )
    client = DataForSEOClient(login, password) if login and password else None

    hub_links = load_hub_links(args.hub_links)
    serp_by_query: dict[str, list[dict[str, Any]]] = {}
    item_types_by_query: dict[str, list[str]] = {}
    if client:
        serp_cache_path = os.path.abspath(".serp_cache.json")
        # Cache values are {"items": [...], "item_types": [...]} since the
        # item_types persistence upgrade; normalize legacy plain-list entries.
        cache: dict[str, Any] = {}
        if os.path.exists(serp_cache_path):
            with open(serp_cache_path, encoding="utf-8") as fh:
                cache = json.load(fh)
        for keyword, value in list(cache.items()):
            if isinstance(value, list):
                cache[keyword] = {"items": value, "item_types": []}
        # Fleet-shared SERP cache layer (30d TTL): entries other skill
        # invocations already paid for fill in before any new task is posted.
        if state_conn is not None:
            db_entries = load_cached_serps(state_conn, [c["query"] for c in candidates])
            merged = 0
            for keyword, entry in db_entries.items():
                if keyword not in cache:
                    cache[keyword] = entry
                    merged += 1
            if merged:
                print(f"      State DB: {merged} cached SERP entries reused (30d TTL).")
        missing = [c["query"] for c in candidates if c["query"] not in cache]
        print(
            f"[2/3] DataForSEO: {len(cache)} cached, {len(missing)} to fetch (budget cap ${args.max_serp_cost:.2f}) ..."
        )
        unit_cost = 0.0006
        affordable = (
            missing[: int(args.max_serp_cost / unit_cost)] if unit_cost else missing
        )
        # Daily budget gate: across ALL skill invocations on this machine,
        # never post more than the per-day Standard-Queue task cap (fleet
        # default 150; cost bounds it when the USD cap is tighter). The
        # domain activates the property-level starvation floor (review R3).
        if state_conn is not None and affordable:
            gate = DailyBudgetGate(
                args.state_db,
                daily_cap=min(
                    DEFAULT_DAILY_SERP_BUDGET,
                    max(1, int(args.max_serp_cost / unit_cost)),
                ),
            )
            remaining = gate.remaining(domain=args.site)
            if remaining <= 0:
                print(
                    "      Daily DataForSEO budget exhausted (gate) - fetching "
                    "from cache only until tomorrow (UTC)."
                )
                affordable = []
            else:
                affordable = affordable[:remaining]
        if affordable:
            try:
                client.post_serp_tasks(affordable, depth=10)
                if state_conn is not None:
                    spent = DailyBudgetGate(args.state_db).record(
                        len(affordable), domain=args.site
                    )
                    print(
                        f"      Budget gate: {len(affordable)} tasks recorded, {spent} left today."
                    )
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
                    # Persist result-level item_types (SERP feature flags come
                    # free with every response; no extra parser cost).
                    cache[keyword] = {
                        "items": items,
                        "item_types": entry.get("item_types") or [],
                    }
            got = sum(1 for q in affordable if q in cache)
            print(f"      {got}/{len(affordable)} fetched ...")
        with open(serp_cache_path, "w", encoding="utf-8") as fh:
            json.dump(cache, fh)
        if state_conn is not None:
            fresh_entries = {
                keyword: value
                for keyword, value in cache.items()
                if isinstance(value, dict) and value.get("items")
            }
            for keyword, entry in fresh_entries.items():
                upsert_serp_cache(
                    state_conn, keyword, entry["items"], entry.get("item_types") or []
                )
        serp_by_query = {
            c["query"]: (cache[c["query"]].get("items") or cache[c["query"]])
            for c in candidates
            if c["query"] in cache
        }
        item_types_by_query = {
            c["query"]: (cache[c["query"]].get("item_types") or [])
            for c in candidates
            if c["query"] in cache and isinstance(cache[c["query"]], dict)
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
                "source": cand.get("source", "gsc"),
                "coverage_state": cand.get("coverage_state"),
                "actions": cand.get("actions"),
                "serp_meta": serp_item_metadata(
                    {"item_types": item_types_by_query.get(cand["query"], [])},
                    serp_items,
                    cand["query"],
                ),
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
