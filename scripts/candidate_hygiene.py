"""Candidate hygiene: 301 pre-collapse, utility/brand scrubbing, dedupe.

Wave-63 postmortem (21 leased -> 4 real edits, 28.5% of a wave reverted,
100 SERP credits partially spent on noise) exposed the ROOT CAUSE upstream
of the cursor: the candidate pipeline ingested raw GSC export URLs without
resolving redirects BEFORE scoring and leasing, so multiple legacy 301 URLs
pointing at the same canonical article were leased as separate tasks, and
utility routes (/privacy/, /terms/) plus brand-typo queries consumed SERP
enrichment credits and lease slots before being manually discarded during
adjudication.

This module runs BEFORE DataForSEO SERP enrichment and BEFORE LGBMRanker
scoring (wired into ``collect_features.py`` between candidate assembly and
the enrichment selection):

1. ``resolve_redirects`` resolves candidate URLs against the LIVE site
   (HTTP, no-follow) so legacy 301/302 paths map to their canonical URL.
   Product-side redirect tables (urls.py / RedirectView / middleware) can be
   passed as ``redirect_map`` entries and take precedence.
2. ``canonicalize_and_dedupe_candidates`` maps every candidate page through
   the redirect map, drops utility routes and brand typos, then collapses
   duplicate (page, query) rows - SUMMING impressions and clicks and keeping
   the BEST (minimum) position between legacy and canonical, so demand
   signal is never lost, only de-duplicated.
3. ``is_valid_seo_candidate`` is the per-row gate: hard-blocks utility,
   legal, auth, and system routes, and rejects navigational brand-stem
   typos ('incomecanvascom', 'income canvas com', 'wwwincomecanvascom',
   'brand login') that can never be answered by a single-heading edit.

Pure Python (no pandas): the candidate stream is a list of dicts whose
shape matches ``collect_features.load_report_files`` output.
"""

from __future__ import annotations

import re
import urllib.parse
import urllib.request
from collections.abc import Iterable
from typing import Any

# Blocks utility, legal, auth, and system routes from ever entering the
# candidate pool. Anchored on the FIRST path segment; the (/|$|-) tail keeps
# content pages whose slug merely CONTAINS these words ('/article/privacy-
# coins-audits/', '/privacytools-vpn-comparison/') eligible.
NON_SEO_PATH_RE = re.compile(
    r"^/(privacy|terms|tos|cookie|disclaimer|legal|contact|about|login|logout"
    r"|signup|register|reset|account|billing|admin|api|health|static|media)"
    r"(/|$|-)",
    re.IGNORECASE,
)


def url_path(url: str) -> str:
    """Extracts the path component from a full URL (or passes paths through)."""
    raw = (url or "").strip()
    if "://" in raw:
        return urllib.parse.urlparse(raw).path or "/"
    return raw if raw.startswith("/") else f"/{raw}"


def _brand_stems(domain: str) -> list:
    stem = (domain or "").split(".")[0].lower()
    return [stem, f"{stem}com", f"{stem}net", f"{stem}org", f"www{stem}com"]


def is_valid_seo_candidate(domain: str, url_path_or_url: str, query: str) -> bool:
    """Rejects legal/utility pages and navigational brand-typo queries.

    Called BEFORE SERP enrichment: a rejected row never consumes DataForSEO
    credits or a lease slot.
    """
    if NON_SEO_PATH_RE.search(url_path(url_path_or_url).strip() or "/"):
        return False
    collapsed_q = re.sub(r"[^a-z0-9]", "", (query or "").lower())
    if not collapsed_q:
        return False
    stems = _brand_stems(domain)
    if collapsed_q in stems:
        return False
    base_stem = stems[0]
    # brand + short nav suffix ('brandlogin', 'brandterms', 'brand42') is
    # navigational, not informational demand
    return not (
        collapsed_q.startswith(base_stem) and len(collapsed_q) <= len(base_stem) + 5
    )


def _norm_page_key(page: str) -> str:
    raw = (page or "").strip().rstrip("/")
    return raw.lower()


def canonicalize_and_dedupe_candidates(
    candidates: Iterable[dict[str, Any]],
    redirect_map: dict[str, str] | None = None,
    domain: str = "",
) -> tuple[list, dict[str, int]]:
    """Resolves 301s, scrubs junk, and collapses duplicate (page, query) rows.

    Aggregation semantics when a legacy URL and its canonical share a query:
    impressions and clicks SUM (demand signal is never lost), position keeps
    the MINIMUM (best ranking between legacy and canonical), and every other
    column keeps its first-seen value. Returns ``(rows, report)`` where the
    report counts ``canonicalized`` (URLs remapped), ``scrubbed`` (utility /
    brand-typo rows dropped) and ``deduped_away`` (rows merged into twins).
    """
    # exact map plus a normalized-key index pointing at ORIGINAL values, so
    # path-form values are never mangled before the rebuild step below
    exact = dict(redirect_map or {})
    norm_lookup: dict[str, str] = {}
    for key, target in exact.items():
        norm_lookup[_norm_page_key(key)] = target

    def _find(page: str) -> str | None:
        hit = exact.get(page) or norm_lookup.get(_norm_page_key(page))
        if hit is not None:
            return hit
        path = url_path(page)
        return norm_lookup.get(path) or norm_lookup.get(path.rstrip("/").lower())

    report = {"canonicalized": 0, "scrubbed": 0, "deduped_away": 0}
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for row in candidates:
        page = str(row.get("page", ""))
        target = _find(page)
        if target is not None:
            if target.startswith("http"):
                page = target
            elif "://" in page:
                parsed = urllib.parse.urlparse(page)
                target_path = target if target.startswith("/") else url_path(target)
                page = urllib.parse.urlunparse(
                    (parsed.scheme, parsed.netloc, target_path, "", "", "")
                )
            else:
                page = target
            report["canonicalized"] += 1
        query = str(row.get("query", ""))
        if not is_valid_seo_candidate(domain, page, query):
            report["scrubbed"] += 1
            continue
        key = (_norm_page_key(page), query.lower())
        bucket = grouped.get(key)
        if bucket is None:
            fresh = dict(row)
            fresh["page"] = page
            grouped[key] = fresh
            continue
        report["deduped_away"] += 1
        bucket["impressions"] = float(bucket.get("impressions", 0) or 0) + float(
            row.get("impressions", 0) or 0
        )
        bucket["clicks_30d"] = float(bucket.get("clicks_30d", 0) or 0) + float(
            row.get("clicks_30d", 0) or 0
        )
        bucket_pos = float(bucket.get("current_pos", 99) or 99)
        row_pos = float(row.get("current_pos", 99) or 99)
        bucket["current_pos"] = min(bucket_pos, row_pos)
    merged = sorted(
        grouped.values(),
        key=lambda r: (-float(r.get("impressions", 0) or 0), str(r.get("query", ""))),
    )
    return merged, report


def resolve_redirects(
    urls: Iterable[str],
    timeout: int = 8,
    max_urls: int = 400,
) -> dict[str, str]:
    """Resolves candidate URLs against the LIVE site (HTTP, no redirects followed).

    Returns ``{original_url: final_url}`` for every URL that responded; a URL
    that maps to itself is INCLUDED (explicit identity), so callers can trust
    the map as complete for the resolved set. Network errors are tolerated:
    failed URLs are simply absent from the result (the caller keeps the raw
    URL, which is the honest pre-collapse state).
    """

    mapping: dict[str, str] = {}
    seen: set = set()
    for url in urls:
        if len(mapping) >= max_urls:
            break
        raw = (url or "").strip()
        if not raw or raw in seen or not raw.startswith("http"):
            continue
        seen.add(raw)
        final = _resolve_one(raw, timeout)
        if final:
            mapping[raw] = final
    return mapping


def _resolve_one(url: str, timeout: int) -> str | None:
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (seo-fleet-canonicalizer)",
                "Accept-Encoding": "gzip",
            },
            method="GET",
        )
        resp = urllib.request.urlopen(req, timeout=timeout)
        try:
            resp.read(64)  # touch the body so redirects surface; discard
            final = resp.geturl()
        finally:
            resp.close()
        return final or url
    except Exception:  # noqa: BLE001 - one bad URL must never kill the run
        return None
