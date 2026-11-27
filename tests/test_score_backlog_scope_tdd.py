"""The queue and cursor must obey the same curated footprint as the planner."""

from score_backlog import scope_rows_to_urls


def test_scope_rows_to_urls_drops_retired_pages():
    rows = [
        {"page": "https://smsriver.com/receive-sms/us/", "action_code": "A"},
        {
            "page": "https://smsriver.com/troubleshooting/retired/",
            "action_code": "B",
        },
    ]

    kept = scope_rows_to_urls(rows, {"https://smsriver.com/receive-sms/us/"})

    assert [row["action_code"] for row in kept] == ["A"]


def test_scope_rows_to_urls_is_a_noop_without_a_declared_footprint():
    rows = [{"page": "https://smsriver.com/retired/"}]

    assert scope_rows_to_urls(rows, None) == rows
