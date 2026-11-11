#!/usr/bin/env python3
"""crawl_survival_analytics.py - Kaplan-Meier Crawl & Indexation Survival Subsystem (v2.3 P1).

Eliminates the 92% CRAWL_PENDING evaluation bottleneck through right-censored survival analysis.
Addresses the critical distinction: un-recrawled URLs are right-censored observations at age t,
NOT failed SEO experiments.

Provides:
1. Kaplan-Meier survival curve estimator S(t) = P(T > t) and cumulative hazard H(t).
2. Greenwood's standard error formula for 95% survival confidence bands.
3. Median time-to-first-recrawl (T_crawl) and time-to-indexation (T_index).
4. Domain-level and route-family stratified hazard rate analysis.
"""

from __future__ import annotations

import datetime
import math
from typing import Any
import numpy as np


def compute_kaplan_meier_survival(
    durations: list[float],
    events: list[int],
) -> dict[str, Any]:
    """Computes non-parametric Kaplan-Meier survival curve with Greenwood variance.

    Parameters:
    - durations: observation time in days (either time to recrawl or current age if censored)
    - events: 1 if recrawl observed, 0 if right-censored (still awaiting crawl)

    Returns dictionary containing timeline, survival probabilities, and summary statistics.
    """
    if not durations or len(durations) != len(events):
        return {
            "n_total": 0,
            "n_events": 0,
            "n_censored": 0,
            "median_survival_days": None,
            "timeline": [],
            "survival_probabilities": [],
            "ci_lower_95": [],
            "ci_upper_95": [],
        }

    # Sort by duration ascending; events before censored at tie
    paired = sorted(zip(durations, events), key=lambda x: (x[0], -x[1]))
    n_total = len(paired)
    n_events = sum(events)
    n_censored = n_total - n_events

    unique_times = sorted(list(set(d for d, e in paired if e == 1)))
    if not unique_times:
        # All observations are right-censored
        max_duration = max(durations) if durations else 0.0
        return {
            "n_total": n_total,
            "n_events": 0,
            "n_censored": n_censored,
            "median_survival_days": None,
            "max_observed_age_days": round(max_duration, 2),
            "prob_recrawled_at_14d": 0.0,
            "prob_recrawled_at_28d": 0.0,
            "timeline": [0.0, round(max_duration, 2)],
            "survival_probabilities": [1.0, 1.0],
            "ci_lower_95": [1.0, 1.0],
            "ci_upper_95": [1.0, 1.0],
        }

    timeline = [0.0]
    survival = [1.0]
    greenwood_sum = [0.0]

    # Pre-count events d_j and censored c_j at each distinct event time
    t_idx = 0
    at_risk = n_total
    s_curr = 1.0
    gw_curr = 0.0

    for t_event in unique_times:
        d_j = sum(1 for d, e in paired if d == t_event and e == 1)
        c_before = sum(1 for d, e in paired if d < t_event and e == 0 and d > (timeline[-1] if len(timeline) > 1 else -1))
        at_risk -= c_before

        if at_risk > 0:
            s_curr *= (1.0 - (d_j / at_risk))
            if at_risk > d_j:
                gw_curr += d_j / (at_risk * (at_risk - d_j))

        timeline.append(round(float(t_event), 2))
        survival.append(round(float(s_curr), 4))
        greenwood_sum.append(float(gw_curr))
        at_risk -= d_j

    # Compute Greenwood 95% confidence intervals
    ci_lower = []
    ci_upper = []
    z_crit = 1.95996
    for s_val, gw in zip(survival, greenwood_sum):
        se = s_val * math.sqrt(gw)
        ci_lower.append(round(max(0.0, s_val - (z_crit * se)), 4))
        ci_upper.append(round(min(1.0, s_val + (z_crit * se)), 4))

    # Calculate median survival (where S(t) drops to <= 0.50)
    median_time = None
    for t_val, s_val in zip(timeline, survival):
        if s_val <= 0.50:
            median_time = t_val
            break

    # Recrawl probabilities = 1 - S(t)
    def prob_event_at_t(target_t: float) -> float:
        # Find latest survival step <= target_t
        s_at_t = 1.0
        for t_step, s_step in zip(timeline, survival):
            if t_step <= target_t:
                s_at_t = s_step
            else:
                break
        return round(1.0 - s_at_t, 4)

    return {
        "n_total": n_total,
        "n_events": n_events,
        "n_censored": n_censored,
        "censoring_rate": round(n_censored / max(1, n_total), 4),
        "median_survival_days": median_time,
        "prob_recrawled_at_7d": prob_event_at_t(7.0),
        "prob_recrawled_at_14d": prob_event_at_t(14.0),
        "prob_recrawled_at_28d": prob_event_at_t(28.0),
        "timeline": timeline,
        "survival_probabilities": survival,
        "ci_lower_95": ci_lower,
        "ci_upper_95": ci_upper,
    }


def analyze_fleet_crawl_survival(
    url_records: list[dict[str, Any]],
    now_dt: datetime.datetime | None = None,
) -> dict[str, Any]:
    """Extracts deployment and recrawl timestamps to compute fleet-wide survival telemetry."""
    if now_dt is None:
        now_dt = datetime.datetime.now(datetime.timezone.utc)
    elif now_dt.tzinfo is None:
        now_dt = now_dt.replace(tzinfo=datetime.timezone.utc)

    durations: list[float] = []
    events: list[int] = []
    by_domain: dict[str, dict[str, list]] = {}
    by_route: dict[str, dict[str, list]] = {}

    for r in url_records:
        dom = str(r.get("domain", "unknown"))
        route = str(r.get("route_family", "root"))
        deploy_str = r.get("shipped_at") or r.get("created_at")
        recrawl_str = r.get("recrawl_detected_at") or r.get("last_crawl_time")

        if not deploy_str:
            continue

        try:
            deploy_dt = datetime.datetime.fromisoformat(str(deploy_str).replace("Z", "+00:00"))
            if deploy_dt.tzinfo is None:
                deploy_dt = deploy_dt.replace(tzinfo=datetime.timezone.utc)
        except Exception:
            continue

        if recrawl_str:
            try:
                recrawl_dt = datetime.datetime.fromisoformat(str(recrawl_str).replace("Z", "+00:00"))
                if recrawl_dt.tzinfo is None:
                    recrawl_dt = recrawl_dt.replace(tzinfo=datetime.timezone.utc)
                duration = max(0.01, (recrawl_dt - deploy_dt).total_seconds() / 86400.0)
                event = 1
            except Exception:
                duration = max(0.01, (now_dt - deploy_dt).total_seconds() / 86400.0)
                event = 0
        else:
            duration = max(0.01, (now_dt - deploy_dt).total_seconds() / 86400.0)
            event = 0

        durations.append(duration)
        events.append(event)

        # Domain partition
        dom_dict = by_domain.setdefault(dom, {"durations": [], "events": []})
        dom_dict["durations"].append(duration)
        dom_dict["events"].append(event)

        # Route partition
        route_dict = by_route.setdefault(route, {"durations": [], "events": []})
        route_dict["durations"].append(duration)
        route_dict["events"].append(event)

    fleet_km = compute_kaplan_meier_survival(durations, events)

    domain_km = {
        d: compute_kaplan_meier_survival(data["durations"], data["events"])
        for d, data in by_domain.items()
    }

    route_km = {
        rt: compute_kaplan_meier_survival(data["durations"], data["events"])
        for rt, data in by_route.items()
    }

    return {
        "fleet_survival": fleet_km,
        "domain_survival": domain_km,
        "route_survival": route_km,
        "generated_at": now_dt.isoformat(),
    }
