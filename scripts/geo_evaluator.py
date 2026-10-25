#!/usr/bin/env python3
"""
geo_evaluator.py - Generative Engine Optimization (GEO) & AI Search Readiness Evaluator.
Audits a website for discoverability, indexability, and citation readiness across
AI Search engines (Perplexity, ChatGPT, Claude, Google AI Overviews).

Evaluates:
1. llms.txt & llms-full.txt presence, structure, and validity.
2. robots.txt policies for AI crawler user-agents (GPTBot, ClaudeBot, PerplexityBot).
3. Schema.org JSON-LD structured data completeness.
4. Semantic HTML hierarchy and markdown cleanliness for LLM scrapers.

Usage:
    python3 geo_evaluator.py --url https://example.com
"""

import argparse
import json
import re
import sys
import urllib.parse
import urllib.request
from typing import Any, Dict, List


AI_CRAWLERS = ["GPTBot", "ClaudeBot", "PerplexityBot", "Google-Extended", "CCBot", "Bytespider"]


def fetch_url(url: str, timeout: int = 10) -> tuple[int, str, dict]:
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Antigravity-GEO-Evaluator/1.0"}
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return resp.status, body, dict(resp.headers)
    except urllib.error.HTTPError as e:
        return e.code, "", dict(e.headers)
    except Exception as e:
        return 0, str(e), {}


def evaluate_llms_txt(base_url: str) -> Dict[str, Any]:
    target = urllib.parse.urljoin(base_url, "/llms.txt")
    status, body, _ = fetch_url(target)
    result = {"url": target, "status": status, "present": status == 200, "checks": []}

    if status == 200:
        has_title = body.startswith("# ") or "# " in body[:100]
        has_summary = len(body.splitlines()) >= 3
        has_links = "[" in body and "](" in body
        result["checks"].append({"check": "H1 Heading", "pass": has_title})
        result["checks"].append({"check": "Project Summary", "pass": has_summary})
        result["checks"].append({"check": "Markdown Links", "pass": has_links})
        result["valid"] = has_title and has_links
    else:
        result["valid"] = False

    return result


def evaluate_robots_ai_policies(base_url: str) -> Dict[str, Any]:
    target = urllib.parse.urljoin(base_url, "/robots.txt")
    status, body, _ = fetch_url(target)
    result = {"url": target, "status": status, "crawlers": {}}

    if status == 200:
        lines = body.splitlines()
        current_agent = None
        for line in lines:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.lower().startswith("user-agent:"):
                agent = line.split(":", 1)[1].strip()
                current_agent = agent
            elif line.lower().startswith("disallow:") and current_agent:
                path = line.split(":", 1)[1].strip()
                if current_agent in AI_CRAWLERS or current_agent == "*":
                    result["crawlers"].setdefault(current_agent, []).append({"rule": "disallow", "path": path})
            elif line.lower().startswith("allow:") and current_agent:
                path = line.split(":", 1)[1].strip()
                if current_agent in AI_CRAWLERS or current_agent == "*":
                    result["crawlers"].setdefault(current_agent, []).append({"rule": "allow", "path": path})

    return result


def evaluate_html_page(html: str) -> Dict[str, Any]:
    json_ld_blocks: List[Dict[str, Any]] = []
    matches = re.findall(
        r'<script[^>]*type=[\'"]application/ld\+json[\'"][^>]*>(.*?)</script>', html, re.DOTALL | re.IGNORECASE
    )
    for m in matches:
        try:
            parsed = json.loads(m.strip())
            if isinstance(parsed, list):
                json_ld_blocks.extend(parsed)
            else:
                json_ld_blocks.append(parsed)
        except Exception:
            pass

    schema_types: List[str] = []
    for b in json_ld_blocks:
        if isinstance(b, dict):
            if "@type" in b and isinstance(b["@type"], str):
                schema_types.append(b["@type"])
            if "@graph" in b and isinstance(b["@graph"], list):
                for item in b["@graph"]:
                    if isinstance(item, dict) and "@type" in item and isinstance(item["@type"], str):
                        schema_types.append(item["@type"])

    # Meta tags
    has_og_title = bool(re.search(r'<meta[^>]*property=[\'"]og:title[\'"]', html, re.IGNORECASE))
    has_og_desc = bool(re.search(r'<meta[^>]*property=[\'"]og:description[\'"]', html, re.IGNORECASE))
    has_canonical = bool(re.search(r'<link[^>]*rel=[\'"]canonical[\'"]', html, re.IGNORECASE))

    # Headings hierarchy
    h1_count = len(re.findall(r"<h1[^>]*>.*?</h1>", html, re.DOTALL | re.IGNORECASE))
    h2_count = len(re.findall(r"<h2[^>]*>.*?</h2>", html, re.DOTALL | re.IGNORECASE))

    return {
        "json_ld_count": len(json_ld_blocks),
        "schema_types": schema_types,
        "open_graph": has_og_title and has_og_desc,
        "canonical": has_canonical,
        "h1_count": h1_count,
        "h2_count": h2_count,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate GEO & AI Search Readiness")
    parser.add_argument("--url", required=True, help="Target website URL (e.g. https://example.com)")
    args = parser.parse_args()

    url = args.url if args.url.startswith("http") else f"https://{args.url}"
    print("==================================================================")
    print(f"  GENERATIVE ENGINE OPTIMIZATION (GEO) AUDIT: {url}")
    print("==================================================================")

    # 1. Fetch HTML
    status, html, _ = fetch_url(url)
    if status != 200:
        print(f"[FAIL] Could not fetch homepage. HTTP Status: {status}")
        return 1

    page_signals = evaluate_html_page(html)

    # 2. Check llms.txt
    llms_eval = evaluate_llms_txt(url)

    # 3. Check robots.txt
    robots_eval = evaluate_robots_ai_policies(url)

    # Print Report
    print("\n1. Machine-Readable Documentation (llms.txt):")
    if llms_eval["present"]:
        valid_mark = "[PASS]" if llms_eval.get("valid") else "[WARN]"
        print(f"   {valid_mark} Found /llms.txt (HTTP 200)")
        for c in llms_eval.get("checks", []):
            mark = "✓" if c["pass"] else "✗"
            print(f"       {mark} {c['check']}")
    else:
        print(f"   [FAIL] /llms.txt not found (HTTP {llms_eval['status']}).")
        print("          Deploy templates/llms.txt to the root directory for AI crawlers.")

    print("\n2. AI Crawler Permissions (robots.txt):")
    if robots_eval["status"] == 200:
        print("   [PASS] Found /robots.txt")
        crawlers = robots_eval.get("crawlers", {})
        if crawlers:
            for bot, rules in crawlers.items():
                print(f"       Agent '{bot}': {rules}")
        else:
            print("       No explicit restrictions for GPTBot, ClaudeBot, or PerplexityBot (Default Allow).")
    else:
        print(f"   [WARN] Could not retrieve /robots.txt (HTTP {robots_eval['status']}).")

    print("\n3. Structured Data & Schema.org JSON-LD:")
    if page_signals["json_ld_count"] > 0:
        print(f"   [PASS] Found {page_signals['json_ld_count']} Schema.org JSON-LD blocks.")
        print(f"       Entity Types: {', '.join(page_signals['schema_types'])}")
    else:
        print("   [FAIL] No JSON-LD structured data found.")
        print("          Add Schema.org Organization, WebSite, and FAQPage JSON-LD blocks.")

    print("\n4. On-Page Semantic Signals:")
    h1_mark = "[PASS]" if page_signals["h1_count"] == 1 else "[WARN]"
    print(f"   {h1_mark} H1 Tag Count: {page_signals['h1_count']} (Ideal: exactly 1)")
    print(f"   [INFO] H2 Subheading Count: {page_signals['h2_count']}")
    og_mark = "[PASS]" if page_signals["open_graph"] else "[WARN]"
    print(f"   {og_mark} OpenGraph Tags (og:title, og:description): {page_signals['open_graph']}")
    can_mark = "[PASS]" if page_signals["canonical"] else "[FAIL]"
    print(f"   {can_mark} Rel Canonical Specified: {page_signals['canonical']}")

    print("\n------------------------------------------------------------------")
    score = 0
    if llms_eval["present"]:
        score += 25
    if robots_eval["status"] == 200:
        score += 25
    if page_signals["json_ld_count"] > 0:
        score += 25
    if page_signals["canonical"] and page_signals["h1_count"] == 1:
        score += 25

    print(f"Composite GEO & AI Readiness Score: {score}/100")
    print("------------------------------------------------------------------")
    return 0


if __name__ == "__main__":
    sys.exit(main())
