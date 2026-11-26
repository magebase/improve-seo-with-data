"""DataForSEO publisher-domain resolution contract."""

from dataforseo_client import _item_domain


def test_google_redirect_result_uses_breadcrumb_publisher():
    item = {
        "domain": "google.com",
        "url": "https://google.com/goto?url=abc",
        "breadcrumb": "https://receive-sms.com › blog › articles",
    }
    assert _item_domain(item) == "receive-sms.com"


def test_plain_result_keeps_its_domain():
    assert _item_domain({"domain": "reddit.com"}) == "reddit.com"
