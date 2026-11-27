"""Phase 3 tests: hygiene, GEO disallow penalty, templates, pivot alignment, and wave gate."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import geo_evaluator
from candidate_hygiene import is_lookup_query
from cursor_hygiene import is_clean_english_query, is_clean_query
from seo_shared import check_query_product_alignment


def test_geo_evaluator_penalizes_blocked_ai_bots(capsys):
    with (
        patch.object(geo_evaluator, "fetch_url", return_value=(200, "<html><head><link rel='canonical' href='https://x.com/'/></head><body><h1>Hi</h1></body></html>", {})),
        patch.object(geo_evaluator, "evaluate_llms_txt", return_value={"present": True, "valid": True, "checks": []}),
        patch.object(geo_evaluator, "evaluate_robots_ai_policies", return_value={"status": 200, "crawlers": {"GPTBot": ["Disallow: /"]}}),
        patch("sys.argv", ["geo_evaluator.py", "--url", "https://x.com"]),
    ):
        rc = geo_evaluator.main()
        assert rc == 0
    out = capsys.readouterr().out
    assert "primary AI crawlers are blocked: GPTBot" in out
    assert "Composite GEO & AI Readiness Score: 50/100" in out


def test_multilingual_and_tax_code_hygiene():
    assert is_clean_english_query("объем матки калькулятор") is False
    assert is_clean_query("объем матки калькулятор", allow_multilingual=True) is True
    assert is_clean_query("calcolatore valore umidità a 20 gradi", allow_multilingual=True) is True
    assert is_clean_query('-site:facebook.com "telnyx"', allow_multilingual=True) is False
    assert is_lookup_query("5493812234024") is True
    assert is_lookup_query("0082") is True
    assert is_lookup_query("form 1040") is False


def test_query_product_alignment_flags_pre_pivot_demand():
    homepage = "Compare Delaware vs Wyoming LLC formation, registered agent fees, and corporate tax rules."
    assert check_query_product_alignment(homepage, "delaware vs wyoming llc")["aligned"] is True
    assert check_query_product_alignment(homepage, "warawanaideyo raw")["aligned"] is False


def test_templates_have_no_fake_ratings_or_unconditional_placeholders():
    root = Path(__file__).resolve().parents[1]
    schema = json.loads((root / "templates" / "schema_org.json").read_text(encoding="utf-8"))
    assert "aggregateRating" not in schema["software_application"]
    telemetry = (root / "templates" / "telemetry_snippet.html").read_text(encoding="utf-8")
    assert "default:'XXXXXXXXXX'" not in telemetry
    assert "requestIdleCallback" in telemetry
