#!/usr/bin/env python3
"""
dataforseo_client.py - Cost-routed DataForSEO SERP intelligence client.

Implements the SERP Intelligence Layer of the skill: external SERP evidence that
Google Search Console cannot see (who ranks 1-5, SERP feature crowding, weak-spot
detection), with strict unit economics:

- Standard Queue (`serp/google/organic/task_post` -> `tasks_ready` -> `task_get`)
  costs $0.60 per 1,000 SERPs (~$0.0006 each) — the DEFAULT for batch discovery.
- Live (`serp/google/organic/live`) costs $2.00 per 1,000 SERPs (~$0.002 each,
  >3x queue) — gated behind --mode live / explicit fetch_serp_live() calls.
- Search operators (site:, inurl:, intitle:) trigger DataForSEO's 5x cost
  multiplier — never send them. Fetch the plain Top-N and filter locally.
- `stop_crawl_on_match` lets rank-tracking tasks stop at your domain and refunds
  unused depth; `search_param: "&start=N"` crawls only the page you need
  (e.g. audit position 30-40 without paying for page 1).

Credentials (HTTP Basic login/password, never hardcoded, never logged):
1. --login / --password CLI args
2. DATAFORSEO_LOGIN / DATAFORSEO_PASSWORD env vars
3. DFS_LOGIN / DFS_PASSWORD env vars (publisher_network convention)
4. DATAFORSEO_API_KEY env var ("login:password" combined form)

Store them in .env.credentials (or the skill-adjacent environment) per repo
Rule 34. Example:
    DFS_LOGIN=me@example.com
    DFS_PASSWORD=********

Usage:
    # Dry-run: print the payload plan and cost estimate, touch nothing
    python3 scripts/dataforseo_client.py --keywords-file keywords.txt --dry-run

    # Batch weak-spot scan via the Standard Queue, then score every SERP
    python3 scripts/dataforseo_client.py --keywords-file keywords.txt \\
        --output-json /tmp/serp_weakspots.json

    # Rank tracking that stops at your domain (refunds unused depth)
    python3 scripts/dataforseo_client.py --keywords-file my-queries.txt \\
        --rank-track-domain example.com

    # Audit deep positions only (page 4) instead of paying for page 1
    python3 scripts/dataforseo_client.py --keywords-file deep.txt --offset 30
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request
from typing import Any, Callable, Dict, Iterable, List, Optional

BASE_URL = "https://api.dataforseo.com/v3"

# Unit economics (USD per SERP task). Queue is ~3.3x cheaper than Live.
COST_PER_SERP_QUEUE_USD = 0.0006
COST_PER_SERP_LIVE_USD = 0.002

DEFAULT_LOCATION_CODE = 2840  # United States
DEFAULT_LANGUAGE_CODE = "en"
DEFAULT_DEPTH = 10

# Domains whose presence signals a beatable SERP (UGC / thin community threads).
FORUM_UGC_DOMAINS = (
    "reddit.com",
    "quora.com",
    "stackexchange.com",
    "stackoverflow.com",
    "medium.com",
)

# SERP blocks that push organic results below the fold (CTR suppressors).
CROWDING_BLOCK_TYPES = ("ai_overview", "local_pack", "shopping")

Transport = Callable[..., Dict[str, Any]]


def estimate_serp_cost(num_keywords: int, mode: str = "queue") -> float:
    """Returns the estimated USD cost for `num_keywords` SERP tasks."""
    if mode == "queue":
        return num_keywords * COST_PER_SERP_QUEUE_USD
    if mode == "live":
        return num_keywords * COST_PER_SERP_LIVE_USD
    raise ValueError(f"unknown SERP mode: {mode!r} (expected 'queue' or 'live')")


def resolve_credentials(
    login: Optional[str] = None,
    password: Optional[str] = None,
    env: Optional[Dict[str, str]] = None,
) -> tuple[str, str]:
    """Resolves DataForSEO Basic-auth credentials with documented precedence.

    Precedence: explicit args > DATAFORSEO_LOGIN/PASSWORD > DFS_LOGIN/PASSWORD >
    DATAFORSEO_API_KEY (combined "login:password"). Raises RuntimeError with the
    fix in the message instead of failing silently at request time.
    """
    env = env if env is not None else dict(os.environ)
    if login and password:
        return login, password
    env_login = env.get("DATAFORSEO_LOGIN") or env.get("DFS_LOGIN")
    env_password = env.get("DATAFORSEO_PASSWORD") or env.get("DFS_PASSWORD")
    if env_login and env_password:
        return env_login, env_password
    combined = env.get("DATAFORSEO_API_KEY")
    if combined and ":" in combined:
        combined_login, _, combined_password = combined.partition(":")
        if combined_login and combined_password:
            return combined_login, combined_password
    raise RuntimeError(
        "DataForSEO credentials not found. Set DATAFORSEO_LOGIN/DATAFORSEO_PASSWORD "
        "(or DFS_LOGIN/DFS_PASSWORD) in .env.credentials, or DATAFORSEO_API_KEY as "
        "'login:password'. Never hardcode them in scripts."
    )


def _tokenize(query: str) -> set[str]:
    return {tok for tok in query.lower().split() if tok}


def extract_serp_features(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Extracts revenue-relevant SERP feature flags from a SERP items array.

    AI Overviews, People Also Ask, and featured snippets are present in the base
    JSON payload of the standard Google Organic SERP endpoint — no paid
    load_async_ai_overview flag needed.
    """
    total = len(items)
    features: Dict[str, Any] = {
        "ai_overview": False,
        "people_also_ask": False,
        "featured_snippet": False,
        "discussions_and_forums": False,
        "shopping": False,
        "local_pack": False,
        "forum_ugc_ratio": 0.0,
    }
    forum_items = 0
    for item in items:
        item_type = str(item.get("type", ""))
        if item_type in features and isinstance(features.get(item_type), bool):
            features[item_type] = True
        domain = str(item.get("domain", "")).lower()
        if item_type == "organic" and any(d in domain for d in FORUM_UGC_DOMAINS):
            forum_items += 1
        if item_type == "discussions_and_forums":
            forum_items += 1
    if total:
        features["forum_ugc_ratio"] = forum_items / total
    return features


def serp_vulnerability_score(items: List[Dict[str, Any]], query: str) -> Dict[str, Any]:
    """Scores how beatable a SERP is for `query` (0-100) and flags weak spots.

    Components:
    - forum/UGC share of the SERP (Reddit/Quora/thin threads ranking = beatable)
    - title exact-match rate of the top-5 organic results (low = underserved)
    - SERP crowding (AI Overview / local pack / shopping blocks = CTR suppressor)

    A `weak_spot` is a high-score SERP: high-volume queries where forums rank in
    the Top 5 and nobody exact-matches the query in their title are immediate,
    zero-backlink traffic wins.
    """
    organic = [item for item in items if str(item.get("type", "")) == "organic"]
    top5 = organic[:5]
    tokens = _tokenize(query)

    forum_ugc_count = sum(
        1
        for item in items
        if str(item.get("type", "")) == "discussions_and_forums"
        or (
            str(item.get("type", "")) == "organic"
            and any(d in str(item.get("domain", "")).lower() for d in FORUM_UGC_DOMAINS)
        )
    )
    if top5:
        title_match_rate = sum(
            1
            for item in top5
            if tokens and tokens.issubset(_tokenize(str(item.get("title", ""))))
        ) / len(top5)
    else:
        title_match_rate = 0.0
    crowding_penalty = sum(1 for item in items if str(item.get("type", "")) in CROWDING_BLOCK_TYPES)

    forum_share_top5 = forum_ugc_count / len(items) if items else 0.0
    score = int(
        round(
            40 * forum_share_top5
            + 40 * (1.0 - title_match_rate)
            + 10 * min(crowding_penalty, 2) / 2
            + 10 * (1.0 if forum_ugc_count >= 3 else 0.0)
        )
    )
    score = max(0, min(100, score))
    return {
        "score": score,
        "weak_spot": score >= 70,
        "components": {
            "forum_ugc_count": forum_ugc_count,
            "title_exact_match_rate": round(title_match_rate, 4),
            "crowding_penalty": crowding_penalty,
            "organic_count": len(organic),
        },
    }


def _default_transport(method: str, url: str, body: Optional[str] = None, headers: Optional[Dict[str, str]] = None, timeout: float = 60) -> Dict[str, Any]:
    req = urllib.request.Request(url, data=body.encode("utf-8") if body is not None else None, method=method)
    for key, value in (headers or {}).items():
        req.add_header(key, value)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        # Surface the API's error envelope when one is present.
        try:
            return json.loads(e.read().decode("utf-8"))
        except Exception:
            raise RuntimeError(f"DataForSEO HTTP error {e.code} for {url}") from e
    except Exception as e:  # noqa: BLE001 - surfaced verbatim without credentials
        raise RuntimeError(f"DataForSEO request failed: {e}") from e


class DataForSEOClient:
    """Cost-routed DataForSEO v3 client (stdlib-only, injectable transport)."""

    def __init__(self, login: str, password: str, transport: Optional[Transport] = None):
        self._auth_pair = (login, password)
        self._auth_header = "Basic " + base64.b64encode(f"{login}:{password}".encode()).decode()
        self._transport = transport or _default_transport
        self.last_queue_state: Dict[str, Any] = {}

    # ------------------------------------------------------------------ posts

    def _post(self, path: str, payload: Any) -> Dict[str, Any]:
        body = json.dumps(payload)
        try:
            data = self._transport(
                "POST",
                f"{BASE_URL}{path}",
                body=body,
                headers={"Authorization": self._auth_header, "Content-Type": "application/json"},
            )
        except RuntimeError:
            raise
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(f"DataForSEO request failed: {e}") from e
        if not isinstance(data, dict) or data.get("status_code") != 20000:
            status = data.get("status_code") if isinstance(data, dict) else "no-envelope"
            message = data.get("status_message") if isinstance(data, dict) else data
            raise RuntimeError(f"DataForSEO API error {status}: {message}")
        return data

    def _get(self, path: str) -> Dict[str, Any]:
        try:
            data = self._transport("GET", f"{BASE_URL}{path}", headers={"Authorization": self._auth_header})
        except RuntimeError:
            raise
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(f"DataForSEO request failed: {e}") from e
        if not isinstance(data, dict) or data.get("status_code") != 20000:
            status = data.get("status_code") if isinstance(data, dict) else "no-envelope"
            message = data.get("status_message") if isinstance(data, dict) else data
            raise RuntimeError(f"DataForSEO API error {status}: {message}")
        return data

    @staticmethod
    def _task(keyword: str, location_code: int, language_code: str, depth: int, tag: Optional[str], stop_crawl_on_match: Optional[List[str]], offset: Optional[int]) -> Dict[str, Any]:
        task: Dict[str, Any] = {
            "keyword": keyword,
            "location_code": location_code,
            "language_code": language_code,
            "depth": depth,
        }
        if tag:
            task["tag"] = tag
        if stop_crawl_on_match:
            # Rank-tracking refund: DataForSEO stops crawling once a matching
            # domain is found and refunds the unused depth pages.
            task["stop_crawl_on_match"] = stop_crawl_on_match
        if offset:
            # Offset crawling: inspect deep pages only (e.g. "&start=30" = page 4)
            # instead of paying full depth from position 1.
            task["search_param"] = f"&start={offset}"
        return task

    def post_serp_tasks(
        self,
        keywords: Iterable[str],
        location_code: int = DEFAULT_LOCATION_CODE,
        language_code: str = DEFAULT_LANGUAGE_CODE,
        depth: int = DEFAULT_DEPTH,
        tag: Optional[str] = None,
        stop_crawl_on_match: Optional[List[str]] = None,
        offset: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Posts keywords to the Standard Queue SERP endpoint ($0.0006/SERP).

        NEVER append search operators (site:, inurl:, intitle:) to keywords —
        DataForSEO bills a 5x multiplier for operator queries. Fetch the plain
        Top-N and filter locally.
        """
        payload = [
            self._task(kw, location_code, language_code, depth, tag, stop_crawl_on_match, offset)
            for kw in keywords
        ]
        return self._post("/serp/google/organic/task_post", payload)

    def fetch_serp_live(
        self,
        keyword: str,
        location_code: int = DEFAULT_LOCATION_CODE,
        language_code: str = DEFAULT_LANGUAGE_CODE,
        depth: int = DEFAULT_DEPTH,
    ) -> List[Dict[str, Any]]:
        """Synchronous Live SERP fetch (~$0.002/SERP, >3x queue cost).

        Returns result entries in the same shape as `collect_ready_tasks`
        (each carrying `keyword` + `items`). Use ONLY for interactive single
        queries; batch discovery MUST go through post_serp_tasks/collect_ready_tasks.
        """
        envelope = self._post(
            "/serp/google/organic/live/regular",
            [self._task(keyword, location_code, language_code, depth, None, None, None)],
        )
        fetched: List[Dict[str, Any]] = []
        for task in envelope.get("tasks") or []:
            result_payload = task.get("result") or []
            if isinstance(result_payload, dict):
                result_payload = [result_payload]
            for result_entry in result_payload:
                entry = dict(result_entry)
                entry.setdefault("keyword", keyword)
                fetched.append(entry)
        return fetched

    # ------------------------------------------------------------------ queue

    def collect_ready_tasks(self) -> List[Dict[str, Any]]:
        """Single sweep of the Standard Queue; returns completed SERP results.

        Queue turnaround is typically ~5 minutes; this method never blocks —
        incomplete tasks are reported in `last_queue_state["pending"]` and the
        caller simply sweeps again later (e.g. on the next cron run).
        """
        fetched: List[Dict[str, Any]] = []
        self.last_queue_state = {"completed": [], "pending": 0, "fetched": 0}
        ready = self._get("/serp/google/organic/tasks_ready")
        tasks = (ready.get("tasks") or [])
        completed = [t for t in tasks if t.get("status_code") == 20000]
        pending = [t for t in tasks if t.get("status_code") != 20000]
        self.last_queue_state["pending"] = len(pending)
        for task in completed:
            task_id = str(task.get("id", ""))
            detail = self._get(f"/serp/google/organic/task_get/{task_id}")
            result_payload = detail.get("result") or []
            if isinstance(result_payload, dict):
                result_payload = [result_payload]
            for result_entry in result_payload:
                entry = dict(result_entry)
                entry.setdefault("task_id", task_id)
                fetched.append(entry)
        self.last_queue_state["completed"].extend(str(t.get("id")) for t in completed)
        self.last_queue_state["fetched"] = len(fetched)
        return fetched

    # ----------------------------------------------------------------- output

    @staticmethod
    def score_fetched_results(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Attaches SERP feature flags + vulnerability scores to fetched results."""
        scored: List[Dict[str, Any]] = []
        for entry in results:
            items = entry.get("items") or []
            keyword = entry.get("keyword") or ""
            scored.append(
                {
                    "keyword": keyword,
                    "task_id": entry.get("task_id"),
                    "features": extract_serp_features(items),
                    "vulnerability": serp_vulnerability_score(items, keyword),
                    "top_10": [
                        {
                            "rank": item.get("rank_group"),
                            "type": item.get("type"),
                            "title": item.get("title"),
                            "domain": item.get("domain"),
                            "url": item.get("url"),
                        }
                        for item in items[:10]
                    ],
                }
            )
        return scored


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Cost-routed DataForSEO SERP intelligence (weak-spot scanning, rank tracking, cost caps).")
    parser.add_argument("--keywords-file", required=True, help="File with one query per line")
    parser.add_argument("--mode", choices=["queue", "live"], default="queue", help="queue = Standard Queue $0.0006/SERP (default); live = synchronous $0.002/SERP")
    parser.add_argument("--location-code", type=int, default=DEFAULT_LOCATION_CODE)
    parser.add_argument("--language-code", default=DEFAULT_LANGUAGE_CODE)
    parser.add_argument("--depth", type=int, default=DEFAULT_DEPTH)
    parser.add_argument("--max-tasks", type=int, default=500, help="Hard cap on keywords per run (cost guard)")
    parser.add_argument("--rank-track-domain", default=None, help="Adds stop_crawl_on_match for this domain (refunds unused depth)")
    parser.add_argument("--offset", type=int, default=None, help="Deep-page crawl via search_param '&start=N' (e.g. 30 = page 4)")
    parser.add_argument("--tag", default=None, help="Optional task tag")
    parser.add_argument("--output-json", default=None)
    parser.add_argument("--dry-run", action="store_true", help="Print the payload plan + cost estimate; touch no network")
    parser.add_argument("--login", default=None)
    parser.add_argument("--password", default=None)
    args = parser.parse_args(argv)

    with open(args.keywords_file, encoding="utf-8") as fh:
        keywords = [line.strip() for line in fh if line.strip()]
    keywords = keywords[: max(1, args.max_tasks)]
    if not keywords:
        print("No keywords found in", args.keywords_file)
        return 1

    estimated_cost = estimate_serp_cost(len(keywords), mode=args.mode)
    stop_list = None
    if args.rank_track_domain:
        stop_list = [args.rank_track_domain, f"*.{args.rank_track_domain}"]

    print(
        f"Plan: mode={args.mode} tasks={len(keywords)} depth={args.depth} "
        f"location={args.location_code} language={args.language_code} "
        f"estimated_cost=${estimated_cost:.4f}"
    )
    if args.rank_track_domain:
        print(f"Rank tracking: stop_crawl_on_match={stop_list}")
    if args.offset:
        print(f"Offset crawling: search_param=&start={args.offset} (skipping paid depth you don't need)")

    if args.dry_run:
        print("DRY-RUN: no network calls made. First 5 task payloads:")
        for kw in keywords[:5]:
            print(
                "  "
                + json.dumps(
                    DataForSEOClient._task(kw, args.location_code, args.language_code, args.depth, args.tag, stop_list, args.offset)
                )
            )
        return 0

    login, password = resolve_credentials(login=args.login, password=args.password)
    client = DataForSEOClient(login, password)

    if args.mode == "live":
        scored = []
        for kw in keywords:
            for entry in client.fetch_serp_live(kw, args.location_code, args.language_code, args.depth):
                scored.extend(DataForSEOClient.score_fetched_results([entry]))
    else:
        client.post_serp_tasks(
            keywords,
            location_code=args.location_code,
            language_code=args.language_code,
            depth=args.depth,
            tag=args.tag,
            stop_crawl_on_match=stop_list,
            offset=args.offset,
        )
        print(f"Queued {len(keywords)} tasks; polling tasks_ready (queue turnaround is typically ~5 minutes)...")
        results = client.collect_ready_tasks()
        scored = DataForSEOClient.score_fetched_results(results)
        pending = client.last_queue_state.get("pending", 0)
        if pending:
            print(f"[INFO] {pending} task(s) still in queue; re-run collect to fetch them.")

    weak_spots = [row for row in scored if row["vulnerability"]["weak_spot"]]
    print(f"Scored {len(scored)} SERPs; weak spots: {len(weak_spots)}")
    for row in weak_spots[:10]:
        comps = row["vulnerability"]["components"]
        print(
            f"  [WEAK] {row['keyword']} score={row['vulnerability']['score']} "
            f"forums={comps['forum_ugc_count']} title_match={comps['title_exact_match_rate']}"
        )
    if args.output_json:
        with open(args.output_json, "w", encoding="utf-8") as fh:
            json.dump({"generated_by": "improve-seo-with-data/dataforseo_client", "results": scored}, fh, indent=2)
        print("Wrote", args.output_json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
