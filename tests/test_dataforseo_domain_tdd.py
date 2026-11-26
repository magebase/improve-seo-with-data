"""DataForSEO publisher-domain resolution contract."""

from dataforseo_client import DataForSEOClient, _item_domain


def test_google_redirect_result_uses_breadcrumb_publisher():
    item = {
        "domain": "google.com",
        "url": "https://google.com/goto?url=abc",
        "breadcrumb": "https://receive-sms.com › blog › articles",
    }
    assert _item_domain(item) == "receive-sms.com"


def test_ugc_result_uses_website_name_when_breadcrumb_is_missing():
    item = {
        "domain": "google.com",
        "url": "https://google.com/goto?url=abc",
        "website_name": "Reddit",
    }
    assert _item_domain(item) == "reddit.com"


def test_garbage_website_name_is_not_a_domain():
    item = {"domain": "google.com", "website_name": "140+"}
    assert _item_domain(item) == ""


def test_unresolved_goto_is_empty_not_google():
    item = {"domain": "google.com", "url": "https://google.com/goto?url=abc"}
    assert _item_domain(item) == ""


def test_plain_result_keeps_its_domain():
    assert _item_domain({"domain": "reddit.com"}) == "reddit.com"


def test_backlinks_summary_normalizes_authority_fields():
    class Fake(DataForSEOClient):
        def _post(self, path, payload):
            assert path == "/backlinks/summary/live"
            return {
                "tasks": [
                    {
                        "result": [
                            {
                                "target": "smsriver.com",
                                "rank": 0,
                                "backlinks": 46,
                                "referring_domains": 42,
                                "referring_main_domains": 41,
                                "backlinks_spam_score": 52,
                            }
                        ]
                    }
                ]
            }

    row = Fake("login", "password").backlinks_summary("smsriver.com")
    assert row["rank"] == 0
    assert row["referring_domains"] == 42
    assert row["backlinks_spam_score"] == 52
