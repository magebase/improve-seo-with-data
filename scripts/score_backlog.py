#!/usr/bin/env python3
"""
score_backlog.py - Stage 3 of the Learning-to-Rank closed loop. ALWAYS-ON.

Scores the collected candidate backlog (data/ltr_features.json) with the
trained model bundle (models/seo_lgbm_ranker.txt), prescribes an executable
action per candidate from SHAP drivers, calibrates margins into Expected
30-Day Clicks, and emits the 85/15 exploration/exploitation queue:

    data/action_queue.json

Always-on behavior: when no model bundle exists yet, this stage AUTO-TRAINS
a rank_xendcg ranker on the candidate rows themselves — labels come from
DataForSEO SERP-structure bootstrap grades (bootstrap_labels.py), never
from the linear proxy. The deterministic formula survives ONLY as the
init_score residual baseline inside training. If there is genuinely nothing
to train on (< MIN_TRAINABLE_ROWS candidate rows), the stage exits 2 with
pooling instructions instead of emitting proxy-ranked guesses.

Usage:
    python3 scripts/score_backlog.py
    python3 scripts/score_backlog.py --features data/ltr_features.json \\
        --models-dir models/ --queue-size 20
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from bootstrap_labels import generate_bootstrap_grades
from fleet_state import enqueue_tasks, lease_tasks, pending_count
from ltr_ranker import (
    EXPLOIT_SLOTS,
    EXPLORE_SLOTS,
    FEATURES,
    MIN_TRAINABLE_ROWS,
    compile_wave_backlog,
    detect_cannibalization,
    filter_cooldown,
    heuristic_base_score,
    load_bundle,
    load_cooldown_keys,
    prescribe_action,
    prescribe_all_actions,
    record_shipped,
    save_bundle,
    slice_per_domain,
    split_action_queue,
    train_seo_ranker,
    derive_sibling_counts,
)


def _train_on_the_fly(rows: list[dict[str, Any]], models_dir: str) -> dict[str, Any]:
    """Always-on fallback: trains a bootstrap-grade ranker on the very rows
    being scored (and persists it so later runs reuse the bundle)."""
    if len(rows) < MIN_TRAINABLE_ROWS:
        raise RuntimeError(
            f"Only {len(rows)} candidate rows — below the {MIN_TRAINABLE_ROWS}-row "
            "training floor. Run collect_features.py (more candidates), pool the "
            "fleet (fleet_ingest.py), and rerun. The linear proxy is retired; "
            "guess-ranked queues are no longer emitted."
        )
    grades, label_meta = generate_bootstrap_grades(rows)
    X = np.array([[float(r["features"][f]) for f in FEATURES] for r in rows])
    clusters = np.array([str(r.get("cluster_id", "root")) for r in rows])
    init_score = np.array(
        [
            heuristic_base_score(
                impressions=r.get("impressions", 0),
                current_pos=r.get("current_pos", 50),
                current_ctr=r.get("current_ctr", 0.0),
                conv_value=r.get("conv_value", 1.0),
            )
            for r in rows
        ]
    )
    booster, meta = train_seo_ranker(
        X, grades, clusters, objective="rank_xendcg", init_score=init_score
    )
    os.makedirs(models_dir, exist_ok=True)
    save_bundle(models_dir, booster, meta, None)
    print(
        f"Auto-trained rank_xendcg bundle on {len(rows)} rows "
        f"(label_mode={label_meta['label_mode']}, "
        f"best_iteration={meta['best_iteration']}) -> {models_dir}"
    )
    return {"label_mode": label_meta["label_mode"]}


def score_rows(rows: list[dict[str, Any]], models_dir: str) -> dict[str, Any]:
    """Scores rows with the bundle when present, else auto-trains one."""
    bundle = None
    if os.path.exists(os.path.join(models_dir, "seo_lgbm_ranker.txt")):
        bundle = load_bundle(models_dir)
    label_mode = None

    if bundle is None:
        print(
            "No trained bundle found -> AUTO-TRAINING a rank_xendcg ranker on "
            "bootstrap grades (the linear proxy is retired)."
        )
        label_mode = _train_on_the_fly(rows, models_dir)["label_mode"]
        bundle = load_bundle(models_dir)

    print(
        f"Scoring {len(rows)} candidates with trained {bundle['objective']} model ..."
    )
    X = np.array([[float(r["features"][f]) for f in bundle["features"]] for r in rows])
    raw_scores = bundle["model"].predict(X)

    # SHAP contributions: (n, n_features + 1); last column is the bias term.
    shap_matrix = bundle["model"].predict(X, pred_contrib=True)
    has_calibrator = bundle["calibrator"] is not None
    for i, row in enumerate(rows):
        feats = row["features"]
        row["rank_score"] = float(raw_scores[i])
        if has_calibrator:
            row["expected_clicks_30d"] = float(
                bundle["calibrator"].transform(np.array([raw_scores[i]]))[0]
            )
        else:
            row["expected_clicks_30d"] = None
        shap_row = shap_matrix[i][: len(FEATURES)]
        shap = dict(zip(FEATURES, (float(v) for v in shap_row)))
        row["shap"] = {k: round(v, 6) for k, v in shap.items()}
        row["prescribed_action"] = prescribe_action(
            current_pos=feats["current_pos"],
            title_match_rate=feats["title_exact_match_rate"],
            hub_links_shap=shap["parent_hub_internal_links"],
            centroid_sim=feats["domain_centroid_sim"],
            forum_ratio=feats["serp_forum_ratio"],
            shap=shap,
        )
        # Multi-prescription explosion: one row can carry several atomic
        # bottlenecks; each becomes its own TDD work item (primary first).
        # Rows arriving with an explicit prescription set (orphan routes) keep
        # it — their routes exist, so the generic pos=100 explosion is wrong.
        if not row.get("actions"):
            row["actions"] = prescribe_all_actions(
                current_pos=feats["current_pos"],
                title_match_rate=feats["title_exact_match_rate"],
                hub_links_shap=shap["parent_hub_internal_links"],
                centroid_sim=feats["domain_centroid_sim"],
                forum_ratio=feats["serp_forum_ratio"],
                impressions=float(row.get("impressions", 0) or 0),
                clicks=float(row.get("clicks_30d", 0) or 0),
                shap=shap,
            )
    return {"mode": "trained_model", "label_mode": label_mode, "rows": rows}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--features", default="data/ltr_features.json")
    parser.add_argument("--models-dir", default="models/")
    parser.add_argument("--output", default="data/action_queue.json")
    parser.add_argument("--queue-size", type=int, default=20)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--ledger",
        default="data/shipped_actions.jsonl",
        help="cooldown ledger; (page, action) pairs shipped within --cooldown-days are filtered from this queue",
    )
    parser.add_argument(
        "--cooldown-days",
        type=int,
        default=30,
        help="cooldown window in days (0 disables filtering)",
    )
    parser.add_argument(
        "--per-domain-top",
        type=int,
        default=0,
        help="cap the final queue at N tasks per registered domain (0 = no per-domain quota)",
    )
    parser.add_argument(
        "--record",
        action="store_true",
        help="append the emitted queue to the cooldown ledger",
    )
    parser.add_argument(
        "--compile-wave",
        type=int,
        default=0,
        metavar="N",
        help="additionally compile an atomic TDD wave of N tasks (compile_wave_backlog) into the output",
    )
    parser.add_argument(
        "--state-db",
        default="",
        help="SQLite fleet state DB; when set, emitted tasks are enqueued and leased (PENDING -> LEASED)",
    )
    parser.add_argument(
        "--lease-size",
        type=int,
        default=35,
        help="tasks leased per invocation from the state-DB cursor (the "
        "backlog is replenished at FULL depth regardless; 0 leases everything "
        "enqueued this run). When the cursor already holds >= lease-size "
        "PENDING tasks, this invocation takes the fast path: lease only, no "
        "collection/scoring.",
    )
    args = parser.parse_args(argv)

    # Fast path (the 50x/day cursor): when the backlog already holds a full
    # wave of PENDING tasks, lease and return in well under a second — no
    # feature file, no model, no network.
    if args.state_db and args.lease_size > 0:
        from fleet_state import (
            connect_state_db as _connect,
            lease_tasks as _lease,
            pending_count as _pending,
        )

        fast_conn = _connect(args.state_db)
        if _pending(fast_conn) >= args.lease_size:
            leased = _lease(fast_conn, limit=args.lease_size)
            os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
            with open(args.output, "w", encoding="utf-8") as fh:
                json.dump({"fast_path": True, "leased": leased}, fh, indent=2)
            print(
                f"Fast path: leased {len(leased)} tasks from the backlog cursor "
                f"(no collection/scoring; {_pending(fast_conn)} still pending)."
            )
            for task in leased[:5]:
                print(
                    f"  LEASED {task['action_code']} -> {task['page']}"
                    + (f" ({task['file_target']})" if task.get("file_target") else "")
                )
            fast_conn.close()
            return 0
        fast_conn.close()

    if not os.path.exists(args.features):
        print(f"ERROR: {args.features} not found. Run collect_features.py first.")
        return 1

    with open(args.features, encoding="utf-8") as fh:
        payload = json.load(fh)
    rows = payload.get("rows") or []
    if not rows:
        print("ERROR: feature file contains no rows.")
        return 1

    result = score_rows(rows, args.models_dir)
    scored = result["rows"]

    # Cannibalization detector: BEFORE the per-query collapse (which discards
    # the competitor rows), flag queries carried by >= 2 distinct pages all
    # ranking beyond position 10. The keeper row gains the
    # CONSOLIDATE_CANNIBALIZED_URLS action; full competing-URL sets are
    # emitted alongside the queue for the implementing agent.
    scored, consolidation_tasks = detect_cannibalization(scored)

    # One action per query: cannibalised (query, page) pairs collapse onto the
    # best-scoring row (the URL-ownership model allows a single owner per task).
    by_query: dict[str, dict[str, Any]] = {}
    for row in scored:
        keeper = by_query.get(row["query"])
        if keeper is None or row.get("rank_score", 0.0) > keeper.get("rank_score", 0.0):
            by_query[row["query"]] = row
    scored = list(by_query.values())

    # Orphan-route rows already prescribe BOOST_INTERNAL_LINKS /
    # EXPAND_THIN_ROUTE (the routes exist); preserve that override instead of
    # letting the generic pos=100 -> LAUNCH_PSEO_ROUTE mapping win.
    for row in scored:
        if row.get("source") == "orphan_route" and row.get("actions"):
            row["prescribed_action"] = row["actions"][0]

    # Cooldown: drop (page, action) pairs already shipped recently so back-to-
    # back runs surface the NEXT wave of unoptimized pages instead of the
    # same recommendations.
    if args.cooldown_days > 0:
        cooled = load_cooldown_keys(args.ledger, within_days=args.cooldown_days)
        if cooled:
            fresh_count = len(scored)
            scored, skipped = filter_cooldown(scored, cooled)
            print(
                f"Cooldown ledger ({args.ledger}): {fresh_count - len(skipped)} rows fresh, "
                f"{len(skipped)} fully cooled rows dropped."
            )
    else:
        print("Cooldown disabled (--cooldown-days 0).")

    n_exploit = max(
        1, int(args.queue_size * EXPLOIT_SLOTS / (EXPLOIT_SLOTS + EXPLORE_SLOTS))
    )
    n_explore = max(1, args.queue_size - n_exploit)
    queue = split_action_queue(
        scored, n_exploit=n_exploit, n_explore=n_explore, seed=args.seed
    )

    # Per-domain quota: a big property must not crowd young properties out of
    # the queue; slice the globally ranked queue per registered domain.
    if args.per_domain_top > 0:
        pre_slice = len(queue)
        queue = slice_per_domain(queue, per_domain_top=args.per_domain_top)
        print(
            f"Per-domain quota (top {args.per_domain_top}/domain): {pre_slice} -> {len(queue)} tasks."
        )

    if args.record:
        written = record_shipped(queue, args.ledger)
        print(f"Recorded {written} task(s) -> {args.ledger} (cooldown ledger).")

    # Atomic TDD wave compiler: decompose the scored backlog into 35-60
    # file-targeted tasks (multi-action per row, cooldown-masked, deduped).
    wave_tasks: list[dict[str, Any]] = []
    if args.compile_wave > 0:
        cooled_keys = (
            load_cooldown_keys(args.ledger, within_days=args.cooldown_days)
            if args.cooldown_days > 0
            else set()
        )
        # FULL-depth decomposition: the SQLite backlog gets EVERY rule hit
        # across ALL scored rows (600-900 tasks), so runs 2..50 lease from the
        # cursor without re-running collection/scoring. The JSON output keeps
        # only the actionable --compile-wave slice of that inventory.
        full_backlog = compile_wave_backlog(
            scored,
            shipped_ledger=cooled_keys,
            target_wave_size=10_000_000,
            # Catalog families are derived from the rows themselves so a
            # top-ranked child route propagates its fix across every sibling
            # without a hand-maintained prefix map.
            sibling_counts=derive_sibling_counts(scored),
        )
        wave_tasks = full_backlog[: max(0, args.compile_wave)]
        print(
            f"Compiled {len(full_backlog)}-task backlog inventory; "
            f"{len(wave_tasks)} in this wave slice (--compile-wave "
            f"{args.compile_wave})."
        )

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as fh:
        json.dump(
            {
                "site": payload.get("site"),
                "scoring_mode": result["mode"],
                "queue": queue,
                "consolidation": consolidation_tasks,
                "wave_tasks": wave_tasks,
            },
            fh,
            indent=2,
        )

    # Fleet state machine: enqueue the FULL backlog inventory, then lease only
    # --lease-size tasks so the next invocations lease fresh work (#36-70,
    # #71-105, ...) instead of draining the cursor dry.
    if args.state_db:
        from fleet_state import connect_state_db

        conn = connect_state_db(args.state_db)
        pending = full_backlog + queue if args.compile_wave > 0 else queue
        added = enqueue_tasks(conn, pending)
        lease_n = args.lease_size if args.lease_size > 0 else len(pending)
        leased = lease_tasks(conn, limit=lease_n)
        still_pending = pending_count(conn)
        print(
            f"State DB {args.state_db}: enqueued {added} new, leased {len(leased)} "
            f"(PENDING -> LEASED), {still_pending} still pending."
        )
        if 0 < still_pending < 100:
            print(
                "      NOTE: backlog below 100 pending - the next collection "
                "run will replenish it (waterfall + matrix + surrogate)."
            )
        for task in leased[:5]:
            print(
                f"  LEASED {task['action_code']} -> {task['page']}"
                + (f" ({task['file_target']})" if task.get("file_target") else "")
            )
        conn.close()
    if consolidation_tasks:
        print(
            f"\nCannibalization: {len(consolidation_tasks)} CONSOLIDATE_CANNIBALIZED_URLS task(s):"
        )
        for task in consolidation_tasks:
            print(
                f"  {task['query'][:50]!r}: {len(task['pages'])} competing URLs {task['positions']}"
            )

    print(f"\nAction queue ({result['mode']}, {len(queue)} tasks) -> {args.output}")
    print(f"{'slot':<9} {'action':<32} {'score':>8} {'exp30d':>8}  query")
    for entry in queue:
        exp = entry.get("expected_clicks_30d")
        exp_s = f"{exp:.1f}" if isinstance(exp, float) else "-"
        extra = len(entry.get("actions") or [1]) - 1
        extra_s = f" (+{extra} more)" if extra > 0 else ""
        print(
            f"{entry['slot']:<9} {entry['prescribed_action'][:32]:<32} "
            f"{entry['rank_score']:>8.3f} {exp_s:>8}  {entry['query'][:52]}{extra_s}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
