"""Cold-start launch evidence from cached DataForSEO data, with no GSC history."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from collect_features import load_or_fetch_search_volumes, max_sibling_similarity
from fleet_state import (
    connect_state_db,
    load_cached_serp_volumes,
    save_serp_volumes,
    upsert_serp_cache,
)


def test_cached_volume_is_reused_without_a_network_call():
    conn = connect_state_db(":memory:")
    save_serp_volumes(conn, {"receive sms online in germany": 320.0})
    volumes = load_cached_serp_volumes(conn, ["receive sms online in germany"])
    assert volumes == {"receive sms online in germany": 320.0}
    conn.close()


def test_volume_survives_a_serp_cache_refresh():
    conn = connect_state_db(":memory:")
    save_serp_volumes(conn, {"q": 440.0})
    upsert_serp_cache(conn, "q", [{"type": "organic", "title": "Q"}], ["organic"])
    volumes = load_cached_serp_volumes(conn, ["q"])
    assert volumes == {"q": 440.0}
    conn.close()


def test_stale_volume_is_not_reused():
    conn = connect_state_db(":memory:")
    save_serp_volumes(conn, {"q": 440.0})
    old = (datetime.now(timezone.utc) - timedelta(days=40)).isoformat()
    conn.execute("UPDATE dfs_serp_cache SET fetched_at = ? WHERE query = ?", (old, "q"))
    conn.commit()
    assert load_cached_serp_volumes(conn, ["q"]) == {}
    conn.close()


def test_dataforseo_evidence_alone_can_clear_the_cold_start_gate():
    from indexation_forecast import evaluate_launch_candidate

    candidate = {
        "query": "receive sms online in germany",
        "page": "https://example.com/receive-sms/de/",
        "current_pos": 100.0,
        "impressions": 0.0,
        # DataForSEO Keywords-Data volume (cached) + cached SERP features.
        "search_volume_log": 2.4,
        "serp_forum_ratio": 0.35,
        "title_exact_match_rate": 0.2,
        "template_index_rate": 0.5,
        # Live page/site evidence, not historical index labels.
        "unique_data_fields": 5,
        "sibling_similarity": 0.18,
        "inlinks_from_indexed": 4,
    }
    decision = evaluate_launch_candidate(candidate)
    assert decision.eligible is True, decision.reasons
    assert decision.features["search_volume_log"] == 2.4


def test_dataforseo_volume_is_paid_once_then_reused_from_cache():
    conn = connect_state_db(":memory:")

    class FakeClient:
        def __init__(self):
            self.calls = []

        def keyword_search_volume_live(self, keywords):
            self.calls.append(list(keywords))
            return {keyword: 250.0 for keyword in keywords}

    client = FakeClient()
    first = load_or_fetch_search_volumes(conn, ["new demand query"], client)
    second = load_or_fetch_search_volumes(conn, ["new demand query"], client)

    assert first == {"new demand query": 250.0}
    assert second == {"new demand query": 250.0}
    assert len(client.calls) == 1, "the second run must reuse the 30-day cache"
    conn.close()


def test_country_service_route_is_a_duplicate_of_its_country_sibling():
    sitemap = [
        "https://example.com/receive-sms/us/",
        "https://example.com/receive-sms/gb/",
    ]
    similarity = max_sibling_similarity(
        "receive sms online in us whatsapp",
        "https://example.com/receive-sms/us/whatsapp/",
        sitemap,
    )
    assert similarity >= 0.50


def test_unique_long_tail_route_is_not_forced_to_look_like_a_sibling():
    sitemap = [
        "https://example.com/receive-sms/us/",
        "https://example.com/receive-sms/gb/",
    ]
    similarity = max_sibling_similarity(
        "how to port a business number to a virtual carrier",
        "https://example.com/guides/port-business-number-virtual-carrier/",
        sitemap,
    )
    assert similarity <= 0.50
