#!/usr/bin/env python3
"""Unified pSEO state machine: repair, contracts, cohorts and winnability.

The existing skill is a launch gate.  This module adds the missing lifecycle:
every URL is either protected, merged, noindexed, or gone; every new cluster
needs real demand and a weak-enough SERP; every page is bound to a dry-run
data contract; every pilot cohort advances only on measured GSC outcomes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))

from dataforseo_client import _item_domain
from fleet_state import connect_state_db

MIN_UNIQUE_DATA_FIELDS = 3
MAX_STRIPPED_OVERLAP = 0.45
MIN_PLANNED_INLINKS = 3
MIN_PILOT_INDEX_RATE = 0.80
FREEZE_TEMPLATE_RATE = 0.50
MIN_CLUSTER_DEMAND = 500.0
MIN_CLUSTER_ENTITIES = 15
MIN_WEAK_TOP10 = 2
WEAK_REFERRING_DOMAIN_LIMIT = 250.0

MERGE_FAMILIES = {"country-codes", "compare", "guides"}
PROTECTED_ROUTES = {"/", "/developer/", "/verify/google/"}
USER_FACING_NOINDEX = {"status", "workbench"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _norm(url: str) -> str:
    return str(url).strip().rstrip("/") or "/"


def _path(url: str) -> str:
    parsed = urlparse(url if "://" in url else f"https://x{url}")
    return "/" + parsed.path.strip("/") + ("/" if parsed.path.strip("/") else "")


def _tokens(url: str) -> set[str]:
    return {
        token
        for token in re.split(r"[^a-z0-9]+", url.lower())
        if len(token) > 2
        and token not in {"https", "http", "www", "com", "net", "org", "smsriver"}
    }


def _family(url: str) -> str:
    parts = [part for part in _path(url).split("/") if part]
    return parts[0] if parts else "root"


def _is_protected(row: dict[str, Any]) -> bool:
    return bool(
        float(row.get("clicks_90d") or 0) > 0
        or (
            str(row.get("coverage_state", ""))
            .lower()
            .startswith("submitted and indexed")
            and float(row.get("impressions_90d") or 0) > 0
        )
        or _norm(row.get("url", "")) in PROTECTED_ROUTES
    )


def find_merge_target(
    url: str,
    sitemap_urls: list[str],
) -> str | None:
    """Find a genuine ancestor replacement; never a sibling or the homepage.

    ``/country-codes/germany/`` may merge to ``/country-codes/``.  The hub
    itself has no ancestor and must be enriched, not redirected into a child.
    """
    family = _family(url)
    if family not in MERGE_FAMILIES:
        return None
    paths = {_path(candidate): candidate for candidate in sitemap_urls}
    parts = [part for part in _path(url).split("/") if part]
    for depth in range(len(parts) - 1, 0, -1):
        ancestor = "/" + "/".join(parts[:depth]) + "/"
        for key, candidate in paths.items():
            if key == ancestor:
                return candidate
    return None


def classify_disposal(
    row: dict[str, Any],
    *,
    sitemap_urls: list[str],
) -> dict[str, Any]:
    """Four-way disposal decision for one existing URL."""
    url = str(row.get("url") or "")
    evidence = {
        "clicks_90d": float(row.get("clicks_90d") or 0),
        "impressions_90d": float(row.get("impressions_90d") or 0),
        "coverage_state": row.get("coverage_state"),
        "backlinks": float(row.get("backlinks") or 0),
        "legitimate_referring_domains": float(
            row.get("legitimate_referring_domains") or 0
        ),
        "live_inventory_count": float(row.get("live_inventory_count") or 0),
    }
    if _is_protected(row):
        return {
            "url": url,
            "decision": "PROTECT",
            "reason": "clicks_or_indexed_or_backlinks",
            "target": None,
            "evidence": evidence,
        }
    family = _family(url)
    if family in USER_FACING_NOINDEX or any(
        part in USER_FACING_NOINDEX for part in _path(url).split("/")
    ):
        return {
            "url": url,
            "decision": "NOINDEX",
            "reason": "user_facing_no_search_intent",
            "target": None,
            "evidence": evidence,
        }
    target = find_merge_target(url, sitemap_urls)
    if target:
        family = _family(url)
        absorbed = bool(row.get("content_absorbed"))
        if (
            family in {"compare", "guides"}
            and not absorbed
            and evidence["legitimate_referring_domains"] <= 0
        ):
            return {
                "url": url,
                "decision": "GONE_410",
                "reason": "generic_hub_without_content_absorption_or_backlinks",
                "target": None,
                "evidence": {**evidence, "content_absorbed": absorbed},
            }
        return {
            "url": url,
            "decision": "MERGE_301",
            "reason": "ancestor_replacement",
            "target": target,
            "evidence": {**evidence, "content_absorbed": absorbed},
        }
    if evidence["impressions_90d"] > 0 or evidence["live_inventory_count"] > 0:
        return {
            "url": url,
            "decision": "ENRICH",
            "reason": "has_demand_or_live_inventory_but_not_enough_value",
            "target": None,
            "evidence": evidence,
        }
    return {
        "url": url,
        "decision": "GONE_410",
        "reason": "no_clicks_no_backlinks_no_parent",
        "target": None,
        "evidence": evidence,
    }


def plan_site_repair(
    rows: list[dict[str, Any]],
    *,
    sitemap_urls: list[str],
    domain: str,
    conn: Any = None,
) -> dict[str, Any]:
    decisions = [classify_disposal(row, sitemap_urls=sitemap_urls) for row in rows]
    counts = Counter(decision["decision"] for decision in decisions)
    if conn is not None:
        stamp = _now()
        for decision in decisions:
            conn.execute(
                """
                INSERT INTO url_lifecycle (url, domain, state, reason, cluster_id, updated_at)
                VALUES (?, ?, ?, ?, NULL, ?)
                ON CONFLICT(url) DO UPDATE SET
                    state = excluded.state,
                    reason = excluded.reason,
                    updated_at = excluded.updated_at
                """,
                (
                    decision["url"],
                    domain,
                    decision["decision"],
                    decision["reason"],
                    stamp,
                ),
            )
            if decision["decision"] != "PROTECT":
                conn.execute(
                    """
                    INSERT INTO repair_actions
                    (domain, url, action, target_url, reason, status, created_at)
                    VALUES (?, ?, ?, ?, ?, 'PENDING', ?)
                    ON CONFLICT(domain, url, action) DO UPDATE SET
                        target_url = excluded.target_url,
                        reason = excluded.reason
                    """,
                    (
                        domain,
                        decision["url"],
                        decision["decision"],
                        decision["target"],
                        decision["reason"],
                        stamp,
                    ),
                )
        conn.commit()
    return {
        "domain": domain,
        "total": len(decisions),
        "counts": dict(counts),
        "decisions": decisions,
    }


def should_noindex_empty_state(
    *,
    zero_inventory_days: int,
    has_unique_telemetry: bool = False,
    threshold_days: int = 14,
) -> bool:
    """Prevent soft-404 creep on live-inventory pages.

    A page with no live inventory for longer than the threshold must switch to
    noindex until inventory returns — unless it carries persistent first-party
    telemetry that keeps the document useful.
    """
    if has_unique_telemetry:
        return False
    return int(zero_inventory_days) >= int(threshold_days)


def select_keep_list(
    decisions: list[dict[str, Any]],
    *,
    limit: int = 18,
) -> list[str]:
    """Pick a tight indexable footprint from a repair plan.

    Protected URLs are always kept.  Remaining slots go to the highest measured
    demand, then the largest live inventory.  Everything else must leave the
    indexable footprint even if the page still exists for users.
    """
    protected = [d for d in decisions if d["decision"] == "PROTECT"]
    enrich = sorted(
        (d for d in decisions if d["decision"] == "ENRICH"),
        key=lambda d: (
            -float(d.get("evidence", {}).get("impressions_90d") or 0),
            -float(d.get("evidence", {}).get("live_inventory_count") or 0),
            d["url"],
        ),
    )
    keep = protected + enrich[: max(0, int(limit) - len(protected))]
    return [d["url"] for d in keep]


def finalize_footprint(
    decisions: list[dict[str, Any]],
    *,
    keep_urls: list[str],
) -> dict[str, Any]:
    """Turn a repair plan into the final indexable footprint.

    A non-kept ENRICH page with live inventory becomes NOINDEX (users can still
    reach it); a non-kept page with no inventory becomes GONE_410.
    """
    keep = {str(url).rstrip("/") for url in keep_urls}
    finalized = []
    for decision in decisions:
        item = dict(decision)
        if item["url"].rstrip("/") not in keep and item["decision"] == "ENRICH":
            has_inventory = (
                float(item.get("evidence", {}).get("live_inventory_count") or 0) > 0
            )
            item["decision"] = "NOINDEX" if has_inventory else "GONE_410"
            item["reason"] = "outside_final_keep_list"
            item["target"] = None
        finalized.append(item)
    counts = Counter(item["decision"] for item in finalized)
    return {"total": len(finalized), "counts": dict(counts), "decisions": finalized}


def validate_page_contract(contract: dict[str, Any]) -> dict[str, Any]:
    reasons: list[str] = []
    if not str(contract.get("data_source_hash") or "").strip():
        reasons.append("missing_data_source_hash")
    if int(contract.get("unique_data_fields") or 0) < MIN_UNIQUE_DATA_FIELDS:
        reasons.append("insufficient_unique_data_fields")
    if float(contract.get("stripped_overlap_score") or 1.0) > MAX_STRIPPED_OVERLAP:
        reasons.append("entity_stripped_overlap_too_high")
    if int(contract.get("planned_indexed_inlinks") or 0) < MIN_PLANNED_INLINKS:
        reasons.append("insufficient_planned_inlinks")
    if str(contract.get("tier") or "B").upper() == "B" and not contract.get(
        "cluster_id"
    ):
        reasons.append("untethered_cluster")
    return {"valid": not reasons, "reasons": reasons}


def register_page_contract(conn: Any, contract: dict[str, Any]) -> dict[str, Any]:
    validation = validate_page_contract(contract)
    stamp = _now()
    conn.execute(
        """
        INSERT INTO page_contracts
        (url, cluster_id, tier, data_source_hash, unique_data_fields,
         stripped_overlap_score, planned_indexed_inlinks, rendered_at, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(url) DO UPDATE SET
            cluster_id = excluded.cluster_id,
            tier = excluded.tier,
            data_source_hash = excluded.data_source_hash,
            unique_data_fields = excluded.unique_data_fields,
            stripped_overlap_score = excluded.stripped_overlap_score,
            planned_indexed_inlinks = excluded.planned_indexed_inlinks,
            rendered_at = excluded.rendered_at,
            status = excluded.status
        """,
        (
            contract["url"],
            contract.get("cluster_id"),
            str(contract.get("tier") or "B").upper(),
            contract.get("data_source_hash"),
            int(contract.get("unique_data_fields") or 0),
            float(contract.get("stripped_overlap_score") or 1.0),
            int(contract.get("planned_indexed_inlinks") or 0),
            contract.get("rendered_at") or stamp,
            "VALID" if validation["valid"] else "INVALID",
        ),
    )
    conn.commit()
    return {
        "url": contract["url"],
        **validation,
        "status": "VALID" if validation["valid"] else "INVALID",
    }


def compute_stripped_overlap(
    texts: list[str],
    entities: list[str],
    *,
    shingle_size: int = 4,
) -> float:
    """Max pairwise shingle overlap after stripping entity tokens.

    The CI test for a template batch: if removing the entity names leaves
    near-identical prose, the template is generating one page N times.
    """
    if len(texts) < 2:
        return 0.0
    stripped: list[list[str]] = []
    for text in texts:
        body = str(text).lower()
        for entity in entities:
            if entity:
                body = body.replace(str(entity).lower(), " ")
        tokens = re.findall(r"[a-z0-9]+", body)
        stripped.append(
            [
                " ".join(tokens[i : i + shingle_size])
                for i in range(max(0, len(tokens) - shingle_size + 1))
            ]
        )
    worst = 0.0
    for i in range(len(stripped)):
        for j in range(i + 1, len(stripped)):
            a, b = set(stripped[i]), set(stripped[j])
            if not a and not b:
                continue
            worst = max(worst, len(a & b) / len(a | b))
    return round(worst, 4)


def evaluate_cluster(
    *,
    volumes: list[float],
    top10_domains: list[str],
    authority: dict[str, dict[str, Any]],
    forum_domains: set[str] | None = None,
    min_demand: float = MIN_CLUSTER_DEMAND,
    min_entities: int = MIN_CLUSTER_ENTITIES,
) -> dict[str, Any]:
    """Outside-in cluster gate: demand + weak top-10 authority."""
    forum_domains = forum_domains or {
        "reddit.com",
        "quora.com",
        "medium.com",
        "youtube.com",
        "facebook.com",
        "instagram.com",
        "github.com",
    }
    demand = float(sum(max(0.0, float(v)) for v in volumes))
    entities = sum(1 for volume in volumes if float(volume) > 0)
    weak = 0
    weakest = None
    for domain in top10_domains:
        key = str(domain).lower().removeprefix("www.")
        metrics = authority.get(key) or {}
        ref = metrics.get("referring_domains")
        if key in forum_domains or (
            ref is not None and float(ref) <= WEAK_REFERRING_DOMAIN_LIMIT
        ):
            weak += 1
        if ref is not None and (weakest is None or float(ref) < weakest):
            weakest = float(ref)
    reasons: list[str] = []
    if demand < min_demand:
        reasons.append("insufficient_demand")
    if entities < min_entities:
        reasons.append("insufficient_entities")
    if weak < MIN_WEAK_TOP10:
        reasons.append("top10_too_authoritative")
    if weakest is None:
        reasons.append("missing_backlink_evidence")
    score = min(100.0, (demand / min_demand) * 40.0 + min(weak, 4) * 15.0)
    return {
        "demand_score": round(demand, 2),
        "entities": entities,
        "winnability_score": round(score, 2),
        "weakest_top10_rd": weakest,
        "weak_top10_count": weak,
        "winnable": not reasons,
        "reasons": reasons,
    }


def save_cluster(
    conn: Any,
    *,
    niche: str,
    entity_pattern: str,
    evaluation: dict[str, Any],
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cluster_id = (
        "cl_" + hashlib.sha1(f"{niche}|{entity_pattern}".encode()).hexdigest()[:12]
    )
    stamp = _now()
    conn.execute(
        """
        INSERT INTO clusters
        (cluster_id, niche, entity_pattern, demand_score, winnability_score,
         weakest_top10_rd, status, evidence_json, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(cluster_id) DO UPDATE SET
            demand_score = excluded.demand_score,
            winnability_score = excluded.winnability_score,
            weakest_top10_rd = excluded.weakest_top10_rd,
            status = excluded.status,
            evidence_json = excluded.evidence_json,
            updated_at = excluded.updated_at
        """,
        (
            cluster_id,
            niche,
            entity_pattern,
            float(evaluation.get("demand_score") or 0),
            float(evaluation.get("winnability_score") or 0),
            evaluation.get("weakest_top10_rd"),
            "WINNABLE" if evaluation.get("winnable") else "REJECTED",
            json.dumps(evidence or {}),
            stamp,
            stamp,
        ),
    )
    conn.commit()
    return {
        "cluster_id": cluster_id,
        "status": "WINNABLE" if evaluation.get("winnable") else "REJECTED",
        **evaluation,
    }


def discover_cluster_candidates(
    client: Any,
    *,
    seeds: list[str],
    niche: str,
    limit: int = 100,
    max_keywords: int = 5,
    diagnostics: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Outside-in discovery with real volume, SERP and backlink evidence.

    The cluster is the aggregate pattern, not one keyword.  Aggregate demand and
    entity count are evaluated together; a single 50-volume keyword is not a
    business.  A missing API response is an error, not zero demand.

    ``diagnostics`` receives the compact funnel for an empty result, so a
    rejected niche is distinguishable from a parser that extracted nothing.
    """
    raw_suggestions = list(client.keyword_suggestions(seeds, limit=limit))
    raw_ideas: list[dict[str, Any]] = []
    ideas_method = getattr(client, "keyword_ideas", None)
    if callable(ideas_method):
        raw_ideas = list(ideas_method(seeds, limit=limit))
    merged: dict[str, dict[str, Any]] = {}
    for row in [*raw_suggestions, *raw_ideas]:
        keyword = str(row.get("keyword") or "").strip().lower()
        if keyword and keyword not in merged:
            merged[keyword] = row
    suggestions = [
        row
        for row in merged.values()
        if row.get("keyword") and float(row.get("volume") or 0) > 0
    ]
    funnel: dict[str, Any] = {
        "seeds": list(seeds),
        "raw_suggestions": len(raw_suggestions),
        "raw_ideas": len(raw_ideas),
        "valid_entities": len(suggestions),
        "aggregate_demand": round(sum(float(row["volume"]) for row in suggestions), 2),
        "serps_checked": 0,
        "weak_top10_slots": 0,
        "rejection_reason": "",
    }
    if not suggestions:
        funnel["rejection_reason"] = "no_valid_entities"
        if diagnostics is not None:
            diagnostics.update(funnel)
        return []
    volumes = [float(row["volume"]) for row in suggestions]
    domains: list[str] = []
    for suggestion in suggestions[: max(0, int(max_keywords))]:
        serp = client.fetch_serp_live(suggestion["keyword"], depth=10)
        funnel["serps_checked"] += 1
        for item in (serp[0].get("items") if serp else []) or []:
            if item.get("type") != "organic":
                continue
            domain = _item_domain(item)
            if domain and domain not in domains:
                domains.append(domain)
    authority: dict[str, dict[str, Any]] = {}
    for domain in domains[:10]:
        try:
            authority[domain] = client.backlinks_summary(domain)
        except Exception:  # noqa: BLE001 - a failed backlink probe is missing evidence
            authority[domain] = {}
    evaluation = evaluate_cluster(
        volumes=volumes,
        top10_domains=domains,
        authority=authority,
    )
    funnel["weak_top10_slots"] = evaluation["weak_top10_count"]
    if not evaluation["winnable"]:
        funnel["rejection_reason"] = ",".join(evaluation["reasons"])
    if diagnostics is not None:
        diagnostics.update(funnel)
    return [
        {
            "entity_pattern": " | ".join(seeds),
            "keywords": [row["keyword"] for row in suggestions],
            "volume": round(sum(volumes), 2),
            "top10_domains": domains,
            "authority": authority,
            "funnel": funnel,
            **evaluation,
        }
    ]


def create_cohort(
    conn: Any,
    *,
    template_id: str,
    domain: str,
    urls: list[str],
    launched_at: str | None = None,
) -> dict[str, Any]:
    if len(urls) < 5:
        raise ValueError("a pilot cohort needs at least 5 URLs")
    cohort_id = "coh_" + uuid.uuid4().hex[:12]
    stamp = launched_at or _now()
    conn.execute(
        """
        INSERT INTO cohorts
        (cohort_id, template_id, domain, stage, urls_json, launched_at, updated_at)
        VALUES (?, ?, ?, 'PILOT_LIVE', ?, ?, ?)
        """,
        (cohort_id, template_id, domain, json.dumps(urls), stamp, _now()),
    )
    conn.commit()
    return {
        "cohort_id": cohort_id,
        "template_id": template_id,
        "stage": "PILOT_LIVE",
        "urls": urls,
    }


def record_cohort_measurement(
    conn: Any,
    cohort_id: str,
    *,
    day: int,
    indexed: int,
    total: int,
    impressions: float,
) -> dict[str, Any]:
    if day not in {7, 14, 21, 45}:
        raise ValueError("day must be 7, 14, 21 or 45")
    rate = round(indexed / total, 4) if total else 0.0
    column = {7: "day7_indexed", 14: "day14_indexed", 21: "day21_indexed"}.get(day)
    if column:
        conn.execute(
            f"UPDATE cohorts SET {column} = ?, updated_at = ? WHERE cohort_id = ?",
            (rate, _now(), cohort_id),
        )
    else:
        conn.execute(
            "UPDATE cohorts SET day45_impressions = ?, updated_at = ? WHERE cohort_id = ?",
            (float(impressions), _now(), cohort_id),
        )
    conn.commit()
    return advance_cohort(conn, cohort_id)


def advance_cohort(conn: Any, cohort_id: str) -> dict[str, Any]:
    row = conn.execute(
        "SELECT template_id, stage, day7_indexed, day14_indexed, day21_indexed, day45_impressions FROM cohorts WHERE cohort_id = ?",
        (cohort_id,),
    ).fetchone()
    if not row:
        raise KeyError(f"unknown cohort {cohort_id}")
    template_id, stage, day7, day14, day21, day45_imp = row
    reasons: list[str] = []
    new_stage = stage
    if (
        day21 is not None
        and float(day21) >= MIN_PILOT_INDEX_RATE
        and float(day45_imp or 0) > 0
    ):
        new_stage = "SCALING"
    elif day21 is not None and float(day21) < FREEZE_TEMPLATE_RATE:
        new_stage = "FROZEN"
        reasons.append("day21_indexation_below_fifty_percent")
    elif (
        day45_imp is not None
        and float(day45_imp) <= 0
        and float(day21 or 0) < MIN_PILOT_INDEX_RATE
    ):
        new_stage = "PRUNE"
        reasons.append("no_indexation_and_no_impressions_at_day45")
    verdict = None
    if new_stage == "SCALING":
        verdict = "SCALE"
    elif new_stage == "FROZEN":
        verdict = "FREEZE_AND_REVIEW_CONTRACT"
    elif new_stage == "PRUNE":
        verdict = "PRUNE_TO_REPAIR_QUEUE"
    conn.execute(
        "UPDATE cohorts SET stage = ?, verdict = ?, updated_at = ? WHERE cohort_id = ?",
        (new_stage, verdict, _now(), cohort_id),
    )
    conn.commit()
    return {
        "cohort_id": cohort_id,
        "template_id": template_id,
        "stage": new_stage,
        "verdict": verdict,
        "reasons": reasons,
        "day7_indexed": day7,
        "day14_indexed": day14,
        "day21_indexed": day21,
        "day45_impressions": day45_imp,
    }


def hash_contract_source(source: str | bytes) -> str:
    data = source.encode("utf-8") if isinstance(source, str) else source
    return hashlib.sha256(data).hexdigest()[:16]


def _read_json(path: str) -> Any:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Unified pSEO state machine")
    parser.add_argument(
        "--db-path", default=str(Path.home() / ".seo_fleet" / "fleet_state.db")
    )
    sub = parser.add_subparsers(dest="command", required=True)

    repair = sub.add_parser(
        "repair-plan",
        help="classify existing URLs into PROTECT/MERGE/NOINDEX/ENRICH/GONE",
    )
    repair.add_argument("--input", required=True, help="JSON list of URL rows")
    repair.add_argument("--sitemap-file", required=True)
    repair.add_argument("--domain", required=True)
    repair.add_argument("--output", default="")
    repair.add_argument("--persist", action="store_true")

    finalize = sub.add_parser(
        "finalize", help="cap the indexable footprint to a keep list"
    )
    finalize.add_argument("--input", required=True, help="repair plan JSON")
    finalize.add_argument("--keep-limit", type=int, default=18)
    finalize.add_argument("--output", default="")

    contracts = sub.add_parser(
        "contracts", help="validate/register dry-run page contracts"
    )
    contracts.add_argument(
        "--input", required=True, help="JSON list of contract objects"
    )

    cluster = sub.add_parser("cluster-check", help="score an outside-in cluster")
    cluster.add_argument(
        "--input", required=True, help="JSON {volumes, top10_domains, authority}"
    )

    discover = sub.add_parser(
        "discover", help="outside-in DataForSEO cluster discovery"
    )
    discover.add_argument("--seeds", required=True, help="CSV of seed keywords")
    discover.add_argument("--niche", required=True)
    discover.add_argument("--limit", type=int, default=100)
    discover.add_argument("--max-keywords", type=int, default=5)
    discover.add_argument("--output", default="")

    cohort = sub.add_parser("cohort-create", help="create a pilot cohort")
    cohort.add_argument("--template", required=True)
    cohort.add_argument("--domain", required=True)
    cohort.add_argument("--urls", required=True, help="JSON list of URLs")

    measure = sub.add_parser("cohort-measure", help="record day 7/14/21/45 outcome")
    measure.add_argument("--cohort", required=True)
    measure.add_argument("--day", type=int, choices=[7, 14, 21, 45], required=True)
    measure.add_argument("--indexed", type=int, required=True)
    measure.add_argument("--total", type=int, required=True)
    measure.add_argument("--impressions", type=float, default=0.0)

    advance = sub.add_parser("cohort-advance", help="recompute a cohort verdict")
    advance.add_argument("--cohort", required=True)

    args = parser.parse_args(argv)
    conn = connect_state_db(args.db_path)
    try:
        if args.command == "repair-plan":
            sitemap = _read_json(args.sitemap_file)
            plan = plan_site_repair(
                _read_json(args.input),
                sitemap_urls=sitemap,
                domain=args.domain,
                conn=conn if args.persist else None,
            )
            text = json.dumps(plan, indent=2)
            if args.output:
                Path(args.output).write_text(text, encoding="utf-8")
            print(text)
            return 0
        if args.command == "finalize":
            plan = _read_json(args.input)
            decisions = plan.get("decisions") or plan
            keep = select_keep_list(decisions, limit=args.keep_limit)
            final = finalize_footprint(decisions, keep_urls=keep)
            text = json.dumps(
                {"keep": keep, "keep_count": len(keep), **final}, indent=2
            )
            if args.output:
                Path(args.output).write_text(text, encoding="utf-8")
            print(text)
            return 0
        if args.command == "contracts":
            results = [register_page_contract(conn, c) for c in _read_json(args.input)]
            print(json.dumps(results, indent=2))
            return 0
        if args.command == "cluster-check":
            payload = _read_json(args.input)
            print(
                json.dumps(
                    evaluate_cluster(
                        volumes=payload["volumes"],
                        top10_domains=payload["top10_domains"],
                        authority=payload["authority"],
                    ),
                    indent=2,
                )
            )
            return 0
        if args.command == "discover":
            from dataforseo_client import DataForSEOClient, resolve_credentials

            login, password = resolve_credentials()
            diagnostics: dict[str, Any] = {}
            rows = discover_cluster_candidates(
                DataForSEOClient(login, password),
                seeds=[s.strip() for s in args.seeds.split(",") if s.strip()],
                niche=args.niche,
                limit=args.limit,
                max_keywords=args.max_keywords,
                diagnostics=diagnostics,
            )
            saved = [
                save_cluster(
                    conn,
                    niche=args.niche,
                    entity_pattern=row["entity_pattern"],
                    evaluation=row,
                    evidence=row,
                )
                for row in rows
            ]
            text = json.dumps({"funnel": diagnostics, "clusters": saved}, indent=2)
            if args.output:
                Path(args.output).write_text(text, encoding="utf-8")
            print(text)
            return 0
        if args.command == "cohort-create":
            print(
                json.dumps(
                    create_cohort(
                        conn,
                        template_id=args.template,
                        domain=args.domain,
                        urls=_read_json(args.urls),
                    ),
                    indent=2,
                )
            )
            return 0
        if args.command == "cohort-measure":
            print(
                json.dumps(
                    record_cohort_measurement(
                        conn,
                        args.cohort,
                        day=args.day,
                        indexed=args.indexed,
                        total=args.total,
                        impressions=args.impressions,
                    ),
                    indent=2,
                )
            )
            return 0
        if args.command == "cohort-advance":
            print(json.dumps(advance_cohort(conn, args.cohort), indent=2))
            return 0
    finally:
        conn.close()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
