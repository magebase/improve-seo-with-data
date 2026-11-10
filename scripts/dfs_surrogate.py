#!/usr/bin/env python3
"""dfs_surrogate.py - Offline predictor of the DataForSEO SERP columns.

Given ONLY a candidate keyword string (zero API calls), predicts the four
external columns the LTR feature matrix consumes:

    search_volume_log, serp_forum_ratio, title_exact_match_rate,
    serp_pixel_crowding

Trained on every cached DataForSEO payload the fleet has ever fetched
(`.serp_cache.json` + the SQLite `dfs_serp_cache` table), so 20-30 daily
skill invocations score thousands of unseen keyword/entity combinations
offline in milliseconds instead of paying for (and waiting on) a queue sweep
per run. A daily uncertainty-sampling budget feeds a handful of REAL SERP
pulls back into the cache; refitting keeps the surrogate honest.

Implementation notes:
- LightGBM ONLY (no sklearn/joblib): four independent LGBMRegressor models,
  one per target — same capacity as MultiOutputRegressor without the dep.
- Lexical features are pure-Python: hashed char_wb n-grams (2-4) plus
  structural intent flags (comparison/tool/how-to/number tokens).
- Refuses to fit below SURROGATE_MIN_ROWS (guessing from <20 rows would
  poison the feature matrix).
"""

from __future__ import annotations

import json
import math
import os
import re
import hashlib
from typing import Any, Dict, List, Optional

import numpy as np

SURROGATE_MIN_ROWS = 20
MODEL_PREFIX = "dfs_surrogate"
TARGETS = (
    "search_volume_log",
    "serp_forum_ratio",
    "title_exact_match_rate",
    "serp_pixel_crowding",
)
FEATURE_SOURCE = "local_surrogate"

_HASH_DIMS = 512
_CHAR_NGRAM_RANGE = (2, 4)

_INTENT_PATTERNS = {
    "comparison": re.compile(r"\b(vs|versus|compare|alternative)\b"),
    "how_to": re.compile(r"\b(how|what|why|can|fix|error)\b"),
    "tool_intent": re.compile(r"\b(free|online|tool|calculator|converter)\b"),
    "number_token": re.compile(r"(\d|\+\d+)"),
}


def _hash_vector(text: str, dims: int = _HASH_DIMS) -> List[float]:
    """Deterministic char_wb n-gram hashed counts (2-4 grams, padded words)."""
    vec = [0.0] * dims
    padded = f" {text.lower().strip()} "
    grams: List[str] = []
    for word in padded.split():
        for n in range(_CHAR_NGRAM_RANGE[0], _CHAR_NGRAM_RANGE[1] + 1):
            for i in range(max(0, len(word) - n + 1)):
                grams.append(word[i : i + n])
    for gram in grams:
        digest = hashlib.md5(gram.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "little") % dims
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vec[index] += sign
    return vec


def lexical_features(query: str) -> List[float]:
    """Structural intent flags + hashed char n-grams for one query string."""
    q = (query or "").lower().strip()
    tokens = q.split()
    struct = [
        float(len(tokens)),
        float(len(q)),
        1.0 if _INTENT_PATTERNS["comparison"].search(q) else 0.0,
        1.0 if _INTENT_PATTERNS["how_to"].search(q) else 0.0,
        1.0 if _INTENT_PATTERNS["tool_intent"].search(q) else 0.0,
        1.0 if _INTENT_PATTERNS["number_token"].search(q) else 0.0,
    ]
    return struct + _hash_vector(q)


class OfflineDataForSEOSurrogate:
    """Multi-output LightGBM surrogate over the cached DataForSEO history."""

    def __init__(self) -> None:
        import lightgbm as lgb

        self._lgb = lgb
        self.models: dict[str, Any] = {}
        self._fitted = False

    # ------------------------------------------------------------------ fit

    def fit(
        self, rows: List[Dict[str, Any]], models_dir: str = "models/"
    ) -> Dict[str, Any]:
        valid = [
            r
            for r in rows
            if all(r.get(t) is not None for t in TARGETS) and r.get("query")
        ]
        if len(valid) < SURROGATE_MIN_ROWS:
            raise RuntimeError(
                f"Only {len(valid)} surrogate training rows — below the "
                f"{SURROGATE_MIN_ROWS}-row floor. Collect more cached DataForSEO "
                "SERPs before refitting."
            )
        X = np.asarray([lexical_features(r["query"]) for r in valid], dtype="float64")
        meta: Dict[str, Any] = {"targets": list(TARGETS), "rows": len(valid)}
        os.makedirs(models_dir, exist_ok=True)
        # Native LightGBM API (the sklearn wrapper needs scikit-learn, which is
        # deliberately absent from this skill's dependency footprint).
        params = {
            "objective": "regression",
            "num_leaves": 15,
            "learning_rate": 0.05,
            "min_data_in_leaf": 10,
            "seed": 42,
            "verbose": -1,
        }
        for target in TARGETS:
            y = [float(r[target]) for r in valid]
            dataset = self._lgb.Dataset(X, label=y)
            booster = self._lgb.train(params, dataset, num_boost_round=120)
            model_path = os.path.join(models_dir, f"{MODEL_PREFIX}_{target}.txt")
            booster.save_model(model_path)
            meta[target] = model_path
        with open(
            os.path.join(models_dir, f"{MODEL_PREFIX}.meta.json"), "w", encoding="utf-8"
        ) as fh:
            json.dump(meta, fh, indent=2)
        self.models = {t: self._lgb.Booster(model_file=meta[t]) for t in TARGETS}
        self._fitted = True
        return meta

    def load(self, models_dir: str = "models/") -> bool:
        meta_path = os.path.join(models_dir, f"{MODEL_PREFIX}.meta.json")
        if not os.path.exists(meta_path):
            return False
        with open(meta_path, encoding="utf-8") as fh:
            meta = json.load(fh)
        self.models = {t: self._lgb.Booster(model_file=meta[t]) for t in TARGETS}
        self._fitted = True
        return True

    # --------------------------------------------------------------- predict

    def predict_serp_features(self, queries: List[str]) -> List[Dict[str, Any]]:
        """Predicts the four DataForSEO columns offline (clipped to valid ranges)."""
        if not self._fitted:
            raise RuntimeError(
                "Surrogate not fitted/loaded; call fit() or load() first."
            )
        X = np.asarray([lexical_features(q) for q in queries], dtype="float64")
        out: List[Dict[str, Any]] = []
        for i, query in enumerate(queries):
            preds = {t: float(self.models[t].predict(X[i : i + 1])[0]) for t in TARGETS}
            out.append(
                {
                    "query": query,
                    "search_volume_log": round(
                        min(5.0, max(0.5, preds["search_volume_log"])), 6
                    ),
                    "serp_forum_ratio": round(
                        min(1.0, max(0.0, preds["serp_forum_ratio"])), 6
                    ),
                    "title_exact_match_rate": round(
                        min(1.0, max(0.0, preds["title_exact_match_rate"])), 6
                    ),
                    "serp_pixel_crowding": round(
                        min(6.0, max(0.0, preds["serp_pixel_crowding"])), 6
                    ),
                    "feature_source": FEATURE_SOURCE,
                }
            )
        return out


def rows_from_serp_cache(cache: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Extracts surrogate training rows from a .serp_cache.json-shaped payload.

    Volume is only present in keyword-info blocks (suggestions), so SERP-only
    cache entries train the three SERP targets with volume=None (filtered by
    fit()'s completeness check).
    """
    from dataforseo_client import extract_serp_features

    rows: List[Dict[str, Any]] = []
    for query, payload in cache.items():
        items = payload.get("items") if isinstance(payload, dict) else payload
        if not items:
            continue
        feats = extract_serp_features(items)
        volume = None
        for item in items:
            if item.get("type") == "keyword_info" or "keyword_volume" in item:
                volume = (
                    float(item.get("keyword_volume") or item.get("vol") or 0) or None
                )
                break
        rows.append(
            {
                "query": query,
                "search_volume_log": math.log10(volume + 1) if volume else None,
                "serp_forum_ratio": feats.get("serp_forum_ratio"),
                "title_exact_match_rate": feats.get("title_exact_match_rate"),
                "serp_pixel_crowding": feats.get("serp_pixel_crowding"),
            }
        )
    return rows
