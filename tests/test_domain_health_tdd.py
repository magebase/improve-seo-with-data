"""Domain baseline health gate contract."""

from fleet_state import connect_state_db, domain_indexed_rate, save_url_inspections
from indexation_forecast import domain_health_gate


def test_domain_indexed_rate_reads_inspection_cache():
    conn = connect_state_db(":memory:")
    save_url_inspections(
        conn,
        "smsriver.com",
        {
            "https://smsriver.com/a/": {"coverage_state": "Submitted and indexed"},
            "https://smsriver.com/b/": {
                "coverage_state": "Crawled - currently not indexed"
            },
        },
    )
    result = domain_indexed_rate(conn, "sc-domain:smsriver.com")
    assert result["known"] is True
    assert result["total"] == 2
    assert result["indexed"] == 1
    assert result["rate"] == 0.5
    conn.close()


def test_stale_and_deleted_urls_are_excluded_from_the_denominator():
    conn = connect_state_db(":memory:")
    save_url_inspections(
        conn,
        "smsriver.com",
        {
            "https://smsriver.com/live/": {"coverage_state": "Submitted and indexed"},
            "https://smsriver.com/deleted/": {
                "coverage_state": "Submitted and indexed"
            },
        },
    )
    result = domain_indexed_rate(
        conn,
        "smsriver.com",
        sitemap_urls=["https://smsriver.com/live/"],
        max_age_days=21,
    )
    assert result["total"] == 1
    assert result["indexed"] == 1
    assert result["filtered"] == 1
    conn.close()


def test_unhealthy_domain_blocks_canary():
    assert domain_health_gate(4, 40, min_indexed_rate=0.65)["canary_allowed"] is False
    assert domain_health_gate(28, 40, min_indexed_rate=0.65)["canary_allowed"] is True
