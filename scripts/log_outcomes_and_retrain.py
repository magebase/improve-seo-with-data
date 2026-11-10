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
from datetime import datetime, timedelta, timezone
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from collect_features import find_performance_rows, pull_gsc_window
from gsc_analyzer import find_seo_binary, run_seo_report
from ltr_ranker import record_shipped
from train_ranker import load_history, train_from_history


def _pages_with_impressions(outcomes: dict[str, dict[str, Any]]) -> dict[str, float]:
    """Collapses (query, page)-keyed outcomes into per-page impression totals."""
    pages: dict[str, float] = {}
    for stats in outcomes.values():
        page = str(stats.get("page", ""))
        if not page:
            continue
        pages[page] = pages.get(page, 0.0) + float(stats.get("impressions", 0) or 0)
    return pages


def outcome_key(query: str, page: str) -> str:
    return f"{query.strip().lower()}\n{page.strip().lower()}"


# Minimum days between deploy and the fresh window before a shipped action may
# be graded: Googlebot needs time to recrawl; grading earlier teaches the
# ranker from phantom zeros (recrawl-lag poisoning).
MIN_GRADE_DAYS_AFTER_DEPLOY = 7

# A shipped page counts as "recrawled" once it registers ANY impressions in a
# post-deploy GSC window (Google served it -> Googlebot crawled it). This is
# the available proxy for URL Inspection's lastCrawlTime via the seo binary.
POSITION_DROP_THRESHOLD = 4.0
IMPRESSION_DROP_SHARE = 0.30
PROTECTED_POSITION_BAND = (4.0, 15.0)


def has_recrawl_evidence(
    page: str, post_deploy_outcomes: dict[str, dict[str, Any]]
) -> bool:
    """True when the page registered post-deploy impressions (=> recrawled)."""
    stats = post_deploy_outcomes.get(page)
    return bool(stats and float(stats.get("impressions", 0) or 0) > 0)


def detect_regressions(
    executed_queue: list[dict[str, Any]],
    pre_outcomes: dict[str, dict[str, Any]],
    post_outcomes: dict[str, dict[str, Any]],
    recrawled_pages: set[str],
    *,
    pos_drop: float = POSITION_DROP_THRESHOLD,
    imp_drop_share: float = IMPRESSION_DROP_SHARE,
) -> list[dict[str, Any]]:
    """Flags shipped actions that made their page WORSE (auto-rollback gate).

    A row regresses when: it was graded (recrawled), its pre-deploy position
    sat inside the protected band (4-15), AND post-deploy it either dropped
    more than 4 positions or lost more than 30% of its impressions. Regressions
    emit REVERT_WAVE_COMMIT rollback tasks and are reported separately so the
    next retrain sees the honest realized outcome (real clicks are kept; the
    revert itself is what restores the pre-deploy SERP state).
    """
    regressions: list[dict[str, Any]] = []
    band_lo, band_hi = PROTECTED_POSITION_BAND
    for entry in executed_queue:
        page = str(entry.get("page", ""))
        key = outcome_key(entry.get("query", ""), page)
        pre = pre_outcomes.get(key)
        post = post_outcomes.get(key)
        if not pre or not post or page not in recrawled_pages:
            continue
        pre_pos = float(pre.get("current_pos", 99) or 99)
        if not (band_lo <= pre_pos <= band_hi):
            continue
        post_pos = float(post.get("current_pos", 99) or 99)
        pre_imp = float(pre.get("impressions", 0) or 0)
        post_imp = float(post.get("impressions", 0) or 0)
        dropped_pos = (post_pos - pre_pos) > pos_drop
        lost_impressions = pre_imp > 0 and post_imp < pre_imp * (1 - imp_drop_share)
        if dropped_pos or lost_impressions:
            reasons = []
            if dropped_pos:
                reasons.append(f"position {pre_pos:.1f} -> {post_pos:.1f}")
            if lost_impressions:
                reasons.append(f"impressions {pre_imp:.0f} -> {post_imp:.0f}")
            regressions.append(
                {
                    "query": entry.get("query"),
                    "page": page,
                    "action": "REVERT_WAVE_COMMIT",
                    "original_action": entry.get("prescribed_action"),
                    "pre_position": pre_pos,
                    "post_position": post_pos,
                    "pre_impressions": pre_imp,
                    "post_impressions": post_imp,
                    "reason": "; ".join(reasons),
                }
            )
    return regressions


def load_outcomes(
    path: str | None, site: str | None
) -> dict[str, dict[str, Any]]:
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
        raise RuntimeError(
            "Provide --outcomes FILE or --site DOMAIN for fresh outcomes."
        )

    outcomes: dict[str, dict[str, Any]] = {}
    for row in rows:
        query = row.get("query", row.get("keyword"))
        page = row.get("page", row.get("url", row.get("landing_page", "")))
        if not query or not page:
            continue
        outcomes[outcome_key(str(query), str(page))] = {
            "query": str(query),
            "page": str(page),
            "clicks_30d": float(row.get("clicks", 0) or 0),
            "impressions": float(row.get("impressions", 0) or 0),
            "current_pos": float(
                row.get("position", row.get("avg_position", 99)) or 99
            ),
            "ctr": float(row.get("ctr", 0) or 0),
        }
    return outcomes


def load_window_outcomes(path: str) -> dict[str, dict[str, Any]]:
    """Loads a `seo gsc-query --json` export (rows[].keys shape) into outcomes.

    Used for pre-deploy snapshots and post-deploy recrawl-verification windows.
    """
    with open(path, encoding="utf-8") as fh:
        payload = json.load(fh)
    if payload.get("ok") is False:
        raise RuntimeError(f"window export error: {str(payload.get('error'))[:120]}")
    outcomes: dict[str, dict[str, Any]] = {}
    for row in payload.get("rows") or []:
        keys = row.get("keys") or []
        if len(keys) < 2:
            continue
        key = outcome_key(str(keys[0]), str(keys[1]))
        outcomes[key] = {
            "query": str(keys[0]),
            "page": str(keys[1]),
            "clicks_30d": float(row.get("clicks", 0) or 0),
            "impressions": float(row.get("impressions", 0) or 0),
            "current_pos": float(row.get("position", 99) or 99),
            "ctr": float(row.get("ctr", 0) or 0),
        }
    return outcomes


def append_labeled_rows(
    executed_queue: list[dict[str, Any]],
    outcomes: dict[str, dict[str, Any]],
    conversions: dict[str, float],
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--executed", required=True, help="previously executed action queue JSON"
    )
    parser.add_argument("--site", help="GSC property for fresh outcomes")
    parser.add_argument(
        "--outcomes", help="offline fresh-outcomes JSON (instead of --site)"
    )
    parser.add_argument(
        "--conversions", help="JSON map 'query\\npage' -> conversion count"
    )
    parser.add_argument("--history", default="data/ltr_training_history.jsonl")
    parser.add_argument("--models-dir", default="models/")
    parser.add_argument("--no-retrain", action="store_true")
    parser.add_argument(
        "--force", action="store_true", help="retrain even below the 300-outcome guard"
    )
    parser.add_argument(
        "--deployed-at",
        default="",
        help="ISO timestamp of the wave deploy (enables the recrawl-lag guard)",
    )
    parser.add_argument(
        "--require-recrawl",
        action="store_true",
        help="grade only pages with post-deploy impressions (recrawled); the rest go to pending_verification",
    )
    parser.add_argument(
        "--post-deploy",
        default="",
        help="post-deploy `seo gsc-query --json` export for recrawl evidence (default: pull the window via --site)",
    )
    parser.add_argument(
        "--pre-deploy",
        default="",
        help="pre-deploy `seo gsc-query --json` snapshot; enables negative-delta rollback detection",
    )
    parser.add_argument("--rollback-output", default="data/rollback_queue.json")
    parser.add_argument(
        "--ledger",
        default="data/shipped_actions.jsonl",
        help="cooldown ledger appended with graded shipped tasks",
    )
    args = parser.parse_args(argv)

    with open(args.executed, encoding="utf-8") as fh:
        executed = json.load(fh)
    queue = executed.get("queue") if isinstance(executed, dict) else executed
    if not queue:
        print("ERROR: executed queue contains no tasks.")
        return 1

    conversions: dict[str, float] = {}
    if args.conversions:
        with open(args.conversions, encoding="utf-8") as fh:
            conversions = {str(k): float(v) for k, v in json.load(fh).items()}

    outcomes = load_outcomes(args.outcomes, args.site)
    print(f"Fresh outcomes matched: {len(outcomes)} query/page pairs.")

    # ---------------------------------------------------- recrawl-lag guard
    pending: list[dict[str, Any]] = []
    graded = queue
    post_window: dict[str, dict[str, Any]] = {}
    if args.require_recrawl:
        if not args.deployed_at:
            print("ERROR: --require-recrawl needs --deployed-at.")
            return 1
        deployed = datetime.fromisoformat(args.deployed_at.replace("Z", "+00:00"))
        now = datetime.now(deployed.tzinfo or timezone.utc)
        if now < deployed + timedelta(days=MIN_GRADE_DAYS_AFTER_DEPLOY):
            print(
                f"Too early to grade: deploy was {args.deployed_at}, the guard "
                f"requires {MIN_GRADE_DAYS_AFTER_DEPLOY} days. All {len(queue)} tasks "
                "stay pending."
            )
            pending = list(queue)
            graded = []
        else:
            if args.post_deploy:
                post_window = load_window_outcomes(args.post_deploy)
            elif args.site:
                end = datetime.now().date()
                start = max(deployed.date(), end - timedelta(days=28))
                post_window_rows = pull_gsc_window(
                    args.site, start.isoformat(), end.isoformat()
                )
                post_window = {}
                for row in post_window_rows:
                    post_window[outcome_key(row["query"], row["page"])] = row
            else:
                print(
                    "WARNING: --require-recrawl without --post-deploy/--site; "
                    "recrawl evidence unavailable, grading everything."
                )
                post_window = {}
            post_pages = _pages_with_impressions(post_window)
            graded, pending = [], []
            for entry in queue:
                page = str(entry.get("page", ""))
                if has_recrawl_evidence(page, post_pages):
                    graded.append(entry)
                else:
                    pending.append(entry)
            print(
                f"Recrawl evidence: {len(graded)} graded, {len(pending)} pending "
                "(no post-deploy impressions yet -> kept out of training)."
            )

    # ------------------------------------------- negative-delta auto-rollback
    regressions: list[dict[str, Any]] = []
    if args.pre_deploy and graded:
        pre_outcomes = load_window_outcomes(args.pre_deploy)
        # Regression math MUST compare pre-deploy against the strict
        # post-deploy window; the overall fresh outcomes may blend windows.
        post_for_regression = (
            post_window
            if args.require_recrawl and (args.post_deploy or args.site)
            else outcomes
        )
        recrawled = {str(e.get("page", "")) for e in graded}
        regressions = detect_regressions(
            graded, pre_outcomes, post_for_regression, recrawled
        )
        if regressions:
            os.makedirs(os.path.dirname(args.rollback_output) or ".", exist_ok=True)
            with open(args.rollback_output, "w", encoding="utf-8") as fh:
                json.dump({"regressions": regressions}, fh, indent=2)
            print(
                f"REGRESSIONS: {len(regressions)} shipped action(s) backfired "
                f"-> {args.rollback_output} (REVERT_WAVE_COMMIT tasks at the top "
                "of the next queue)."
            )
            for reg in regressions:
                print(f"  REVERT {reg['page']} ({reg['reason']})")

    added = append_labeled_rows(graded, outcomes, conversions, args.history)
    total = len(load_history(args.history)) if os.path.exists(args.history) else 0
    print(f"Labeled {added} new outcome rows -> {args.history} (total: {total}).")

    if graded:
        record_shipped(graded, args.ledger, deployed_at=args.deployed_at or None)
        print(
            f"Recorded {len(graded)} shipped task(s) -> {args.ledger} (cooldown ledger)."
        )
    if pending:
        os.makedirs(
            os.path.dirname("data/pending_verification.json") or ".", exist_ok=True
        )
        with open("data/pending_verification.json", "w", encoding="utf-8") as fh:
            json.dump({"pending": pending}, fh, indent=2)
        print(
            f"Pending verification (not graded): {len(pending)} -> data/pending_verification.json"
        )

    if args.no_retrain:
        return 0
    summary = train_from_history(args.history, args.models_dir, force=args.force)
    return 0 if summary else 2


if __name__ == "__main__":
    sys.exit(main())
