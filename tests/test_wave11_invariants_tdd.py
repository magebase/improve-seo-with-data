"""TDD tests for Wave 11 Invariants F, G, and H:
1. Triplet collapse for unbuilt routes in compile_wave_backlog (Invariant F).
2. Skipping hub routes and single-token category slugs in synthesize_orphan_rows (Invariant F).
3. Scoped zone purging in deploy_seo_alpha_worker (Invariant G).
4. Em-dash SERP pixel width modeling in estimate_title_display_width (Invariant H).
"""

from unittest.mock import patch, MagicMock
import json


def test_unbuilt_routes_collapse_triplets():
    """Unbuilt routes (pos >= 90) must emit ONLY CREATE_PROGRAMMATIC_ROUTE."""
    from ltr_ranker import compile_wave_backlog

    rows = [
        {
            "query": "section 179 calculator",
            "page": "https://incomecanvas.com/calculators/section-179-calculator/",
            "current_pos": 95.0,
            "impressions": 0.0,
            "clicks_30d": 0.0,
            "features": {
                "title_exact_match_rate": 0.1,  # would trigger INJECT_EXACT_TITLE_AND_H2
                "parent_hub_internal_links": 1.0,  # would trigger STRENGTHEN_HUB_INTERNAL_LINKS
            },
            "source": "orphan_route",
            "rank_score": 10.0,
        }
    ]

    tasks = compile_wave_backlog(rows, shipped_ledger=set(), target_wave_size=5)
    codes = [t["action_code"] for t in tasks]

    assert codes == ["CREATE_PROGRAMMATIC_ROUTE"], (
        f"Expected only CREATE_PROGRAMMATIC_ROUTE, got: {codes}"
    )


def test_orphan_synthesizer_skips_hub_and_single_token_category_slugs():
    """Hub roots and single-token category slugs must be skipped from orphan synthesis."""
    from collect_features import synthesize_orphan_rows

    sitemap_urls = [
        "https://incomecanvas.com/compare/",
        "https://incomecanvas.com/calculators/",
        "https://incomecanvas.com/tools/",
        "https://incomecanvas.com/niche/insurance/",
        "https://incomecanvas.com/calculators/section-179-calculator/",
        "https://incomecanvas.com/tools/merge-pdf/",
    ]

    rows = synthesize_orphan_rows(sitemap_urls, gsc_pages=set(), domain="incomecanvas.com")
    pages = [r["page"] for r in rows]

    assert "https://incomecanvas.com/compare/" not in pages
    assert "https://incomecanvas.com/calculators/" not in pages
    assert "https://incomecanvas.com/tools/" not in pages
    assert "https://incomecanvas.com/niche/insurance/" not in pages
    assert "https://incomecanvas.com/calculators/section-179-calculator/" in pages
    assert "https://incomecanvas.com/tools/merge-pdf/" in pages


def test_estimate_title_display_width_accounts_for_em_dash():
    """Em-dash (—) must be modeled at 12.5px vs pipe (|) at 4.5px (8.0px wider)."""
    from seo_growth_intelligence import estimate_title_display_width

    title_pipe = "Calculator | IncomeCanvas"
    title_emdash = "Calculator — IncomeCanvas"

    res_pipe = estimate_title_display_width(title_pipe)
    res_emdash = estimate_title_display_width(title_emdash)

    diff = res_emdash["estimated_pixel_width"] - res_pipe["estimated_pixel_width"]
    assert round(diff, 1) == 8.0, f"Expected 8.0px diff between — and |, got {diff}"

    # Verify long title with em-dash exceeds desktop cutoff (580px)
    long_title = "A Comprehensive and Very Long Financial Modeling Calculator With Many Inputs — IncomeCanvas"
    res_long = estimate_title_display_width(long_title)
    assert res_long["estimated_pixel_width"] > 580.0
    assert not res_long["fits_desktop"]


def test_purge_seo_alpha_zones_scoped_to_target_zone(monkeypatch):
    """purge_seo_alpha_zones must only purge requested target_zones when specified."""
    import sys
    from pathlib import Path

    candidate_roots = [
        Path(__file__).resolve().parents[3] / "Projects" / "saas-factory",
        Path(__file__).resolve().parents[5] / "Projects" / "saas-factory",
        Path.home() / "Projects" / "saas-factory",
    ]
    repo_root = next((p for p in candidate_roots if p.exists()), Path.home() / "Projects" / "saas-factory")
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    if str(repo_root / "scripts") not in sys.path:
        sys.path.insert(0, str(repo_root / "scripts"))

    from scripts.deploy_seo_alpha_worker import purge_seo_alpha_zones

    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "mock_token")

    purged_zones = []

    def fake_urlopen(req, timeout=15):
        url = req.full_url
        if "zones?name=" in url:
            zone_name = url.split("zones?name=")[-1]
            return MagicMock(
                __enter__=lambda s: s,
                __exit__=lambda s, *a: False,
                read=lambda: json.dumps({"result": [{"id": f"id_{zone_name}"}]}).encode("utf-8"),
            )
        if "purge_cache" in url:
            purged_zones.append(url)
            return MagicMock(
                __enter__=lambda s: s,
                __exit__=lambda s, *a: False,
                read=lambda: json.dumps({"success": True}).encode("utf-8"),
            )
        raise ValueError(f"Unexpected URL: {url}")

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        # 1. Scoped purge
        purged_zones.clear()
        res = purge_seo_alpha_zones(target_zones=["incomecanvas.com"])
        assert res is True
        assert len(purged_zones) == 1
        assert "id_incomecanvas.com" in purged_zones[0]

        # 2. Fleet purge (default)
        purged_zones.clear()
        res_fleet = purge_seo_alpha_zones()
        assert res_fleet is True
        assert len(purged_zones) == 3
