"""Unit tests for the post-enrichment cache re-warm client (Invariant E).

A D1 content mutation wave (ADD_D1_SPEC_COMPARISON_TABLE & friends) that
touches pre-warmed URLs must atomically overwrite the edge caches so
Googlebot never crawls stale pre-enrichment HTML from the KV L2 or the
colo-local L1. The re-warm client fires `X-SEO-Verify: 1` GETs per mutated
URL: the worker bypasses BOTH cache reads, freshly renders (the enriched
DOM), and stores — L1 put + KV overwrite — in the same request.

Covers:
- request shape: GET, X-SEO-Verify: 1 header present, no spoofed crawler UA
- per-URL result reporting: status code capture, failure isolation
- retry behavior: transient transport failures retried with bounded attempts
- never raises: a dead origin degrades to a reported failure, not an exception
"""

from __future__ import annotations

import urllib.error
import urllib.request

import pytest

from improve_seo_rewarm import RewarmResult, RewarmSummary, RewarmTargets, rewarm_urls


class _FakeOpener:
    """Records calls; replays canned responses per path."""

    def __init__(self, responses: dict[str, tuple[int, Exception | None]]):
        self.responses = responses
        self.calls: list[tuple[str, dict[str, str]]] = []

    def open(self, request: urllib.request.Request, timeout: float = 0):
        path = request.full_url.split("//", 1)[1]
        status, exc = self.responses.get(path, (404, None))
        self.calls.append((request.full_url, dict(request.header_items())))
        if exc is not None:
            raise exc
        return status

    def add_header_mock(self):  # pragma: no cover - unused hook
        raise NotImplementedError


def _call(
    targets: RewarmTargets,
    opener: _FakeOpener,
    attempts: int = 2,
) -> RewarmSummary:
    return rewarm_urls(
        targets,
        opener=opener,
        timeout_seconds=5,
        max_attempts=attempts,
        retry_backoff_seconds=0,
    )


def test_every_mutated_url_gets_a_verify_get_with_header(tmp_path):
    opener = _FakeOpener(
        {
            "figiva.com/calculators/fmcg-scheme/": (200, None),
            "figiva.com/niche/finance/": (200, None),
        }
    )
    summary = _call(
        RewarmTargets(
            host="figiva.com",
            paths=["/calculators/fmcg-scheme/", "/niche/finance/"],
        ),
        opener,
    )
    assert [r.path for r in summary.results] == [
        "/calculators/fmcg-scheme/",
        "/niche/finance/",
    ]
    assert len(opener.calls) == 2
    for url, headers in opener.calls:
        flat = {k.lower(): v for k, v in headers.items()}
        assert flat.get("x-seo-verify") == "1"


def test_no_spoofed_crawler_user_agent_is_sent():
    opener = _FakeOpener({"figiva.com/a/": (200, None)})
    _call(RewarmTargets(host="figiva.com", paths=["/a/"]), opener)
    headers = {k.lower(): v for k, v in opener.calls[0][1].items()}
    ua = headers.get("user-agent", "").lower()
    assert "googlebot" not in ua
    assert "bingbot" not in ua


def test_status_codes_are_reported_per_url():
    opener = _FakeOpener(
        {
            "figiva.com/good/": (200, None),
            "figiva.com/broken/": (500, None),
        }
    )
    summary = _call(
        RewarmTargets(host="figiva.com", paths=["/good/", "/broken/"]),
        opener,
    )
    by_path = {r.path: r for r in summary.results}
    assert by_path["/good/"].status == 200
    assert by_path["/good/"].ok is True
    assert by_path["/broken/"].status == 500
    assert by_path["/broken/"].ok is False


def test_transport_failure_is_isolated_and_retried_then_reported():
    boom = urllib.error.URLError("connection reset")
    opener = _FakeOpener({"figiva.com/dead/": (0, boom)})
    summary = _call(
        RewarmTargets(host="figiva.com", paths=["/dead/"]),
        opener,
        attempts=3,
    )
    assert len(opener.calls) == 3  # retried max_attempts times
    result = summary.results[0]
    assert result.ok is False
    assert result.status is None


def test_never_raises_even_when_every_request_fails():
    opener = _FakeOpener(
        {
            "figiva.com/x/": (0, urllib.error.URLError("dns")),
            "figiva.com/y/": (0, urllib.error.URLError("dns")),
        }
    )
    summary = _call(
        RewarmTargets(host="figiva.com", paths=["/x/", "/y/"]),
        opener,
    )
    assert summary.all_ok is False
    assert len(summary.results) == 2


def test_summary_counts_and_all_ok():
    opener = _FakeOpener(
        {
            "figiva.com/ok1/": (200, None),
            "figiva.com/ok2/": (200, None),
            "figiva.com/bad/": (503, None),
        }
    )
    summary = _call(
        RewarmTargets(host="figiva.com", paths=["/ok1/", "/ok2/", "/bad/"]),
        opener,
    )
    assert summary.ok_count == 2
    assert summary.fail_count == 1
    assert summary.all_ok is False


def test_non_200_is_not_ok_even_without_exception():
    opener = _FakeOpener({"figiva.com/redirect/": (301, None)})
    summary = _call(RewarmTargets(host="figiva.com", paths=["/redirect/"]), opener)
    assert summary.results[0].ok is False


def test_retry_backoff_receives_attempt_number():
    recorded: list[int] = []

    class _Recorder(_FakeOpener):
        pass

    def fake_sleep(seconds: float) -> None:
        recorded.append(int(seconds))

    opener = _FakeOpener({"figiva.com/dead/": (0, urllib.error.URLError("reset"))})
    rewarm_urls(
        RewarmTargets(host="figiva.com", paths=["/dead/"]),
        opener=opener,
        timeout_seconds=5,
        max_attempts=3,
        retry_backoff_seconds=7,
        sleep=fake_sleep,
    )
    assert recorded == [7, 7]


def test_rewarm_targets_rejects_paths_without_leading_slash():
    with pytest.raises(ValueError):
        RewarmTargets(host="figiva.com", paths=["calculators/no-slash/"])


def test_rewarm_result_dataclass_shape():
    r = RewarmResult(path="/a/", status=200, attempts=1, error=None)
    assert r.ok is True
    r2 = RewarmResult(path="/b/", status=None, attempts=3, error="URLError")
    assert r2.ok is False
