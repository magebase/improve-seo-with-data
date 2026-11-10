"""Regression tests: URL-ownership majority gate, new-page demand floor, State-8 micro-volume downgrade.

The improve-seo-with-data growth engine emitted three classes of unsafe actions,
each reproduced against real GSC data during the 2026-11-06 fleet dispositions
(``docs/seo-fleet-disposition-2026-11-06.md`` + per-property docs):

1. New-page proposals onto non-hub URLs that already receive 100% of a query's
   impressions (skrino: a position-56 article landing still got a competing
   ``/articles/`` proposal because token-overlap matching missed it).
2. Page-creation actions justified by 1-10 monthly impressions (7-factor
   demand-factor failure).
3. Canonicalize/301 consolidation contracts at 58-100 impression volumes —
   including a proposal to 301 a property's homepage onto a country number page.

The engine ships with the skill under ``.agents/skills/`` (untracked), so this
module skips cleanly wherever that path is absent — mirroring
``test_seo_growth_engine_no_demo_data.py``.
"""

import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest

ENGINE = (
    Path(__file__).resolve().parents[2]
    / ".agents"
    / "skills"
    / "improve-seo-with-data"
    / "scripts"
    / "seo_growth_intelligence.py"
)

pytestmark = pytest.mark.skipif(
    not ENGINE.exists(), reason="skill engine not provisioned on this checkout"
)


def _load_engine() -> ModuleType:
    spec = importlib.util.spec_from_file_location("seo_growth_intelligence", ENGINE)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _row(q, page, imp, clicks=0, pos=50.0, site="skrino.com"):
    return {
        "query": q,
        "page": page,
        "impressions": imp,
        "clicks": clicks,
        "position": pos,
        "site": site,
    }


def test_no_new_page_when_non_hub_landing_receives_majority():
    mod = _load_engine()
    rows = [
        _row(
            "video game villains who were right",
            "https://skrino.com/articles/10-gaming-villains-that-were-actually-right/",
            30,
            1,
            56.0,
        ),
    ]
    acts = mod.detect_new_page_opportunities(rows, site="sc-domain:skrino.com")
    new_pages = [a for a in acts if a.get("action_type") == "new_page_creation"]
    assert not new_pages, (
        f"URL-ownership gate violated, proposed: {[a['target_urls'] for a in new_pages]}"
    )


def test_new_page_still_proposed_for_hub_landing_with_demand():
    mod = _load_engine()
    rows = [_row("btu to cfm conversion", "https://skrino.com/", 50, 1, 40.0)]
    acts = mod.detect_new_page_opportunities(rows, site="sc-domain:skrino.com")
    assert any(a.get("action_type") == "new_page_creation" for a in acts), (
        "genuine new-page detection lost"
    )


def test_new_page_suppressed_below_demand_floor():
    mod = _load_engine()
    rows = [_row("obscure tiny query", "https://skrino.com/", 10, 0, 80.0)]
    acts = mod.detect_new_page_opportunities(rows, site="sc-domain:skrino.com")
    assert not any(a.get("action_type") == "new_page_creation" for a in acts), (
        f"demand floor not enforced: {[a['target_urls'] for a in acts]}"
    )


def test_micro_split_downgraded_to_differentiation():
    mod = _load_engine()
    rows = [
        _row(
            "online sms state",
            "https://smsriver.com/status/",
            43,
            0,
            5.2,
            "smsriver.com",
        ),
        _row(
            "online sms state",
            "https://smsriver.com/receive-sms/us/",
            57,
            0,
            8.0,
            "smsriver.com",
        ),
    ]
    acts = mod.detect_content_expansion_and_cannibalization(rows)
    cann = [a for a in acts if a.get("action_id", "").startswith("seo_cannibal")]
    assert cann, "detection visibility lost at micro volume"
    a = cann[0]
    blob = json.dumps(a).lower()
    assert (
        "canonicalize" not in blob
        and "301-redirect" not in blob
        and "301 redirect" not in blob
    ), "destructive consolidation verb present at micro volume"
    assert a["page_level_action"] == "differentiate_overlapping_pages", a[
        "page_level_action"
    ]


def test_consolidation_contract_preserved_at_scale():
    mod = _load_engine()
    rows = [
        _row("big head term", "https://x.com/a/", 220, 5, 6.0, "x.com"),
        _row("big head term", "https://x.com/b/", 180, 3, 9.0, "x.com"),
    ]
    acts = mod.detect_content_expansion_and_cannibalization(rows)
    a5 = [a for a in acts if a.get("action_id", "").startswith("seo_cannibal")][0]
    assert a5["action_type"] == "content_consolidation", a5["action_type"]
