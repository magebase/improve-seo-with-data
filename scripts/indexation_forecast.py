#!/usr/bin/env python3
"""Indexation forecasting and evidence-gated programmatic page launches.

The historical skill flow treated ``current_pos >= 90`` as proof that a new
route should exist. That is a demand *absence* signal, not a demand signal:
the old waterfall filled the candidate pool with synthetic pairwise routes at
``current_pos=100`` and ``impressions=0``, then compiled them into
``CREATE_PROGRAMMATIC_ROUTE`` tasks. Google crawled those pages and declined
to index them.

This module replaces the positional guess with two evidence layers:

1. A calibrated indexation model trained on historical launch outcomes
   (URL Inspection coverage state + GSC).  It predicts the probability that a
   candidate is indexed within 28 and 56 days.
2. A hard launch gate that requires real demand, live data depth, sibling
   uniqueness, and internal-link equity before a new route can be emitted.

No page-count cap is applied.  Every candidate that clears the gate is
eligible; candidates that do not clear it are not replaced with synthetic
filler.

Dependencies: numpy only (already in the skill environment).  The model is a
small L2-regularised logistic regression trained with IRLS, persisted as JSON
so it is portable and inspectable.  A transparent prior is used until enough
labelled outcomes exist.
"""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from collections.abc import Iterable

import numpy as np

MODEL_PATH = "models/indexation_forecast.json"

# Order is load-bearing: persisted models store coefficients in this order.
FEATURE_NAMES = [
    "search_volume_log",
    "impressions_log",
    "position_strength",
    "template_index_rate",
    "unique_data_fields",
    "sibling_similarity",
    "inlinks_from_indexed",
    "freshness_days_log",
    "serp_forum_ratio",
    "title_exact_match_rate",
    "has_existing_owner",
    "page_age_days_log",
    "horizon_days_norm",
]

# Transparent cold-start prior.  It is deliberately conservative on pages
# without demand, data, links, or uniqueness.  Once >= MIN_TRAINING_ROWS
# labelled outcomes exist, ``fit`` replaces these coefficients with the
# empirical model.
PRIOR_INTERCEPT = -4.0
PRIOR_COEFFICIENTS = np.array(
    [
        0.70,  # search_volume_log: DataForSEO demand is the primary cold signal
        0.50,  # impressions_log
        0.50,  # position_strength
        2.00,  # template_index_rate
        0.50,  # unique_data_fields
        -2.50,  # sibling_similarity
        0.40,  # inlinks_from_indexed
        0.10,  # freshness_days_log
        0.30,  # serp_forum_ratio
        -0.20,  # title_exact_match_rate
        -2.00,  # has_existing_owner
        0.10,  # page_age_days_log
        0.20,  # horizon_days_norm
    ],
    dtype=float,
)

MIN_TRAINING_ROWS = 20
MIN_POSITIVES = 3
MIN_NEGATIVES = 3
DEFAULT_PROB_28D = 0.80
DEFAULT_LOWER_28D = 0.70
DEFAULT_PROB_56D = 0.85
DEFAULT_LOWER_56D = 0.70
DEFAULT_MAX_SIBLING_SIMILARITY = 0.50
DEFAULT_MIN_INLINKS = 3
DEFAULT_MIN_DATA_FIELDS = 3
DEFAULT_MIN_IMPRESSIONS = 10.0


def _sigmoid(z: float | np.ndarray) -> float | np.ndarray:
    z_arr = np.asarray(z, dtype=float)
    out = np.empty_like(z_arr)
    positive = z_arr >= 0
    out[positive] = 1.0 / (1.0 + np.exp(-z_arr[positive]))
    exp_z = np.exp(z_arr[~positive])
    out[~positive] = exp_z / (1.0 + exp_z)
    return float(out) if out.ndim == 0 else out


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _first(mapping: dict[str, Any], keys: Iterable[str], default: Any = None) -> Any:
    for key in keys:
        if key in mapping and mapping[key] is not None:
            return mapping[key]
    return default


def _nested_value(row: dict[str, Any], keys: Iterable[str], default: Any = None) -> Any:
    features = row.get("features") or {}
    if not isinstance(features, dict):
        features = {}
    value = _first(row, keys, None)
    if value is None:
        value = _first(features, keys, None)
    return default if value is None else value


def ranking_potential(row: dict[str, Any]) -> dict[str, Any] | None:
    """Winnability estimate, only when SERP evidence actually exists.

    This is deliberately separate from P(indexed): a page can be indexable and
    still belong to a SERP dominated by authoritative docs.  Missing SERP
    features return ``None`` rather than a fabricated score.
    """
    features = extract_launch_features(row)
    if features["serp_fetched"] <= 0.0:
        return None
    forum = features["serp_forum_ratio"]
    title_gap = 1.0 - features["title_exact_match_rate"]
    crowding = _as_float(_nested_value(row, ["serp_pixel_crowding"], 0.0), 0.0)
    topical = _as_float(_nested_value(row, ["domain_centroid_sim"], 0.0), 0.0)
    volume = features["search_volume_log"]
    score = (
        35.0 * forum
        + 30.0 * title_gap
        + 15.0 * max(0.0, min(1.0, topical))
        + 10.0 * min(1.0, volume / 4.0)
        - 20.0 * max(0.0, min(1.0, crowding))
    )
    score = max(0.0, min(100.0, score))
    return {
        "score": round(score, 1),
        "label": "strong" if score >= 60 else ("moderate" if score >= 40 else "weak"),
        "components": {
            "forum_ratio": round(forum, 4),
            "title_gap": round(title_gap, 4),
            "topical_fit": round(topical, 4),
            "crowding": round(crowding, 4),
            "search_volume_log": round(volume, 4),
        },
    }


def candidate_kind(row: dict[str, Any]) -> str:
    explicit = str(_nested_value(row, ["candidate_kind"], "")).strip().lower()
    if explicit in {"new_route", "existing_page"}:
        return explicit
    if _nested_value(row, ["page_exists", "is_existing_page"], False):
        return "existing_page"
    if str(_nested_value(row, ["coverage_state"], "")).strip():
        return "existing_page"
    return "new_route"


def extract_launch_features(row: dict[str, Any]) -> dict[str, float]:
    """Extract the forecast vector from a scored candidate row.

    Missing evidence is represented honestly as the pessimistic value rather
    than silently imputed upward: missing similarity becomes 1.0 (maximally
    duplicate), missing inlinks becomes 0, and missing data depth becomes 0.
    """
    kind = candidate_kind(row)
    impressions = _as_float(
        _nested_value(row, ["impressions", "total_page_impressions"], 0.0)
    )
    position = _as_float(_nested_value(row, ["current_pos", "position"], 100.0), 100.0)

    search_volume_log = _as_float(_nested_value(row, ["search_volume_log"], 0.0), 0.0)
    if search_volume_log <= 0.0:
        volume = _as_float(_nested_value(row, ["search_volume"], 0.0), 0.0)
        search_volume_log = math.log1p(max(0.0, volume))

    template_index_rate = _as_float(
        _nested_value(row, ["template_index_rate", "family_index_rate"], 0.5), 0.5
    )
    unique_data_fields = _as_float(
        _nested_value(
            row, ["unique_data_fields", "data_fields", "live_data_fields"], 0.0
        ),
        0.0,
    )
    sibling_similarity = _as_float(
        _nested_value(row, ["sibling_similarity", "content_similarity"], 1.0), 1.0
    )
    planned_inlinks = _as_float(
        _nested_value(row, ["planned_indexed_inlinks"], 0.0), 0.0
    )
    live_inlinks = _as_float(
        _nested_value(
            row,
            ["inlinks_from_indexed", "indexed_inlinks", "parent_hub_internal_links"],
            0.0,
        ),
        0.0,
    )
    inlinks = planned_inlinks if kind == "new_route" else live_inlinks
    freshness_days = _as_float(
        _nested_value(row, ["freshness_days", "data_age_days"], 365.0), 365.0
    )
    forum_ratio = _as_float(_nested_value(row, ["serp_forum_ratio"], 0.0), 0.0)
    title_match = _as_float(_nested_value(row, ["title_exact_match_rate"], 1.0), 1.0)
    existing_owner = (
        1.0
        if _nested_value(row, ["has_existing_owner", "existing_owner"], False)
        else 0.0
    )
    page_age_days = _as_float(
        _nested_value(row, ["page_age_days", "age_days"], 0.0), 0.0
    )
    serp_item_types = _nested_value(row, ["serp_item_types"], []) or []
    serp_fetched = bool(_nested_value(row, ["serp_fetched"], False)) or bool(
        serp_item_types
    )
    intent_match = _nested_value(row, ["intent_match"], None)
    non_boilerplate = _as_float(_nested_value(row, ["non_boilerplate_ratio"], 0.0), 0.0)

    return {
        "search_volume_log": max(0.0, search_volume_log),
        "impressions_log": math.log1p(max(0.0, impressions)),
        "position_strength": max(0.0, min(1.0, 1.0 - (max(0.0, position) / 100.0))),
        "template_index_rate": max(0.0, min(1.0, template_index_rate)),
        "unique_data_fields": max(0.0, unique_data_fields),
        "sibling_similarity": max(0.0, min(1.0, sibling_similarity)),
        "inlinks_from_indexed": max(0.0, inlinks),
        "freshness_days_log": math.log1p(max(0.0, freshness_days)),
        "serp_forum_ratio": max(0.0, min(1.0, forum_ratio)),
        "title_exact_match_rate": max(0.0, min(1.0, title_match)),
        "has_existing_owner": existing_owner,
        "page_age_days_log": math.log1p(max(0.0, page_age_days)),
        # Evidence-presence flags (not model coefficients).
        "serp_fetched": 1.0 if serp_fetched else 0.0,
        "intent_match": 1.0 if intent_match is True else 0.0,
        "intent_evidence": 1.0 if intent_match is not None else 0.0,
        "planned_indexed_inlinks": max(0.0, planned_inlinks),
        "non_boilerplate_ratio": max(0.0, min(1.0, non_boilerplate)),
        "candidate_kind": 1.0 if kind == "existing_page" else 0.0,
    }


def vectorize_features(
    features: dict[str, float], horizon_days: int = 28
) -> np.ndarray:
    horizon_norm = max(0.0, min(1.0, float(horizon_days) / 56.0))
    return np.array(
        [float(features.get(name, 0.0)) for name in FEATURE_NAMES[:-1]]
        + [horizon_norm],
        dtype=float,
    )


def _auc(y_true: np.ndarray, scores: np.ndarray) -> float:
    """Rank-based ROC AUC; ties get the average rank."""
    positives = y_true == 1
    negatives = y_true == 0
    n_pos = int(positives.sum())
    n_neg = int(negatives.sum())
    if n_pos == 0 or n_neg == 0:
        return float("nan")
    order = np.argsort(scores, kind="mergesort")
    ranks = np.empty_like(order, dtype=float)
    ranks[order] = np.arange(1, len(scores) + 1, dtype=float)
    # Average ranks for ties.
    sorted_scores = scores[order]
    start = 0
    for index in range(1, len(sorted_scores) + 1):
        if index == len(sorted_scores) or sorted_scores[index] != sorted_scores[start]:
            if index - start > 1:
                ranks[order[start:index]] = np.mean(ranks[order[start:index]])
            start = index
    rank_sum_pos = float(ranks[positives].sum())
    return (rank_sum_pos - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg)


def _brier(y_true: np.ndarray, probabilities: np.ndarray) -> float:
    if len(y_true) == 0:
        return float("nan")
    return float(np.mean((probabilities - y_true) ** 2))


@dataclass
class LaunchDecision:
    eligible: bool
    p_index_28d: float
    p_index_56d: float
    lower_28d: float
    lower_56d: float
    features: dict[str, float] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)
    status: str = "eligible"
    missing_features: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "eligible": self.eligible,
            "status": self.status,
            "missing_features": list(self.missing_features),
            "p_index_28d": round(self.p_index_28d, 4),
            "p_index_56d": round(self.p_index_56d, 4),
            "lower_28d": round(self.lower_28d, 4),
            "lower_56d": round(self.lower_56d, 4),
            "features": {key: round(value, 4) for key, value in self.features.items()},
            "reasons": list(self.reasons),
            "evidence": dict(self.evidence),
        }


class IndexationModel:
    """Small, inspectable logistic indexation model with a cold-start prior."""

    def __init__(
        self,
        coefficients: np.ndarray | None = None,
        intercept: float = PRIOR_INTERCEPT,
        mean: np.ndarray | None = None,
        std: np.ndarray | None = None,
        covariance: np.ndarray | None = None,
        n_train: int = 0,
        fitted: bool = False,
    ) -> None:
        self.coefficients = (
            PRIOR_COEFFICIENTS.copy()
            if coefficients is None
            else np.asarray(coefficients, dtype=float)
        )
        self.intercept = float(intercept)
        self.mean = (
            np.zeros(len(FEATURE_NAMES))
            if mean is None
            else np.asarray(mean, dtype=float)
        )
        self.std = (
            np.ones(len(FEATURE_NAMES)) if std is None else np.asarray(std, dtype=float)
        )
        # The cold-start prior is a deliberate point estimate, not a noisy
        # sample: keep its 80% band tight enough to be useful while the first
        # real outcomes are collected. Fitted models replace this with the
        # inverse Hessian from the training data.
        self.covariance = (
            np.eye(len(FEATURE_NAMES)) * 0.0025
            if covariance is None
            else np.asarray(covariance, dtype=float)
        )
        self.n_train = int(n_train)
        self.fitted = bool(fitted)

    @staticmethod
    def _standardize(x: np.ndarray, mean: np.ndarray, std: np.ndarray) -> np.ndarray:
        safe_std = np.where(std < 1e-9, 1.0, std)
        return (x - mean) / safe_std

    def _logit(
        self, features: dict[str, float], horizon_days: int
    ) -> tuple[float, float]:
        x = vectorize_features(features, horizon_days)
        z = self._standardize(x.reshape(1, -1), self.mean, self.std)[0]
        logit = float(self.intercept + np.dot(self.coefficients, z))
        variance = float(z @ self.covariance @ z)
        se = math.sqrt(max(0.0, variance))
        return logit, se

    def predict(
        self, features: dict[str, float], horizon_days: int = 28
    ) -> dict[str, float]:
        logit, se = self._logit(features, horizon_days)
        probability = float(_sigmoid(logit))
        lower = float(_sigmoid(logit - 1.2816 * se))  # 80% one-sided lower bound
        upper = float(_sigmoid(logit + 1.2816 * se))
        return {
            "probability": probability,
            "lower": lower,
            "upper": upper,
            "logit": logit,
            "std_error": se,
        }

    def fit(
        self,
        records: list[dict[str, Any]],
        l2: float = 1.0,
        max_iterations: int = 80,
    ) -> IndexationModel:
        """Fit by IRLS on records with ``features`` / ``label`` / ``horizon_days``."""
        rows: list[np.ndarray] = []
        labels: list[float] = []
        for record in records:
            label = record.get("label")
            if label is None:
                continue
            features = record.get("features")
            if not isinstance(features, dict):
                continue
            horizon = int(record.get("horizon_days") or 28)
            rows.append(vectorize_features(features, horizon))
            labels.append(1.0 if int(label) == 1 else 0.0)

        y = np.asarray(labels, dtype=float)
        n_pos = int((y == 1).sum())
        n_neg = int((y == 0).sum())
        if len(y) < MIN_TRAINING_ROWS or n_pos < MIN_POSITIVES or n_neg < MIN_NEGATIVES:
            # Not enough evidence to beat the transparent prior.  Stay on the
            # prior rather than overfitting four positives.
            return self

        x = np.asarray(rows, dtype=float)
        self.mean = x.mean(axis=0)
        self.std = x.std(axis=0)
        self.std = np.where(self.std < 1e-9, 1.0, self.std)
        x_std = self._standardize(x, self.mean, self.std)
        design = np.column_stack([np.ones(len(x_std)), x_std])
        beta = np.zeros(design.shape[1], dtype=float)

        penalty = np.eye(design.shape[1], dtype=float) * float(l2)
        penalty[0, 0] = 1e-9  # do not penalise the intercept
        for _ in range(max_iterations):
            eta = design @ beta
            p = np.clip(_sigmoid(eta), 1e-9, 1.0 - 1e-9)
            weights = p * (1.0 - p)
            gradient = design.T @ (y - p) - penalty @ beta
            hessian = design.T @ (design * weights[:, None]) + penalty
            try:
                step = np.linalg.solve(hessian, gradient)
            except np.linalg.LinAlgError:
                step = np.linalg.pinv(hessian) @ gradient
            beta += step
            if float(np.max(np.abs(step))) < 1e-8:
                break

        self.intercept = float(beta[0])
        self.coefficients = beta[1:]
        self.n_train = len(y)
        self.fitted = True
        # Approximate coefficient covariance at the solution for uncertainty.
        eta = design @ beta
        p = np.clip(_sigmoid(eta), 1e-9, 1.0 - 1e-9)
        weights = p * (1.0 - p)
        hessian = design.T @ (design * weights[:, None]) + penalty
        try:
            covariance = np.linalg.inv(hessian)[1:, 1:]
        except np.linalg.LinAlgError:
            covariance = np.eye(len(self.coefficients)) * 0.25
        self.covariance = covariance
        return self

    def to_dict(self) -> dict[str, Any]:
        return {
            "feature_names": FEATURE_NAMES,
            "coefficients": self.coefficients.tolist(),
            "intercept": self.intercept,
            "mean": self.mean.tolist(),
            "std": self.std.tolist(),
            "covariance": self.covariance.tolist(),
            "n_train": self.n_train,
            "fitted": self.fitted,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> IndexationModel:
        return cls(
            coefficients=np.asarray(
                payload.get("coefficients", PRIOR_COEFFICIENTS), dtype=float
            ),
            intercept=float(payload.get("intercept", PRIOR_INTERCEPT)),
            mean=np.asarray(
                payload.get("mean", np.zeros(len(FEATURE_NAMES))), dtype=float
            ),
            std=np.asarray(
                payload.get("std", np.ones(len(FEATURE_NAMES))), dtype=float
            ),
            covariance=np.asarray(
                payload.get("covariance", np.eye(len(FEATURE_NAMES)) * 0.0025),
                dtype=float,
            ),
            n_train=int(payload.get("n_train", 0)),
            fitted=bool(payload.get("fitted", False)),
        )

    def save(self, path: str | Path = MODEL_PATH) -> Path:
        destination = Path(path).expanduser()
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")
        return destination

    @classmethod
    def load(cls, path: str | Path = MODEL_PATH) -> IndexationModel:
        source = Path(path).expanduser()
        if not source.exists():
            return cls()
        return cls.from_dict(json.loads(source.read_text(encoding="utf-8")))


def evaluate_launch_candidate(
    row: dict[str, Any],
    model: IndexationModel | None = None,
    *,
    prob_28d: float = DEFAULT_PROB_28D,
    lower_28d: float = DEFAULT_LOWER_28D,
    prob_56d: float = DEFAULT_PROB_56D,
    lower_56d: float = DEFAULT_LOWER_56D,
    max_sibling_similarity: float = DEFAULT_MAX_SIBLING_SIMILARITY,
    min_inlinks: float = DEFAULT_MIN_INLINKS,
    min_data_fields: float = DEFAULT_MIN_DATA_FIELDS,
    min_impressions: float = DEFAULT_MIN_IMPRESSIONS,
    min_non_boilerplate_ratio: float = 0.50,
) -> LaunchDecision:
    """Decide whether a candidate deserves a new indexable URL.

    The gate is intentionally evidence-first.  Missing SERP, volume, data
    payload, intent, or planned links produces ``unscored_missing_serp`` /
    ``rejected_missing_evidence`` and no probability is reported.  A missing
    signal is never silently imputed into a high score.
    """
    model = model or IndexationModel()
    features = extract_launch_features(row)
    kind = candidate_kind(row)
    impressions = _as_float(
        _nested_value(row, ["impressions", "total_page_impressions"], 0.0)
    )
    volume_log = features["search_volume_log"]
    serp_fetched = features["serp_fetched"] > 0.0
    intent_evidence = features["intent_evidence"] > 0.0
    intent_match = features["intent_match"] > 0.0
    planned_inlinks = features["planned_indexed_inlinks"]

    reasons: list[str] = []
    missing: list[str] = []

    if kind == "existing_page":
        reasons.append("existing_page_requires_enrichment")
        return LaunchDecision(
            eligible=False,
            p_index_28d=0.0,
            p_index_56d=0.0,
            lower_28d=0.0,
            lower_56d=0.0,
            features=features,
            reasons=reasons,
            evidence={"candidate_kind": kind},
            status="existing_page_requires_enrichment",
            missing_features=[],
        )

    if not serp_fetched:
        missing.append("serp_features")
    if volume_log <= 0.0 and impressions < min_impressions:
        missing.append("search_volume")
    if not intent_evidence:
        missing.append("intent_match")
    elif not intent_match:
        reasons.append("intent_mismatch")
    if planned_inlinks < min_inlinks:
        missing.append("planned_indexed_inlinks")
    if features["non_boilerplate_ratio"] < min_non_boilerplate_ratio:
        missing.append("non_boilerplate_ratio")
    if features["sibling_similarity"] > max_sibling_similarity:
        reasons.append("sibling_similarity_too_high")
    required_fields = _as_float(
        _nested_value(
            row, ["required_data_fields", "required_live_records"], min_data_fields
        ),
        min_data_fields,
    )
    if features["unique_data_fields"] < max(min_data_fields, required_fields):
        missing.append("unique_data_fields")
    if features["has_existing_owner"] > 0.0:
        reasons.append("query_owned_by_existing_page")

    if missing:
        reasons = missing + reasons
        status = (
            "unscored_missing_serp"
            if "serp_features" in missing
            else "rejected_missing_evidence"
        )
        return LaunchDecision(
            eligible=False,
            p_index_28d=0.0,
            p_index_56d=0.0,
            lower_28d=0.0,
            lower_56d=0.0,
            features=features,
            reasons=reasons,
            evidence={
                "candidate_kind": kind,
                "impressions": impressions,
                "search_volume_log": round(volume_log, 4),
                "serp_fetched": serp_fetched,
                "intent_match": intent_match,
                "planned_indexed_inlinks": planned_inlinks,
                "unique_data_fields": round(features["unique_data_fields"], 4),
                "sibling_similarity": round(features["sibling_similarity"], 4),
                "non_boilerplate_ratio": round(features["non_boilerplate_ratio"], 4),
            },
            status=status,
            missing_features=missing,
        )

    p28 = model.predict(features, horizon_days=28)
    p56 = model.predict(features, horizon_days=56)

    if p28["probability"] < prob_28d or p28["lower"] < lower_28d:
        reasons.append("p_index_28d_below_floor")
    if p56["probability"] < prob_56d or p56["lower"] < lower_56d:
        reasons.append("p_index_56d_below_floor")

    evidence = {
        "candidate_kind": kind,
        "impressions": impressions,
        "search_volume_log": round(volume_log, 4),
        "serp_fetched": serp_fetched,
        "intent_match": intent_match,
        "required_data_fields": max(min_data_fields, required_fields),
        "unique_data_fields": round(features["unique_data_fields"], 4),
        "sibling_similarity": round(features["sibling_similarity"], 4),
        "inlinks_from_indexed": round(features["inlinks_from_indexed"], 4),
        "planned_indexed_inlinks": planned_inlinks,
        "non_boilerplate_ratio": round(features["non_boilerplate_ratio"], 4),
        "has_existing_owner": bool(features["has_existing_owner"]),
        "demand_source": "keywords_data"
        if volume_log > 0
        else ("gsc_impressions" if impressions >= min_impressions else "none"),
        "ranking_potential": ranking_potential(row),
    }

    return LaunchDecision(
        eligible=not reasons,
        p_index_28d=float(p28["probability"]),
        p_index_56d=float(p56["probability"]),
        lower_28d=float(p28["lower"]),
        lower_56d=float(p56["lower"]),
        features=features,
        reasons=reasons,
        evidence=evidence,
        status="eligible" if not reasons else "rejected_probability",
        missing_features=[],
    )


CANARY_MIN_SIZE = 10
CANARY_MAX_SIZE = 20
CANARY_MIN_INDEXED_RATE = 0.80
CANARY_MIN_IMPRESSIONS = 1.0


def _template_family(page: str) -> str:
    path = str(page).split("://", 1)[-1].split("?", 1)[0]
    parts = [part for part in path.split("/") if part]
    return parts[1] if len(parts) > 2 else (parts[0] if parts else "root")


def build_canary_cohort(
    rows: list[dict[str, Any]],
    *,
    size: int = CANARY_MAX_SIZE,
    model: IndexationModel | None = None,
    max_per_family: int = 5,
) -> list[dict[str, Any]]:
    """Select a small, evidence-qualified, family-diverse canary cohort.

    The cohort is the empirical proof step: never scale a template until its
    canary URLs are actually indexed.  Every member carries its gate decision
    so the ledger can compare forecast with outcome later.
    """
    size = max(0, min(int(size), CANARY_MAX_SIZE))
    if size < CANARY_MIN_SIZE:
        return []
    eligible: list[tuple[dict[str, Any], LaunchDecision]] = []
    for row in rows:
        decision = evaluate_launch_candidate(row, model=model)
        if decision.eligible:
            eligible.append((row, decision))
    by_family: dict[str, list[tuple[dict[str, Any], LaunchDecision]]] = {}
    for row, decision in eligible:
        by_family.setdefault(_template_family(row.get("page", "")), []).append(
            (row, decision)
        )
    selected: list[dict[str, Any]] = []
    while len(selected) < size and any(by_family.values()):
        for family in list(by_family):
            bucket = by_family[family]
            if not bucket:
                del by_family[family]
                continue
            if (
                sum(1 for item in selected if item["template_family"] == family)
                >= max_per_family
            ):
                by_family.pop(family, None)
                continue
            row, decision = bucket.pop(0)
            selected.append(
                {
                    **row,
                    "template_family": family,
                    "canary": True,
                    "p_index_28d": round(decision.p_index_28d, 4),
                    "p_index_56d": round(decision.p_index_56d, 4),
                    "launch_evidence": decision.evidence,
                }
            )
            if len(selected) >= size:
                break
    return selected


def evaluate_canary_outcomes(
    outcomes: list[dict[str, Any]],
    *,
    min_indexed_rate: float = CANARY_MIN_INDEXED_RATE,
    min_impressions: float = CANARY_MIN_IMPRESSIONS,
) -> dict[str, Any]:
    """Scaling gate for a canary cohort.

    ``coverage_state`` is the GSC URL Inspection verdict.  A cohort only earns
    template-level scale-up when enough URLs are indexed *and* the cohort has
    non-zero impressions; otherwise the template is rejected or pruned.
    """
    total = len(outcomes)
    indexed = sum(
        1
        for outcome in outcomes
        if "submitted and indexed" in str(outcome.get("coverage_state", "")).lower()
    )
    impressions = sum(float(outcome.get("impressions") or 0.0) for outcome in outcomes)
    rate = indexed / total if total else 0.0
    reasons: list[str] = []
    if total < CANARY_MIN_SIZE:
        reasons.append("cohort_too_small")
    if rate < min_indexed_rate:
        reasons.append("indexed_rate_below_floor")
    if impressions < min_impressions:
        reasons.append("no_impressions")
    return {
        "total": total,
        "indexed": indexed,
        "indexed_rate": round(rate, 4),
        "impressions": round(impressions, 4),
        "scale_allowed": not reasons,
        "reasons": reasons,
    }


def canary_sitemap(urls: list[str], *, base_url: str = "") -> str:
    """Dedicated sitemap so a canary cohort is isolated from bulk sitemaps."""
    rows = []
    for url in urls:
        target = (
            url
            if url.startswith("http")
            else f"{base_url.rstrip('/')}/{url.lstrip('/')}"
        )
        rows.append(f"  <url><loc>{target}</loc></url>")
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "\n".join(rows)
        + "\n</urlset>\n"
    )


def _parse_timestamp(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def sync_outcomes_from_inspections(conn: sqlite3.Connection) -> int:
    """Copy URL Inspection coverage states into the launch ledger.

    This is the bridge between the crawler evidence already cached by
    ``collect_features.inspect_coverage_states`` and the model labels.  It
    never invents a crawl time: the inspection timestamp is used as the
    observed indexed/crawled time only when Google reports a positive state.
    """
    updated = 0
    rows = conn.execute(
        "SELECT url, coverage_state, last_crawl_time, inspected_at FROM url_inspections"
    ).fetchall()
    for url, coverage_state, last_crawl_time, inspected_at in rows:
        coverage = str(coverage_state or "")
        indexed_at = (
            inspected_at if "submitted and indexed" in coverage.lower() else None
        )
        cursor = conn.execute(
            """
            UPDATE page_launch_outcomes
            SET coverage_state = ?,
                first_crawled_at = COALESCE(first_crawled_at, ?),
                indexed_at = COALESCE(indexed_at, ?),
                updated_at = ?
            WHERE url = ?
            """,
            (
                coverage_state,
                last_crawl_time,
                indexed_at,
                datetime.now(timezone.utc).isoformat(),
                url,
            ),
        )
        updated += max(0, int(cursor.rowcount or 0))
    conn.commit()
    return updated


def labels_from_outcomes(
    conn: sqlite3.Connection,
    domain: str | None = None,
) -> list[dict[str, Any]]:
    """Build 28/56-day labelled records from the launch outcome ledger.

    A launch is positive at a horizon when ``indexed_at`` is on or before the
    horizon.  It is negative only after the horizon has elapsed without an
    index.  Recent unresolved launches are censored and excluded.
    """
    query = "SELECT * FROM page_launch_outcomes"
    params: tuple[Any, ...] = ()
    if domain:
        query += " WHERE domain = ?"
        params = (domain,)
    records: list[dict[str, Any]] = []
    now = datetime.now(timezone.utc)
    cursor = conn.execute(query, params)
    columns = [description[0] for description in cursor.description]
    for row in cursor.fetchall():
        payload = dict(zip(columns, row))
        launched = _parse_timestamp(payload.get("launched_at"))
        if launched is None:
            continue
        features = json.loads(payload.get("features_json") or "{}")
        indexed = _parse_timestamp(payload.get("indexed_at"))
        coverage = str(payload.get("coverage_state") or "").lower()
        for horizon in (28, 56):
            deadline = launched + timedelta(days=horizon)
            label: int | None = None
            if indexed is not None and indexed <= deadline:
                label = 1
            elif indexed is None and coverage and "submitted and indexed" in coverage:
                label = 1
            elif now >= deadline:
                if indexed is not None:
                    label = 0  # indexed after this horizon
                elif any(
                    marker in coverage
                    for marker in ("not indexed", "excluded", "error", "blocked")
                ):
                    label = 0
                # Unknown coverage after the deadline stays censored rather
                # than being guessed negative.
            if label is None:
                continue
            records.append(
                {
                    "domain": payload.get("domain"),
                    "url": payload.get("url"),
                    "template_family": payload.get("template_family"),
                    "launched_at": payload.get("launched_at"),
                    "horizon_days": horizon,
                    "label": label,
                    "features": features,
                }
            )
    return records


def record_launch_outcome(
    conn: sqlite3.Connection,
    *,
    domain: str,
    url: str,
    template_family: str,
    launched_at: str,
    features: dict[str, float],
    p_index_28d: float | None = None,
    p_index_56d: float | None = None,
    source: str = "programmatic_route",
) -> None:
    """Idempotently record a launch so future runs can learn from it."""
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """
        INSERT INTO page_launch_outcomes
            (domain, url, template_family, launched_at, features_json,
             p_index_28d, p_index_56d, source, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(domain, url) DO UPDATE SET
            template_family = excluded.template_family,
            launched_at = excluded.launched_at,
            features_json = excluded.features_json,
            p_index_28d = excluded.p_index_28d,
            p_index_56d = excluded.p_index_56d,
            source = excluded.source,
            updated_at = excluded.updated_at
        """,
        (
            domain,
            url,
            template_family,
            launched_at,
            json.dumps(features, sort_keys=True),
            p_index_28d,
            p_index_56d,
            source,
            now,
        ),
    )
    conn.commit()


def record_indexation_outcome(
    conn: sqlite3.Connection,
    *,
    domain: str,
    url: str,
    coverage_state: str,
    indexed_at: str | None = None,
    first_crawled_at: str | None = None,
) -> None:
    conn.execute(
        """
        UPDATE page_launch_outcomes
        SET coverage_state = ?, indexed_at = ?, first_crawled_at = ?, updated_at = ?
        WHERE domain = ? AND url = ?
        """,
        (
            coverage_state,
            indexed_at,
            first_crawled_at,
            datetime.now(timezone.utc).isoformat(),
            domain,
            url,
        ),
    )
    conn.commit()


def record_launches_from_tasks(
    conn: sqlite3.Connection,
    tasks: Iterable[dict[str, Any]],
    *,
    launched_at: str | None = None,
) -> int:
    """Persist eligible new-route tasks so their coverage can be learned from.

    This is intentionally limited to ``CREATE_PROGRAMMATIC_ROUTE`` tasks that
    already carry a forecast.  Existing-page edits do not need a launch row.
    """
    stamp = launched_at or datetime.now(timezone.utc).isoformat()
    recorded = 0
    for task in tasks:
        if str(task.get("action_code") or "").upper() != "CREATE_PROGRAMMATIC_ROUTE":
            continue
        features = task.get("launch_features")
        if not isinstance(features, dict):
            features = extract_launch_features(task)
        domain = str(task.get("domain") or "")
        page = str(task.get("page") or "")
        if not domain or not page:
            continue
        record_launch_outcome(
            conn,
            domain=domain,
            url=page,
            template_family=str(task.get("template_family") or "root"),
            launched_at=stamp,
            features=features,
            p_index_28d=task.get("p_index_28d"),
            p_index_56d=task.get("p_index_56d"),
            source=str(task.get("source") or "programmatic_route"),
        )
        recorded += 1
    return recorded


def fit_from_state_db(
    conn: sqlite3.Connection,
    *,
    domain: str | None = None,
    output_path: str | Path = MODEL_PATH,
) -> tuple[IndexationModel, dict[str, Any]]:
    synced = sync_outcomes_from_inspections(conn)
    records = labels_from_outcomes(conn, domain=domain)
    model = IndexationModel().fit(records)
    path = model.save(output_path)
    return model, {
        "records": len(records),
        "inspection_rows_synced": synced,
        "fitted": model.fitted,
        "n_train": model.n_train,
        "model_path": str(path),
    }


def backtest(
    records: list[dict[str, Any]],
    *,
    train_fraction: float = 0.70,
    threshold: float = DEFAULT_PROB_28D,
) -> dict[str, Any]:
    """Time-ordered holdout backtest of the indexation model.

    Records are sorted by ``launched_at`` when present so the test set is
    later than the train set.  Returns discrimination, calibration, and the
    precision of the launch gate at ``threshold``.
    """
    usable = [
        record
        for record in records
        if record.get("label") is not None and isinstance(record.get("features"), dict)
    ]
    if len(usable) < 10:
        return {
            "n": len(usable),
            "error": "need at least 10 labelled records",
        }
    usable.sort(key=lambda record: str(record.get("launched_at") or ""))
    split = max(1, min(len(usable) - 1, int(len(usable) * train_fraction)))
    train, test = usable[:split], usable[split:]
    model = IndexationModel().fit(train)
    y = np.array([int(record["label"]) for record in test], dtype=float)
    probabilities = np.array(
        [
            model.predict(record["features"], int(record.get("horizon_days") or 28))[
                "probability"
            ]
            for record in test
        ],
        dtype=float,
    )
    predicted = (probabilities >= threshold).astype(int)
    tp = int(((predicted == 1) & (y == 1)).sum())
    fp = int(((predicted == 1) & (y == 0)).sum())
    fn = int(((predicted == 0) & (y == 1)).sum())
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    return {
        "n": len(usable),
        "train_n": len(train),
        "test_n": len(test),
        "base_rate": round(float(y.mean()), 4) if len(y) else 0.0,
        "model_fitted": model.fitted,
        "auc": round(float(_auc(y, probabilities)), 4) if len(y) else 0.0,
        "brier": round(_brier(y, probabilities), 4) if len(y) else 0.0,
        "threshold": threshold,
        "precision": round(float(precision), 4),
        "recall": round(float(recall), 4),
        "tp": tp,
        "fp": fp,
        "fn": fn,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Train/backtest the indexation forecast and inspect a launch candidate."
    )
    parser.add_argument(
        "--state-db", help="SQLite fleet state DB with page_launch_outcomes"
    )
    parser.add_argument("--domain", help="Restrict training/backtest to one domain")
    parser.add_argument(
        "--fit", action="store_true", help="Fit and save the model from the state DB"
    )
    parser.add_argument("--model", default=MODEL_PATH, help="Model JSON path")
    parser.add_argument(
        "--backtest-json", help="JSON file of labelled records for a holdout backtest"
    )
    parser.add_argument(
        "--candidate-json", help="JSON object describing one candidate to evaluate"
    )
    args = parser.parse_args(argv)

    if args.fit:
        if not args.state_db:
            parser.error("--fit requires --state-db")
        from fleet_state import connect_state_db  # local import keeps CLI startup small

        conn = connect_state_db(args.state_db)
        try:
            model, report = fit_from_state_db(
                conn, domain=args.domain, output_path=args.model
            )
        finally:
            conn.close()
        print(json.dumps(report, indent=2))
        return 0

    if args.backtest_json:
        records = json.loads(Path(args.backtest_json).read_text(encoding="utf-8"))
        print(json.dumps(backtest(records), indent=2))
        return 0

    if args.candidate_json:
        candidate = json.loads(Path(args.candidate_json).read_text(encoding="utf-8"))
        model = IndexationModel.load(args.model)
        print(
            json.dumps(
                evaluate_launch_candidate(candidate, model=model).as_dict(), indent=2
            )
        )
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
