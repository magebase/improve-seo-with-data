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
import urllib.error
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

# Canonical action taxonomy (Wave-65 quota integrity upgrade):
# Synonym action codes bypass PARTITION BY action_code quota splits and cause
# 2x-3x oversubscription of link/route tasks while starving data-table tasks.
# All synonym strings collapse to their single authoritative canonical counterpart.
CANONICAL_ACTION_CODE_MAP: dict[str, str] = {
    "INJECT_EXACT_H2_AND_TITLE": "INJECT_EXACT_TITLE_AND_H2",
    "LAUNCH_PSEO_ROUTE": "CREATE_PROGRAMMATIC_ROUTE",
    "STRENGTHEN_HUB_INTERNAL_LINKS": "WIRE_HUB_AND_FOOTER_INLINKS",
    "BOOST_INTERNAL_LINKS": "WIRE_HUB_AND_FOOTER_INLINKS",
    "RESCUE_ORPHAN_ROUTE_INLINKS": "WIRE_HUB_AND_FOOTER_INLINKS",
}


def canonicalize_action_code(code: str) -> str:
    """Normalizes synonym action codes to their single canonical counterpart."""
    return CANONICAL_ACTION_CODE_MAP.get(code, code)


def url_path(url: str) -> str:
    """Extracts the path component from a full URL (or passes paths through)."""
    raw = (url or "").strip()
    if "://" in raw:
        return urllib.parse.urlparse(raw).path or "/"
    return raw if raw.startswith("/") else f"/{raw}"


_TRACKING_PARAM_RE = re.compile(r"^(utm_|fbclid$|gclid$)", re.IGNORECASE)


def strip_tracking_params(url: str) -> str:
    """Drops campaign/tracking query params so canonical keys never fragment."""
    raw = (url or "").strip()
    if "://" not in raw and not raw.startswith("/"):
        return raw
    parsed = urllib.parse.urlparse(raw)
    if not parsed.query:
        return raw
    kept = [
        (k, v)
        for k, v in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
        if not _TRACKING_PARAM_RE.match(k)
    ]
    cleaned = urllib.parse.urlunparse(parsed._replace(query=urllib.parse.urlencode(kept)))
    return cleaned


def _brand_stems(domain: str) -> list:
    stem = (domain or "").split(".")[0].lower()
    return [stem, f"{stem}com", f"{stem}net", f"{stem}org", f"www{stem}com"]


def is_valid_seo_candidate(domain: str, url_path_or_url: str, query: str) -> bool:
    """Rejects legal/utility pages, foreign subdomains, and navigational brand-typo queries.

    Called BEFORE SERP enrichment: a rejected row never consumes DataForSEO
    credits or a lease slot.
    """
    clean_domain = (domain or "").strip().lower()
    if clean_domain.startswith("sc-domain:"):
        clean_domain = clean_domain[len("sc-domain:") :]

    raw_url = (url_path_or_url or "").strip()
    if "://" in raw_url:
        parsed = urllib.parse.urlparse(raw_url)
        netloc = (parsed.netloc or "").split(":")[0].lower()
        if clean_domain and netloc:
            allowed = {clean_domain, f"www.{clean_domain}"}
            if netloc not in allowed:
                return False

    if NON_SEO_PATH_RE.search(url_path(url_path_or_url).strip() or "/"):
        return False
    collapsed_q = re.sub(r"[^a-z0-9]", "", (query or "").lower())
    if not collapsed_q:
        return False
    stems = _brand_stems(clean_domain)
    if collapsed_q in stems:
        return False
    base_stem = stems[0]
    # brand + short nav suffix ('brandlogin', 'brandterms', 'brand42') is
    # navigational, not informational demand
    return not (collapsed_q.startswith(base_stem) and len(collapsed_q) <= len(base_stem) + 5)


def _norm_page_key(page: str) -> str:
    raw = (page or "").strip().rstrip("/")
    return raw.lower()


def canonicalize_and_dedupe_candidates(
    candidates: Iterable[dict[str, Any]],
    redirect_map: dict[str, str] | None = None,
    domain: str = "",
) -> tuple[list, dict[str, int]]:
    """Resolves 301s, scrubs junk, and collapses duplicate (page, query) rows.

    Aggregation semantics when a legacy URL and its canonical share a query
    (anti-inflation, review hardening R2): impressions are NOT blind-summed.
    Rows carry an optional ``date``/``day`` field:
    - dated rows: per (date, page, query) the MAX impression count wins (the
      same SERP impression is never counted twice), then daily maxima SUM
      across the window (genuine day-by-day demand accumulates);
    - dateless rows (aggregated export windows): MAX across the duplicates
      (an index transition serves one of the two URLs per impression day,
      so blind SUM inflates volume and deflates true CTR);
    clicks SUM across all rows (click events are real regardless of which
    URL variant captured them), position keeps the MINIMUM (best ranking
    between legacy and canonical), and ``ctr`` is RE-DERIVED from the
    aggregated clicks / impressions. Every other column keeps its
    first-seen value. Returns ``(rows, report)`` where the report counts
    ``canonicalized`` (URLs remapped), ``scrubbed`` (utility / brand-typo
    rows dropped) and ``deduped_away`` (rows merged into twins).
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
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in candidates:
        page = str(row.get("page", ""))
        target = _find(page)
        if target is not None:
            if target.startswith("http"):
                page = target
            elif "://" in page:
                parsed = urllib.parse.urlparse(page)
                target_path = target if target.startswith("/") else url_path(target)
                page = urllib.parse.urlunparse((parsed.scheme, parsed.netloc, target_path, "", "", ""))
            else:
                page = target
            report["canonicalized"] += 1
        page = strip_tracking_params(page)
        query = str(row.get("query", ""))
        if not is_valid_seo_candidate(domain, page, query):
            report["scrubbed"] += 1
            continue
        key = (_norm_page_key(page), query.lower())
        stored = dict(row)
        stored["page"] = page  # canonicalized + tracking-param-stripped
        grouped.setdefault(key, []).append(stored)

    merged: list[dict[str, Any]] = []
    for rows in grouped.values():
        first = dict(rows[0])
        # anti-inflation (review R2): per-date MAX impressions, summed across
        # dates; dateless rows (aggregated export windows) MAX across twins
        per_date: dict[str, float] = {}
        undated: list[float] = []
        clicks = 0.0
        best_pos = 99.0
        for row in rows:
            day = str(row.get("date") or row.get("day") or "")
            impressions = float(row.get("impressions", 0) or 0)
            if day:
                per_date[day] = max(per_date.get(day, 0.0), impressions)
            else:
                undated.append(impressions)
            clicks += float(row.get("clicks_30d", 0) or 0)
            best_pos = min(best_pos, float(row.get("current_pos", 99) or 99))
        impressions = sum(per_date.values()) + (max(undated) if undated else 0.0)
        first["impressions"] = impressions
        first["clicks_30d"] = clicks
        first["current_pos"] = best_pos
        if impressions > 0:
            first["ctr"] = clicks / impressions
        report["deduped_away"] += len(rows) - 1
        merged.append(first)
    merged.sort(key=lambda r: (-float(r.get("impressions", 0) or 0), str(r.get("query", ""))))
    return merged, report


def resolve_redirects(
    urls: Iterable[str],
    timeout: float = 2.0,
    max_urls: int = 400,
    max_hops: int = 3,
) -> dict[str, str]:
    """Resolves candidate URLs against the LIVE site (redirect-followed).

    Hardened per the wave-64 review: redirects follow at most ``max_hops``
    hops (a redirect LOOP is left unmapped rather than crash-looping the
    fleet), the per-request timeout is capped at 2.0s, and tracking params
    (``utm_*``, ``fbclid``, ``gclid``) are stripped from every final URL so
    canonical lookup never fragments on campaign suffixes.

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
        final = _resolve_one(raw, min(float(timeout), 2.0), max_hops)
        if final:
            mapping[raw] = final
    return mapping


class _HopLimitedRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Redirect handler that treats hop budget exhaustion as a normal miss."""

    def __init__(self, max_hops: int):
        super().__init__()
        self._max_hops = max_hops

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        hops = getattr(req, "_seo_fleet_hops", 0) + 1
        if hops > self._max_hops:
            raise urllib.error.URLError(f"redirect hop budget exceeded (>{self._max_hops})")
        req._seo_fleet_hops = hops  # type: ignore[attr-defined]
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _resolve_one(url: str, timeout: float, max_hops: int = 3) -> str | None:
    try:
        opener = urllib.request.build_opener(_HopLimitedRedirectHandler(max_hops))
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (seo-fleet-canonicalizer)",
                "Accept-Encoding": "gzip",
            },
            method="GET",
        )
        resp = opener.open(req, timeout=timeout)
        try:
            resp.read(64)  # touch the body so redirects surface; discard
            final = resp.geturl()
        finally:
            resp.close()
        return strip_tracking_params(final or url)
    except Exception:  # noqa: BLE001 - one bad URL must never kill the run
        return None
