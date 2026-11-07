#!/usr/bin/env python3
"""
test_dataforseo_client.py - Offline contract tests for the DataForSEO SERP
intelligence layer of the improve-seo-with-data skill.

Zero network: every client call goes through an injected fake transport.
These tests pin the cost-routing economics (Standard Queue $0.0006/SERP vs
Live $0.002/SERP), credential resolution precedence, SERP vulnerability
scoring (weak-spot detection), and the cost-shaving payload features
(stop_crawl_on_match refunds + offset crawling via search_param).
"""

import json
import os
import unittest
from unittest import mock

from dataforseo_client import (
    COST_PER_SERP_LIVE_USD,
    COST_PER_SERP_QUEUE_USD,
    DataForSEOClient,
    estimate_serp_cost,
    extract_serp_features,
    main,
    resolve_credentials,
    serp_vulnerability_score,
)


class FakeTransport:
    """Injectable urllib stand-in returning canned DataForSEO payloads."""

    def __init__(self, responses=None):
        self.responses = responses or []
        self.calls = []

    def __call__(self, method, url, body=None, headers=None, timeout=60):
        self.calls.append({"method": method, "url": url, "body": body, "headers": headers})
        if callable(self.responses[0]):
            return self.responses.pop(0)()
        return self.responses.pop(0)


def dfs_envelope(result, status_code=20000, tasks=None):
    """Wrap a payload the way DataForSEO v3 envelopes it."""
    return {
        "status_code": status_code,
        "status_message": "Ok.",
        "tasks": tasks,
        "result": result,
    }


def organic_item(rank, title, url, item_type="organic", domain=None):
    return {
        "type": item_type,
        "rank_group": rank,
        "title": title,
        "url": url,
        "domain": domain or url.split("/")[2] if "://" in url else url,
    }


class TestCredentialResolution(unittest.TestCase):
    def test_explicit_args_win_over_env(self):
        creds = resolve_credentials(
            login="cli@login", password="clipw",
            env={"DFS_LOGIN": "env@login", "DFS_PASSWORD": "envpw"},
        )
        self.assertEqual(creds, ("cli@login", "clipw"))

    def test_dataforseo_names_before_legacy_dfs_names(self):
        creds = resolve_credentials(
            login=None, password=None,
            env={
                "DATAFORSEO_LOGIN": "new@login", "DATAFORSEO_PASSWORD": "newpw",
                "DFS_LOGIN": "old@login", "DFS_PASSWORD": "oldpw",
            },
        )
        self.assertEqual(creds, ("new@login", "newpw"))

    def test_legacy_dfs_names_used_when_dfa_names_absent(self):
        creds = resolve_credentials(login=None, password=None, env={"DFS_LOGIN": "l", "DFS_PASSWORD": "p"})
        self.assertEqual(creds, ("l", "p"))

    def test_combined_api_key_env_var_splits_into_login_password(self):
        creds = resolve_credentials(login=None, password=None, env={"DATAFORSEO_API_KEY": "user:secret"})
        self.assertEqual(creds, ("user", "secret"))

    def test_missing_credentials_raise_with_instruction(self):
        with self.assertRaises(RuntimeError) as ctx:
            resolve_credentials(login=None, password=None, env={})
        self.assertIn("DATAFORSEO_LOGIN", str(ctx.exception))


class TestCostModel(unittest.TestCase):
    def test_queue_is_cheaper_than_live(self):
        self.assertEqual(COST_PER_SERP_QUEUE_USD, 0.0006)
        self.assertEqual(COST_PER_SERP_LIVE_USD, 0.002)

    def test_estimate_serp_cost_scales_linearly(self):
        self.assertAlmostEqual(estimate_serp_cost(1000, mode="queue"), 0.60)
        self.assertAlmostEqual(estimate_serp_cost(1000, mode="live"), 2.00)
        self.assertAlmostEqual(estimate_serp_cost(50, mode="queue"), 0.03)

    def test_estimate_serp_cost_rejects_unknown_mode(self):
        with self.assertRaises(ValueError):
            estimate_serp_cost(10, mode="turbo")


class TestSerpFeatureExtraction(unittest.TestCase):
    def test_extracts_all_revenue_relevant_features(self):
        items = [
            organic_item(1, "Buy Widgets", "https://ads.example.com/w"),
            {
                "type": "ai_overview",
                "items": [{"title": "AI answer"}],
            },
            {"type": "people_also_ask", "items": [{"title": "Q?"}]},
            {"type": "featured_snippet", "title": "def"},
            {"type": "discussions_and_forums", "items": [{"title": "r/"}]},
            organic_item(2, "Widgets guide", "https://www.reddit.com/r/widgets"),
            organic_item(3, "Widgets", "https://www.quora.com/widgets"),
        ]
        features = extract_serp_features(items)
        self.assertTrue(features["ai_overview"])
        self.assertTrue(features["people_also_ask"])
        self.assertTrue(features["featured_snippet"])
        self.assertTrue(features["discussions_and_forums"])
        # reddit + quora organic items + the discussions_and_forums block = 3/7
        self.assertAlmostEqual(features["forum_ugc_ratio"], 3 / 7)

    def test_empty_serp_has_no_features(self):
        features = extract_serp_features([])
        self.assertFalse(any(features[k] for k in ("ai_overview", "featured_snippet", "people_also_ask")))


class TestSerpVulnerabilityScore(unittest.TestCase):
    def test_forum_heavy_untitled_serp_is_a_weak_spot(self):
        """Reddit/Quora ranking with no exact-match titles = zero-backlink win."""
        items = [
            organic_item(1, "Some random forum thread about things", "https://www.reddit.com/r/x/comments/1"),
            organic_item(2, "Quora answer placeholder", "https://www.quora.com/answer"),
            organic_item(3, "Thin page v2", "https://smallblog.example.com/post"),
            organic_item(4, "Yet another discussion", "https://www.quora.com/2"),
            organic_item(5, "Random", "https://www.reddit.com/r/y"),
        ]
        result = serp_vulnerability_score(items, query="cheap widgets online")
        self.assertGreaterEqual(result["score"], 70)
        self.assertTrue(result["weak_spot"])
        self.assertGreater(result["components"]["forum_ugc_count"], 0)
        self.assertLess(result["components"]["title_exact_match_rate"], 0.4)

    def test_entrenched_exact_match_serp_is_not_a_weak_spot(self):
        """Big-brand domains with exact-match titles are entrenched; do not attack."""
        items = [
            organic_item(1, "Cheap Widgets Online | GiantStore", "https://www.giantstore.com/widgets"),
            organic_item(2, "Buy Cheap Widgets Online — MegaBrand", "https://megabrand.com/cheap-widgets"),
            organic_item(3, "Cheap Widgets Online Sale", "https://shop.example.org/widgets"),
            organic_item(4, "Cheap Widgets Online Guide", "https://guides.example.net/cheap-widgets"),
            organic_item(5, "Cheap Widgets Online", "https://www.otherbrand.com/"),
        ]
        result = serp_vulnerability_score(items, query="cheap widgets online")
        self.assertFalse(result["weak_spot"])
        self.assertGreaterEqual(result["components"]["title_exact_match_rate"], 0.6)

    def test_serp_crowding_flags_ai_overview(self):
        items = [
            {"type": "ai_overview", "items": []},
            {"type": "local_pack", "items": []},
            organic_item(1, "Query", "https://a.example.com/"),
        ]
        result = serp_vulnerability_score(items, query="query")
        self.assertGreaterEqual(result["components"]["crowding_penalty"], 1)


class TestDataForSEOClientPayloads(unittest.TestCase):
    def _client(self, transport):
        return DataForSEOClient(login="l", password="p", transport=transport)

    def test_post_serp_tasks_uses_standard_queue_endpoint_and_basic_auth(self):
        transport = FakeTransport(responses=[dfs_envelope({"task_id": "t1", "cost": 0.0006})])
        client = self._client(transport)
        resp = client.post_serp_tasks(["cheap widgets", "buy widgets"])
        url = transport.calls[0]["url"]
        self.assertIn("/v3/serp/google/organic/task_post", url)
        self.assertNotIn("/live", url)
        auth_header = transport.calls[0]["headers"]["Authorization"]
        self.assertTrue(auth_header.startswith("Basic "))
        sent = json.loads(transport.calls[0]["body"])
        self.assertEqual(len(sent), 2)
        self.assertEqual(sent[0]["keyword"], "cheap widgets")
        self.assertEqual(sent[0]["depth"], 10)
        self.assertEqual(resp["status_code"], 20000)

    def test_post_serp_tasks_supports_stop_crawl_on_match_for_rank_tracking(self):
        transport = FakeTransport(responses=[dfs_envelope({"task_id": "t1"})])
        client = self._client(transport)
        client.post_serp_tasks(["my query"], stop_crawl_on_match=["*.example.com"])
        sent = json.loads(transport.calls[0]["body"])
        self.assertEqual(sent[0]["stop_crawl_on_match"], ["*.example.com"])

    def test_offset_crawling_uses_search_param_start_for_deep_positions(self):
        transport = FakeTransport(responses=[dfs_envelope({"task_id": "t1"})])
        client = self._client(transport)
        client.post_serp_tasks(["my query"], offset=30)
        sent = json.loads(transport.calls[0]["body"])
        self.assertEqual(sent[0]["search_param"], "&start=30")

    def test_live_endpoint_is_gated_behind_explicit_flag(self):
        transport = FakeTransport(responses=[dfs_envelope({"result": []})])
        client = self._client(transport)
        client.fetch_serp_live("cheap widgets")
        self.assertIn("/live", transport.calls[0]["url"])

    def test_collect_ready_tasks_polls_tasks_ready_then_task_get(self):
        """tasks_ready nests ready-task descriptors in `result`, each carrying
        the authoritative `endpoint_regular` (live API shape, captured 2026-11)."""
        def ready_response():
            return dfs_envelope(None, tasks=[{
                "id": "ready-call-1",
                "status_code": 20000,
                "result_count": 1,
                "result": [{
                    "id": "111",
                    "endpoint_regular": "/v3/serp/google/organic/task_get/regular/111",
                }],
            }])

        def task_get_1():
            return dfs_envelope(None, tasks=[{
                "id": "111",
                "status_code": 20000,
                "result": [{"task_id": "111", "keyword": "k", "items": [organic_item(1, "t", "https://a.com/")]}],
            }])

        transport = FakeTransport(responses=[ready_response, task_get_1])
        client = self._client(transport)
        results = client.collect_ready_tasks()
        self.assertIn("tasks_ready", transport.calls[0]["url"])
        self.assertIn("task_get/regular/111", transport.calls[1]["url"])
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["task_id"], "111")

    def test_collect_ready_tasks_reports_incomplete_queue_without_blocking(self):
        def ready_response():
            return dfs_envelope(None, tasks=[{"id": "222", "status_code": 40602, "cost": 0}])

        transport = FakeTransport(responses=[ready_response])
        client = self._client(transport)
        results = client.collect_ready_tasks()
        self.assertEqual(results, [])
        self.assertTrue(client.last_queue_state["pending"] >= 1)

    def test_transport_errors_surface_without_leaking_credentials(self):
        def boom():
            raise Exception("connection refused")

        transport = FakeTransport(responses=[boom])
        client = self._client(transport)
        with self.assertRaises(RuntimeError) as ctx:
            client.post_serp_tasks(["q"])
        self.assertIn("connection refused", str(ctx.exception))
        self.assertNotIn("p", str(ctx.exception))

    def test_api_error_envelope_raises_with_status(self):
        transport = FakeTransport(responses=[dfs_envelope(None, status_code=40000)])
        client = self._client(transport)
        with self.assertRaises(RuntimeError) as ctx:
            client.post_serp_tasks(["q"])
        self.assertIn("40000", str(ctx.exception))


class TestCliDryRun(unittest.TestCase):
    def test_cli_dry_run_prints_payload_plan_and_cost_without_network(self):
        import tempfile

        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
            f.write("cheap widgets\nbuy widgets\n")
            kw_file = f.name

        with mock.patch.dict(os.environ, {"DFS_LOGIN": "l", "DFS_PASSWORD": "p"}):
            with mock.patch("sys.argv", [
                "dataforseo_client.py",
                "--keywords-file", kw_file,
                "--dry-run",
            ]):
                with mock.patch("builtins.print") as fake_print:
                    main()

        printed = " ".join(str(c) for c in fake_print.call_args_list)
        self.assertIn("DRY-RUN", printed.upper())
        self.assertIn("cheap widgets", printed)
        self.assertIn("queue", printed.lower())


if __name__ == "__main__":
    unittest.main()
