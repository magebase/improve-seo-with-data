"""Sensitivity test: the growth engine must never fabricate demand for empty properties.

The engine carried a hardcoded "demo" GSC dataset (figiva-flavored queries) that was
injected whenever a property returned no query-page rows — silently producing
speculative action queues for any site with no real search demand (Invariant 11
violation, and it poisoned cross-fleet prioritization).
"""

import importlib.util
import json
from pathlib import Path

ENGINE = Path(
    "/home/aqua/Projects/saas-factory/.agents/skills/improve-seo-with-data/scripts/seo_growth_intelligence.py"
)


def _load_engine():
    spec = importlib.util.spec_from_file_location("seo_growth_intelligence", ENGINE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_empty_property_yields_zero_actions_and_no_data_marker(monkeypatch):
    mod = _load_engine()

    def _no_data(report_id, site, params=None):
        return {"ok": True}

    monkeypatch.setattr(mod, "run_seo_cli", _no_data)

    manifest = mod.orchestrate_seo_growth(site="sc-domain:crewelo-with-no-data.com")

    assert manifest["dimensions"]["total_query_page_rows"] == 0
    assert manifest["data_coverage"]["state"] == "no_gsc_query_data"
    blob = json.dumps(manifest)
    assert "calcsite" not in blob, "engine fabricated demo demand for an empty property"
    assert "fmcg scheme" not in blob, (
        "engine fabricated demo demand for an empty property"
    )
    assert manifest["total_actions_detected"] == 0
