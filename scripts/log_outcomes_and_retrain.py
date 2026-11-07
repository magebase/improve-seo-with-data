#!/usr/bin/env python3
"""
log_outcomes_and_retrain.py - Stage 4 of the Learning-to-Rank closed loop.

Closes the loop: joins a previously executed action queue against fresh GSC
performance 30 days later, appends the labeled outcomes to the training
history (data/ltr_training_history.jsonl), and triggers retraining when the
history has enough rows.

Outcome rows are labeled from ABSOLUTE fresh-window clicks/conversions (not
deltas against the pre-execution snapshot), so every executed task becomes an
honest (features -> realized clicks) training example. Conversions come from
--conversions (JSON: {"<query>\n<page>": n, ...}); pages without conversion
data are labeled conversions_30d=0.

Usage:
    python3 scripts/log_outcomes_and_retrain.py \\
        --executed data/action_queue_2026-01.json --site smsriver.com

    # Offline: supply outcomes instead of pulling GSC (used in CI/tests)
    python3 scripts/log_outcomes_and_retrain.py \\
        --executed data/action_queue.json --outcomes data/fresh_gsc.json

    # Log only, skip the retrain step (e.g. history still young)
    python3 scripts/log_outcomes_and_retrain.py \\
        --executed data/action_queue.json --no-retrain
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from collect_features import find_performance_rows  # noqa: E402
from gsc_analyzer import find_seo_binary, run_seo_report  # noqa: E402
from train_ranker import load_history, train_from_history  # noqa: E402


def outcome_key(query: str, page: str) -> str:
    return f"{query.strip().lower()}\n{page.strip().lower()}"


def load_outcomes(path: Optional[str], site: Optional[str]) -> Dict[str, Dict[str, Any]]:
    """Loads fresh-window GSC outcomes from a file or the seo binary."""
    if path:
        with open(path, encoding="utf-8") as fh:
            payload = json.load(fh)
        rows = payload.get("rows") if isinstance(payload, dict) else payload
        rows = rows or []
    elif site:
        if not find_seo_binary():
            raise RuntimeError("seo binary not found; cannot pull fresh GSC outcomes")
        print(f"Pulling fresh GSC outcomes for {site} ...")
        report = run_seo_report("search-performance-overview", site)
        rows = find_performance_rows(report)
    else:
        raise RuntimeError("Provide --outcomes FILE or --site DOMAIN for fresh outcomes.")

    outcomes: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        query = row.get("query", row.get("keyword"))
        page = row.get("page", row.get("url", row.get("landing_page", "")))
        if not query or not page:
            continue
        outcomes[outcome_key(str(query), str(page))] = {
            "clicks_30d": float(row.get("clicks", 0) or 0),
            "impressions": float(row.get("impressions", 0) or 0),
            "current_pos": float(row.get("position", row.get("avg_position", 99)) or 99),
            "ctr": float(row.get("ctr", 0) or 0),
        }
    return outcomes


def append_labeled_rows(
    executed_queue: List[Dict[str, Any]],
    outcomes: Dict[str, Dict[str, Any]],
    conversions: Dict[str, float],
    history_path: str,
) -> int:
    """Appends (features -> realized outcome) training rows; returns rows added."""
    existing = set()
    if os.path.exists(history_path):
        for row in load_history(history_path):
            existing.add(outcome_key(row.get("query", ""), row.get("page", "")))

    added = 0
    os.makedirs(os.path.dirname(history_path) or ".", exist_ok=True)
    with open(history_path, "a", encoding="utf-8") as fh:
        for entry in executed_queue:
            key = outcome_key(entry.get("query", ""), entry.get("page", ""))
            if key in existing:
                continue  # idempotent: never double-log an outcome
            fresh = outcomes.get(key)
            if not fresh:
                print(f"  SKIP (no fresh GSC data): {entry.get('query', '?')!r}")
                continue
            record = {
                "query": entry.get("query"),
                "page": entry.get("page"),
                "cluster_id": entry.get("cluster_id", "root"),
                "features": entry.get("features")
                or {f: entry.get(f, 0.0) for f in entry.get("features", {})},
                "clicks_30d": fresh["clicks_30d"],
                "conversions_30d": float(conversions.get(key, 0)),
                "impressions": fresh["impressions"],
                "current_pos": fresh["current_pos"],
                "current_ctr": fresh["ctr"],
                "conv_value": 1.0,
                "source": entry.get("slot", "unknown"),
            }
            fh.write(json.dumps(record) + "\n")
            existing.add(key)
            added += 1
    return added


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--executed", required=True, help="previously executed action queue JSON")
    parser.add_argument("--site", help="GSC property for fresh outcomes")
    parser.add_argument("--outcomes", help="offline fresh-outcomes JSON (instead of --site)")
    parser.add_argument("--conversions", help="JSON map 'query\\npage' -> conversion count")
    parser.add_argument("--history", default="data/ltr_training_history.jsonl")
    parser.add_argument("--models-dir", default="models/")
    parser.add_argument("--no-retrain", action="store_true")
    parser.add_argument("--force", action="store_true",
                        help="retrain even below the 300-outcome guard")
    args = parser.parse_args(argv)

    with open(args.executed, encoding="utf-8") as fh:
        executed = json.load(fh)
    queue = executed.get("queue") if isinstance(executed, dict) else executed
    if not queue:
        print("ERROR: executed queue contains no tasks.")
        return 1

    conversions: Dict[str, float] = {}
    if args.conversions:
        with open(args.conversions, encoding="utf-8") as fh:
            conversions = {str(k): float(v) for k, v in json.load(fh).items()}

    outcomes = load_outcomes(args.outcomes, args.site)
    print(f"Fresh outcomes matched: {len(outcomes)} query/page pairs.")

    added = append_labeled_rows(queue, outcomes, conversions, args.history)
    total = len(load_history(args.history)) if os.path.exists(args.history) else 0
    print(f"Labeled {added} new outcome rows -> {args.history} (total: {total}).")

    if args.no_retrain:
        return 0
    summary = train_from_history(args.history, args.models_dir, force=args.force)
    return 0 if summary else 2


if __name__ == "__main__":
    sys.exit(main())
