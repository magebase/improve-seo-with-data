"""Shared canonical utilities for domain parsing, feature transforms, CTR curves, and HMAC signing."""

from __future__ import annotations

import hashlib
import hmac
import math
import os
import re
import time
from datetime import datetime, timezone
from urllib.parse import urlparse

_MULTI_PART_PUBLIC_SUFFIXES = frozenset({
    "ac.uk", "co.uk", "gov.uk", "ltd.uk", "me.uk", "net.uk", "org.uk", "plc.uk", "sch.uk",
    "com.au", "net.au", "org.au", "edu.au", "gov.au",
    "co.jp", "ne.jp", "or.jp", "ac.jp", "go.jp",
    "com.br", "net.br", "org.br", "gov.br",
    "com.mx", "org.mx", "gob.mx",
    "co.nz", "net.nz", "org.nz", "govt.nz",
    "co.za", "org.za", "gov.za",
    "co.in", "net.in", "org.in", "gov.in",
    "com.sg", "org.sg", "edu.sg", "gov.sg",
    "com.hk", "org.hk", "edu.hk", "gov.hk",
    "com.tw", "org.tw", "edu.tw", "gov.tw",
    "co.kr", "or.kr", "ne.kr", "go.kr",
    "com.cn", "net.cn", "org.cn", "gov.cn",
    "com.tr", "org.tr", "gov.tr",
    "com.ar", "com.pl", "com.ua", "co.il", "org.il",
})

_TRANSACTIONAL_INTENT_TOKENS = frozenset({
    "buy", "price", "pricing", "cost", "rate", "rates", "fee", "fees",
    "quote", "quotes", "cheap", "cheapest", "discount", "coupon", "deal",
    "plan", "plans", "subscription", "trial", "signup", "register", "order",
    "hire", "service", "services", "provider", "providers",
})

_UTILITY_INTENT_TOKENS = frozenset({
    "calculator", "calc", "converter", "convert", "generator", "tool", "tools",
    "checker", "validator", "tester", "estimator", "lookup", "api", "sdk",
    "download", "online", "free", "instant", "template", "templates",
    "verify", "verification", "otp", "sms", "receive",
})

_COMPARISON_INTENT_TOKENS = frozenset({
    "vs", "versus", "compare", "comparison", "alternative", "alternatives",
    "best", "top", "review", "reviews", "benchmark", "difference",
})

SWEEP_USER_AGENT = "saas-factory-seo-verifier/2.0 (outcome-engine; +https://adstim.net)"


def strip_www(host: str) -> str:
    """Removes a leading 'www.' label without stripping leading 'w' characters."""
    return re.sub(r"^www\.", "", str(host or "").strip().lower())


def extract_registered_domain(url_or_host: str) -> str:
    """Extracts the registrable apex domain, preserving multi-part public suffixes."""
    raw = str(url_or_host or "").strip().lower()
    if not raw:
        return ""
    host = urlparse(raw).hostname if "://" in raw else raw.split("/")[0].split(":")[0]
    host = strip_www(host or raw)
    parts = [p for p in host.split(".") if p]
    if len(parts) <= 2:
        return ".".join(parts)
    tail2 = ".".join(parts[-2:])
    if tail2 in _MULTI_PART_PUBLIC_SUFFIXES and len(parts) >= 3:
        return ".".join(parts[-3:])
    return tail2


def canonical_expected_ctr(position: float) -> float:
    """Single canonical position-impression propensity curve: 0.28 / p^1.15."""
    p = max(1.0, float(position))
    return 0.28 / (p**1.15)


def search_volume_to_log(volume: float) -> float:
    """Unified base-10 log transform for search_volume_log across all pipeline stages."""
    v = max(0.0, float(volume or 0.0))
    return math.log10(v + 1.0) if v > 0.0 else 0.0


def score_conversion_intent(query: str) -> float:
    """Deterministic [0.0, 1.0] commercial/utility conversion intent score."""
    tokens = set(re.findall(r"[a-z0-9]+", str(query or "").lower()))
    if not tokens:
        return 0.0
    score = 0.0
    if tokens & _TRANSACTIONAL_INTENT_TOKENS:
        score += 0.55
    if tokens & _UTILITY_INTENT_TOKENS:
        score += 0.35
    if tokens & _COMPARISON_INTENT_TOKENS:
        score += 0.30
    if "2026" in tokens or "2025" in tokens or "2027" in tokens:
        score += 0.10
    return round(min(1.0, score), 6)


def utc_iso_now(now: datetime | None = None) -> str:
    """Returns strict UTC ISO-8601 string with 'T' and 'Z' suffix."""
    dt = now or datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def sign_sweep_headers(
    url: str,
    secret: str | None = None,
    timestamp: int | None = None,
    user_agent: str = SWEEP_USER_AGENT,
) -> dict[str, str]:
    """Builds verification headers with HMAC-SHA256 signature when secret is configured."""
    headers: dict[str, str] = {
        "User-Agent": user_agent,
        "X-SEO-Verify": "1",
    }
    resolved_secret = secret if secret is not None else os.environ.get("SEO_SWEEP_SECRET", "")
    if resolved_secret:
        ts = str(int(timestamp if timestamp is not None else time.time()))
        parsed = urlparse(url)
        target = parsed.path or "/"
        if parsed.query:
            target = f"{target}?{parsed.query}"
        payload = f"{ts}:{target}".encode()
        sig = hmac.new(resolved_secret.encode(), payload, hashlib.sha256).hexdigest()
        headers["X-SEO-Sweep-Ts"] = ts
        headers["X-SEO-Sweep-Sig"] = sig
    return headers


def check_query_product_alignment(
    homepage_text: str,
    query: str,
    min_shared_tokens: int = 1,
) -> dict[str, object]:
    """Detects pre-pivot legacy queries that have zero topical overlap with live homepage copy."""
    stop = {"the", "a", "an", "for", "to", "of", "in", "on", "and", "or", "is", "with", "vs", "free", "online"}
    home_tokens = {
        t for t in re.findall(r"[a-z0-9]+", str(homepage_text or "").lower()) if len(t) > 2 and t not in stop
    }
    query_tokens = {
        t for t in re.findall(r"[a-z0-9]+", str(query or "").lower()) if len(t) > 2 and t not in stop
    }
    overlap = sorted(home_tokens & query_tokens)
    aligned = (not home_tokens) or (len(overlap) >= min_shared_tokens)
    return {
        "aligned": aligned,
        "shared_tokens": overlap,
        "query_tokens": sorted(query_tokens),
    }
