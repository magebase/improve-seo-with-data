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
            if r.get("query") and any(r.get(t) is not None for t in TARGETS)
        ]
        if len(valid) < SURROGATE_MIN_ROWS:
            raise RuntimeError(
                f"Only {len(valid)} surrogate training rows — below the "
                f"{SURROGATE_MIN_ROWS}-row floor. Collect more cached DataForSEO "
                "SERPs before refitting."
            )
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
        # Per-target fitting: SERP-only cache entries (no keyword-info volume
        # block) still train the three SERP-structure targets;
        # search_volume_log trains on whichever rows carry a volume.
        for target in TARGETS:
            subset = [r for r in valid if r.get(target) is not None]
            if len(subset) < SURROGATE_MIN_ROWS:
                meta[target] = None  # not enough labeled rows for this target yet
                continue
            X = np.asarray(
                [lexical_features(r["query"]) for r in subset], dtype="float64"
            )
            y = [float(r[target]) for r in subset]
            dataset = self._lgb.Dataset(X, label=y)
            booster = self._lgb.train(params, dataset, num_boost_round=120)
            model_path = os.path.join(models_dir, f"{MODEL_PREFIX}_{target}.txt")
            booster.save_model(model_path)
            meta[target] = model_path
        with open(
            os.path.join(models_dir, f"{MODEL_PREFIX}.meta.json"), "w", encoding="utf-8"
        ) as fh:
            json.dump(meta, fh, indent=2)
        self.models = {
            t: self._lgb.Booster(model_file=meta[t]) for t in TARGETS if meta[t]
        }
        self._fitted = True
        return meta

    def load(self, models_dir: str = "models/") -> bool:
        meta_path = os.path.join(models_dir, f"{MODEL_PREFIX}.meta.json")
        if not os.path.exists(meta_path):
            return False
        with open(meta_path, encoding="utf-8") as fh:
            meta = json.load(fh)
        self.models = {
            t: self._lgb.Booster(model_file=meta[t]) for t in TARGETS if meta.get(t)
        }
        self._fitted = True
        return True

    # --------------------------------------------------------------- predict

    def predict_serp_features(self, queries: List[str]) -> List[Dict[str, Any]]:
        """Predicts the available DataForSEO columns offline (clipped to ranges).

        Targets whose per-target training subset never reached the floor are
        omitted (fit() records them as null in the meta file) instead of
        guessing from an untrained model.
        """
        if not self._fitted:
            raise RuntimeError(
                "Surrogate not fitted/loaded; call fit() or load() first."
            )
        X = np.asarray([lexical_features(q) for q in queries], dtype="float64")
        bounds = {
            "search_volume_log": (0.5, 5.0),
            "serp_forum_ratio": (0.0, 1.0),
            "title_exact_match_rate": (0.0, 1.0),
            "serp_pixel_crowding": (0.0, 6.0),
        }
        out: List[Dict[str, Any]] = []
        for i, query in enumerate(queries):
            row: Dict[str, Any] = {"query": query}
            for target, (low, high) in bounds.items():
                if target in self.models:
                    raw = float(self.models[target].predict(X[i : i + 1])[0])
                    row[target] = round(min(high, max(low, raw)), 6)
            row["feature_source"] = FEATURE_SOURCE
            out.append(row)
        return out


def rows_from_serp_cache(cache: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Extracts surrogate training rows from a .serp_cache.json-shaped payload.

    Uses the REAL extractor outputs: ``forum_ugc_ratio`` (extract_serp_features)
    becomes serp_forum_ratio; ``title_exact_match_rate`` and the crowding-block
    count come from serp_vulnerability_score's components. Volume is only
    present in keyword-info blocks (suggestions), so SERP-only entries train
    the three SERP targets; fit() trains each target on the rows that carry it.
    """
    from dataforseo_client import extract_serp_features, serp_vulnerability_score

    rows: List[Dict[str, Any]] = []
    for query, payload in cache.items():
        items = payload.get("items") if isinstance(payload, dict) else payload
        if not items:
            continue
        feats = extract_serp_features(items)
        vuln = serp_vulnerability_score(items, query)
        components = vuln.get("components") or {}
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
                "serp_forum_ratio": feats.get("forum_ugc_ratio"),
                "title_exact_match_rate": components.get("title_exact_match_rate"),
                "serp_pixel_crowding": components.get("crowding_penalty"),
            }
        )
    return rows


def refit_from_state_db(
    db_path: str,
    models_dir: str = "models/",
    serp_cache_path: Optional[str] = None,
    max_age_days: int = 30,
) -> Dict[str, Any]:
    """Rebuilds the surrogate from the fleet's persisted SERP caches.

    Reads every fresh (<= max_age_days) entry from the state DB's
    ``dfs_serp_cache`` table, optionally merges a .serp_cache.json file, and
    refits. This is the nightly active-learning half-step: the daily budget
    gate spends the SERP quota, this turns the responses into model updates.
    """
    from datetime import datetime, timedelta, timezone

    from fleet_state import connect_state_db

    cache: Dict[str, Any] = {}
    conn = connect_state_db(db_path)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=max_age_days)).isoformat()
    for query, items_json in conn.execute(
        "SELECT query, items_json FROM dfs_serp_cache WHERE fetched_at >= ?", (cutoff,)
    ):
        cache[str(query)] = json.loads(items_json)
    conn.close()

    if serp_cache_path and os.path.exists(serp_cache_path):
        with open(serp_cache_path, encoding="utf-8") as fh:
            file_cache = json.load(fh)
        for query, value in file_cache.items():
            if query not in cache:
                cache[str(query)] = value

    rows = rows_from_serp_cache(cache)
    surrogate = OfflineDataForSEOSurrogate()
    meta = surrogate.fit(rows, models_dir=models_dir)
    meta["cache_entries"] = len(cache)
    return meta


if __name__ == "__main__":  # pragma: no cover - thin CLI wrapper
    import argparse

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--fit-from-state-db", default="", help="fleet state DB path to refit from"
    )
    parser.add_argument(
        "--serp-cache", default=".serp_cache.json", help="file SERP cache to merge"
    )
    parser.add_argument("--models-dir", default="models/")
    args = parser.parse_args()
    if not args.fit_from_state_db:
        parser.error("--fit-from-state-db is required")
    summary = refit_from_state_db(
        args.fit_from_state_db,
        models_dir=args.models_dir,
        serp_cache_path=args.serp_cache,
    )
    print(
        f"Surrogate refit: {summary['rows']} training rows from "
        f"{summary['cache_entries']} cache entries -> {args.models_dir}"
    )
