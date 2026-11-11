"""TDD test suite for automated Tier-2/Tier-3 candidate expansion:
1. Mined People-Also-Ask (PAA) and related searches from cached SERPs (dfs_serp_cache)
2. Auto-expansion trigger when domain pending backlog < threshold (default 15)
3. Idle state when domain pending backlog is healthy (>= threshold and >= min_rows)
4. Force flag override (--force-expand)
5. Full pipeline integration preserving 21-day URL title lock cooldown
"""

from __future__ import annotations

import json

import pytest
from collect_features import (
    auto_expand_candidates_if_depleted,
    mine_paa_and_related_from_cache,
)
from cursor_hygiene import preflight_hygiene
from fleet_state import connect_state_db, enqueue_tasks


@pytest.fixture
def mem_db():
    return connect_state_db(":memory:")


def test_mine_paa_and_related_from_cache_extracts_and_maps_queries(mem_db):
    """Verifies that PAA questions and related searches are extracted and mapped to matching URLs."""
    # Seed a cached SERP for 'stl to step' containing PAA and related searches
    serp_items = [
        {
            "type": "organic",
            "rank_group": 1,
            "url": "https://example.com/stl-to-step",
            "title": "Convert STL to STEP Online",
        },
        {
            "type": "people_also_ask",
            "items": [
                {
                    "type": "people_also_ask_element",
                    "title": "Can OBJ files be converted to STL?",
                },
                {
                    "type": "people_also_ask_element",
                    "title": "How to convert STL mesh to STEP CAD solid?",
                },
            ],
        },
        {
            "type": "related_searches",
            "items": [
                "STL to STEP free converter",
                "Mesh to solid CAD conversion",
                "Unrelated medical billing software",  # Should be filtered out by topical gate
            ],
        },
    ]

    mem_db.execute(
        """
        INSERT INTO dfs_serp_cache (query, fetched_at, items_json, item_types, search_volume)
        VALUES (?, datetime('now'), ?, '[]', 150.0)
        """,
        ("stl to step", json.dumps(serp_items)),
    )

    # Seed known query for domain in atomic_task_backlog so originating SERP matches
    mem_db.execute(
        """
        INSERT INTO atomic_task_backlog (domain, page, query, action_code, status, created_at)
        VALUES ('openfileconverter.com', 'https://openfileconverter.com/convert/stl-to-step/', 'stl to step', 'INJECT_EXACT_TITLE_AND_H2', 'SHIPPED', datetime('now'))
        """
    )
    mem_db.commit()

    sitemap_urls = [
        "https://openfileconverter.com/convert/stl-to-step/",
        "https://openfileconverter.com/convert/obj-to-stl/",
    ]

    mined = mine_paa_and_related_from_cache(
        mem_db,
        domain="openfileconverter.com",
        sitemap_urls=sitemap_urls,
        max_candidates=10,
    )

    assert len(mined) >= 3

    # Check PAA candidate mapping
    queries = {m["query"]: m for m in mined}
    assert "Can OBJ files be converted to STL" in queries or "Can OBJ files be converted to STL?" in queries
    # High token overlap with /convert/obj-to-stl/
    obj_item = next(m for m in mined if "OBJ" in m["query"])
    assert obj_item["page"] == "https://openfileconverter.com/convert/obj-to-stl/"
    assert obj_item["source"] == "paa_expansion"

    # Check related search mapping
    stl_free = next(m for m in mined if "STL to STEP free converter" in m["query"])
    assert stl_free["page"] == "https://openfileconverter.com/convert/stl-to-step/"
    assert stl_free["source"] == "related_search_expansion"

    # Check that unrelated query was excluded
    assert not any("medical billing" in m["query"].lower() for m in mined)


def test_mine_paa_and_related_from_cache_dict_input():
    """Verifies offline dictionary input extraction without sqlite DB."""
    cache_dict = {
        "pdf to docx": {
            "items": [
                {
                    "type": "people_also_ask",
                    "items": [
                        {"title": "How to convert PDF to editable DOCX free?"},
                    ],
                },
                {
                    "type": "related_searches",
                    "items": [
                        "PDF to Word OCR converter online",
                    ],
                },
            ]
        }
    }

    sitemap_urls = [
        "https://openfileconverter.com/convert/pdf-to-docx/",
    ]

    mined = mine_paa_and_related_from_cache(
        cache_dict,
        domain="openfileconverter.com",
        sitemap_urls=sitemap_urls,
        max_candidates=5,
    )

    assert len(mined) == 2
    paa = next(m for m in mined if m["source"] == "paa_expansion")
    assert "PDF to editable DOCX" in paa["query"]
    assert paa["page"] == "https://openfileconverter.com/convert/pdf-to-docx/"


def test_auto_expand_triggers_when_pending_below_threshold(mem_db):
    """Auto-expansion triggers when domain pending task count < threshold."""
    # Seed 3 PENDING tasks for openfileconverter.com (< threshold 15)
    for i in range(3):
        mem_db.execute(
            """
            INSERT INTO atomic_task_backlog (domain, page, query, action_code, status, priority_score, created_at)
            VALUES ('openfileconverter.com', ?, ?, 'INJECT_EXACT_TITLE_AND_H2', 'PENDING', 0.5, datetime('now'))
            """,
            (f"https://openfileconverter.com/convert/route-{i}/", f"query {i}"),
        )

    # Seed cached SERP for PAA mining
    serp_items = [
        {
            "type": "related_searches",
            "items": ["Convert PNG to SVG vector online"],
        }
    ]
    mem_db.execute(
        """
        INSERT INTO dfs_serp_cache (query, fetched_at, items_json, item_types, search_volume)
        VALUES ('png to svg', datetime('now'), ?, '[]', 100.0)
        """,
        (json.dumps(serp_items),),
    )
    # Also add known query so SERP matches domain
    mem_db.execute(
        """
        INSERT INTO atomic_task_backlog (domain, page, query, action_code, status, created_at)
        VALUES ('openfileconverter.com', 'https://openfileconverter.com/convert/png-to-svg/', 'png to svg', 'INJECT_EXACT_TITLE_AND_H2', 'SHIPPED', datetime('now'))
        """
    )
    mem_db.commit()

    initial_candidates = [
        {
            "query": "png to svg",
            "page": "https://openfileconverter.com/convert/png-to-svg/",
            "clicks_30d": 5.0,
            "impressions": 100.0,
            "current_pos": 8.0,
            "ctr": 0.05,
            "window_days": 28,
            "source": "gsc",
        }
    ]

    sitemap_urls = [
        "https://openfileconverter.com/convert/png-to-svg/",
        "https://openfileconverter.com/convert/step-to-stl/",  # Unseen orphan route
    ]

    expanded, report = auto_expand_candidates_if_depleted(
        domain="openfileconverter.com",
        candidates=initial_candidates,
        sitemap_urls=sitemap_urls,
        state_conn=mem_db,
        pending_threshold=15,
        min_rows=150,
    )

    assert report["expanded"] is True
    assert report["pending_before"] == 3
    assert len(expanded) > len(initial_candidates)
    # Proves orphan route was injected
    assert any(c["page"] == "https://openfileconverter.com/convert/step-to-stl/" for c in expanded)
    # Proves mined related search was injected
    assert any("Convert PNG to SVG" in c["query"] for c in expanded)


def test_auto_expand_stays_idle_when_backlog_healthy(mem_db):
    """Auto-expansion stays idle when pending tasks >= threshold and candidate pool is sufficient."""
    # Seed 20 PENDING tasks (healthy backlog >= 15)
    for i in range(20):
        mem_db.execute(
            """
            INSERT INTO atomic_task_backlog (domain, page, query, action_code, status, priority_score, created_at)
            VALUES ('incomecanvas.com', ?, ?, 'INJECT_EXACT_TITLE_AND_H2', 'PENDING', 0.5, datetime('now'))
            """,
            (f"https://incomecanvas.com/tools/calc-{i}/", f"calc {i}"),
        )
    mem_db.commit()

    initial_candidates = [
        {
            "query": f"calc {i}",
            "page": f"https://incomecanvas.com/tools/calc-{i}/",
            "clicks_30d": 1.0,
            "impressions": 20.0,
            "current_pos": 10.0,
            "ctr": 0.05,
            "window_days": 28,
            "source": "gsc",
        }
        for i in range(160)
    ]

    expanded, report = auto_expand_candidates_if_depleted(
        domain="incomecanvas.com",
        candidates=initial_candidates,
        sitemap_urls=["https://incomecanvas.com/tools/calc-0/"],
        state_conn=mem_db,
        pending_threshold=15,
        min_rows=150,
        force=False,
    )

    assert report["expanded"] is False
    assert report["pending_before"] == 20
    assert len(expanded) == 160


def test_auto_expand_force_flag_overrides_healthy_backlog(mem_db):
    """The force=True flag triggers expansion even when pending count >= threshold."""
    for i in range(25):
        mem_db.execute(
            """
            INSERT INTO atomic_task_backlog (domain, page, query, action_code, status, priority_score, created_at)
            VALUES ('smsriver.com', ?, ?, 'INJECT_EXACT_TITLE_AND_H2', 'PENDING', 0.5, datetime('now'))
            """,
            (f"https://smsriver.com/receive-sms/country-{i}/", f"sms {i}"),
        )
    mem_db.commit()

    sitemap_urls = [
        "https://smsriver.com/receive-sms/united-states/",
        "https://smsriver.com/receive-sms/canada/",
    ]

    expanded, report = auto_expand_candidates_if_depleted(
        domain="smsriver.com",
        candidates=[],
        sitemap_urls=sitemap_urls,
        state_conn=mem_db,
        pending_threshold=15,
        min_rows=10,
        force=True,
    )

    assert report["expanded"] is True
    assert report["pending_before"] == 25
    assert len(expanded) > 0


def test_expansion_respects_url_title_lock_cooldown(mem_db):
    """Tasks generated from candidate expansion on recently shipped URLs must respect the 21-day title lock."""
    # URL was shipped 2 days ago with a title action
    locked_url = "https://openfileconverter.com/convert/stl-to-step/"
    mem_db.execute(
        """
        INSERT INTO atomic_task_backlog (domain, page, query, action_code, status, created_at, shipped_at)
        VALUES ('openfileconverter.com', ?, 'stl to step', 'INJECT_EXACT_TITLE_AND_H2', 'SHIPPED', datetime('now', '-2 days'), datetime('now', '-2 days'))
        """,
        (locked_url,),
    )
    mem_db.commit()

    # Mined secondary candidate targeting the same page
    candidate_task = {
        "domain": "openfileconverter.com",
        "page": locked_url,
        "query": "convert 3d stl mesh to step nurbs solid",
        "action_code": "INJECT_EXACT_TITLE_AND_H2",
        "priority_score": 0.85,
    }

    # Enqueue task
    enqueue_tasks(mem_db, [candidate_task])

    # Run preflight hygiene
    hygiene_report = preflight_hygiene(mem_db)
    assert hygiene_report["title_locked"] == 1

    # Verify that the task on locked_url was downgraded to INJECT_SECONDARY_H2_ONLY
    row = mem_db.execute(
        "SELECT action_code, status FROM atomic_task_backlog WHERE query = ?",
        ("convert 3d stl mesh to step nurbs solid",),
    ).fetchone()

    assert row is not None
    assert row[0] == "INJECT_SECONDARY_H2_ONLY"
    assert row[1] == "PENDING"


def test_mine_paa_and_related_from_cache_cross_tenant_isolation(mem_db):
    """Verifies that queries from sibling domains in dfs_serp_cache never leak across tenant boundaries."""
    # Seed a cached SERP for an SMS query (smsriver.com tenant)
    sms_serp = [
        {
            "type": "people_also_ask",
            "items": [{"type": "elem", "title": "What is the E.164 phone format?"}],
        },
        {
            "type": "related_searches",
            "items": ["E 164 format converter free", "SMS receive online"],
        },
    ]
    mem_db.execute(
        """
        INSERT INTO dfs_serp_cache (query, fetched_at, items_json, item_types, search_volume)
        VALUES ('e 164 phone number format', datetime('now'), ?, '[]', 500.0)
        """,
        (json.dumps(sms_serp),),
    )

    # Seed known query ONLY for smsriver.com, NOT openfileconverter.com
    mem_db.execute(
        """
        INSERT INTO atomic_task_backlog (domain, page, query, action_code, status, created_at)
        VALUES ('smsriver.com', 'https://smsriver.com/tools/format/', 'e 164 phone number format', 'INJECT_EXACT_TITLE_AND_H2', 'SHIPPED', datetime('now'))
        """
    )
    mem_db.commit()

    # Mining for openfileconverter.com MUST NOT return any candidates from smsriver's SERP cache
    mined = mine_paa_and_related_from_cache(
        mem_db,
        domain="openfileconverter.com",
        sitemap_urls=["https://openfileconverter.com/convert/pdf-to-docx/"],
        max_candidates=10,
    )

    assert len(mined) == 0, f"Expected 0 cross-tenant leaked candidates, got {len(mined)}: {mined}"

