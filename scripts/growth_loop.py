#!/usr/bin/env python3
"""growth_loop.py - positive-expectation invocation planner for SEO work.

The rest of the skill is a set of gates: it can correctly refuse a bad page and
still emit an empty queue.  This module is the missing execution loop.  Every
invocation produces a ranked set of actions drawn from four portfolios:

* GROW      - new routes whose demand and payload evidence cleared the launch gate
* IMPROVE   - existing pages with a measured SERP/CTR/content gap
* CONNECT   - internal links and hub equity for pages that already exist
* MAINTAIN  - indexation fixes, pruning, and outcome measurement

The planner is deliberately not a promise that Google will index or rank a
page.  It is a promise that a run never ends with "nothing to do": when no
action has a positive *measured* click-lift lower bound, it emits a measurement
or instrumentation action and labels the run honestly.

The ranking probability is a transparent prior, not a calibrated claim.  It
becomes an empirical estimate when action-effectiveness history exists, and it
is always reported with its model name and lower bound.

State lives in the same ``~/.seo_fleet/fleet_state.db`` used by the rest of the
skill.  New tables are additive and created on first connection.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sqlite3
import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

DEFAULT_STATE_DB = str(Path.home() / ".seo_fleet" / "fleet_state.db")
DEFAULT_COOLDOWN_DAYS = 30
DEFAULT_REVIEW_DAYS = 21
DEFAULT_LIMIT = 5
DEFAULT_VALUE_PER_CLICK = 0.0
#: A "positive" label must clear this lower-bound click lift. Below it, a
#: title tweak or internal link is unmeasurable noise, not growth.
MATERIALITY_FLOOR_CLICKS_90D = 10.0
MIN_TITLE_IMPRESSIONS = 50
MIN_TITLE_POSITION = 4.0
MAX_TITLE_POSITION = 20.0
#: Reviews below this baseline volume cannot detect a meaningful lift.
MIN_REVIEW_IMPRESSIONS = 200
#: Known Google core/spam rollout windows. A review whose observation window
#: overlaps one is quarantined instead of poisoning action effectiveness.
CORE_UPDATE_WINDOWS = (
    ("2026-11-01", "2026-11-24"),
    ("2026-12-01", "2026-12-31"),
)

# Position -> conservative organic CTR prior.  These are planning priors, not
# promises: the observed CTR from GSC always wins when it is present.
CTR_BY_POSITION = (
    (1.0, 0.30),
    (2.0, 0.18),
    (3.0, 0.12),
    (5.0, 0.07),
    (10.0, 0.03),
    (20.0, 0.015),
    (50.0, 0.006),
)

EFFORT_HOURS = {
    "REWRITE_TITLE_META": 0.35,
    "INJECT_SECONDARY_H2_ONLY": 0.6,
    "INJECT_CONTEXTUAL_INLINK": 0.4,
    "ENRICH_UNIQUE_DATA": 1.2,
    "FIX_INDEXABILITY": 0.75,
    "REFRESH_STALE_CONTENT": 1.0,
    "REQUEST_INDEXING": 0.1,
    "CONSOLIDATE_CANNIBALIZED_URLS": 1.5,
    "PRUNE_OR_NOINDEX": 0.3,
    "MEASURE_OUTCOME": 0.15,
    "INSTRUMENT_TELEMETRY": 0.2,
    "LAUNCH_PSEO_ROUTE": 2.5,
    "CREATE_PROGRAMMATIC_ROUTE": 2.5,
}

ACTION_KIND = {
    "REWRITE_TITLE_META": "IMPROVE",
    "INJECT_SECONDARY_H2_ONLY": "IMPROVE",
    "INJECT_CONTEXTUAL_INLINK": "CONNECT",
    "ENRICH_UNIQUE_DATA": "IMPROVE",
    "FIX_INDEXABILITY": "MAINTAIN",
    "REFRESH_STALE_CONTENT": "IMPROVE",
    "REQUEST_INDEXING": "MAINTAIN",
    "CONSOLIDATE_CANNIBALIZED_URLS": "MAINTAIN",
    "PRUNE_OR_NOINDEX": "MAINTAIN",
    "MEASURE_OUTCOME": "MEASURE",
    "INSTRUMENT_TELEMETRY": "MEASURE",
    "LAUNCH_PSEO_ROUTE": "GROW",
    "CREATE_PROGRAMMATIC_ROUTE": "GROW",
}

SUCCESS_PRIOR = {
    "REWRITE_TITLE_META": 0.55,
    "INJECT_SECONDARY_H2_ONLY": 0.48,
    "INJECT_CONTEXTUAL_INLINK": 0.40,
    "ENRICH_UNIQUE_DATA": 0.42,
    "FIX_INDEXABILITY": 0.55,
    "REFRESH_STALE_CONTENT": 0.50,
    "REQUEST_INDEXING": 0.35,
    "CONSOLIDATE_CANNIBALIZED_URLS": 0.60,
    "PRUNE_OR_NOINDEX": 0.85,
    "LAUNCH_PSEO_ROUTE": 0.55,
    "CREATE_PROGRAMMATIC_ROUTE": 0.55,
    "MEASURE_OUTCOME": 1.0,
    "INSTRUMENT_TELEMETRY": 1.0,
}

# Conservative lower-bound shrink for a cold-start prior: 55% prior becomes a
# 40% lower bound.  Empirical action-effectiveness shrinks toward its observed
# Beta posterior instead.
PRIOR_LOWER_FACTOR = 0.72


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _f(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _i(value: Any, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _sigmoid(value: float) -> float:
    if value >= 50:
        return 1.0
    if value <= -50:
        return 0.0
    return 1.0 / (1.0 + math.exp(-value))


def _domain_from_url(value: str) -> str:
    host = (urlparse(value).hostname or "").lower()
    if not host:
        return ""
    parts = host.split(".")
    return ".".join(parts[-2:]) if len(parts) > 2 else host


def _normalize_page(value: str) -> str:
    return str(value or "").strip()


def _normalize_query(value: str) -> str:
    return " ".join(str(value or "").lower().split())


def _usable_query(value: str) -> bool:
    """Reject phone-number/digit strings masquerading as search intent."""
    query = _normalize_query(value)
    if not query:
        return True  # page-level maintenance actions are allowed
    if not re.search(r"[a-z]", query):
        return False
    return not re.fullmatch(r"[\d\s+()\-./]+", query)


def expected_ctr(position: float) -> float:
    """Conservative position -> CTR planning prior."""
    pos = max(1.0, _f(position, 100.0))
    for limit, ctr in CTR_BY_POSITION:
        if pos <= limit:
            return ctr
    return 0.002


PBN_TOKENS = (
    "pbn",
    "backlink",
    "linkboost",
    "seoninjia",
    "seoninja",
    "guestpost",
    "guest-post",
    "linkfarm",
    "link-building",
    "buy-links",
    "seocodeminty",
    "cripio",
    "prepaidgiftbalance",
)
PBN_TLDS = {".site", ".shop", ".online", ".top", ".click", ".loan", ".buzz"}


def is_flagged_pbn_domain(domain: str) -> bool:
    """Conservative PBN/spam filter for referring-domain counts.

    A suspicious token is enough. A risky TLD alone is not: plenty of real
    businesses use .shop/.online, so require the token there too.
    """
    value = str(domain or "").strip().lower().strip(".")
    if not value:
        return True
    if any(token in value for token in PBN_TOKENS):
        return True
    return value.endswith(tuple(PBN_TLDS)) and bool(
        re.search(r"(seo|link|rank|traffic|boost|marketing)", value)
    )


def legitimate_referring_domain_count(
    domains: Iterable[str] | None,
    *,
    fallback: float = 0.0,
) -> float:
    """Count distinct referring domains after removing flagged PBN hosts."""
    if domains is None:
        return fallback
    clean = {
        str(domain).strip().lower()
        for domain in domains
        if str(domain).strip() and not is_flagged_pbn_domain(str(domain))
    }
    return float(len(clean))


def indexing_state(row: dict[str, Any]) -> bool | None:
    """True indexed, False explicitly rejected, None unknown.

    Never infer "indexed" from an absent coverage field: a page with no
    evidence is not a safe target for a title test.
    """
    coverage = str(row.get("coverage_state") or "").strip().lower()
    if not coverage:
        value = row.get("is_indexed")
        return bool(value) if value is not None else None
    if any(
        token in coverage
        for token in (
            "not indexed",
            "unknown to google",
            "discovered",
            "crawled",
            "excluded",
            "duplicate",
            "alternate page",
            "redirect",
        )
    ):
        return False
    if "submitted and indexed" in coverage or coverage in {
        "indexed",
        "submitted and indexed",
    }:
        return True
    return None


def estimate_ranking_probability(row: dict[str, Any]) -> dict[str, Any]:
    """Transparent P(top-10 / top-3) prior for an existing or planned page.

    Inputs are the same flat evidence fields the launch gate carries, plus
    GSC position/CTR and the competitor-authority fields from DataForSEO.
    This is deliberately a prior: no model can know Google's ranking decision
    before the page exists.  When ``action_effectiveness_stats`` has enough
    experiments, ``empirical_lift`` is added as a bounded adjustment.
    """
    feats = row.get("features") if isinstance(row.get("features"), dict) else {}
    pos = _f(row.get("current_pos", feats.get("current_pos")), 30.0)
    if pos <= 0:
        pos = 30.0
    pos = min(pos, 100.0)

    forum = _clamp(
        _f(feats.get("serp_forum_ratio", row.get("serp_forum_ratio"))), 0.0, 1.0
    )
    title_match = _clamp(
        _f(feats.get("title_exact_match_rate", row.get("title_exact_match_rate"))),
        0.0,
        1.0,
    )
    crowding = _clamp(
        _f(feats.get("serp_pixel_crowding", row.get("serp_pixel_crowding"))),
        0.0,
        1.0,
    )
    hub_links = max(
        0.0,
        _f(
            feats.get("parent_hub_internal_links", row.get("parent_hub_internal_links"))
        ),
    )
    inlinks = max(
        0.0, _f(row.get("inlinks_from_indexed", feats.get("inlinks_from_indexed")))
    )
    unique_fields = max(
        0.0, _f(row.get("unique_data_fields", feats.get("unique_data_fields")))
    )
    weakest_rd = _f(row.get("weakest_top10_rd", feats.get("weakest_top10_rd")), 0.0)
    volume_log = max(
        0.0, _f(feats.get("search_volume_log", row.get("search_volume_log")))
    )
    p_index = _clamp(
        _f(row.get("p_index_28d", feats.get("p_index_28d")), 0.5), 0.0, 1.0
    )

    position_signal = _clamp((31.0 - pos) / 30.0, 0.0, 1.0)
    serp_openness = _clamp(
        0.45 * forum + 0.35 * (1.0 - title_match) + 0.20 * (1.0 - crowding),
        0.0,
        1.0,
    )
    link_equity = _clamp((inlinks + hub_links) / 12.0, 0.0, 1.0)
    content_depth = _clamp(unique_fields / 6.0, 0.0, 1.0)
    authority_penalty = 0.0
    if weakest_rd > 0:
        authority_penalty = _clamp(math.log1p(weakest_rd) / 8.0, 0.0, 1.0)

    logit_top10 = (
        -1.55
        + 2.10 * position_signal
        + 0.85 * serp_openness
        + 0.55 * link_equity
        + 0.30 * content_depth
        + 0.10 * min(volume_log, 6.0)
        - 0.35 * authority_penalty
    )
    referring_domains = (
        row.get("referring_domains")
        or feats.get("referring_domains")
        or row.get("host_referring_domains")
    )
    if isinstance(referring_domains, (list, tuple, set)):
        host_rd = legitimate_referring_domain_count(referring_domains)
    else:
        host_rd = _f(
            row.get(
                "host_legitimate_rd",
                row.get("host_referring_domains", feats.get("host_legitimate_rd")),
            ),
            0.0,
        )
    weakest_rd = _f(row.get("weakest_top10_rd", feats.get("weakest_top10_rd")), 0.0)
    authority_source = "provided"
    if host_rd > 0 and weakest_rd > 0:
        authority_ratio = host_rd / weakest_rd
        # A 42-RD site facing 674-2,390-RD competitors is not a 35% top-10
        # candidate. Square-rooting the ratio keeps a 5x gap meaningful while
        # sharply capping 10x+ cliffs.
        authority_factor = _clamp(authority_ratio**0.5, 0.02, 1.0)
    else:
        authority_ratio = 0.0
        authority_factor = 0.35
        authority_source = "missing"

    p_top10 = _clamp(_sigmoid(logit_top10) * p_index * authority_factor, 0.0, 1.0)
    p_top3 = _clamp(_sigmoid(logit_top10 - 1.25) * p_index * authority_factor, 0.0, 1.0)
    p_top10_lower = _clamp(p_top10 * PRIOR_LOWER_FACTOR, 0.0, 1.0)
    p_top3_lower = _clamp(p_top3 * PRIOR_LOWER_FACTOR, 0.0, 1.0)

    return {
        "model": "transparent_prior_v1",
        "p_top10": round(p_top10, 4),
        "p_top10_lower": round(p_top10_lower, 4),
        "p_top3": round(p_top3, 4),
        "p_top3_lower": round(p_top3_lower, 4),
        "p_indexed_28d": round(p_index, 4),
        "position_signal": round(position_signal, 4),
        "serp_openness": round(serp_openness, 4),
        "authority_penalty": round(authority_penalty, 4),
        "authority_factor": round(authority_factor, 4),
        "authority_ratio": round(authority_ratio, 4),
        "authority_source": authority_source,
        "host_legitimate_rd": round(host_rd, 3),
        "weakest_top10_rd": round(weakest_rd, 3),
        "note": "Prior, not a Google guarantee; recalibrate from measured outcomes.",
    }


def _action_key(
    domain: str,
    page: str,
    query: str,
    action_code: str,
    target: str = "",
) -> str:
    raw = "|".join(
        (
            (domain or "").lower(),
            _normalize_page(page),
            _normalize_query(query),
            action_code.upper(),
            str(target or "").lower(),
        )
    )
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:24]


def _baseline(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "clicks": round(_f(row.get("clicks_30d", row.get("clicks"))), 4),
        "impressions": round(_f(row.get("impressions")), 4),
        "ctr": round(_f(row.get("ctr")), 6),
        "position": round(
            _f(row.get("current_pos", (row.get("features") or {}).get("current_pos"))),
            4,
        ),
        "measured_at": str(row.get("measured_at") or ""),
    }


@dataclass
class GrowthAction:
    action_key: str
    domain: str
    page: str
    query: str
    action_code: str
    kind: str
    target: str = ""
    priority_track: str = "ranking"
    p_success: float = 0.4
    p_success_lower: float = 0.3
    expected_clicks_90d: float = 0.0
    expected_clicks_lower: float = 0.0
    expected_value: float = 0.0
    effort_hours: float = 0.5
    score: float = 0.0
    baseline: dict[str, Any] = field(default_factory=dict)
    evidence: dict[str, Any] = field(default_factory=dict)
    status: str = "OPEN"
    created_at: str = ""
    due_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_key": self.action_key,
            "domain": self.domain,
            "page": self.page,
            "query": self.query,
            "action_code": self.action_code,
            "kind": self.kind,
            "target": self.target,
            "priority_track": self.priority_track,
            "p_success": round(self.p_success, 4),
            "p_success_lower": round(self.p_success_lower, 4),
            "expected_clicks_90d": round(self.expected_clicks_90d, 4),
            "expected_clicks_lower": round(self.expected_clicks_lower, 4),
            "expected_value": round(self.expected_value, 4),
            "effort_hours": round(self.effort_hours, 3),
            "score": round(self.score, 4),
            "baseline": self.baseline,
            "evidence": self.evidence,
            "status": self.status,
            "created_at": self.created_at,
            "due_at": self.due_at,
        }


def _make_action(
    *,
    domain: str,
    page: str,
    query: str,
    action_code: str,
    target: str = "",
    p_success: float,
    lift_clicks: float,
    effort_hours: float | None = None,
    evidence: dict[str, Any] | None = None,
    baseline: dict[str, Any] | None = None,
    priority_track: str = "ranking",
    now: datetime | None = None,
) -> GrowthAction:
    code = action_code.upper()
    p = _clamp(p_success, 0.01, 0.99)
    lower = _clamp(p * PRIOR_LOWER_FACTOR, 0.0, 0.99)
    clicks = max(0.0, float(lift_clicks))
    effort = max(0.05, float(effort_hours or EFFORT_HOURS.get(code, 0.75)))
    lower_clicks = clicks * lower
    # Click-equivalent score.  A monetary value is intentionally optional;
    # the executor can pass --value-per-click when it has a defensible number.
    score = lower_clicks / effort
    created = _iso(now or _now())
    return GrowthAction(
        action_key=_action_key(domain, page, query, code, target),
        domain=domain,
        page=page,
        query=query,
        action_code=code,
        kind=ACTION_KIND.get(code, "IMPROVE"),
        target=target,
        priority_track=priority_track,
        p_success=p,
        p_success_lower=lower,
        expected_clicks_90d=clicks,
        expected_clicks_lower=lower_clicks,
        expected_value=0.0,
        effort_hours=effort,
        score=score,
        baseline=baseline or {},
        evidence=evidence or {},
        status="OPEN",
        created_at=created,
        due_at=_iso((now or _now()) + timedelta(days=DEFAULT_REVIEW_DAYS)),
    )


def _row_domain(row: dict[str, Any], fallback: str) -> str:
    return str(
        row.get("domain") or _domain_from_url(str(row.get("page") or "")) or fallback
    )


def _row_pages(row: dict[str, Any]) -> tuple[str, str]:
    page = str(row.get("page") or row.get("url") or "").strip()
    query = str(row.get("query") or "").strip()
    return page, query


def _queue_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("leased", "tasks", "queue", "actions", "route_rescue"):
        value = payload.get(key)
        if isinstance(value, list):
            return [row for row in value if isinstance(row, dict)]
    return []


def actions_from_queue(
    rows: Iterable[dict[str, Any]],
    *,
    domain: str,
    now: datetime | None = None,
) -> list[GrowthAction]:
    actions: list[GrowthAction] = []
    for row in rows:
        page, query = _row_pages(row)
        code = str(row.get("action_code") or row.get("prescribed_action") or "").upper()
        if not code or not _usable_query(query):
            continue
        row_domain = _row_domain(row, domain)
        if domain and row_domain.lower() != domain.lower():
            continue
        impressions = _f(row.get("impressions"))
        current_pos = _f(
            row.get("current_pos", (row.get("features") or {}).get("current_pos")),
            100.0,
        )
        p_success = _f(
            row.get("posterior_success_prob", row.get("p_success")),
            SUCCESS_PRIOR.get(code, 0.40),
        )
        expected = _f(row.get("expected_clicks_30d"))
        if expected > 0:
            lift = expected * 3.0
            basis = "ranker_expected_clicks_30d*3"
        else:
            # A queue task without a measured click forecast still has a
            # conservative impression-based estimate; never a fabricated exact.
            ctr_gain = max(0.002, expected_ctr(current_pos) * 0.35)
            lift = max(0.0, impressions * ctr_gain)
            basis = "impressions*conservative_ctr_gain"
        if code in {"LAUNCH_PSEO_ROUTE", "CREATE_PROGRAMMATIC_ROUTE"}:
            volume = _f(row.get("search_volume"))
            lift = max(lift, volume * 0.03)
            basis = "keyword_volume*0.03_as_impressions_proxy"
        actions.append(
            _make_action(
                domain=row_domain,
                page=page,
                query=query,
                action_code=code,
                target=str(row.get("target_component") or row.get("target") or ""),
                p_success=p_success,
                lift_clicks=lift,
                evidence={
                    "source": "action_queue",
                    "basis": basis,
                    "rank": estimate_ranking_probability(row),
                    "queue_decision": row.get("decision_class", ""),
                    "expected_value": row.get("expected_value", 0.0),
                },
                baseline=_baseline(row),
                now=now,
            )
        )
    return actions


def actions_from_features(
    rows: Iterable[dict[str, Any]],
    *,
    domain: str,
    now: datetime | None = None,
) -> list[GrowthAction]:
    """Generate existing-page actions from measured GSC/SERP rows.

    Indexation blockers are a separate mandatory track. A title rewrite is
    only proposed for a URL that is already indexed, at position 4-20, with at
    least 50 impressions in the window: editing the title of a rejected page
    cannot create ranking evidence and is actively misleading.
    """
    actions: list[GrowthAction] = []
    for row in rows:
        page, query = _row_pages(row)
        if not page or not _usable_query(query):
            continue
        feats = row.get("features") if isinstance(row.get("features"), dict) else {}
        impressions = _f(row.get("impressions", feats.get("impressions")))
        clicks = _f(row.get("clicks_30d", row.get("clicks")))
        pos = _f(feats.get("current_pos", row.get("current_pos")), 100.0)
        if pos <= 0:
            pos = 100.0
        ctr = clicks / impressions if impressions > 0 else 0.0
        ranking = estimate_ranking_probability(row)
        row_domain = _row_domain(row, domain)
        if domain and row_domain.lower() != domain.lower():
            continue
        indexed = indexing_state(row)

        if indexed is False:
            unique_fields = _f(
                row.get("unique_data_fields", feats.get("unique_data_fields"))
            )
            non_boilerplate = _f(
                row.get("non_boilerplate_ratio", feats.get("non_boilerplate_ratio")),
                1.0,
            )
            actions.append(
                _make_action(
                    domain=row_domain,
                    page=page,
                    query=query,
                    action_code="ENRICH_UNIQUE_DATA",
                    p_success=SUCCESS_PRIOR["ENRICH_UNIQUE_DATA"],
                    lift_clicks=0.0,
                    priority_track="indexation",
                    evidence={
                        "source": "measured_gsc_row",
                        "reason": "unindexed_content_depth",
                        "indexation_state": "not_indexed",
                        "unique_data_fields": round(unique_fields, 3),
                        "non_boilerplate_ratio": round(non_boilerplate, 3),
                        "impressions_30d": round(impressions, 3),
                        "ranking": ranking,
                        "honest_note": "Required before any CTR/ranking action; no click lift claimed.",
                    },
                    baseline=_baseline(row),
                    now=now,
                )
            )
            coverage = str(row.get("coverage_state") or "").lower()
            if any(
                token in coverage
                for token in (
                    "discovered",
                    "unknown to google",
                    "duplicate",
                    "canonical",
                    "excluded",
                )
            ):
                actions.append(
                    _make_action(
                        domain=row_domain,
                        page=page,
                        query=query,
                        action_code="FIX_INDEXABILITY",
                        p_success=SUCCESS_PRIOR["FIX_INDEXABILITY"],
                        lift_clicks=0.0,
                        priority_track="indexation",
                        evidence={
                            "source": "measured_gsc_row",
                            "reason": "coverage_not_indexed",
                            "coverage_state": row.get("coverage_state"),
                            "ranking": ranking,
                        },
                        baseline=_baseline(row),
                        now=now,
                    )
                )
            if impressions >= 10:
                actions.append(
                    _make_action(
                        domain=row_domain,
                        page=page,
                        query=query,
                        action_code="INJECT_CONTEXTUAL_INLINK",
                        p_success=SUCCESS_PRIOR["INJECT_CONTEXTUAL_INLINK"],
                        lift_clicks=0.0,
                        priority_track="indexation",
                        evidence={
                            "source": "measured_gsc_row",
                            "reason": "unindexed_kept_url_link_equity",
                            "impressions_30d": round(impressions, 3),
                            "ranking": ranking,
                        },
                        baseline=_baseline(row),
                        now=now,
                    )
                )
            continue

        if indexed is not True:
            # Unknown coverage is not permission to run a title test.
            continue

        # CTR underperformance is only a ranking action on an indexed URL with
        # enough demand to make a lower-bound click estimate measurable.
        if (
            impressions >= MIN_TITLE_IMPRESSIONS
            and MIN_TITLE_POSITION <= pos <= MAX_TITLE_POSITION
            and ctr < expected_ctr(pos) * 0.70
        ):
            p_rank = float(ranking.get("p_top10", 0.0) or 0.0)
            delta_ctr = max(0.0, expected_ctr(pos) * 0.70 - ctr)
            lift = p_rank * delta_ctr * impressions
            actions.append(
                _make_action(
                    domain=row_domain,
                    page=page,
                    query=query,
                    action_code="REWRITE_TITLE_META",
                    p_success=SUCCESS_PRIOR["REWRITE_TITLE_META"],
                    lift_clicks=lift,
                    evidence={
                        "source": "measured_gsc_row",
                        "reason": "ctr_underperformance_indexed_only",
                        "current_ctr": round(ctr, 5),
                        "expected_ctr": round(expected_ctr(pos), 5),
                        "impressions_30d": round(impressions, 3),
                        "indexation_state": "indexed",
                        "lift_formula": "p_index(1.0) * p_top10 * delta_ctr * impressions",
                        "ranking": ranking,
                    },
                    baseline=_baseline(row),
                    now=now,
                )
            )

        # Striking distance is a section change, still only on indexed pages.
        if 10.0 <= pos <= 30.0 and impressions >= 10:
            target_pos = max(1.0, pos - 3.0)
            lift = impressions * max(
                0.001, expected_ctr(target_pos) - expected_ctr(pos)
            )
            actions.append(
                _make_action(
                    domain=row_domain,
                    page=page,
                    query=query,
                    action_code="INJECT_SECONDARY_H2_ONLY",
                    p_success=SUCCESS_PRIOR["INJECT_SECONDARY_H2_ONLY"],
                    lift_clicks=lift,
                    evidence={
                        "source": "measured_gsc_row",
                        "reason": "striking_distance_indexed_only",
                        "current_position": round(pos, 3),
                        "target_position": round(target_pos, 3),
                        "impressions_30d": round(impressions, 3),
                        "indexation_state": "indexed",
                        "ranking": ranking,
                    },
                    baseline=_baseline(row),
                    now=now,
                )
            )

        inlinks = _f(row.get("inlinks_from_indexed", feats.get("inlinks_from_indexed")))
        hub_links = _f(feats.get("parent_hub_internal_links"))
        if impressions >= 10 and (inlinks < 3 or hub_links < 2):
            lift = impressions * max(0.001, expected_ctr(pos) * 0.08)
            actions.append(
                _make_action(
                    domain=row_domain,
                    page=page,
                    query=query,
                    action_code="INJECT_CONTEXTUAL_INLINK",
                    p_success=SUCCESS_PRIOR["INJECT_CONTEXTUAL_INLINK"],
                    lift_clicks=lift,
                    evidence={
                        "source": "measured_gsc_row",
                        "reason": "thin_internal_link_equity",
                        "inlinks_from_indexed": round(inlinks, 3),
                        "parent_hub_internal_links": round(hub_links, 3),
                        "impressions_30d": round(impressions, 3),
                        "ranking": ranking,
                    },
                    baseline=_baseline(row),
                    now=now,
                )
            )

        unique_fields = _f(
            row.get("unique_data_fields", feats.get("unique_data_fields"))
        )
        non_boilerplate = _f(
            row.get("non_boilerplate_ratio", feats.get("non_boilerplate_ratio")), 1.0
        )
        if impressions >= 10 and (unique_fields < 3 or non_boilerplate < 0.50):
            actions.append(
                _make_action(
                    domain=row_domain,
                    page=page,
                    query=query,
                    action_code="ENRICH_UNIQUE_DATA",
                    p_success=SUCCESS_PRIOR["ENRICH_UNIQUE_DATA"],
                    lift_clicks=impressions * max(0.001, expected_ctr(pos) * 0.10),
                    evidence={
                        "source": "measured_gsc_row",
                        "reason": "thin_or_boilerplate_content",
                        "unique_data_fields": round(unique_fields, 3),
                        "non_boilerplate_ratio": round(non_boilerplate, 3),
                        "ranking": ranking,
                    },
                    baseline=_baseline(row),
                    now=now,
                )
            )
    return actions


def actions_from_repair_queue(
    conn: sqlite3.Connection | None,
    *,
    domain: str,
    now: datetime | None = None,
) -> list[GrowthAction]:
    if conn is None:
        return []
    try:
        rows = list(
            conn.execute(
                "SELECT domain, url, action, target_url, reason FROM repair_actions "
                "WHERE status = 'PENDING' AND (domain = ? OR ? = '')",
                (domain, domain),
            )
        )
    except sqlite3.Error:
        return []
    actions: list[GrowthAction] = []
    for row in rows:
        row_domain, url, action, target_url, reason = (
            str(value or "") for value in row
        )
        code = action.upper()
        # Repair dispositions are indexation hygiene, not click forecasts.  A
        # prune is still a valid action but must not claim positive clicks.
        lift = 0.0
        p = SUCCESS_PRIOR.get(code, 0.75)
        if code in {"ENRICH", "MERGE_301"}:
            p = 0.55
        actions.append(
            _make_action(
                domain=row_domain or domain,
                page=url,
                query="",
                action_code=code,
                target=target_url,
                p_success=p,
                lift_clicks=lift,
                priority_track=(
                    "indexation"
                    if code
                    in {
                        "ENRICH",
                        "FIX_INDEXABILITY",
                        "MERGE_301",
                        "NOINDEX",
                        "PRUNE_OR_NOINDEX",
                        "REQUEST_INDEXING",
                    }
                    else "ranking"
                ),
                evidence={"source": "repair_actions", "reason": reason},
                now=now,
            )
        )
    return actions


def actions_from_indexation(
    conn: sqlite3.Connection | None,
    *,
    domain: str,
    allowed_urls: set[str] | None = None,
    now: datetime | None = None,
) -> list[GrowthAction]:
    """Turn cached URL-Inspection failures into explicit indexation fixes."""
    if conn is None or not domain:
        return []
    try:
        rows = list(
            conn.execute(
                "SELECT url, coverage_state, last_crawl_time FROM url_inspections "
                "WHERE site LIKE ? ORDER BY inspected_at DESC LIMIT 200",
                (f"%{domain}%",),
            )
        )
    except sqlite3.Error:
        return []
    seen: set[str] = set()
    actions: list[GrowthAction] = []
    for url, coverage, last_crawl in rows:
        page = str(url or "").strip()
        if allowed_urls is not None and _normalize_page(page) not in allowed_urls:
            continue
        if not page or page in seen:
            continue
        seen.add(page)
        state = str(coverage or "").lower()
        if not state or "submitted and indexed" in state or state == "indexed":
            continue
        if "discovered" in state:
            code = "REQUEST_INDEXING"
            reason = "discovered_not_indexed"
        elif "crawled" in state and "not indexed" in state:
            code = "ENRICH_UNIQUE_DATA"
            reason = "crawled_not_indexed_content_depth"
        elif "duplicate" in state or "canonical" in state:
            code = "FIX_INDEXABILITY"
            reason = "canonical_or_duplicate"
        else:
            code = "FIX_INDEXABILITY"
            reason = "coverage_not_indexed"
        actions.append(
            _make_action(
                domain=domain,
                page=page,
                query="",
                action_code=code,
                p_success=SUCCESS_PRIOR.get(code, 0.45),
                lift_clicks=0.0,
                priority_track="indexation",
                evidence={
                    "source": "url_inspections",
                    "reason": reason,
                    "coverage_state": coverage,
                    "last_crawl_time": last_crawl,
                    "honest_note": "Indexation fix; no click lift claimed before impressions exist.",
                },
                now=now,
            )
        )
    return actions


PAGE_LEVEL_ACTIONS = {
    "ENRICH_UNIQUE_DATA",
    "FIX_INDEXABILITY",
    "INJECT_CONTEXTUAL_INLINK",
    "PRUNE_OR_NOINDEX",
    "REQUEST_INDEXING",
}


def _dedupe_actions(actions: Iterable[GrowthAction]) -> list[GrowthAction]:
    best: dict[Any, GrowthAction] = {}
    for action in actions:
        key: Any = action.action_key
        if action.action_code in PAGE_LEVEL_ACTIONS:
            # A page-level defect is one task, not one task per query it
            # happens to receive impressions for.
            key = (
                action.domain.lower(),
                _normalize_page(action.page),
                action.action_code,
                action.target,
            )
        current = best.get(key)
        quality = (
            action.expected_clicks_lower,
            _f(action.baseline.get("impressions")),
        )
        current_quality = (
            (
                current.expected_clicks_lower,
                _f(current.baseline.get("impressions")),
            )
            if current
            else (0.0, 0.0)
        )
        if current is None or quality > current_quality:
            best[key] = action
    return list(best.values())


def _open_or_recent_keys(
    conn: sqlite3.Connection | None,
    *,
    domain: str,
    cooldown_days: int,
    now: datetime,
) -> set[str]:
    if conn is None:
        return set()
    cutoff = _iso(now - timedelta(days=max(0, cooldown_days)))
    try:
        rows = conn.execute(
            "SELECT action_key FROM growth_actions "
            "WHERE domain = ? AND (status = 'OPEN' OR (status = 'SHIPPED' AND completed_at >= ?))",
            (domain, cutoff),
        )
        return {str(row[0]) for row in rows}
    except sqlite3.Error:
        return set()


def _fallback_action(
    rows: Iterable[dict[str, Any]],
    *,
    domain: str,
    now: datetime,
) -> GrowthAction:
    """Never return an empty plan.  Prefer a measurable existing-page fix.

    If the site has no measured pages at all, emit an instrumentation action.
    That action does not claim a ranking lift; the plan reports
    ``information_only`` honestly.
    """
    candidates = [
        row
        for row in rows
        if not domain or _row_domain(row, domain).lower() == domain.lower()
    ]
    best: dict[str, Any] | None = None
    for row in candidates:
        page, query = _row_pages(row)
        if not page:
            continue
        impressions = _f(row.get("impressions"))
        key = (impressions, -abs(_f(row.get("current_pos", 100.0))))
        if best is None or key > best["key"]:
            best = {"key": key, "row": row, "page": page, "query": query}
    if best:
        row = best["row"]
        return _strategic_action(
            domain=domain,
            rows=candidates,
            reason="no_measurable_action_on_existing_pages",
            now=now,
        )
    return _make_action(
        domain=domain,
        page=f"https://{domain}/" if domain else "/",
        query="",
        action_code="INSTRUMENT_TELEMETRY",
        p_success=1.0,
        lift_clicks=0.0,
        evidence={
            "source": "fallback_instrumentation",
            "reason": "no_measured_pages_or_action_queue",
            "honest_note": "Connect GSC/SERP evidence before claiming a ranking lift.",
        },
        now=now,
    )


def _strategic_action(
    *,
    domain: str,
    rows: list[dict[str, Any]],
    reason: str,
    now: datetime,
) -> GrowthAction:
    """The honest exit when every measurable on-page action is below noise."""
    page = f"https://{domain}/" if domain else "/"
    return _make_action(
        domain=domain,
        page=page,
        query="",
        action_code="BUILD_TIER_A_ASSET",
        p_success=0.55,
        lift_clicks=0.0,
        priority_track="strategic",
        evidence={
            "source": "strategic_escalation",
            "reason": reason,
            "honest_note": (
                "On-page actions are below the materiality floor. Build one "
                "first-party benchmark or utility asset, or run outside-in "
                "discovery; do not ship a sub-click title edit."
            ),
            "materiality_floor_clicks_90d": MATERIALITY_FLOOR_CLICKS_90D,
            "measured_rows": len(rows),
        },
        now=now,
    )


def hydrate_inspection_states(
    rows: list[dict[str, Any]],
    conn: sqlite3.Connection | None,
    *,
    domain: str,
) -> list[dict[str, Any]]:
    """Attach cached URL-Inspection coverage to matching feature rows."""
    if conn is None or not domain:
        return rows
    try:
        inspections = {
            str(url): coverage
            for url, coverage in conn.execute(
                "SELECT url, coverage_state FROM url_inspections "
                "WHERE site LIKE ? ORDER BY inspected_at DESC",
                (f"%{domain}%",),
            )
        }
    except sqlite3.Error:
        return rows
    if not inspections:
        return rows
    for row in rows:
        if row.get("coverage_state"):
            continue
        page = str(row.get("page") or row.get("url") or "")
        if page and page in inspections:
            row["coverage_state"] = inspections[page]
    return rows


def build_growth_plan(
    rows: Iterable[dict[str, Any]],
    *,
    domain: str = "",
    queue: Iterable[dict[str, Any]] | None = None,
    conn: sqlite3.Connection | None = None,
    limit: int = DEFAULT_LIMIT,
    cooldown_days: int = DEFAULT_COOLDOWN_DAYS,
    sitemap_urls: set[str] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build a non-empty, de-duplicated, evidence-ranked action plan."""
    now = now or _now()
    rows = list(rows)
    domain = domain or next(
        (_row_domain(row, "") for row in rows if _row_domain(row, "")), ""
    )
    rows = hydrate_inspection_states(rows, conn, domain=domain)
    if sitemap_urls is not None:
        rows = [
            row
            for row in rows
            if _normalize_page(str(row.get("page") or row.get("url") or ""))
            in sitemap_urls
        ]
    all_actions: list[GrowthAction] = []
    all_actions.extend(actions_from_queue(queue or [], domain=domain, now=now))
    all_actions.extend(actions_from_features(rows, domain=domain, now=now))
    all_actions.extend(actions_from_repair_queue(conn, domain=domain, now=now))
    all_actions.extend(
        actions_from_indexation(conn, domain=domain, allowed_urls=sitemap_urls, now=now)
    )
    actions = _dedupe_actions(all_actions)

    blocked = _open_or_recent_keys(
        conn, domain=domain, cooldown_days=cooldown_days, now=now
    )
    actions = [action for action in actions if action.action_key not in blocked]
    indexation = [action for action in actions if action.priority_track == "indexation"]
    material = [
        action
        for action in actions
        if action.priority_track != "indexation"
        and action.expected_clicks_lower >= MATERIALITY_FLOOR_CLICKS_90D
    ]
    indexation.sort(key=lambda action: (action.p_success, action.score), reverse=True)
    material.sort(key=lambda action: action.score, reverse=True)

    if indexation:
        selected = indexation[: max(1, limit)]
        guarantee = "indexation_prerequisite"
        reason = (
            "indexation blockers must be fixed before CTR/ranking actions; "
            "no click lift is claimed"
        )
    elif material:
        selected = material[: max(1, limit)]
        guarantee = "positive_expected_click_lift"
        reason = (
            "at least one action clears the materiality floor with a positive "
            "measured click-lift lower bound"
        )
    elif actions:
        strategic = _strategic_action(
            domain=domain,
            rows=rows,
            reason="all_on_page_actions_below_materiality_floor",
            now=now,
        )
        if strategic.action_key in blocked:
            strategic = _make_action(
                domain=domain,
                page=f"https://{domain}/" if domain else "/",
                query="",
                action_code="MEASURE_OUTCOME",
                target="strategic-action-in-flight",
                p_success=1.0,
                lift_clicks=0.0,
                priority_track="measurement",
                evidence={
                    "source": "fallback_measurement",
                    "reason": "strategic_action_already_open",
                    "honest_note": "Wait for the open strategic action and measure it.",
                },
                now=now,
            )
        selected = [strategic]
        guarantee = "below_materiality_floor"
        reason = (
            f"no action clears the {MATERIALITY_FLOOR_CLICKS_90D:g}-click/90d "
            "floor; escalating to a Tier A asset instead of shipping busywork"
        )
    else:
        fallback = _fallback_action(rows, domain=domain, now=now)
        if fallback.action_key in blocked:
            fallback = _make_action(
                domain=fallback.domain,
                page=fallback.page,
                query=fallback.query,
                action_code="MEASURE_OUTCOME",
                target="open-action-in-flight",
                p_success=1.0,
                lift_clicks=0.0,
                priority_track="measurement",
                evidence={
                    "source": "fallback_measurement",
                    "reason": "all_known_actions_open_or_cooling",
                    "honest_note": "No duplicate work: wait for the open action and measure it.",
                },
                now=now,
            )
        selected = [fallback]
        if fallback.action_code == "INSTRUMENT_TELEMETRY":
            guarantee = "information_only"
        elif fallback.action_code == "MEASURE_OUTCOME":
            guarantee = "measurement_only"
        else:
            guarantee = "below_materiality_floor"
        reason = fallback.evidence.get("reason", "no_candidate_actions")

    for action in selected:
        action.evidence["plan_guarantee"] = guarantee
    return {
        "generated_at": _iso(now),
        "domain": domain,
        "guarantee": guarantee,
        "reason": reason,
        "materiality_floor_clicks_90d": MATERIALITY_FLOOR_CLICKS_90D,
        "positive_action_count": sum(
            1
            for action in selected
            if action.expected_clicks_lower >= MATERIALITY_FLOOR_CLICKS_90D
        ),
        "indexation_action_count": sum(
            1 for action in selected if action.priority_track == "indexation"
        ),
        "actions": [action.to_dict() for action in selected],
        "evaluated_due": [],
    }


def ensure_growth_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS growth_actions (
            action_key          TEXT PRIMARY KEY,
            domain              TEXT NOT NULL,
            page                TEXT NOT NULL,
            query               TEXT NOT NULL DEFAULT '',
            action_code         TEXT NOT NULL,
            kind                TEXT NOT NULL,
            target              TEXT NOT NULL DEFAULT '',
            status              TEXT NOT NULL DEFAULT 'OPEN',
            p_success           REAL NOT NULL DEFAULT 0.0,
            p_success_lower     REAL NOT NULL DEFAULT 0.0,
            expected_clicks_90d REAL NOT NULL DEFAULT 0.0,
            expected_clicks_lower REAL NOT NULL DEFAULT 0.0,
            expected_value      REAL NOT NULL DEFAULT 0.0,
            effort_hours        REAL NOT NULL DEFAULT 0.0,
            score               REAL NOT NULL DEFAULT 0.0,
            baseline_json       TEXT NOT NULL DEFAULT '{}',
            evidence_json       TEXT NOT NULL DEFAULT '{}',
            created_at          TEXT NOT NULL,
            due_at              TEXT,
            completed_at        TEXT,
            outcome_json        TEXT,
            updated_at          TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS growth_actions_domain_status
            ON growth_actions (domain, status, due_at);
        CREATE INDEX IF NOT EXISTS growth_actions_due
            ON growth_actions (status, due_at);
        CREATE TABLE IF NOT EXISTS growth_runs (
            run_id          TEXT PRIMARY KEY,
            domain          TEXT NOT NULL,
            created_at      TEXT NOT NULL,
            action_count    INTEGER NOT NULL DEFAULT 0,
            positive_count  INTEGER NOT NULL DEFAULT 0,
            guarantee       TEXT NOT NULL DEFAULT '',
            manifest_json   TEXT NOT NULL DEFAULT '{}'
        );
        CREATE INDEX IF NOT EXISTS growth_runs_domain_created
            ON growth_runs (domain, created_at);
        """
    )
    columns = {row[1] for row in conn.execute("PRAGMA table_info(growth_actions)")}
    if "priority_track" not in columns:
        conn.execute(
            "ALTER TABLE growth_actions ADD COLUMN priority_track TEXT NOT NULL DEFAULT 'ranking'"
        )
    conn.commit()


def record_growth_plan(
    conn: sqlite3.Connection,
    plan: dict[str, Any],
    *,
    now: datetime | None = None,
) -> int:
    """Persist selected actions and the run manifest. Idempotent on action_key."""
    ensure_growth_schema(conn)
    now = now or _now()
    inserted = 0
    for action in plan.get("actions", []):
        if not isinstance(action, dict):
            continue
        try:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO growth_actions (
                    action_key, domain, page, query, action_code, kind, target,
                    priority_track, status, p_success, p_success_lower,
                    expected_clicks_90d, expected_clicks_lower, expected_value,
                    effort_hours, score, baseline_json, evidence_json, created_at,
                    due_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    action["action_key"],
                    action.get("domain", ""),
                    action.get("page", ""),
                    action.get("query", ""),
                    action.get("action_code", ""),
                    action.get("kind", ""),
                    action.get("target", ""),
                    action.get("priority_track", "ranking"),
                    "OPEN",
                    _f(action.get("p_success")),
                    _f(action.get("p_success_lower")),
                    _f(action.get("expected_clicks_90d")),
                    _f(action.get("expected_clicks_lower")),
                    _f(action.get("expected_value")),
                    _f(action.get("effort_hours")),
                    _f(action.get("score")),
                    json.dumps(action.get("baseline") or {}, sort_keys=True),
                    json.dumps(action.get("evidence") or {}, sort_keys=True),
                    action.get("created_at") or _iso(now),
                    action.get("due_at")
                    or _iso(now + timedelta(days=DEFAULT_REVIEW_DAYS)),
                    _iso(now),
                ),
            )
            inserted += int(cursor.rowcount or 0)
        except sqlite3.Error:
            continue
    conn.execute(
        "INSERT INTO growth_runs "
        "(run_id, domain, created_at, action_count, positive_count, guarantee, manifest_json) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            uuid.uuid4().hex,
            plan.get("domain", ""),
            _iso(now),
            len(plan.get("actions", [])),
            _i(plan.get("positive_action_count")),
            plan.get("guarantee", ""),
            json.dumps(plan, sort_keys=True),
        ),
    )
    conn.commit()
    return inserted


def complete_growth_action(
    conn: sqlite3.Connection,
    action_key: str,
    *,
    commit_sha: str = "",
    outcome: dict[str, Any] | None = None,
    review_days: int = DEFAULT_REVIEW_DAYS,
    now: datetime | None = None,
) -> bool:
    ensure_growth_schema(conn)
    now = now or _now()
    payload = {"commit_sha": commit_sha, "completed": True}
    payload.update(outcome or {})
    changed = conn.execute(
        "UPDATE growth_actions SET status = 'SHIPPED', completed_at = ?, due_at = ?, "
        "outcome_json = ?, updated_at = ? WHERE action_key = ? AND status = 'OPEN'",
        (
            _iso(now),
            _iso(now + timedelta(days=max(1, review_days))),
            json.dumps(payload, sort_keys=True),
            _iso(now),
            action_key,
        ),
    ).rowcount
    conn.commit()
    return bool(changed)


def due_growth_actions(
    conn: sqlite3.Connection,
    *,
    domain: str = "",
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    ensure_growth_schema(conn)
    now = now or _now()
    rows = conn.execute(
        "SELECT * FROM growth_actions WHERE status = 'SHIPPED' AND due_at IS NOT NULL "
        "AND due_at <= ? AND (? = '' OR domain = ?) ORDER BY due_at ASC",
        (_iso(now), domain, domain),
    ).fetchall()
    columns = [
        column[0]
        for column in conn.execute("SELECT * FROM growth_actions LIMIT 0").description
    ]
    return [dict(zip(columns, row)) for row in rows]


def _window_overlaps_core_update(start: str, end: str) -> bool:
    try:
        start_dt = datetime.fromisoformat(start)
        end_dt = datetime.fromisoformat(end)
    except (TypeError, ValueError):
        return False
    for window_start, window_end in CORE_UPDATE_WINDOWS:
        update_start = datetime.fromisoformat(f"{window_start}T00:00:00+00:00")
        update_end = datetime.fromisoformat(f"{window_end}T23:59:59+00:00")
        if start_dt <= update_end and end_dt >= update_start:
            return True
    return False


def review_growth_actions(
    conn: sqlite3.Connection,
    observations: dict[str, dict[str, Any]],
    *,
    domain: str = "",
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Compare due actions with observed page/query metrics.

    ``observations`` is keyed by page URL or ``page|query``.  Each value may
    carry clicks, impressions, ctr, and position.  An action succeeds when the
    observed clicks improve by at least 10% or position improves by at least
    one rank; otherwise it is marked FAILED.  Missing observations stay due.
    """
    ensure_growth_schema(conn)
    now = now or _now()
    reviews: list[dict[str, Any]] = []
    for row in due_growth_actions(conn, domain=domain, now=now):
        key = row["page"]
        obs = (
            observations.get(key)
            or observations.get(f"{key}|{row['query']}")
            or observations.get(row["query"])
        )
        if not obs:
            reviews.append(
                {"action_key": row["action_key"], "status": "AWAITING_OBSERVATION"}
            )
            continue
        baseline = json.loads(row.get("baseline_json") or "{}")
        base_clicks = _f(baseline.get("clicks"))
        base_impressions = _f(baseline.get("impressions"))
        base_pos = _f(baseline.get("position"), 100.0)
        clicks = _f(obs.get("clicks"))
        pos = _f(obs.get("position"), base_pos)

        completed = str(row.get("completed_at") or row.get("updated_at") or "")
        if _window_overlaps_core_update(completed, _iso(now)):
            outcome = {
                "baseline_impressions": base_impressions,
                "baseline_clicks": base_clicks,
                "observed_clicks": clicks,
                "observed_position": pos,
                "reviewed_at": _iso(now),
                "quarantined": True,
                "reason": "core_update_window",
            }
            conn.execute(
                "UPDATE growth_actions SET status = ?, outcome_json = ?, updated_at = ? "
                "WHERE action_key = ?",
                (
                    "QUARANTINED_CORE_UPDATE",
                    json.dumps(outcome, sort_keys=True),
                    _iso(now),
                    row["action_key"],
                ),
            )
            reviews.append(
                {
                    "action_key": row["action_key"],
                    "status": "QUARANTINED_CORE_UPDATE",
                    "outcome": outcome,
                }
            )
            continue

        if base_impressions < MIN_REVIEW_IMPRESSIONS:
            outcome = {
                "baseline_impressions": base_impressions,
                "baseline_clicks": base_clicks,
                "observed_clicks": clicks,
                "observed_position": pos,
                "reviewed_at": _iso(now),
                "reason": "baseline_below_minimum_detectable_effect",
            }
            conn.execute(
                "UPDATE growth_actions SET status = ?, outcome_json = ?, updated_at = ? "
                "WHERE action_key = ?",
                (
                    "INSUFFICIENT_BASELINE",
                    json.dumps(outcome, sort_keys=True),
                    _iso(now),
                    row["action_key"],
                ),
            )
            reviews.append(
                {
                    "action_key": row["action_key"],
                    "status": "INSUFFICIENT_BASELINE",
                    "outcome": outcome,
                }
            )
            continue

        click_ok = clicks >= base_clicks * 1.10 if base_clicks > 0 else clicks > 0
        pos_ok = pos <= base_pos - 1.0 if base_pos > 0 else False
        success = bool(click_ok or pos_ok)
        outcome = {
            "observed_clicks": clicks,
            "baseline_clicks": base_clicks,
            "observed_position": pos,
            "baseline_position": base_pos,
            "click_ok": click_ok,
            "position_ok": pos_ok,
            "success": success,
            "reviewed_at": _iso(now),
        }
        conn.execute(
            "UPDATE growth_actions SET status = ?, outcome_json = ?, updated_at = ? "
            "WHERE action_key = ?",
            (
                "SUCCESS" if success else "FAILED",
                json.dumps(outcome, sort_keys=True),
                _iso(now),
                row["action_key"],
            ),
        )
        try:
            from fleet_state import extract_route_family, record_action_effectiveness

            record_action_effectiveness(
                conn,
                domain=row["domain"],
                action_code=row["action_code"],
                route_family=extract_route_family(row["page"]),
                is_success=success,
                click_lift=clicks - base_clicks,
                rank_delta=base_pos - pos,
            )
        except (ImportError, sqlite3.Error):
            # The action status is still authoritative if effectiveness
            # bookkeeping is unavailable; never lose the review because of a
            # secondary statistics failure.
            pass
        reviews.append(
            {
                "action_key": row["action_key"],
                "status": "SUCCESS" if success else "FAILED",
                "outcome": outcome,
            }
        )
    conn.commit()
    return reviews


def growth_status(conn: sqlite3.Connection, *, domain: str = "") -> dict[str, Any]:
    ensure_growth_schema(conn)
    counts = {
        status: count
        for status, count in conn.execute(
            "SELECT status, COUNT(*) FROM growth_actions WHERE (? = '' OR domain = ?) GROUP BY status",
            (domain, domain),
        )
    }
    due = len(due_growth_actions(conn, domain=domain))
    return {"domain": domain, "counts": counts, "due_reviews": due}


def fetch_sitemap_urls(url: str) -> set[str]:
    """Fetch one sitemap (or sitemap index) and normalize its <loc> URLs."""
    import xml.etree.ElementTree as ET
    from urllib.request import Request, urlopen

    try:
        request = Request(url, headers={"User-Agent": "improve-seo-with-data/3.0"})
        with urlopen(request, timeout=20) as response:
            payload = response.read()
        root = ET.fromstring(payload)
    except Exception:  # noqa: BLE001 - unreachable sitemap is missing evidence
        return set()
    locs = {
        (element.text or "").strip()
        for element in root.iter()
        if element.tag.endswith("loc") and element.text
    }
    if not locs:
        return set()
    # A sitemap index points at family sitemaps, not pages. Follow one level
    # so the planner sees the real URL set instead of nine .xml files.
    if all(loc.endswith((".xml", ".xml.gz")) for loc in locs):
        pages: set[str] = set()
        for child in list(locs)[:20]:
            pages.update(fetch_sitemap_urls(child))
        return pages
    return {_normalize_page(loc) for loc in locs if loc}


def _read_json(path: str) -> Any:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _connect(db_path: str) -> sqlite3.Connection:
    from fleet_state import connect_state_db

    conn = connect_state_db(db_path)
    ensure_growth_schema(conn)
    return conn


def _cmd_plan(args: argparse.Namespace) -> int:
    rows: list[dict[str, Any]] = []
    if args.features and Path(args.features).exists():
        payload = _read_json(args.features)
        rows = payload.get("rows", []) if isinstance(payload, dict) else []
    queue: list[dict[str, Any]] = []
    if args.action_queue and Path(args.action_queue).exists():
        queue = _queue_rows(_read_json(args.action_queue))
    sitemap_urls: set[str] | None = None
    if args.keep_urls:
        try:
            sitemap_urls = {
                _normalize_page(str(url)) for url in _read_json(args.keep_urls)
            }
        except Exception:  # noqa: BLE001 - malformed keep file is missing evidence
            sitemap_urls = set()
    elif args.sitemap:
        sitemap_urls = fetch_sitemap_urls(args.sitemap)
    conn = _connect(args.state_db) if args.state_db else None
    try:
        plan = build_growth_plan(
            rows,
            domain=args.domain,
            queue=queue,
            conn=conn,
            limit=args.limit,
            cooldown_days=args.cooldown_days,
            sitemap_urls=sitemap_urls,
            now=_now(),
        )
        if args.record and conn is not None:
            inserted = record_growth_plan(conn, plan)
            plan["recorded"] = inserted
        output = args.output
        if output:
            Path(output).parent.mkdir(parents=True, exist_ok=True)
            Path(output).write_text(json.dumps(plan, indent=2), encoding="utf-8")
        print(json.dumps(plan, indent=2))
        return 0
    finally:
        if conn is not None:
            conn.close()


def _cmd_record(args: argparse.Namespace) -> int:
    conn = _connect(args.state_db)
    try:
        plan = _read_json(args.plan)
        inserted = record_growth_plan(conn, plan)
        print(f"Recorded {inserted} growth action(s).")
        return 0
    finally:
        conn.close()


def _cmd_complete(args: argparse.Namespace) -> int:
    conn = _connect(args.state_db)
    try:
        ok = complete_growth_action(
            conn,
            args.action_key,
            commit_sha=args.commit_sha,
            outcome=_read_json(args.outcome) if args.outcome else {},
            review_days=args.review_days,
        )
        print("SHIPPED" if ok else "NOT_OPEN")
        return 0 if ok else 2
    finally:
        conn.close()


def _cmd_review(args: argparse.Namespace) -> int:
    conn = _connect(args.state_db)
    try:
        observations = _read_json(args.observations) if args.observations else {}
        reviews = review_growth_actions(conn, observations, domain=args.domain)
        print(json.dumps(reviews, indent=2))
        return 0
    finally:
        conn.close()


def _cmd_status(args: argparse.Namespace) -> int:
    conn = _connect(args.state_db)
    try:
        print(json.dumps(growth_status(conn, domain=args.domain), indent=2))
        return 0
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--state-db", dest="state_db_global", default=None)
    sub = parser.add_subparsers(dest="command", required=True)

    plan = sub.add_parser("plan", help="emit the next non-empty action plan")
    plan.add_argument("--state-db", default=None)
    plan.add_argument("--features", default="data/ltr_features.json")
    plan.add_argument("--action-queue", default="data/action_queue.json")
    plan.add_argument("--domain", default="")
    plan.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    plan.add_argument("--cooldown-days", type=int, default=DEFAULT_COOLDOWN_DAYS)
    plan.add_argument(
        "--sitemap",
        default="",
        help="live sitemap URL; limits actions to URLs Google can actually see",
    )
    plan.add_argument(
        "--keep-urls",
        default="",
        help="JSON list of allowed URLs; overrides --sitemap for a curated footprint",
    )
    plan.add_argument("--output", default="data/growth_plan.json")
    plan.add_argument("--record", action="store_true")
    plan.set_defaults(func=_cmd_plan)

    record = sub.add_parser("record", help="persist an already-emitted plan")
    record.add_argument("--state-db", default=None)
    record.add_argument("--plan", required=True)
    record.set_defaults(func=_cmd_record)

    complete = sub.add_parser("complete", help="mark an open action SHIPPED")
    complete.add_argument("--state-db", default=None)
    complete.add_argument("action_key")
    complete.add_argument("--commit-sha", default="")
    complete.add_argument("--outcome", default="")
    complete.add_argument("--review-days", type=int, default=DEFAULT_REVIEW_DAYS)
    complete.set_defaults(func=_cmd_complete)

    review = sub.add_parser("review", help="compare due actions with observations")
    review.add_argument("--state-db", default=None)
    review.add_argument("--observations", required=True)
    review.add_argument("--domain", default="")
    review.set_defaults(func=_cmd_review)

    status = sub.add_parser("status", help="show action-ledger status")
    status.add_argument("--state-db", default=None)
    status.add_argument("--domain", default="")
    status.set_defaults(func=_cmd_status)

    args = parser.parse_args(argv)
    args.state_db = args.state_db or args.state_db_global or DEFAULT_STATE_DB
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
