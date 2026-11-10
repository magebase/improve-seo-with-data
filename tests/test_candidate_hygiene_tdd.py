"""
Unit TDD tests for wave-64 candidate hygiene: 301 pre-collapse, utility/brand
scrubbing, and dedupe-aggregation BEFORE SERP enrichment and LGBMRanker
scoring (fixes wave-63's 21-leased -> 4-edits collapse and the wasted SERP
credits on /privacy/, /terms/ and the brand typo 'incomecanvascom').
"""

import pytest

from candidate_hygiene import (
    NON_SEO_PATH_RE,
    canonicalize_and_dedupe_candidates,
    is_valid_seo_candidate,
    url_path,
)


def _c(page, query, impressions=10.0, clicks=0.0, pos=20.0, **extra):
    row = {
        "query": query,
        "page": page,
        "clicks_30d": clicks,
        "impressions": impressions,
        "current_pos": pos,
        "ctr": 0.01,
        "window_days": 28,
    }
    row.update(extra)
    return row


# ------------------------------------------------------------ path scrubbing


@pytest.mark.parametrize(
    "path",
    [
        "/privacy/",
        "/terms/",
        "/tos/",
        "/cookie-policy/",
        "/disclaimer/",
        "/legal/",
        "/contact/",
        "/about/",
        "/login/",
        "/signup/",
        "/account/",
        "/billing/",
        "/admin/",
        "/api/docs/",
        "/health/",
        "/static/app.js",
        "/terms-of-service/",
    ],
)
def test_utility_paths_are_rejected(path):
    assert NON_SEO_PATH_RE.search(path), f"utility path survived: {path}"


@pytest.mark.parametrize(
    "path",
    [
        "/guides/dnd-scrubbing/",
        "/article/privacy-coins-audits/",
        "/insurance/average-car-insurance-rates-cost",
        "/calculators/dscr/",
        "/privacytools-vpn-comparison/",  # 'privacy' inside a longer token is content
    ],
)
def test_content_paths_survive(path):
    assert not NON_SEO_PATH_RE.search(path), f"false positive on: {path}"


def test_url_path_extracts_path_from_full_url():
    assert url_path("https://www.incomecanvas.com/terms/") == "/terms/"
    assert url_path("/privacy/") == "/privacy/"
    assert url_path("https://x.com/guides/a/") == "/guides/a/"


# ------------------------------------------------------------- brand typos


def test_brand_typo_variants_are_rejected():
    domain = "incomecanvas.com"
    assert not is_valid_seo_candidate(domain, "/articles/a/", "incomecanvascom")
    assert not is_valid_seo_candidate(domain, "/articles/a/", "income canvas com")
    assert not is_valid_seo_candidate(domain, "/articles/a/", "wwwincomecanvascom")
    assert not is_valid_seo_candidate(domain, "/articles/a/", "incomecanvas")
    assert not is_valid_seo_candidate(domain, "/articles/a/", "incomecanvas login")


def test_brand_adjacent_real_queries_survive():
    domain = "incomecanvas.com"
    assert is_valid_seo_candidate(domain, "/articles/a/", "incomecanvas reviews")
    assert is_valid_seo_candidate(
        domain, "/articles/a/", "income canvas vs mintok calculators"
    )
    assert is_valid_seo_candidate(
        domain, "/articles/a/", "average cost of car insurance"
    )


def test_smsriver_brand_typo_rejected():
    assert not is_valid_seo_candidate("smsriver.com", "/articles/a/", "smsrivercom")


# ----------------------------------------------- canonicalize + dedupe + scrub


def test_legacy_301_urls_collapse_onto_canonical_and_sum_impressions():
    candidates = [
        _c(
            "https://www.incomecanvas.com/insurance/average-car-insurance-rates-cost",
            "average cost of car insurance",
            impressions=251.0,
            pos=97.0,
        ),
        _c(
            "https://incomecanvas.com/article/commercial-personal-auto-insurance-cost-benchmarks-deductibles/",
            "average cost of car insurance",
            impressions=102.0,
            pos=41.0,
            clicks=1.0,
        ),
        _c(
            "https://incomecanvas.com/article/commercial-personal-auto-insurance-cost-benchmarks-deductibles/",
            "car insurance benchmarks",
            impressions=30.0,
            pos=55.0,
        ),
    ]
    redirect_map = {
        "https://www.incomecanvas.com/insurance/average-car-insurance-rates-cost": "https://incomecanvas.com/article/commercial-personal-auto-insurance-cost-benchmarks-deductibles/",
    }
    merged, report = canonicalize_and_dedupe_candidates(
        candidates, redirect_map=redirect_map, domain="incomecanvas.com"
    )
    assert report["canonicalized"] == 1
    assert report["deduped_away"] == 1
    rows = [(r["page"], r["query"]) for r in merged]
    assert (
        rows.count(
            (
                "https://incomecanvas.com/article/commercial-personal-auto-insurance-cost-benchmarks-deductibles/",
                "average cost of car insurance",
            )
        )
        == 1
    )
    row = next(r for r in merged if r["query"] == "average cost of car insurance")
    assert row["impressions"] == 353.0, "legacy + canonical impressions must sum"
    assert row["current_pos"] == 41.0, "best position between legacy and canonical wins"
    assert row["clicks_30d"] == 1.0


def test_path_form_redirect_map_also_collapses():
    candidates = [
        _c(
            "https://incomecanvas.com/loans/personal-loans-rates",
            "personal loans rates",
            impressions=426.0,
        ),
        _c(
            "https://incomecanvas.com/article/unsecured-personal-loan-aprs-underwriting-dti-debt-consolidation/",
            "personal loans rates",
            impressions=10.0,
        ),
    ]
    redirect_map = {
        "/loans/personal-loans-rates": "/article/unsecured-personal-loan-aprs-underwriting-dti-debt-consolidation/"
    }
    merged, report = canonicalize_and_dedupe_candidates(
        candidates, redirect_map=redirect_map, domain="incomecanvas.com"
    )
    assert report["canonicalized"] == 1
    assert len(merged) == 1
    assert merged[0]["impressions"] == 436.0


def test_utility_and_typo_rows_never_reach_the_pool():
    candidates = [
        _c("https://incomecanvas.com/privacy/", "privacy", impressions=5.0),
        _c("https://incomecanvas.com/terms/", "terms", impressions=5.0),
        _c("https://incomecanvas.com/", "incomecanvascom", impressions=3.0),
        _c(
            "https://incomecanvas.com/article/a/", "real demand query", impressions=40.0
        ),
    ]
    merged, report = canonicalize_and_dedupe_candidates(
        candidates, redirect_map={}, domain="incomecanvas.com"
    )
    assert report["scrubbed"] == 3
    assert [r["query"] for r in merged] == ["real demand query"]


def test_no_redirect_map_is_a_pure_scrub_and_dedupe():
    candidates = [
        _c("https://incomecanvas.com/article/a/", "q one", impressions=10.0),
        _c("https://incomecanvas.com/article/a/", "q one", impressions=5.0, pos=12.0),
        _c("https://incomecanvas.com/contact/", "contact", impressions=2.0),
    ]
    merged, report = canonicalize_and_dedupe_candidates(
        candidates, domain="incomecanvas.com"
    )
    assert len(merged) == 1
    assert merged[0]["impressions"] == 15.0
    assert merged[0]["current_pos"] == 12.0
    assert report["scrubbed"] == 1


# ------------------------------------------------- live redirect resolution


def test_resolve_redirects_follows_legacy_paths(monkeypatch):
    from candidate_hygiene import resolve_redirects

    calls = []

    def fake_open(req, timeout=None):
        calls.append(req.get_full_url())

        class R:
            def __init__(self, url, status):
                self.url = url
                self.status = status

            def geturl(self):
                return self.url

            def read(self, *args, **kwargs):
                return b""

            def close(self):
                pass

        if req.get_full_url().endswith("/loans/personal-loans-rates"):
            return R(
                "https://incomecanvas.com/article/unsecured-personal-loan-aprs/", 301
            )
        return R(req.get_full_url(), 200)

    import urllib.request

    monkeypatch.setattr(urllib.request, "urlopen", fake_open)
    mapping = resolve_redirects(
        [
            "https://www.incomecanvas.com/loans/personal-loans-rates",
            "https://incomecanvas.com/article/unsecured-personal-loan-aprs/",
        ],
        timeout=5,
    )
    assert (
        mapping["https://www.incomecanvas.com/loans/personal-loans-rates"]
        == "https://incomecanvas.com/article/unsecured-personal-loan-aprs/"
    )
    # a non-redirecting URL maps to itself (or is absent); never mapped to junk
    assert not any(v.endswith("/privacy/") for v in mapping.values())
