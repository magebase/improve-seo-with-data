"""Seed the persistent query ownership map from measured GSC performance.

`query_ownership_map` is the anti-cannibalization backbone: `get_query_owner`
prices `cannibalization_risk` from it, and `score_backlog` refuses to ship
competing edits when an owner is known. Nothing populated it, so every property
carried zero rows and every risk resolved to 0.0.

Ownership is derived from Google's own verdict, not from a guess:

1. realised clicks (the page Google's users actually chose),
2. then best position,
3. then impressions.

A query with one competing URL is OWNED. A query split across URLs where the
best page still carries >= 60% of the clicks is OWNED with the full share
recorded. A genuine split without a clear winner is flagged
CONFIRMED_COMPETITION so the compiler prices the risk.

Usage:
    python3 scripts/seed_query_ownership.py \
        --features data/ltr_features.json \
        --state-db ~/.seo_fleet/fleet_state.db \
        --domain smsriver.com
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fleet_state import connect_state_db, upsert_query_ownership  # noqa: E402

#: A page carrying at least this share of a query's clicks owns it outright.
OWNERSHIP_SHARE_THRESHOLD = 0.60


def _clicks(row: dict[str, Any]) -> float:
    return float(row.get("clicks_30d") or row.get("clicks") or 0.0)


def _impressions(row: dict[str, Any]) -> float:
    return float(row.get("impressions") or 0.0)


def _position(row: dict[str, Any]) -> float:
    feats = row.get("features") or {}
    return float(feats.get("current_pos", row.get("current_pos", 100.0)) or 100.0)


def derive_ownership(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One ownership decision per query, chosen by realised performance."""
    by_query: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        query = str(row.get("query") or "").strip()
        page = str(row.get("page") or "").strip()
        if not query or not page:
            continue
        by_query.setdefault(query.lower(), []).append(row)

    decisions: list[dict[str, Any]] = []
    for query, group in by_query.items():
        ranked = sorted(group, key=lambda r: (-_clicks(r), _position(r), -_impressions(r)))
        owner = ranked[0]
        owner_page = str(owner.get("page")) or "/"
        owner_key = owner_page.rstrip("/")
        total_clicks = sum(_clicks(r) for r in group)
        total_impressions = sum(_impressions(r) for r in group)
        share = (_clicks(owner) / total_clicks) if total_clicks > 0 else (
            _impressions(owner) / total_impressions if total_impressions > 0 else 0.0
        )
        competitors = [str(r.get("page")) for r in ranked[1:]]
        # Distinct URLs only: the same page can appear twice for one query after
        # redirect/canonical collapse.
        competitors = [c for c in dict.fromkeys(competitors) if c.rstrip("/") != owner_key]

        if not competitors:
            classification = "OWNED"
            overlap = 0.0
        elif share >= OWNERSHIP_SHARE_THRESHOLD:
            classification = "OWNED"
            overlap = round(1.0 - share, 4)
        else:
            classification = "CONFIRMED_COMPETITION"
            overlap = round(1.0 - share, 4)

        decisions.append(
            {
                "primary_query": query,
                "query_cluster": query,
                "canonical_url": owner_page,
                "secondary_queries": [],
                "competitors": competitors,
                "intent_category": "tool" if any(t in query for t in ("convert", "tool", "api")) else "informational",
                "ownership_risk_classification": classification,
                "serp_overlap_score": overlap,
                "historical_traffic_share": round(share, 4),
            }
        )
    return decisions


def seed_ownership(conn, *, domain: str, rows: list[dict[str, Any]]) -> dict[str, int]:
    decisions = derive_ownership(rows)
    for decision in decisions:
        upsert_query_ownership(
            conn,
            domain=domain,
            query_cluster=decision["query_cluster"],
            canonical_url=decision["canonical_url"],
            primary_query=decision["primary_query"],
            secondary_queries=decision["secondary_queries"],
            intent_category=decision["intent_category"],
            ownership_risk_classification=decision["ownership_risk_classification"],
            serp_overlap_score=decision["serp_overlap_score"],
            historical_traffic_share=decision["historical_traffic_share"],
        )
    conn.commit()
    return {"written": len(decisions)}


def fetch_gsc_rows(site: str, days: int = 28) -> list[dict[str, Any]]:
    """Raw (page, query) rows from GSC.

    Ownership must be derived from the FULL joint export, not from the Stage-1
    feature file: candidate hygiene scrubs brand-stem queries and the per-query
    collapse keeps one page per query, both of which erase exactly the competing
    URLs ownership is supposed to adjudicate.
    """
    end = dt.date.today()
    start = end - dt.timedelta(days=days)
    proc = subprocess.run(
        [
            "seo", "gsc-query", f"--site={site}",
            f"--start-date={start.isoformat()}", f"--end-date={end.isoformat()}",
            "--dimensions=page,query", "--limit=2000", "--json",
        ],
        capture_output=True, text=True, timeout=300,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"gsc-query failed: {proc.stderr[:300]}")
    payload = json.loads(proc.stdout or "{}")
    rows = []
    for row in payload.get("rows", []):
        keys = row.get("keys") or []
        if len(keys) < 2:
            continue
        rows.append(
            {
                "page": keys[0],
                "query": keys[1],
                "clicks_30d": float(row.get("clicks", 0.0)),
                "impressions": float(row.get("impressions", 0.0)),
                "current_pos": float(row.get("position", 100.0)),
            }
        )
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Seed query ownership from measured GSC rows.")
    parser.add_argument("--features", default="", help="Stage-1 features JSON (offline fallback)")
    parser.add_argument("--gsc-site", default="", help="GSC property, e.g. sc-domain:smsriver.com (preferred)")
    parser.add_argument("--days", type=int, default=28, help="GSC window length in days")
    parser.add_argument("--state-db", required=True, help="fleet_state.db path")
    parser.add_argument("--domain", required=True, help="property domain, e.g. smsriver.com")
    args = parser.parse_args(argv)

    if args.gsc_site:
        rows = fetch_gsc_rows(args.gsc_site, days=args.days)
        print(f"Pulled {len(rows)} raw (page, query) rows from {args.gsc_site}.")
    elif args.features:
        payload = json.load(open(args.features, encoding="utf-8"))
        rows = payload.get("rows", payload) if isinstance(payload, dict) else payload
    else:
        parser.error("pass --gsc-site (preferred) or --features")
        return 2
    conn = connect_state_db(args.state_db)
    try:
        report = seed_ownership(conn, domain=args.domain, rows=rows)
    finally:
        conn.close()
    print(f"Seeded {report['written']} ownership decision(s) for {args.domain}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
